"""Natural-language -> SQL layer (PRD 7.2 / 7.3 / 11 LLM Layer).

Turns a plain-English question plus a dataset profile into a query plan: a single
read-only DuckDB SQL statement, a chart intent, assumptions, columns used, and a
confidence level -- or a clarification question when the intent is ambiguous.

Backends (auto-selected in this order, override with INSIGHT_COPILOT_PROVIDER):
  * openrouter -- OpenRouter's OpenAI-compatible API (OPENROUTER_API_KEY). Lets you
    use cheap or free models; JSON is requested in the prompt and parsed robustly
    so even free models that lack strict structured-output support work.
  * anthropic  -- Claude via the Anthropic SDK (ANTHROPIC_API_KEY), forced JSON.
  * heuristic  -- a rule-based generator so the app is fully demoable offline.

Model is chosen per provider and can be overridden with INSIGHT_COPILOT_MODEL.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Chart intents understood by charts.recommend_chart (kept in sync deliberately).
_INTENTS = ["trend", "ranking", "comparison", "share", "correlation", "kpi", "detail"]

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
# OpenRouter free model. Free-model availability changes over time -- browse
# https://openrouter.ai/models?max_price=0 and override with INSIGHT_COPILOT_MODEL.
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Suggested free OpenRouter models for the UI picker. Free-model IDs change over
# time -- the picker also offers a custom-entry option. Browse the live list at
# https://openrouter.ai/models?max_price=0
SUGGESTED_FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "google/gemini-2.0-flash-exp:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]

SUGGESTED_ANTHROPIC_MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]


@dataclass
class QueryPlan:
    sql: Optional[str] = None
    intent: str = "detail"
    assumptions: List[str] = field(default_factory=list)
    columns_used: List[str] = field(default_factory=list)
    confidence: str = "medium"
    clarification: Optional[str] = None
    backend: str = "heuristic"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sql": self.sql,
            "intent": self.intent,
            "assumptions": self.assumptions,
            "columns_used": self.columns_used,
            "confidence": self.confidence,
            "clarification": self.clarification,
            "backend": self.backend,
        }


# --- provider selection -------------------------------------------------------

def resolve_provider() -> str:
    """Return the active provider: 'openrouter', 'anthropic', or 'heuristic'."""
    forced = os.environ.get("INSIGHT_COPILOT_PROVIDER", "").strip().lower()
    if forced in {"openrouter", "anthropic", "heuristic"}:
        return forced
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "heuristic"


def model_for(provider: str) -> str:
    override = os.environ.get("INSIGHT_COPILOT_MODEL")
    if override:
        return override
    if provider == "openrouter":
        return DEFAULT_OPENROUTER_MODEL
    if provider == "anthropic":
        return DEFAULT_ANTHROPIC_MODEL
    return "rule-based"


def active_backend_label() -> str:
    """Short human-readable label for the UI (e.g. 'OpenRouter · <model>')."""
    provider = resolve_provider()
    if provider == "heuristic":
        return "rule-based (no API key)"
    return f"{provider} - {model_for(provider)}"


def generate_query(
    question: str,
    profile: Dict[str, Any],
    model: Optional[str] = None,
) -> QueryPlan:
    """Generate a QueryPlan for ``question`` against a profiled dataset.

    Tries the resolved LLM provider, falling back to the rule-based generator on
    any error. Never raises for a normal question -- returns a plan whose
    ``clarification`` is set instead of ``sql`` when intent can't be resolved.
    """
    provider = resolve_provider()
    try:
        if provider == "openrouter":
            return _generate_with_openrouter(question, profile, model or model_for(provider))
        if provider == "anthropic":
            return _generate_with_claude(question, profile, model or model_for(provider))
    except Exception as exc:  # noqa: BLE001 -- degrade to heuristic rather than fail
        plan = _generate_heuristic(question, profile)
        plan.assumptions.append(f"(LLM backend '{provider}' failed: {exc}; used rule-based fallback)")
        return plan
    return _generate_heuristic(question, profile)


# --- shared prompt ------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are the query-generation layer of an analytics copilot. Translate the "
    "user's business question into a single read-only DuckDB SQL query over a "
    "table named `data`.\n"
    "Rules:\n"
    "- Use ONLY the columns listed in the schema; never invent columns or metrics.\n"
    '- Quote column names that contain spaces with double quotes, e.g. "Order Date".\n'
    "- Cast text date columns before date math: CAST(\"Order Date\" AS DATE).\n"
    "- Use SUM for totals, AVG for rates/averages (including 0/1 flags), COUNT for volumes.\n"
    "- Only emit SELECT or WITH statements. Never write/DDL.\n"
    "- If the metric, time window, or which date column to use is genuinely "
    "ambiguous, ask a clarification instead of guessing.\n"
    "- Pick `intent` to drive chart choice: trend (over time), ranking (top/bottom), "
    "comparison (by category), share (% of total), correlation (two metrics), "
    "kpi (single number), detail (raw rows)."
)


def _schema_text(profile: Dict[str, Any]) -> str:
    lines = []
    for c in profile.get("columns", []):
        samples = ", ".join(str(v) for v in c.get("sample_values", [])[:3])
        lines.append(f'  - "{c["name"]}" ({c["dtype"]}, role={c["role"]}) e.g. {samples}')
    return "\n".join(lines)


def _user_prompt(question: str, profile: Dict[str, Any]) -> str:
    return (
        f"Dataset schema (table `data`):\n{_schema_text(profile)}\n\n"
        f"Detected metrics: {profile.get('metrics')}\n"
        f"Detected dimensions: {profile.get('dimensions')}\n"
        f"Detected date fields: {profile.get('date_fields')}\n\n"
        f"Question: {question}"
    )


def _plan_from_dict(d: Dict[str, Any], backend: str) -> QueryPlan:
    intent = d.get("intent") if d.get("intent") in _INTENTS else "detail"
    conf = d.get("confidence") if d.get("confidence") in {"high", "medium", "low"} else "medium"
    sql = (d.get("sql") or "").strip() or None
    clar = (d.get("clarification") or "").strip() or None
    if not sql and not clar:
        clar = "I couldn't turn that into a query — could you rephrase, naming a metric and a dimension?"
    return QueryPlan(
        sql=sql,
        intent=intent,
        assumptions=[str(a) for a in (d.get("assumptions") or [])],
        columns_used=[str(c) for c in (d.get("columns_used") or [])],
        confidence=conf,
        clarification=clar,
        backend=backend,
    )


def _extract_json(text: str) -> Dict[str, Any]:
    """Parse a JSON object from a model response, tolerating fences and prose."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    return json.loads(t)


# --- OpenRouter backend (OpenAI-compatible) -----------------------------------

def _generate_with_openrouter(question: str, profile: Dict[str, Any], model: str) -> QueryPlan:
    from openai import OpenAI

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        # Optional attribution headers for OpenRouter's dashboards/leaderboards.
        default_headers={
            "HTTP-Referer": os.environ.get("INSIGHT_COPILOT_SITE_URL", "https://localhost"),
            "X-Title": "Insight Copilot",
        },
    )
    user = _user_prompt(question, profile) + (
        "\n\nRespond with ONLY a JSON object (no markdown fences, no commentary) "
        "with keys: clarification (string or null), sql (string or null), "
        f"intent (one of {_INTENTS}), assumptions (array of strings), "
        "columns_used (array of strings), confidence (\"high\"|\"medium\"|\"low\")."
    )
    kwargs: Dict[str, Any] = dict(
        model=model,
        max_tokens=1200,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )
    # Ask for JSON mode where supported; retry plain if the model rejects it.
    try:
        resp = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
    except Exception:
        resp = client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    return _plan_from_dict(_extract_json(text), backend=f"openrouter:{model}")


# --- Anthropic backend --------------------------------------------------------

def _generate_with_claude(question: str, profile: Dict[str, Any], model: str) -> QueryPlan:
    import anthropic
    from pydantic import BaseModel, Field

    class QueryPlanOut(BaseModel):
        clarification: Optional[str] = Field(
            default=None,
            description="If the question is ambiguous, a single targeted "
            "clarification question. Otherwise null.",
        )
        sql: Optional[str] = Field(
            default=None,
            description="A single read-only DuckDB SELECT/WITH query against the "
            "table named `data`. Null if a clarification is needed.",
        )
        intent: str = Field(description="One of: " + ", ".join(_INTENTS))
        assumptions: List[str] = Field(default_factory=list)
        columns_used: List[str] = Field(default_factory=list)
        confidence: str = Field(description="high, medium, or low")

    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _user_prompt(question, profile)}],
        output_format=QueryPlanOut,
    )
    out = resp.parsed_output
    return _plan_from_dict(
        {
            "clarification": out.clarification,
            "sql": out.sql,
            "intent": out.intent,
            "assumptions": out.assumptions,
            "columns_used": out.columns_used,
            "confidence": out.confidence,
        },
        backend=f"anthropic:{model}",
    )


# --- Heuristic backend --------------------------------------------------------

def _q(name: str) -> str:
    return f'"{name}"'


def _find_column(question_l: str, candidates: List[str]) -> Optional[str]:
    """Return the candidate column best matched in the question.

    Matches a substring first; otherwise requires every token of the column to
    appear in the question by a prefix match, so 'Product Category' matches
    'product categories'. Prefers the column with the most matched tokens.
    """
    q_words = re.findall(r"[a-z0-9]+", question_l)
    best: Optional[str] = None
    best_score = 0
    for col in candidates:
        cl = col.lower()
        if cl in question_l:
            return col
        tokens = re.findall(r"[a-z0-9]+", cl)
        if tokens and all(_token_in_words(t, q_words) for t in tokens):
            if len(tokens) > best_score:
                best, best_score = col, len(tokens)
    return best


def _token_in_words(token: str, words: List[str]) -> bool:
    """True if some question word shares a >=4-char prefix with the column token."""
    prefix = token[:4]
    return any(w.startswith(prefix) or token.startswith(w[:4]) for w in words)


def _generate_heuristic(question: str, profile: Dict[str, Any]) -> QueryPlan:
    ql = question.lower()
    metrics: List[str] = profile.get("metrics", [])
    dimensions: List[str] = profile.get("dimensions", [])
    dates: List[str] = profile.get("date_fields", [])

    if not metrics and not dimensions:
        return QueryPlan(
            clarification="I couldn't detect any metrics or dimensions to analyse. "
            "Is this a tabular dataset with numeric and categorical columns?",
            confidence="low",
        )

    metric = _find_column(ql, metrics) or (metrics[0] if metrics else None)
    dimension = _find_column(ql, dimensions) or (dimensions[0] if dimensions else None)
    date_col = _find_column(ql, dates) or (dates[0] if dates else None)

    assumptions: List[str] = []
    if metric and not _find_column(ql, metrics):
        assumptions.append(f"Assumed the metric is '{metric}'.")
    if len(dates) > 1 and date_col:
        assumptions.append(f"Assumed the date field is '{date_col}' (of {dates}).")

    def agg(m: str) -> str:
        return f"AVG({_q(m)})" if _is_rate_metric(m, profile) else f"SUM({_q(m)})"

    is_trend = any(w in ql for w in ["trend", "over time", "by month", "by day", "monthly", "daily", "by week"])
    is_share = any(w in ql for w in ["share", "percentage", "percent", "% of", "proportion", "contribution"])
    is_rank = any(w in ql for w in ["top", "highest", "lowest", "best", "worst", "rank", "most", "least", "bottom"])

    if is_trend and metric and date_col:
        sql = (
            f"SELECT strftime(CAST({_q(date_col)} AS DATE), '%Y-%m') AS month, "
            f"{agg(metric)} AS {_safe(metric)} "
            f"FROM data GROUP BY month ORDER BY month"
        )
        return QueryPlan(sql=sql, intent="trend", assumptions=assumptions,
                         columns_used=[date_col, metric], confidence="medium")

    if is_share and metric and dimension:
        sql = (
            f"SELECT {_q(dimension)} AS {_safe(dimension)}, "
            f"{agg(metric)} AS {_safe(metric)}, "
            f"100.0 * {agg(metric)} / (SELECT {agg(metric)} FROM data) AS pct_of_total "
            f"FROM data GROUP BY {_q(dimension)} ORDER BY {_safe(metric)} DESC"
        )
        return QueryPlan(sql=sql, intent="share", assumptions=assumptions,
                         columns_used=[dimension, metric], confidence="medium")

    if metric and dimension:
        n = _extract_top_n(ql)
        order = "ASC" if any(w in ql for w in ["lowest", "worst", "bottom", "least"]) else "DESC"
        limit = f" LIMIT {n}" if n else ""
        sql = (
            f"SELECT {_q(dimension)} AS {_safe(dimension)}, "
            f"{agg(metric)} AS {_safe(metric)} "
            f"FROM data GROUP BY {_q(dimension)} ORDER BY {_safe(metric)} {order}{limit}"
        )
        intent = "ranking" if (is_rank or n) else "comparison"
        return QueryPlan(sql=sql, intent=intent, assumptions=assumptions,
                         columns_used=[dimension, metric], confidence="medium")

    if metric:
        sql = f"SELECT {agg(metric)} AS {_safe(metric)} FROM data"
        return QueryPlan(sql=sql, intent="kpi", assumptions=assumptions,
                         columns_used=[metric], confidence="low")

    return QueryPlan(
        clarification="Which metric would you like to analyse, and broken down by "
        f"which dimension? Available metrics: {metrics}; dimensions: {dimensions}.",
        confidence="low",
    )


def _is_rate_metric(metric: str, profile: Dict[str, Any]) -> bool:
    for c in profile.get("columns", []):
        if c["name"] == metric:
            vals = c.get("sample_values", [])
            numeric = [v for v in vals if isinstance(v, (int, float))]
            if numeric and set(numeric) <= {0, 1}:
                return True
    return False


def _extract_top_n(question_l: str) -> Optional[int]:
    m = re.search(r"top\s+(\d+)|(\d+)\s+(?:highest|lowest|best|worst)", question_l)
    if m:
        return int(next(g for g in m.groups() if g))
    return None


def _safe(name: str) -> str:
    alias = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return alias or "value"
