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

import pandas as pd
import streamlit as st

from insight_copilot.profiler import profile_dataset
from insight_copilot.engine import run_sql
from insight_copilot.charts import recommend_chart, build_figure
from insight_copilot.trust import build_trust_panel, check_insight_faithfulness
from insight_copilot.nl2sql import (
    generate_query,
    resolve_provider,
    model_for,
    SUGGESTED_FREE_MODELS,
    SUGGESTED_ANTHROPIC_MODELS,
)
from insight_copilot.evaluate import run_suite

st.set_page_config(page_title="Insight Copilot", page_icon="📊", layout="wide")


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


def _load_dataset(path: str) -> None:
    st.session_state["dataset_path"] = path
    st.session_state["profile"] = profile_dataset(path)
    st.session_state.pop("last_answer", None)


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

def _screen_ask() -> None:
    st.subheader("Ask a question")
    if "profile" not in st.session_state:
        st.info("Load a dataset from the sidebar first.")
        return
    p = st.session_state["profile"]
    path = st.session_state["dataset_path"]

    suggestions = p.get("suggested_questions", [])
    placeholder = suggestions[0] if suggestions else "e.g. Which region had the highest revenue?"
    question = st.text_input("Your question", value="", placeholder=placeholder)
    if st.button("Answer", type="primary") and question.strip():
        with st.spinner("Generating query..."):
            plan = generate_query(question, p, model=st.session_state.get("model"))
        st.session_state["last_answer"] = {"question": question, "plan": plan}

    ans = st.session_state.get("last_answer")
    if not ans:
        return
    plan = ans["plan"]

    # Clarification path (PRD 7.7).
    if plan.clarification and not plan.sql:
        st.warning(f"**Clarification needed:** {plan.clarification}")
        return

    result = run_sql(path, plan.sql)
    if not result.ok:
        st.error(f"Query failed: {result.error}")
        st.code(plan.sql, language="sql")
        return

    df = pd.DataFrame(result.rows)

    # Answer / insight.
    insight = _build_insight(ans["question"], df, plan.intent)
    st.markdown("### Answer")
    st.write(insight)

    # Chart + table.
    col_chart, col_table = st.columns([3, 2])
    spec = recommend_chart(plan.intent, df, date_cols=p["date_fields"])
    with col_chart:
        try:
            st.plotly_chart(build_figure(spec, df), width="stretch")
        except Exception:
            st.dataframe(df, width="stretch")
        st.caption(f"Chart: {spec['chart_type']} ({spec['reason']})")
    with col_table:
        st.dataframe(df, width="stretch")

    # Trust panel (PRD 7.8).
    faith = check_insight_faithfulness(insight, df)
    panel = build_trust_panel(
        sql=plan.sql,
        result_df=df,
        columns_used=plan.columns_used,
        assumptions=plan.assumptions,
        confidence=plan.confidence,
        aggregation=None,
        warnings=[] if faith["faithful"] else ["Insight cites numbers not in the result."],
    )
    with st.expander("How this was calculated"):
        st.markdown(f"**Confidence:** {panel['confidence']}  ·  **Engine:** {plan.backend}")
        st.code(panel["query"], language="sql")
        st.write("**Columns used:**", ", ".join(panel["columns_used"]) or "—")
        st.write("**Assumptions:**")
        for a in panel["assumptions"] or ["None stated."]:
            st.write(f"- {a}")
        for w in panel["warnings"]:
            st.warning(w)


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
    st.subheader("Evaluation dashboard")
    cases = st.text_input("Benchmark cases file", value=DEFAULT_CASES)
    if st.button("Run evaluation", type="primary"):
        with st.spinner("Running benchmark suite..."):
            st.session_state["eval_report"] = run_suite(cases)

    report = st.session_state.get("eval_report")
    if not report:
        st.info("Run the benchmark suite to see query accuracy and failure types.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Pass rate", f"{report['pass_rate'] * 100:.0f}%")
    c2.metric("Cases", report["n_cases"])
    c3.metric("Passed", report["passed"])

    st.markdown("**Per-dimension averages**")
    dims = report["dimension_averages"]
    st.dataframe(
        pd.DataFrame([{"dimension": k, "score": v} for k, v in dims.items()]),
        width="stretch",
    )

    if report["failure_type_counts"]:
        st.markdown("**Failure types**")
        st.bar_chart(pd.Series(report["failure_type_counts"]))

    st.markdown("**Cases**")
    rows = [
        {
            "id": c["id"],
            "question": c["question"],
            "overall": c["overall"],
            "passed": c["passed"],
            "failures": "; ".join(c["failures"]) or "—",
        }
        for c in report["cases"]
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch")


# --- main ---------------------------------------------------------------------

def main() -> None:
    st.title("📊 Insight Copilot")
    st.caption("Ask questions of your data in plain English — validated queries, charts, and insights.")
    _sidebar()
    tab_profile, tab_ask, tab_eval = st.tabs(["Upload & Profile", "Ask", "Evaluation"])
    with tab_profile:
        _screen_profile()
    with tab_ask:
        _screen_ask()
    with tab_eval:
        _screen_eval()


try:
    main()
except Exception as exc:  # noqa: BLE001 -- surface errors instead of a blank screen
    st.error("The app hit an error while rendering. Details below:")
    st.exception(exc)
