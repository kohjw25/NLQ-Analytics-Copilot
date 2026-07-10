"""Insight Copilot -- Streamlit prototype (PRD sections 10 & 11).

Screens:
  1. Upload & Profile     -- upload CSV/Excel, preview, field summary, starter questions
  2. Ask (Chat-to-Insight)-- NL question -> SQL -> table + chart + insight + trust panel
  3. Evaluation Dashboard -- run the benchmark harness, show scores and failure types

Run:  streamlit run insight_copilot/app.py
The NL->SQL step uses Claude when ANTHROPIC_API_KEY is set; otherwise a rule-based
fallback keeps the app fully functional offline.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date

import pandas as pd
import streamlit as st

from insight_copilot.profiler import profile_dataset
from insight_copilot.engine import run_sql
from insight_copilot.charts import recommend_chart, build_figure, CHART_TYPES
from insight_copilot.trust import build_trust_panel, check_insight_faithfulness
from insight_copilot.nl2sql import (
    generate_query,
    apply_aggregation,
    resolve_provider,
    model_for,
    SUGGESTED_FREE_MODELS,
    SUGGESTED_ANTHROPIC_MODELS,
)

from insight_copilot.evaluate import run_suite, self_evaluate

# Aggregation choices for the Ask tab. Maps the UI label to the SQL function
# (None = leave the query's default: sum, or average for rate columns).
_AGG_OPTIONS = {
    "Auto (sum / avg for rates)": None,
    "Sum": "sum",
    "Average": "avg",
    "Minimum": "min",
    "Maximum": "max",
}

# Chart-type choices for the Ask tab's manual override. Label -> internal type.
_CHART_LABELS = {
    "Auto (recommended)": "auto",
    "Line": "line",
    "Area": "area",
    "Bar (grouped)": "bar",
    "Stacked bar": "stacked_bar",
    "Horizontal bar": "hbar",
    "Scatter": "scatter",
    "Donut": "donut",
    "Pie": "pie",
    "Histogram": "histogram",
    "Box": "box",
    "Table": "table",
}

# Rows shown in the dataset preview on the home screen.
PREVIEW_ROWS = 100

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

st.set_page_config(page_title="Analytics Copilot", page_icon="📊", layout="wide")


def _bridge_secrets_to_env() -> None:
    """Copy Streamlit secrets into env vars so provider selection (which reads
    os.environ) works on Streamlit Community Cloud, where keys come from the
    Secrets UI rather than shell env vars. No-op when no secrets file exists."""
    try:
        for k in (
            "OPENROUTER_API_KEY",
            "ANTHROPIC_API_KEY",
            "INSIGHT_COPILOT_MODEL",
            "INSIGHT_COPILOT_PROVIDER",
        ):
            if k in st.secrets and k not in os.environ:
                os.environ[k] = str(st.secrets[k])
    except Exception:
        pass


_bridge_secrets_to_env()

BENCH_DIR = os.path.join(os.path.dirname(__file__), "benchmarks")
SAMPLE_CSV = os.path.join(BENCH_DIR, "sample_ecommerce.csv")
DEFAULT_CASES = os.path.join(BENCH_DIR, "cases.yaml")


# --- dataset loading ----------------------------------------------------------

def _persist_upload(uploaded) -> str:
    """Write an uploaded file to a temp path so DuckDB can read it, return the path."""
    suffix = os.path.splitext(uploaded.name)[1] or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded.getbuffer())
    tmp.close()
    return tmp.name


# Ask-tab widget keys whose valid options depend on the dataset or the current
# result. Cleared on reset AND on dataset load — otherwise a value stored for one
# dataset/query can be absent from the next one's options, which crashes the
# selectbox/multiselect at render time.
_ASK_WIDGET_PREFIXES = (
    "ask_question", "ask_agg", "ask_chart", "ask_metric", "ask_swap",
    "ask_datecol", "ask_years::", "ask_months::", "ask_use_range::", "ask_range::",
)


def _clear_ask_state() -> None:
    """Drop the last answer and every Ask-tab widget's stored state."""
    for key in [k for k in st.session_state if k.startswith(_ASK_WIDGET_PREFIXES)]:
        del st.session_state[key]
    st.session_state.pop("last_answer", None)


def _load_dataset(path: str) -> None:
    st.session_state["dataset_path"] = path
    st.session_state["profile"] = profile_dataset(path, preview_rows=PREVIEW_ROWS)
    # Reset Ask-tab widgets so options from a previous dataset can't linger and
    # crash the next query (e.g. a date field / metric that no longer exists).
    _clear_ask_state()


def _sidebar() -> None:
    st.sidebar.header("Dataset")
    uploaded = st.sidebar.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"])
    if uploaded is not None:
        if st.session_state.get("uploaded_name") != uploaded.name:
            st.session_state["uploaded_name"] = uploaded.name
            _load_dataset(_persist_upload(uploaded))
    if os.path.exists(SAMPLE_CSV):
        if st.sidebar.button("Use sample e-commerce dataset"):
            _load_dataset(SAMPLE_CSV)
    if "dataset_path" in st.session_state:
        st.sidebar.success(os.path.basename(st.session_state["dataset_path"]))

    st.sidebar.divider()
    st.sidebar.header("Query engine")
    _model_picker(resolve_provider())


def _model_picker(provider: str) -> None:
    """Sidebar control to pick the LLM model. Stores the choice in session state
    as 'model'; the Ask screen passes it to generate_query()."""
    if provider == "heuristic":
        st.sidebar.info(
            "No API key set — using the offline rule-based generator.\n\n"
            "Set **OPENROUTER_API_KEY** (free models at openrouter.ai) or "
            "**ANTHROPIC_API_KEY** to enable an LLM."
        )
        st.session_state.pop("model", None)
        return

    if provider == "openrouter":
        options = list(SUGGESTED_FREE_MODELS)
        current = model_for(provider)
        if current not in options:
            options.insert(0, current)
        options.append("(custom…)")
        choice = st.sidebar.selectbox(
            "OpenRouter model", options, index=options.index(current),
            help="Models ending in ':free' are free. Browse the live list at "
            "openrouter.ai/models?max_price=0",
        )
        model = (
            st.sidebar.text_input("Custom model id", value=current)
            if choice == "(custom…)"
            else choice
        )
        st.session_state["model"] = model
        st.sidebar.caption(f"Active: openrouter · {model}")
    elif provider == "anthropic":
        options = list(SUGGESTED_ANTHROPIC_MODELS)
        current = model_for(provider)
        if current not in options:
            options.insert(0, current)
        model = st.sidebar.selectbox("Claude model", options, index=options.index(current))
        st.session_state["model"] = model
        st.sidebar.caption(f"Active: anthropic · {model}")


# --- Screen 1: Upload & Profile ----------------------------------------------

def _screen_profile() -> None:
    st.subheader("Dataset profile")
    if "profile" not in st.session_state:
        st.info("Upload a dataset or load the sample from the sidebar to begin.")
        return
    p = st.session_state["profile"]
    st.write(p["summary"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", p["n_rows"])
    c2.metric("Columns", p["n_cols"])
    c3.metric("Date fields", len(p["date_fields"]))

    st.markdown("**Preview**")
    st.dataframe(pd.DataFrame(p["preview"]), width="stretch")

    st.markdown("**Detected fields**")
    st.dataframe(
        pd.DataFrame(p["columns"])[["name", "dtype", "role", "missing_pct"]],
        width="stretch",
    )

    if p["quality_warnings"]:
        for w in p["quality_warnings"]:
            st.warning(w)

    st.markdown("**Suggested starter questions**")
    for q in p["suggested_questions"]:
        st.write(f"- {q}")


# --- Screen 2: Ask ------------------------------------------------------------

def _reset_ask() -> None:
    """Clear the Ask tab for a fresh query: the last result, the question box, and
    every Ask-tab widget (aggregation, chart type, metric/axis, date field + filters)."""
    _clear_ask_state()


def _screen_ask() -> None:
    st.subheader("Ask a question")
    if "profile" not in st.session_state:
        st.info("Load a dataset from the sidebar first.")
        return
    p = st.session_state["profile"]
    path = st.session_state["dataset_path"]

    suggestions = p.get("suggested_questions", [])
    placeholder = suggestions[0] if suggestions else "e.g. Which region had the highest revenue?"
    question = st.text_input("Your question", key="ask_question", placeholder=placeholder)

    # Date settings — which date field to aggregate/filter by, plus an optional
    # year/month filter. Always visible when the dataset has date columns, and the
    # chosen field is passed to query generation (so monthly/weekly grouping uses it).
    agg_date, date_filter, filter_desc = _date_controls(p)

    b_answer, b_reset = st.columns([1, 1])
    with b_answer:
        answer_clicked = st.button("Answer", type="primary", width="stretch")
    with b_reset:
        st.button("New query", on_click=_reset_ask, width="stretch",
                  help="Clear the question, filters and result to start fresh.")

    if answer_clicked and question.strip():
        with st.spinner("Generating query..."):
            plan = generate_query(
                question, p, model=st.session_state.get("model"), date_column=agg_date
            )
        st.session_state["last_answer"] = {"question": question, "plan": plan}

    ans = st.session_state.get("last_answer")
    if not ans:
        return
    plan = ans["plan"]

    # Clarification path (PRD 7.7).
    if plan.clarification and not plan.sql:
        st.warning(f"**Clarification needed:** {plan.clarification}")
        return

    # Visual controls — aggregation (rewrites SUM/AVG/MIN/MAX in the query without
    # re-calling the model) and a manual chart-type override.
    ctrl_agg, ctrl_chart = st.columns(2)
    with ctrl_agg:
        agg_label = st.selectbox(
            "Aggregate metrics using",
            list(_AGG_OPTIONS),
            key="ask_agg",
            help="Applies to the numeric metric columns. 'Auto' uses sum (average "
            "for rate columns such as a 0/1 flag).",
        )
    with ctrl_chart:
        chart_label = st.selectbox(
            "Chart type", list(_CHART_LABELS), key="ask_chart",
            help="'Auto' picks a suitable chart; override it to explore other views.",
        )
    sql = apply_aggregation(plan.sql, _AGG_OPTIONS[agg_label])

    result = run_sql(path, sql, date_filter=date_filter)
    if not result.ok:
        st.error(f"Query failed: {result.error}")
        st.code(sql, language="sql")
        return

    df = pd.DataFrame(result.rows)

    # Answer / insight.
    insight = _build_insight(ans["question"], df, plan.intent)
    st.markdown("### Answer")
    st.write(insight)

    # Summary KPI tiles — dataset-level totals for every detected metric, shown
    # after each query for quick reference regardless of what the query selected.
    _kpi_tiles(path, p, date_filter)

    spec = recommend_chart(
        plan.intent, df, date_cols=p["date_fields"], chart_type=_CHART_LABELS[chart_label]
    )

    # Display controls — which metric the chart plots, and axis swap.
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    disp_metric, disp_swap = st.columns(2)
    with disp_metric:
        if len(numeric_cols) > 1:
            metric_field = "x" if spec["chart_type"] == "histogram" else "y"
            current = spec.get(metric_field)
            default_idx = numeric_cols.index(current) if current in numeric_cols else 0
            # Drop a stale selection from a previous, differently-shaped result so
            # the selectbox never receives a stored value outside its options.
            if st.session_state.get("ask_metric") not in numeric_cols:
                st.session_state.pop("ask_metric", None)
            chosen = st.selectbox(
                "Metric shown in chart", numeric_cols, index=default_idx, key="ask_metric",
                help="The chart plots one metric; the table still shows all of them.",
            )
            spec[metric_field] = chosen
            other = spec.get("x") if metric_field == "y" else spec.get("y")
            spec["title"] = f"{chosen} by {other}" if other else chosen
    with disp_swap:
        swap = st.toggle("Swap X / Y axis", key="ask_swap")

    # Chart + table.
    col_chart, col_table = st.columns([3, 2])
    with col_chart:
        try:
            st.plotly_chart(
                build_figure(spec, df, template="plotly_white", swap=swap), width="stretch"
            )
        except Exception:
            st.dataframe(df, width="stretch")
        st.caption(f"Chart: {spec['chart_type']} ({spec['reason']})")
    with col_table:
        st.dataframe(df, width="stretch")

    # Trust panel (PRD 7.8).
    faith = check_insight_faithfulness(insight, df)
    panel = build_trust_panel(
        sql=sql,
        result_df=df,
        columns_used=plan.columns_used,
        assumptions=plan.assumptions,
        confidence=plan.confidence,
        aggregation=agg_label,
        filters=[filter_desc] if filter_desc else [],
        warnings=[] if faith["faithful"] else ["Insight cites numbers not in the result."],
    )
    with st.expander("How this was calculated"):
        st.markdown(f"**Confidence:** {panel['confidence']}  ·  **Engine:** {plan.backend}")
        st.write("**Aggregation:**", panel["aggregation"])
        st.write("**Filters:**", "; ".join(panel["filters"]) or "none")
        st.code(panel["query"], language="sql")
        st.write("**Columns used:**", ", ".join(panel["columns_used"]) or "—")
        st.write("**Assumptions:**")
        for a in panel["assumptions"] or ["None stated."]:
            st.write(f"- {a}")
        for w in panel["warnings"]:
            st.warning(w)


def _kpi_tiles(path, profile, date_filter) -> None:
    """Render one KPI tile per detected metric (dataset-level, respecting the date
    filter). Shown after every query so key totals are always at hand, whether or
    not the current query includes them. Uses AVG for rate metrics, else SUM."""
    from insight_copilot.nl2sql import _is_rate_metric

    metrics = profile.get("metrics", [])
    if not metrics:
        return
    exprs = [
        f'{"AVG" if _is_rate_metric(m, profile) else "SUM"}("{m}") AS "{m}"'
        for m in metrics[:8]
    ]
    res = run_sql(path, "SELECT " + ", ".join(exprs) + " FROM data", date_filter=date_filter)
    if not res.ok or not res.rows:
        return
    items = list(res.rows[0].items())
    scope = " (filtered)" if date_filter else ""
    st.markdown(f"#### Summary metrics{scope}")
    for start_i in range(0, len(items), 4):
        chunk = items[start_i : start_i + 4]
        for c, (name, val) in zip(st.columns(len(chunk)), chunk):
            try:
                c.metric(name, f"{float(val):,.2f}")
            except (TypeError, ValueError):
                c.metric(name, "—" if val is None else str(val))


def _date_controls(profile):
    """Date field + optional year/month filter for the loaded dataset.

    Returns (agg_date_column, date_filter dict|None, filter description). The
    chosen date column governs both time aggregation (passed to query generation)
    and the row filter, so datasets with several date fields can pick which one.
    """
    date_fields = profile.get("date_fields", [])
    if not date_fields:
        return None, None, ""

    # Always render the date-field dropdown (even for a single date field) so the
    # column driving aggregation/filtering is explicit and selectable in the
    # visualisation area, not hidden when there's only one candidate.
    col = st.selectbox(
        "Date field to use", date_fields, key="ask_datecol",
        help="Which date column to aggregate by (monthly/weekly) and filter on.",
    )

    opts = profile.get("date_options", {}).get(col, {})
    start = end = None
    with st.expander("📅 Date filter (optional)"):
        st.caption(f"Aggregation and filtering use **{col}**.")
        c_year, c_month = st.columns(2)
        # Key widgets per-column so switching date columns doesn't carry over a
        # selection that isn't valid for the new column's options.
        with c_year:
            years = st.multiselect("Year(s)", opts.get("years", []), key=f"ask_years::{col}")
        with c_month:
            month_nums = opts.get("months") or list(range(1, 13))
            months = st.multiselect(
                "Month(s)", month_nums, key=f"ask_months::{col}",
                format_func=lambda m: _MONTHS[m - 1],
            )
        # Date-range picker: restrict analysis to an exact window (inclusive).
        lo, hi = opts.get("min"), opts.get("max")
        if lo and hi:
            lo_d, hi_d = date.fromisoformat(lo), date.fromisoformat(hi)
            use_range = st.checkbox("Filter by date range", key=f"ask_use_range::{col}")
            if use_range:
                picked = st.date_input(
                    "Date range", value=(lo_d, hi_d), min_value=lo_d, max_value=hi_d,
                    key=f"ask_range::{col}",
                    help="Only rows whose date falls in this window are analysed.",
                )
                if isinstance(picked, (tuple, list)) and len(picked) == 2:
                    start, end = picked[0].isoformat(), picked[1].isoformat()

    if not years and not months and not start and not end:
        return col, None, ""
    parts = []
    if start or end:
        parts.append(f"{start or lo} to {end or hi}")
    if years:
        parts.append("year " + ", ".join(str(y) for y in years))
    if months:
        parts.append("month " + ", ".join(_MONTHS[m - 1] for m in months))
    date_filter = {"column": col, "years": years, "months": months, "start": start, "end": end}
    return col, date_filter, f"{col}: " + "; ".join(parts)


def _build_insight(question: str, df: pd.DataFrame, intent: str) -> str:
    """A concise, faithful insight built only from the result rows (PRD 7.6)."""
    if df.empty:
        return "The query returned no rows."
    if df.shape == (1, 1):
        return f"The result is **{df.iloc[0, 0]}**."
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cat_cols = [c for c in df.columns if c not in num_cols]
    if num_cols and cat_cols:
        m, d = num_cols[-1], cat_cols[0]
        top = df.sort_values(m, ascending=False).iloc[0]
        bottom = df.sort_values(m, ascending=False).iloc[-1]
        parts = [f"**{top[d]}** leads with {m} of {top[m]:,.2f}."]
        if len(df) > 1:
            parts.append(f"**{bottom[d]}** is lowest at {bottom[m]:,.2f}.")
        if intent == "trend":
            first, last = df.iloc[0], df.iloc[-1]
            parts = [f"{m} moved from {first[m]:,.2f} to {last[m]:,.2f} across the period."]
        return " ".join(parts)
    return f"Returned {len(df)} rows across {len(df.columns)} columns."


# --- Screen 3: Evaluation Dashboard ------------------------------------------

def _screen_eval() -> None:
    st.subheader("Evaluation")
    if "profile" not in st.session_state:
        st.info("Load a dataset from the sidebar first — the evaluation runs against it.")
        return
    p = st.session_state["profile"]
    path = st.session_state["dataset_path"]
    st.caption(f"Evaluating the copilot on: **{os.path.basename(path)}**")
    st.write(
        "Each question below is turned into a query and run against *your* dataset. "
        "This measures reliability — do the generated queries use real columns, run, "
        "and return rows? (Exact-answer scoring needs known correct answers, which "
        "only exist for the built-in benchmark; see the expander below.)"
    )

    default_qs = "\n".join(p.get("suggested_questions", []))
    qs_text = st.text_area(
        "Questions to evaluate (one per line)", value=default_qs, height=170,
        help="Prefilled from your dataset's suggested questions — edit freely.",
    )
    questions = [q.strip() for q in qs_text.splitlines() if q.strip()]
    if resolve_provider() != "heuristic":
        st.caption("⚠️ An LLM backend is active, so each question calls the model — "
                   "keep the list short (free models are slow).")

    if st.button("Run evaluation", type="primary") and questions:
        with st.spinner(f"Evaluating {len(questions)} question(s) on your dataset..."):
            st.session_state["eval_report"] = self_evaluate(
                path, p, questions, model=st.session_state.get("model")
            )

    report = st.session_state.get("eval_report")
    if report and report.get("dataset") == path:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Questions", report["n_questions"])
        c2.metric("Answered", f"{report['answered_pct']}%")
        c3.metric("Ran OK", f"{report['executed_pct']}%")
        c4.metric("Clarifications", report["clarify"])

        if report["failure_type_counts"]:
            st.markdown("**Issues by type**")
            st.bar_chart(pd.Series(report["failure_type_counts"]))

        st.markdown("**Per-question results**")
        rows = [
            {
                "question": r["question"],
                "status": r["status"],
                "intent": r.get("intent", ""),
                "rows": r.get("n_rows", 0),
                "detail": (r.get("detail") or "")[:90],
            }
            for r in report["results"]
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch")
    else:
        st.info("Enter questions and click **Run evaluation**.")

    with st.expander("Advanced: run the built-in benchmark suite (sample dataset, scored vs. known answers)"):
        st.caption(
            "This is the fixed accuracy benchmark with hand-written correct answers "
            "for the sample e-commerce data — it does not use your uploaded dataset."
        )
        if st.button("Run benchmark suite"):
            with st.spinner("Running benchmark suite..."):
                st.session_state["bench_report"] = run_suite(DEFAULT_CASES)
        bench = st.session_state.get("bench_report")
        if bench:
            b1, b2, b3 = st.columns(3)
            b1.metric("Pass rate", f"{bench['pass_rate'] * 100:.0f}%")
            b2.metric("Cases", bench["n_cases"])
            b3.metric("Passed", bench["passed"])
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "id": c["id"],
                            "question": c["question"],
                            "overall": c["overall"],
                            "passed": c["passed"],
                            "failures": "; ".join(c["failures"]) or "—",
                        }
                        for c in bench["cases"]
                    ]
                ),
                width="stretch",
            )


# --- main ---------------------------------------------------------------------

def main() -> None:
    st.title("📊 Analytics Copilot")
    st.subheader("Derive insights without code")
    st.caption(
        "Upload a spreadsheet, ask questions in plain English, and get validated "
        "tables, charts, and written insights — no SQL or BI skills required. Load a "
        "dataset from the sidebar to begin."
    )
    _sidebar()
    tab_profile, tab_ask, tab_eval = st.tabs(["Upload & Profile", "Ask", "Evaluation"])
    with tab_profile:
        _screen_profile()
    with tab_ask:
        _screen_ask()
    with tab_eval:
        _screen_eval()


def run() -> None:
    """Render the app, surfacing errors instead of a blank screen.

    Must be CALLED on every Streamlit run. Do not rely on import side effects:
    the deployment entrypoint (streamlit_app.py) imports this module once, so a
    bottom-of-module main() call would only render on first load and blank on
    every rerun.
    """
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- surface errors instead of a blank screen
        st.error("The app hit an error while rendering. Details below:")
        st.exception(exc)


if __name__ == "__main__":
    # Runs when launched directly: `streamlit run insight_copilot/app.py`.
    run()
