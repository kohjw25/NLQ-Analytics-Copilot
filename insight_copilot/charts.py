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

# All chart types the builder supports (used by the UI's manual chart-type picker).
CHART_TYPES = [
    "line", "area", "bar", "stacked_bar", "hbar",
    "scatter", "donut", "pie", "histogram", "box", "scorecard", "table",
]


def recommend_chart(
    intent: Optional[str],
    result_df: pd.DataFrame,
    date_cols: Optional[List[str]] = None,
    chart_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Recommend a chart type from the intent and the result shape.

    Returns a spec: {chart_type, x, y, color, title, reason}. If ``chart_type`` is
    given (and not 'auto'), it overrides the recommendation so users can switch the
    visual manually; axes are re-derived for the chosen type.
    """
    date_cols = date_cols or []
    n_rows, n_cols = result_df.shape

    if chart_type and chart_type != "auto":
        chart, reason = chart_type, "manual selection"
    elif intent in _INTENT_TO_CHART:
        chart = _INTENT_TO_CHART[intent]
        reason = f"intent='{intent}'"
    else:
        chart, reason = _infer_from_shape(result_df, date_cols)

    # Single scalar result -> a scorecard, unless the user forced another type.
    if n_rows == 1 and n_cols == 1 and (not chart_type or chart_type == "auto"):
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


def _series_is_temporal(series: pd.Series, name: str, date_cols: List[str]) -> bool:
    if name in date_cols:
        return True
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if pd.api.types.is_object_dtype(series):
        sample = series.dropna().astype(str).head(10)
        if len(sample):
            parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
            return parsed.notna().mean() >= 0.8
    return False


_LINE_LIKE = {"line", "area"}
_BAR_LIKE = {"bar", "stacked_bar", "hbar"}
_PIE_LIKE = {"donut", "pie"}


def _assign_axes(df: pd.DataFrame, chart: str, date_cols: List[str]):
    """Return (x, y, color). A second categorical column becomes the colour/series
    dimension so results grouped by two dimensions (e.g. month x category) render
    as multiple lines / grouped bars instead of collapsing into one series."""
    cols = list(df.columns)
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    non_numeric = [c for c in cols if c not in numeric]
    temporal = [c for c in non_numeric if _series_is_temporal(df[c], c, date_cols)]
    first_num = numeric[0] if numeric else None
    first_cat = non_numeric[0] if non_numeric else (cols[0] if cols else None)

    def secondary_category(x_col):
        remaining = [c for c in non_numeric if c != x_col]
        return remaining[0] if remaining else None

    if chart == "scorecard":
        return first_num or first_cat, None, None
    if chart == "scatter":
        return first_num, (numeric[1] if len(numeric) > 1 else None), None
    if chart == "histogram":
        # Distribution of one metric, optionally split by a category.
        return first_num or first_cat, None, (first_cat if first_num else None)
    if chart == "box":
        return (non_numeric[0] if non_numeric else None), first_num, secondary_category(non_numeric[0] if non_numeric else None)

    y = first_num
    if chart in _LINE_LIKE:
        x = temporal[0] if temporal else first_cat
    else:  # bar-like / pie-like / table
        x = first_cat

    color = None
    if chart in _LINE_LIKE or chart in _BAR_LIKE:
        color = secondary_category(x)
    return x, y, color


def _default_title(chart: str, x, y) -> str:
    if chart == "scorecard":
        return str(x) if x else "Result"
    if x and y:
        return f"{y} by {x}"
    return "Result"


def build_figure(
    spec: Dict[str, Any],
    df: pd.DataFrame,
    template: Optional[str] = None,
    swap: bool = False,
):
    """Build a Plotly figure from a spec. Returns a plotly.graph_objects.Figure.

    ``template`` selects a Plotly theme (e.g. 'plotly_dark' for dark mode).
    ``swap`` exchanges the x and y axes (e.g. vertical bars <-> horizontal).
    Imported lazily so profiling/eval work without plotly installed. Falls back to
    a table if the chosen chart can't be built from the columns available.
    """
    import plotly.express as px
    import plotly.graph_objects as go

    chart = spec["chart_type"]
    x, y, color, title = spec.get("x"), spec.get("y"), spec.get("color"), spec.get("title")
    kw: Dict[str, Any] = {"title": title}
    if template:
        kw["template"] = template
    ex, ey = (y, x) if swap else (x, y)  # effective axes for x/y charts

    try:
        if chart == "line":
            return px.line(df, x=ex, y=ey, color=color, markers=True, **kw)
        if chart == "area":
            return px.area(df, x=ex, y=ey, color=color, **kw)
        if chart in ("bar", "stacked_bar"):
            barmode = "stack" if chart == "stacked_bar" else "group"
            if swap:
                return px.bar(df, x=y, y=x, color=color, orientation="h", barmode=barmode, **kw)
            return px.bar(df, x=x, y=y, color=color, barmode=barmode, **kw)
        if chart == "hbar":
            if swap:  # hbar is horizontal by default; swap makes it vertical
                return px.bar(df, x=x, y=y, color=color, barmode="group", **kw)
            return px.bar(df, x=y, y=x, color=color, orientation="h", barmode="group", **kw)
        if chart == "scatter":
            return px.scatter(df, x=ex, y=ey, color=color, **kw)
        if chart == "donut":
            return px.pie(df, names=x, values=y, hole=0.4, **kw)
        if chart == "pie":
            return px.pie(df, names=x, values=y, **kw)
        if chart == "histogram":
            return px.histogram(df, x=x, color=color, **kw)
        if chart == "box":
            return px.box(df, x=ex, y=ey, color=color, **kw)
        if chart == "scorecard":
            val = df.iloc[0][x] if x in df.columns else df.iloc[0, 0]
            fig = go.Figure(go.Indicator(mode="number", value=float(val)))
            fig.update_layout(title=title, template=template)
            return fig
    except Exception:
        pass  # fall through to a table if the chosen chart doesn't fit the data

    fig = go.Figure(
        go.Table(
            header=dict(values=list(df.columns)),
            cells=dict(values=[df[c] for c in df.columns]),
        )
    )
    fig.update_layout(template=template)
    return fig
