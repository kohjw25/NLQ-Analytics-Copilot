"""Query execution layer (PRD 7.3 / 7.4 / 12).

Executes generated SQL against an uploaded dataset using DuckDB. The dataset is
registered as a table named ``data`` so generated SQL is portable across files.
A read-only guard rejects any statement that is not a single SELECT / WITH query,
so a generated (or hallucinated) query can never mutate or drop anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd

from .profiler import coerce_date_columns, load_dataframe, parse_date_series

TABLE_NAME = "data"

# Statements the copilot is allowed to run. Everything else is refused.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|copy|pragma|"
    r"replace|truncate|grant|revoke|call|export)\b",
    re.IGNORECASE,
)


class UnsafeQueryError(ValueError):
    """Raised when a generated query is not a read-only SELECT."""


@dataclass
class QueryResult:
    ok: bool
    sql: str
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    n_rows: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "sql": self.sql,
            "columns": self.columns,
            "rows": self.rows,
            "n_rows": self.n_rows,
            "error": self.error,
        }


def assert_read_only(sql: str) -> None:
    """Raise UnsafeQueryError unless ``sql`` is a single read-only query."""
    stripped = sql.strip().rstrip(";")
    if not stripped:
        raise UnsafeQueryError("Empty query.")
    if ";" in stripped:
        raise UnsafeQueryError("Multiple statements are not allowed.")
    lowered = stripped.lstrip("(").lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise UnsafeQueryError("Only SELECT / WITH queries are allowed.")
    if _FORBIDDEN.search(stripped):
        raise UnsafeQueryError("Query contains a forbidden (write/DDL) keyword.")


def apply_date_filter(df: pd.DataFrame, date_filter: Optional[Dict[str, Any]]) -> pd.DataFrame:
    """Filter rows by year/month and/or a date range on a datetime column.

    ``date_filter`` = {"column": <name>, "years": [...], "months": [...],
    "start": <ISO date>, "end": <ISO date>}. Empty/missing entries mean "no
    restriction" on that dimension. ``start``/``end`` are inclusive bounds.
    """
    if not date_filter:
        return df
    col = date_filter.get("column")
    if not col or col not in df.columns:
        return df
    dt = parse_date_series(df[col])
    mask = dt.notna()
    years = date_filter.get("years")
    months = date_filter.get("months")
    start = date_filter.get("start")
    end = date_filter.get("end")
    if years:
        mask &= dt.dt.year.isin(years)
    if months:
        mask &= dt.dt.month.isin(months)
    if start:
        mask &= dt >= pd.Timestamp(start)
    if end:
        # Inclusive of the whole end day.
        mask &= dt < pd.Timestamp(end) + pd.Timedelta(days=1)
    return df[mask]


def make_connection(path: str, date_filter: Optional[Dict[str, Any]] = None) -> duckdb.DuckDBPyConnection:
    """Load a file and register it as the ``data`` table in a DuckDB connection.

    Date columns are parsed to real datetime dtype (so DuckDB time bucketing works
    regardless of the source text format, e.g. dd/mm/yyyy). If ``date_filter`` is
    given, rows are filtered before the table is registered, so all generated SQL
    runs against the filtered data unchanged.
    """
    df = load_dataframe(path)
    df = coerce_date_columns(df)
    df = apply_date_filter(df, date_filter)
    con = duckdb.connect(database=":memory:")
    con.register(TABLE_NAME, df)
    return con


def run_sql(path_or_con, sql: str, date_filter: Optional[Dict[str, Any]] = None) -> QueryResult:
    """Execute read-only ``sql`` and return a structured QueryResult.

    ``path_or_con`` may be a file path or an existing DuckDB connection.
    ``date_filter`` (path inputs only) restricts rows by year/month before the
    query runs. Errors are returned in the result rather than raised, so callers
    can surface a graceful explanation (PRD 7.4).
    """
    try:
        assert_read_only(sql)
    except UnsafeQueryError as exc:
        return QueryResult(ok=False, sql=sql, error=f"Rejected unsafe query: {exc}")

    con = None
    own_con = False
    try:
        if isinstance(path_or_con, str):
            con = make_connection(path_or_con, date_filter)
            own_con = True
        else:
            con = path_or_con
        df = con.execute(sql).fetchdf()
        return QueryResult(
            ok=True,
            sql=sql,
            columns=list(df.columns),
            rows=df.to_dict(orient="records"),
            n_rows=len(df),
        )
    except Exception as exc:  # duckdb.Error and friends
        return QueryResult(ok=False, sql=sql, error=str(exc))
    finally:
        if own_con and con is not None:
            con.close()


def run_sql_df(path_or_con, sql: str) -> pd.DataFrame:
    """Convenience: execute read-only ``sql`` and return a DataFrame (raises on error)."""
    assert_read_only(sql)
    if isinstance(path_or_con, str):
        con = make_connection(path_or_con)
        try:
            return con.execute(sql).fetchdf()
        finally:
            con.close()
    return path_or_con.execute(sql).fetchdf()
