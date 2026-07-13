"""Dataset upload & profiling layer (PRD 7.1).

Loads a CSV/Excel file and produces a schema profile the LLM can reason over:
column dtypes, a metric/dimension/date role for each column, missing-value counts,
a short metadata summary, and a list of suggested starter questions.
"""
from __future__ import annotations

import os
import re as _re
from typing import Any, Dict, List

import pandas as pd

SUPPORTED_EXTS = {".csv", ".tsv", ".xlsx", ".xls"}


def load_dataframe(path: str) -> pd.DataFrame:
    """Load a supported tabular file into a DataFrame."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(
            f"Unsupported file format '{ext}'. Supported: {sorted(SUPPORTED_EXTS)}"
        )
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    sep = "\t" if ext == ".tsv" else ","
    return pd.read_csv(path, sep=sep)


def _detect_dayfirst(sample: pd.Series) -> bool:
    """True if the values look day-first (dd/mm/yyyy) rather than month-first.

    A value whose first number is >12 can only be a day, so it settles the format
    for the whole column (e.g. '15/06/2023' -> day 15). Defaults to False (ISO /
    US month-first) when nothing is decisive.
    """
    for v in sample:
        m = _re.match(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{2,4}", str(v))
        if m and int(m.group(1)) > 12:
            return True
    return False


def parse_date_series(series: pd.Series) -> pd.Series:
    """Parse a (possibly text) column into datetime, honouring dd/mm/yyyy order."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    sample = series.dropna().astype(str).head(50)
    dayfirst = _detect_dayfirst(sample)
    return pd.to_datetime(series, errors="coerce", dayfirst=dayfirst, format="mixed")


def _looks_like_date(series: pd.Series) -> bool:
    """Best-effort detection of a date/datetime column."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if not pd.api.types.is_object_dtype(series):
        return False
    sample = series.dropna().astype(str).head(25)
    if sample.empty:
        return False
    parsed = pd.to_datetime(sample, errors="coerce", dayfirst=_detect_dayfirst(sample), format="mixed")
    # Require most of the sample to parse to avoid false positives on free text.
    return parsed.notna().mean() >= 0.8


def coerce_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert detected date columns to real datetime64 dtype.

    DuckDB's CAST(... AS DATE) only accepts ISO 'YYYY-MM-DD' text, so leaving
    dd/mm/yyyy (or other) date strings as-is makes time bucketing (strftime /
    date_trunc) fail. Parsing them here — once, with day-first detection — means
    the registered ``data`` table has genuine TIMESTAMP columns that group by
    month/week/quarter correctly regardless of the original text format.
    """
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_datetime64_any_dtype(s) or not pd.api.types.is_object_dtype(s):
            continue
        if not _looks_like_date(s):
            continue
        parsed = parse_date_series(s)
        if parsed.notna().mean() >= 0.8:
            out[col] = parsed
    return out


# Whole-word tokens that mark an identifier column (matched on the last name
# token, not a raw suffix — so "Amount Paid" / "grid" aren't misread as IDs).
_ID_TOKENS = {"id", "code", "key", "uuid", "guid", "number", "no"}


def _looks_like_identifier(name: str, series: pd.Series, n_rows: int) -> bool:
    """A numeric column that identifies rows rather than measuring them."""
    lname = name.strip().lower()
    tokens = [t for t in _re.split(r"[^a-z0-9]+", lname) if t]
    if lname in {"id", "index"} or (tokens and tokens[-1] in _ID_TOKENS):
        return True
    # Near-unique integer column with no fractional part reads as an identifier.
    if n_rows and series.nunique(dropna=True) / n_rows > 0.9:
        try:
            if (series.dropna() % 1 == 0).all():
                return True
        except TypeError:
            return False
    return False


def _date_options(series: pd.Series) -> Dict[str, Any]:
    """Distinct years and months present in a date column, for the UI date filter."""
    dt = parse_date_series(series).dropna()
    if dt.empty:
        return {"years": [], "months": [], "min": None, "max": None}
    return {
        "years": sorted(int(y) for y in dt.dt.year.unique()),
        "months": sorted(int(m) for m in dt.dt.month.unique()),
        "min": dt.min().date().isoformat(),
        "max": dt.max().date().isoformat(),
    }


def _looks_like_year(name: str, series: pd.Series) -> bool:
    """A numeric column that holds calendar years (e.g. 2023, 2024) — a time
    dimension you group by, not a metric you sum."""
    lname = name.strip().lower()
    name_hint = lname in {"year", "yr", "fy", "fiscal year", "fiscal_year"} or lname.endswith(("year", "_yr"))
    if not pd.api.types.is_numeric_dtype(series):
        return name_hint
    s = series.dropna()
    if s.empty:
        return name_hint
    try:
        if not (s % 1 == 0).all():  # years are whole numbers
            return False
        vals = s.astype("int64")
    except (TypeError, ValueError):
        return False
    in_range = vals.between(1900, 2100).mean() >= 0.95
    # Name says year -> just needs plausible values; otherwise require a small,
    # year-like set of distinct values so real metrics aren't misclassified.
    return in_range and (name_hint or vals.nunique() <= 60)


def classify_column(name: str, series: pd.Series, n_rows: int) -> str:
    """Return one of 'date', 'metric', or 'dimension' for a column.

    Numeric columns are metrics by default — including 0/1 outcome flags such as
    ``converted``, which are meaningful when averaged (conversion rate). Numeric
    identifiers (``user_id``) and calendar years (``2024``) are treated as
    dimensions, not metrics.
    """
    if _looks_like_date(series):
        return "date"
    if pd.api.types.is_numeric_dtype(series):
        if _looks_like_identifier(name, series, n_rows) or _looks_like_year(name, series):
            return "dimension"
        return "metric"
    return "dimension"  # text groups better than it aggregates, whatever its cardinality


def profile_dataset(path: str, preview_rows: int = 5) -> Dict[str, Any]:
    """Profile a dataset and return a JSON-serialisable metadata dict."""
    df = load_dataframe(path)
    n_rows = len(df)

    columns: List[Dict[str, Any]] = []
    metrics, dimensions, dates = [], [], []
    for col in df.columns:
        role = classify_column(col, df[col], n_rows)
        missing = int(df[col].isna().sum())
        columns.append(
            {
                "name": col,
                "dtype": str(df[col].dtype),
                "role": role,
                "missing": missing,
                "missing_pct": round(100 * missing / n_rows, 2) if n_rows else 0.0,
                "sample_values": [
                    _jsonable(v) for v in df[col].dropna().unique()[:5]
                ],
            }
        )
        if role == "metric":
            metrics.append(col)
        elif role == "date":
            dates.append(col)
        else:
            dimensions.append(col)

    quality_warnings = [
        f"Column '{c['name']}' has {c['missing_pct']}% missing values"
        for c in columns
        if c["missing_pct"] >= 10
    ]

    date_options = {col: _date_options(df[col]) for col in dates}

    return {
        "path": path,
        "n_rows": n_rows,
        "n_cols": len(df.columns),
        "preview": df.head(preview_rows).to_dict(orient="records"),
        "columns": columns,
        "metrics": metrics,
        "dimensions": dimensions,
        "date_fields": dates,
        "date_options": date_options,
        "summary": _summary_text(n_rows, metrics, dimensions, dates),
        "suggested_questions": suggest_questions(metrics, dimensions, dates),
        "quality_warnings": quality_warnings,
    }


def suggest_questions(
    metrics: List[str], dimensions: List[str], dates: List[str]
) -> List[str]:
    """Generate starter questions grounded in the detected schema (PRD Journey 1)."""
    qs: List[str] = []
    if metrics and dates:
        qs.append(f"Show {metrics[0]} trend over time")
    if metrics and dimensions:
        qs.append(f"Which {dimensions[0]} had the highest {metrics[0]}?")
        qs.append(f"Compare {metrics[0]} across {dimensions[0]}")
    if len(metrics) >= 1 and dimensions:
        qs.append(f"What is the share of total {metrics[0]} by {dimensions[0]}?")
    if metrics and dates and dimensions:
        qs.append(
            f"Which {dimensions[0]} had the highest {metrics[0]} growth last period?"
        )
    return qs[:5]


def _summary_text(n_rows, metrics, dimensions, dates) -> str:
    parts = [f"Dataset has {n_rows} rows."]
    if metrics:
        parts.append("Metrics detected: " + ", ".join(metrics) + ".")
    if dimensions:
        parts.append("Dimensions detected: " + ", ".join(dimensions) + ".")
    if dates:
        parts.append("Date fields detected: " + ", ".join(dates) + ".")
    return " ".join(parts)


def _jsonable(v: Any) -> Any:
    try:
        import numpy as np

        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
    except Exception:
        pass
    return v if isinstance(v, (int, float, str, bool)) or v is None else str(v)
