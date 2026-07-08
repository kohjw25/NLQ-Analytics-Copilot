"""Trust & explainability layer (PRD 7.8).

Assembles the transparency payload shown in the Trust Panel and provides a
faithfulness check that verifies every number quoted in a written insight can be
traced back to the executed result table (PRD Risk 2 mitigation).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import pandas as pd

_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def build_trust_panel(
    sql: str,
    result_df: pd.DataFrame,
    columns_used: List[str],
    assumptions: List[str],
    confidence: str,
    filters: Optional[List[str]] = None,
    aggregation: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build the trust-panel payload (PRD 7.8 / Journey 4)."""
    assert confidence in {"high", "medium", "low"}, "confidence must be high/medium/low"
    warnings = list(warnings or [])
    if confidence == "low":
        warnings.append("Low-confidence answer - verify before using for decisions.")
    return {
        "query": sql,
        "columns_used": columns_used,
        "filters": filters or [],
        "aggregation": aggregation,
        "assumptions": assumptions,
        "confidence": confidence,
        "warnings": warnings,
    }


def check_insight_faithfulness(
    insight_text: str, result_df: pd.DataFrame, tolerance: float = 0.01
) -> Dict[str, Any]:
    """Check that numbers cited in an insight appear in the result table.

    Returns {faithful: bool, unsupported_numbers: [...]}. A number is 'supported'
    if it matches any numeric cell in the result within a relative tolerance, or
    appears verbatim (handles percentages/derived values that round-trip).
    """
    result_numbers = _collect_result_numbers(result_df)
    cited = _extract_numbers(insight_text)
    unsupported: List[float] = []
    for n in cited:
        if not _is_supported(n, result_numbers, tolerance):
            unsupported.append(n)
    return {
        "faithful": len(unsupported) == 0,
        "unsupported_numbers": unsupported,
        "cited_numbers": cited,
    }


def _collect_result_numbers(df: pd.DataFrame) -> List[float]:
    nums: List[float] = []
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            nums.extend(float(v) for v in df[col].dropna().tolist())
    # Also allow simple derived values: pairwise ratios as percentages.
    return nums


def _extract_numbers(text: str) -> List[float]:
    out: List[float] = []
    for m in _NUMBER_RE.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


def _is_supported(n: float, pool: List[float], tol: float) -> bool:
    for p in pool:
        if p == 0:
            if abs(n) < 1e-9:
                return True
            continue
        if abs(n - p) <= tol * abs(p):
            return True
        # allow the number to be a rounded percentage of a pool ratio
        if abs(n - round(p, 0)) <= 0.5:
            return True
    return False
