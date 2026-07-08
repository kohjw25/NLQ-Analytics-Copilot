"""Insight Copilot engine — deterministic core for the NL-to-insight analytics copilot.

Public API mirrors the PRD layers:
    profiler  : profile_dataset, suggest_questions        (PRD 7.1)
    engine    : run_sql, make_connection, assert_read_only (PRD 7.3/7.4)
    charts    : recommend_chart, build_figure             (PRD 7.5)
    trust     : build_trust_panel, check_insight_faithfulness (PRD 7.8)
    evaluate  : run_suite, evaluate_case                   (PRD 7.9)
"""
from .profiler import profile_dataset, suggest_questions, load_dataframe
from .engine import run_sql, run_sql_df, make_connection, assert_read_only, UnsafeQueryError
from .charts import recommend_chart, build_figure, INTENTS
from .trust import build_trust_panel, check_insight_faithfulness
from .evaluate import run_suite, evaluate_case, DIMENSIONS
from .nl2sql import generate_query, QueryPlan

__all__ = [
    "profile_dataset",
    "suggest_questions",
    "load_dataframe",
    "run_sql",
    "run_sql_df",
    "make_connection",
    "assert_read_only",
    "UnsafeQueryError",
    "recommend_chart",
    "build_figure",
    "INTENTS",
    "build_trust_panel",
    "check_insight_faithfulness",
    "run_suite",
    "evaluate_case",
    "DIMENSIONS",
    "generate_query",
    "QueryPlan",
]
