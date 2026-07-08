"""Auto-visualisation layer (PRD 7.5).

Rule-based chart selection (PRD Risk 3 mitigation: deterministic, not LLM-guessed)
plus a Plotly figure/spec builder. The recommender maps a coarse *intent* and the
*shape of the result* to one of a small, safe set of chart types.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

# Intents the copilot can express. The analyst maps a question to one of these.
INTENTS = {
    "trend",       # value over time            -> line
    "ranking",     # top/bottom performers      -> bar
    "comparison",  # category comparison        -> bar
    "share",       # share of total             -> donut
    "correlation", # relationship between metrics-> scatter
    "kpi",         # single number              -> scorecard
    "detail",      # raw rows                   -> table
}

_INTENT_TO_CHART = {
    "trend": "line",
    "ranking": "bar",
    "comparison": "bar",
    "share": "donut",
    "correlation": "scatter",
    "kpi": "scorecard",
    "detail": "table",
}


def recommend_chart(
    intent: Optional[str], result_df: pd.DataFrame, date_cols: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Recommend a chart type from the intent and the result shape.

    Returns a spec: {chart_type, x, y, color, title, reason}. The explicit intent
    wins when given; otherwise we infer from the result shape.
    """
    date_cols = date_cols or []
    cols = list(result_df.columns)
    n_rows, n_cols = result_df.shape

    if intent in _INTENT_TO_CHART:
        chart = _INTENT_TO_CHART[intent]
        reason = f"intent='{intent}'"
    else:
        chart, reason = _infer_from_shape(result_df, date_cols)

    # Single scalar result -> always a scorecard regardless of stated intent.
    if n_rows == 1 and n_cols == 1:
        chart, reason = "scorecard", "single value result"

    x, y, color = _assign_axes(result_df, chart, date_cols)
    return {
        "chart_type": chart,
        "x": x,
        "y": y,
        "color": color,
        "title": _default_title(chart, x, y),
        "reason": reason,
    }


def _infer_from_shape(df: pd.DataFrame, date_cols: List[str]):
    n_rows, n_cols = df.shape
    if n_rows == 1 and n_cols == 1:
        return "scorecard", "single value result"
    has_date = any(c in date_cols for c in df.columns) or _has_temporal(df)
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if has_date and numeric:
        return "line", "temporal column present"
    if len(numeric) >= 2 and n_cols == 2:
        return "scatter", "two numeric columns"
    if n_cols == 2 and numeric:
        return "bar", "one category + one metric"
    return "table", "no clear single-chart shape"


def _has_temporal(df: pd.DataFrame) -> bool:
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return True
        if pd.api.types.is_object_dtype(df[c]):
            parsed = pd.to_datetime(
                df[c].dropna().astype(str).head(10), errors="coerce", format="mixed"
            )
            if len(parsed) and parsed.notna().mean() >= 0.8:
                return True
    return False


def _assign_axes(df: pd.DataFrame, chart: str, date_cols: List[str]):
    cols = list(df.columns)
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    non_numeric = [c for c in cols if c not in numeric]
    if chart == "scorecard":
        return (numeric[0] if numeric else (cols[0] if cols else None)), None, None
    if chart == "scatter":
        x = numeric[0] if numeric else None
        y = numeric[1] if len(numeric) > 1 else None
        return x, y, None
    if chart == "line":
        x = next((c for c in cols if c in date_cols), None) or (
            non_numeric[0] if non_numeric else (cols[0] if cols else None)
        )
        y = numeric[0] if numeric else None
        return x, y, None
    # bar / donut / table
    x = non_numeric[0] if non_numeric else (cols[0] if cols else None)
    y = numeric[0] if numeric else None
    return x, y, None


def _default_title(chart: str, x, y) -> str:
    if chart == "scorecard":
        return str(x) if x else "Result"
    if x and y:
        return f"{y} by {x}"
    return "Result"


def build_figure(spec: Dict[str, Any], df: pd.DataFrame):
    """Build a Plotly figure from a spec. Returns a plotly.graph_objects.Figure.

    Imported lazily so profiling/eval work without plotly installed.
    """
    import plotly.express as px
    import plotly.graph_objects as go

    chart = spec["chart_type"]
    x, y, color, title = spec.get("x"), spec.get("y"), spec.get("color"), spec.get("title")

    if chart == "line":
        return px.line(df, x=x, y=y, color=color, title=title, markers=True)
    if chart == "bar":
        return px.bar(df, x=x, y=y, color=color, title=title)
    if chart == "scatter":
        return px.scatter(df, x=x, y=y, color=color, title=title)
    if chart == "donut":
        return px.pie(df, names=x, values=y, title=title, hole=0.4)
    if chart == "scorecard":
        val = df.iloc[0][x] if x in df.columns else df.iloc[0, 0]
        fig = go.Figure(go.Indicator(mode="number", value=float(val)))
        fig.update_layout(title=title)
        return fig
    # table fallback
    return go.Figure(
        go.Table(
            header=dict(values=list(df.columns)),
            cells=dict(values=[df[c] for c in df.columns]),
        )
    )
