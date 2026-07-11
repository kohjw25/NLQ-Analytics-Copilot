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
    "openai/gpt-oss-120b:free",
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
    date_column: Optional[str] = None,
) -> QueryPlan:
    """Generate a QueryPlan for ``question`` against a profiled dataset.

    ``date_column`` (optional) forces which date field is used for time-based
    grouping — useful when the dataset has several date columns. Tries the
    resolved LLM provider, falling back to the rule-based generator on any error.
    Never raises for a normal question -- returns a plan whose ``clarification`` is
    set instead of ``sql`` when intent can't be resolved.
    """
    provider = resolve_provider()
    try:
        if provider == "openrouter":
            plan = _generate_with_openrouter(question, profile, model or model_for(provider), date_column)
        elif provider == "anthropic":
            plan = _generate_with_claude(question, profile, model or model_for(provider), date_column)
        else:
            plan = _generate_heuristic(question, profile, date_column)
    except Exception as exc:  # noqa: BLE001 -- degrade to heuristic rather than fail
        plan = _generate_heuristic(question, profile, date_column)
        plan.assumptions.append(f"(LLM backend '{provider}' failed: {exc}; used rule-based fallback)")
        return plan
    # Safety net: if the user asked for a time grain but the model grouped by the
    # raw date column (common with weaker models), bucket it deterministically.
    plan.sql = _enforce_time_bucketing(plan.sql, date_column, question, profile)
    return plan


def _enforce_time_bucketing(
    sql: Optional[str], date_column: Optional[str], question: str, profile: Dict[str, Any]
) -> Optional[str]:
    """Rewrite a query that GROUPs BY a raw date column to bucket by the requested
    grain (month/week/etc.). No-op unless the question asks for a time grain, a date
    column is grouped raw, and the query isn't already bucketed (strftime/date_trunc)."""
    if not sql:
        return sql
    ql = question.lower()
    wants_time = any(
        w in ql for w in ["trend", "over time", "by month", "by day", "by week",
                          "by quarter", "by year", "monthly", "daily", "weekly",
                          "quarterly", "yearly", "per month", "per week", "per day",
                          "each month", "each week", "quarter", "annual"]
    )
    if not wants_time:
        return sql
    low = sql.lower()
    if "strftime" in low or "date_trunc" in low:
        return sql  # already bucketed
    col = date_column if date_column in profile.get("date_fields", []) else _find_column(ql, profile.get("date_fields", []))
    if not col:
        return sql
    qcol = _q(col)
    gb = low.find("group by")
    # Only act when the raw date column is actually a grouping key.
    if qcol.lower() not in low or gb == -1 or qcol.lower() not in low[gb:]:
        return sql
    grain = _time_grain(ql)
    period = _period_sql(col, grain)
    # Alias the SELECT occurrence for a clean column name, then reference the alias
    # in GROUP BY / ORDER BY (DuckDB resolves aliases there).
    aliased = sql.replace(qcol, f"{period} AS {grain}", 1)
    return aliased.replace(qcol, grain)


# --- shared prompt ------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are the query-generation layer of an analytics copilot. Translate the "
    "user's business question into a single read-only DuckDB SQL query over a "
    "table named `data`.\n"
    "Rules:\n"
    "- Use ONLY the columns listed in the schema; never invent columns or metrics.\n"
    "- Map business words to the closest schema column by meaning (e.g. "
    "'sales'/'income' -> a revenue-like metric; 'product'/'category' -> a category "
    "dimension; 'when'/'monthly'/'trend' -> a date field).\n"
    '- Quote column names that contain spaces with double quotes, e.g. "Order Date".\n'
    "- Cast text date columns before date math: CAST(\"Order Date\" AS DATE).\n"
    "- For time trends, bucket by the requested grain (day/week/month/quarter/year): "
    "month/year via strftime(CAST(<date> AS DATE), '%Y-%m' or '%Y'); "
    "day/week/quarter via date_trunc('week'|'day'|'quarter', CAST(<date> AS DATE)). "
    "GROUP BY and ORDER BY that period.\n"
    "- Prefer returning SEVERAL metric columns when the user wants to see multiple "
    "measures (e.g. SELECT ..., SUM(\"Revenue\") AS revenue, SUM(\"Orders\") AS orders, "
    "SUM(\"Quantity\") AS quantity). Order by the primary metric.\n"
    "- SUPPORT TWO-DIMENSION BREAKDOWNS. If the question asks for a metric by a time "
    "period AND a category (e.g. 'monthly revenue by product category'), GROUP BY "
    "BOTH (month, category) and SELECT both grouping columns plus the aggregate. "
    "Likewise for two categories (e.g. 'revenue by region and segment' -> "
    "GROUP BY region, segment).\n"
    "- Use SUM for totals, AVG for rates/averages (including 0/1 flags), COUNT for volumes.\n"
    "- Only emit SELECT or WITH statements. Never write/DDL.\n"
    "- If the metric, time window, or which date column to use is genuinely "
    "ambiguous, ask a clarification instead of guessing.\n"
    "- Pick `intent` to drive chart choice: trend (over time, incl. time x category), "
    "ranking (top/bottom), comparison (by one or two categories), share (% of total), "
    "correlation (two metrics), kpi (single number), detail (raw rows).\n"
    "Examples (schema-dependent — adapt column names to the actual schema):\n"
    "  Q: 'monthly revenue trend by product category' -> "
    "SELECT strftime(CAST(\"Order Date\" AS DATE),'%Y-%m') AS month, "
    "\"Product Category\" AS category, SUM(\"Revenue\") AS revenue "
    "FROM data GROUP BY month, category ORDER BY month; intent=trend\n"
    "  Q: 'top 5 regions by revenue' -> SELECT \"Region\", SUM(\"Revenue\") AS revenue "
    "FROM data GROUP BY \"Region\" ORDER BY revenue DESC LIMIT 5; intent=ranking"
)


def _schema_text(profile: Dict[str, Any]) -> str:
    lines = []
    for c in profile.get("columns", []):
        samples = ", ".join(str(v) for v in c.get("sample_values", [])[:3])
        lines.append(f'  - "{c["name"]}" ({c["dtype"]}, role={c["role"]}) e.g. {samples}')
    return "\n".join(lines)


def _user_prompt(question: str, profile: Dict[str, Any], date_column: Optional[str] = None) -> str:
    date_line = (
        f'For ANY time-based grouping (monthly/weekly/etc.), use the "{date_column}" '
        "date column.\n"
        if date_column else ""
    )
    return (
        f"Dataset schema (table `data`):\n{_schema_text(profile)}\n\n"
        f"Detected metrics: {profile.get('metrics')}\n"
        f"Detected dimensions: {profile.get('dimensions')}\n"
        f"Detected date fields: {profile.get('date_fields')}\n"
        f"{date_line}\n"
        f"Question: {question}"
    )


_AGG_FUNCS = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}


def apply_aggregation(sql: Optional[str], agg: Optional[str]) -> Optional[str]:
    """Rewrite the metric aggregate functions in a generated query.

    ``agg`` is one of {sum, avg, min, max} to force that function on every
    aggregated metric, or None to leave the query as generated. Only SUM/AVG/MIN/
    MAX are rewritten (COUNT and non-aggregate functions like strftime/date_trunc
    are untouched), so grouping and time bucketing are preserved.
    """
    if not sql or not agg:
        return sql
    func = _AGG_FUNCS.get(agg.lower())
    if not func:
        return sql
    return re.sub(r"\b(?:SUM|AVG|MIN|MAX)\s*\(", func + "(", sql, flags=re.IGNORECASE)


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

def _generate_with_openrouter(
    question: str, profile: Dict[str, Any], model: str, date_column: Optional[str] = None
) -> QueryPlan:
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
    user = _user_prompt(question, profile, date_column) + (
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

def _generate_with_claude(
    question: str, profile: Dict[str, Any], model: str, date_column: Optional[str] = None
) -> QueryPlan:
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
        messages=[{"role": "user", "content": _user_prompt(question, profile, date_column)}],
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


def _col_matches(question_l: str, col: str) -> bool:
    """True if the column is mentioned in the question (substring or every token
    matched by a >=4-char prefix, so 'Product Category' matches 'product categories')."""
    cl = col.lower()
    if cl in question_l:
        return True
    q_words = re.findall(r"[a-z0-9]+", question_l)
    tokens = re.findall(r"[a-z0-9]+", cl)
    return bool(tokens) and all(_token_in_words(t, q_words) for t in tokens)


def _find_column(question_l: str, candidates: List[str]) -> Optional[str]:
    """Return the single candidate column best matched in the question."""
    matched = [c for c in candidates if _col_matches(question_l, c)]
    # Prefer a substring match, then the most specific (most tokens).
    matched.sort(key=lambda c: (c.lower() in question_l, len(re.findall(r"[a-z0-9]+", c))), reverse=True)
    return matched[0] if matched else None


def _mentioned_columns(question_l: str, candidates: List[str]) -> List[str]:
    """All candidate columns explicitly mentioned in the question, in schema order."""
    return [c for c in candidates if _col_matches(question_l, c)]


def _token_in_words(token: str, words: List[str]) -> bool:
    """True if some question word shares a >=4-char prefix with the column token."""
    prefix = token[:4]
    return any(w.startswith(prefix) or token.startswith(w[:4]) for w in words)


def _time_grain(question_l: str) -> str:
    """Detect the requested time granularity; defaults to month."""
    if "week" in question_l:
        return "week"
    if "quarter" in question_l or "quarterly" in question_l:
        return "quarter"
    if any(w in question_l for w in ["yearly", "annual", "by year", "per year", "each year"]):
        return "year"
    if any(w in question_l for w in ["daily", "by day", "per day", "each day"]):
        return "day"
    return "month"


def _period_sql(date_col: str, grain: str) -> str:
    """DuckDB expression that buckets a (possibly text) date column by ``grain``.

    Month/year return a readable, sortable text label; day/week/quarter return a
    sortable DATE (the first day of the bucket) which plots on a time axis.
    """
    d = f'CAST({_q(date_col)} AS DATE)'
    if grain == "month":
        return f"strftime({d}, '%Y-%m')"
    if grain == "year":
        return f"strftime({d}, '%Y')"
    return f"CAST(date_trunc('{grain}', {d}) AS DATE)"


def _generate_heuristic(
    question: str, profile: Dict[str, Any], date_column: Optional[str] = None
) -> QueryPlan:
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

    mentioned_dims = _mentioned_columns(ql, dimensions)
    mentioned_metrics = _mentioned_columns(ql, metrics)
    primary_metric = mentioned_metrics[0] if mentioned_metrics else (metrics[0] if metrics else None)
    dimension = mentioned_dims[0] if mentioned_dims else None
    # A caller-chosen date column wins; else a column named in the question; else the first.
    chosen_date = date_column if date_column in dates else None
    date_col = chosen_date or _find_column(ql, dates) or (dates[0] if dates else None)

    assumptions: List[str] = []
    if primary_metric and not mentioned_metrics:
        assumptions.append(f"Assumed the metric is '{primary_metric}'.")
    if len(dates) > 1 and date_col and not chosen_date:
        assumptions.append(f"Assumed the date field is '{date_col}' (of {dates}).")

    def agg(m: str) -> str:
        return f"AVG({_q(m)})" if _is_rate_metric(m, profile) else f"SUM({_q(m)})"

    grain = _time_grain(ql)

    # Show the primary metric plus the other detected metrics so the table is
    # rich (capped for readability); the primary metric drives chart + ordering.
    metric_list = (
        ([primary_metric] + [m for m in metrics if m != primary_metric])[:4]
        if primary_metric else []
    )
    metric_select = ", ".join(f"{agg(m)} AS {_safe(m)}" for m in metric_list)
    primary_alias = _safe(primary_metric) if primary_metric else None

    is_trend = any(w in ql for w in ["trend", "over time", "by month", "by day", "by week",
                                     "monthly", "daily", "weekly", "quarterly", "yearly",
                                     "per month", "per week", "per day", "each month",
                                     "each week", "quarter", "annual"])
    is_share = any(w in ql for w in ["share", "percentage", "percent", "% of", "proportion", "contribution"])
    is_rank = any(w in ql for w in ["top", "highest", "lowest", "best", "worst", "rank", "most", "least", "bottom"])

    # Trend over time at the requested grain, optionally broken down by a category.
    if is_trend and primary_metric and date_col:
        period = _period_sql(date_col, grain)
        cat = mentioned_dims[0] if mentioned_dims else None
        if cat:
            sql = (
                f"SELECT {period} AS {grain}, {_q(cat)} AS {_safe(cat)}, {metric_select} "
                f"FROM data GROUP BY {grain}, {_q(cat)} ORDER BY {grain}, {primary_alias} DESC"
            )
            return QueryPlan(sql=sql, intent="trend", assumptions=assumptions,
                             columns_used=[date_col, cat] + metric_list, confidence="medium")
        sql = (
            f"SELECT {period} AS {grain}, {metric_select} "
            f"FROM data GROUP BY {grain} ORDER BY {grain}"
        )
        return QueryPlan(sql=sql, intent="trend", assumptions=assumptions,
                         columns_used=[date_col] + metric_list, confidence="medium")

    # Two categorical dimensions (e.g. revenue by region and segment).
    if primary_metric and len(mentioned_dims) >= 2 and not is_share:
        d1, d2 = mentioned_dims[0], mentioned_dims[1]
        sql = (
            f"SELECT {_q(d1)} AS {_safe(d1)}, {_q(d2)} AS {_safe(d2)}, {metric_select} "
            f"FROM data GROUP BY {_q(d1)}, {_q(d2)} ORDER BY {primary_alias} DESC"
        )
        return QueryPlan(sql=sql, intent="comparison", assumptions=assumptions,
                         columns_used=[d1, d2] + metric_list, confidence="medium")

    # Share of total by a dimension (single metric + its percentage of the total).
    if is_share and primary_metric and dimension:
        sql = (
            f"SELECT {_q(dimension)} AS {_safe(dimension)}, "
            f"{agg(primary_metric)} AS {primary_alias}, "
            f"100.0 * {agg(primary_metric)} / (SELECT {agg(primary_metric)} FROM data) AS pct_of_total "
            f"FROM data GROUP BY {_q(dimension)} ORDER BY {primary_alias} DESC"
        )
        return QueryPlan(sql=sql, intent="share", assumptions=assumptions,
                         columns_used=[dimension, primary_metric], confidence="medium")

    # Ranking / comparison by one dimension.
    if primary_metric and dimension:
        n = _extract_top_n(ql)
        order = "ASC" if any(w in ql for w in ["lowest", "worst", "bottom", "least"]) else "DESC"
        limit = f" LIMIT {n}" if n else ""
        sql = (
            f"SELECT {_q(dimension)} AS {_safe(dimension)}, {metric_select} "
            f"FROM data GROUP BY {_q(dimension)} ORDER BY {primary_alias} {order}{limit}"
        )
        intent = "ranking" if (is_rank or n) else "comparison"
        return QueryPlan(sql=sql, intent=intent, assumptions=assumptions,
                         columns_used=[dimension] + metric_list, confidence="medium")

    # No dimension: a one-row summary of the detected metrics.
    if primary_metric:
        if len(metric_list) > 1:
            sql = f"SELECT {metric_select} FROM data"
            return QueryPlan(sql=sql, intent="detail", assumptions=assumptions,
                             columns_used=metric_list, confidence="low")
        sql = f"SELECT {agg(primary_metric)} AS {primary_alias} FROM data"
        return QueryPlan(sql=sql, intent="kpi", assumptions=assumptions,
                         columns_used=[primary_metric], confidence="low")

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
