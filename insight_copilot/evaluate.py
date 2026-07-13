"""Evaluation harness (PRD 7.9).

Scores a candidate answer against a benchmark case across the PRD's evaluation
dimensions and classifies failure types. Ground truth is expressed as a
``reference_sql`` (the correct logic) rather than hard-coded numbers, so cases
stay valid if the underlying dataset changes.

A case (see benchmarks/cases.yaml):
    id: q2_top_region
    dataset: sample_ecommerce.csv        # relative to the cases file
    question: "Which region had the highest revenue in Q2?"
    reference_sql: "SELECT ... "          # ground-truth logic
    candidate_sql: "SELECT ..."           # the query under test (LLM output)
    expected_chart: bar
    candidate_chart: bar
    insight: "The East region led Q2 with ..."   # optional, faithfulness-checked
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd

from .engine import assert_read_only, make_connection, run_sql_df, UnsafeQueryError
from .trust import check_insight_faithfulness

DIMENSIONS = [
    "query_validity",
    "column_mapping",
    "aggregation_accuracy",
    "filter_accuracy",
    "result_accuracy",
    "chart_relevance",
    "insight_faithfulness",
]


def self_evaluate(
    dataset_path: str,
    profile: Dict[str, Any],
    questions: List[str],
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate the copilot on a user's own dataset (no ground-truth answers).

    For each question it generates a query and runs it against ``dataset_path``,
    then reports how many produced a valid, non-empty answer. Because there are no
    expected answers for an arbitrary upload, this measures reliability (does the
    generated query use real columns, run, and return rows?) rather than exact
    correctness. Column validity is enforced implicitly: DuckDB errors on unknown
    columns, so an execution error means the query referenced something invalid.
    """
    from .nl2sql import generate_query
    from .engine import run_sql

    results: List[Dict[str, Any]] = []
    for q in questions:
        row: Dict[str, Any] = {"question": q}
        try:
            plan = generate_query(q, profile, model=model)
            row["intent"] = plan.intent
            row["backend"] = plan.backend
            if plan.clarification and not plan.sql:
                row.update(status="clarify", ok=False, n_rows=0,
                           detail=plan.clarification, sql=None)
            else:
                res = run_sql(dataset_path, plan.sql)
                row["sql"] = plan.sql
                row["ok"] = res.ok
                row["n_rows"] = res.n_rows
                if not res.ok:
                    row.update(status="error", detail=res.error)
                elif res.n_rows == 0:
                    row.update(status="empty", detail="Query ran but returned no rows.")
                else:
                    row.update(status="ok", detail="")
        except Exception as exc:  # noqa: BLE001 -- one bad question shouldn't stop the run
            row.update(status="error", ok=False, n_rows=0, sql=row.get("sql"),
                       detail=f"{type(exc).__name__}: {exc}")
        results.append(row)

    n = len(results)
    pct = lambda c: round(100 * c / n, 1) if n else 0.0  # noqa: E731
    counts = {"ok": 0, "empty": 0, "error": 0, "clarify": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    failure_type_counts = {k: v for k, v in counts.items() if k != "ok" and v}

    return {
        "dataset": dataset_path,
        "n_questions": n,
        "answered": counts["ok"],
        "answered_pct": pct(counts["ok"]),
        "executed_ok": counts["ok"] + counts["empty"],
        "executed_pct": pct(counts["ok"] + counts["empty"]),
        "empty": counts["empty"],
        "errored": counts["error"],
        "clarify": counts["clarify"],
        "failure_type_counts": failure_type_counts,
        "results": results,
    }


def load_cases(cases_path: str) -> List[Dict[str, Any]]:
    import yaml

    with open(cases_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["cases"] if isinstance(data, dict) else data


def evaluate_case(case: Dict[str, Any], base_dir: str) -> Dict[str, Any]:
    """Evaluate one benchmark case and return a scored report."""
    dataset = os.path.join(base_dir, case["dataset"])
    reference_sql = case["reference_sql"]
    candidate_sql = case.get("candidate_sql", reference_sql)

    scores: Dict[str, Optional[float]] = {d: None for d in DIMENSIONS}
    failures: List[str] = []

    con = make_connection(dataset)
    try:
        # 1. Query validity — does the candidate run at all?
        try:
            assert_read_only(candidate_sql)
            cand_df = con.execute(candidate_sql).fetchdf()
            scores["query_validity"] = 1.0
        except Exception as exc:  # noqa: BLE001 -- UnsafeQueryError is an Exception
            scores["query_validity"] = 0.0
            failures.append(f"invalid_query: {exc}")
            return _finalise(case, scores, failures)

        # A malformed reference query is this case's failure, not a suite-wide crash.
        try:
            ref_df = con.execute(reference_sql).fetchdf()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"bad_reference_sql: {exc}")
            return _finalise(case, scores, failures)

        # 2. Column mapping — did the candidate reference the expected columns?
        scores["column_mapping"] = _column_mapping_score(candidate_sql, ref_df, case)
        if scores["column_mapping"] < 1.0:
            failures.append("wrong_or_missing_column")

        # 3+4+5. Result accuracy (covers aggregation + filter correctness end-to-end).
        result_match = _frames_equivalent(cand_df, ref_df)
        scores["result_accuracy"] = 1.0 if result_match else 0.0
        # Aggregation / filter are diagnostic sub-scores derived from the mismatch.
        scores["aggregation_accuracy"] = 1.0 if result_match else _agg_score(cand_df, ref_df)
        scores["filter_accuracy"] = 1.0 if result_match else _filter_score(cand_df, ref_df)
        if not result_match:
            failures.extend(_classify_result_failure(cand_df, ref_df))

        # 6. Chart relevance.
        expected_chart = case.get("expected_chart")
        candidate_chart = case.get("candidate_chart", expected_chart)
        if expected_chart is not None:
            scores["chart_relevance"] = 1.0 if candidate_chart == expected_chart else 0.0
            if scores["chart_relevance"] == 0.0:
                failures.append(
                    f"wrong_chart: got '{candidate_chart}', expected '{expected_chart}'"
                )

        # 7. Insight faithfulness.
        insight = case.get("insight")
        if insight:
            faith = check_insight_faithfulness(insight, cand_df)
            scores["insight_faithfulness"] = 1.0 if faith["faithful"] else 0.0
            if not faith["faithful"]:
                failures.append(
                    f"unsupported_insight: numbers {faith['unsupported_numbers']} not in result"
                )

        return _finalise(case, scores, failures)
    finally:
        con.close()


def _finalise(case, scores, failures) -> Dict[str, Any]:
    graded = [v for v in scores.values() if v is not None]
    overall = round(sum(graded) / len(graded), 3) if graded else 0.0
    return {
        "id": case.get("id"),
        "question": case.get("question"),
        "scores": scores,
        "overall": overall,
        "passed": overall >= 1.0 and not failures,
        "failures": failures,
    }


def run_suite(cases_path: str) -> Dict[str, Any]:
    """Run every case and return an aggregate report."""
    base_dir = os.path.dirname(os.path.abspath(cases_path))
    cases = load_cases(cases_path)
    results = [evaluate_case(c, base_dir) for c in cases]
    passed = sum(1 for r in results if r["passed"])
    failure_counts: Dict[str, int] = {}
    for r in results:
        for f in r["failures"]:
            key = f.split(":")[0]
            failure_counts[key] = failure_counts.get(key, 0) + 1
    dim_avgs = {}
    for d in DIMENSIONS:
        vals = [r["scores"][d] for r in results if r["scores"][d] is not None]
        dim_avgs[d] = round(sum(vals) / len(vals), 3) if vals else None
    return {
        "n_cases": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else 0.0,
        "dimension_averages": dim_avgs,
        "failure_type_counts": failure_counts,
        "cases": results,
    }


# --- comparison helpers -------------------------------------------------------

def _frames_equivalent(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    if a.shape != b.shape:
        return False
    try:
        aa = a.reset_index(drop=True)
        bb = b.reset_index(drop=True)
        # Order matters for ranking questions, so compare positionally.
        aa.columns = range(len(aa.columns))
        bb.columns = range(len(bb.columns))
        # check_dtype=False so a COUNT (int) matches a SUM (float) of equal value;
        # atol tolerates float rounding without the brittle pre-round + exact equals.
        pd.testing.assert_frame_equal(
            aa, bb, check_dtype=False, check_exact=False, atol=1e-4, rtol=0
        )
        return True
    except Exception:
        return False


def _column_mapping_score(sql: str, ref_df: pd.DataFrame, case) -> float:
    expected = case.get("expected_columns") or list(ref_df.columns)
    low = sql.lower()
    hits = sum(1 for c in expected if str(c).lower() in low)
    return round(hits / len(expected), 3) if expected else 1.0


def _agg_score(a: pd.DataFrame, b: pd.DataFrame) -> float:
    # If the shapes match but values differ, aggregation is the likely culprit.
    return 0.5 if a.shape == b.shape else 0.0


def _filter_score(a: pd.DataFrame, b: pd.DataFrame) -> float:
    # Different row counts usually means a filter (e.g. date range) was wrong.
    return 0.0 if a.shape[0] != b.shape[0] else 0.5


def _classify_result_failure(a: pd.DataFrame, b: pd.DataFrame) -> List[str]:
    out = []
    if a.shape[0] != b.shape[0]:
        out.append("wrong_filter_or_grouping: row count differs")
    elif a.shape[1] != b.shape[1]:
        out.append("wrong_projection: column count differs")
    else:
        # Same shape, different values: check if it's just reversed sort order.
        try:
            if _frames_equivalent(a.iloc[::-1], b):
                out.append("wrong_sort_order")
            else:
                out.append("wrong_aggregation_or_values")
        except Exception:
            out.append("wrong_aggregation_or_values")
    return out
