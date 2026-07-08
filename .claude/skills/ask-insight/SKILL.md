---
name: ask-insight
description: >
  Ask a plain-English business question about a tabular dataset (CSV/Excel) and
  get a validated table, a recommended chart, a written insight, and a trust
  panel. Use when the user wants to analyze/query a data file conversationally —
  "what is revenue by region", "which product declined most", "show the monthly
  trend", "conversion rate by group". Handles ambiguity by asking a clarifying
  question first. Args: an optional dataset path and the question.
---

# Ask an Insight

Turn a business question into a trustworthy answer using the Insight Copilot engine
(`insight_copilot/`, see `Insight_PRD.md`). This skill is the natural-language →
insight workflow (PRD Journeys 2 & 3).

## Inputs
- **Dataset**: a CSV/Excel path. If the user did not name one, look for data files
  in the working directory (e.g. `ab_data.csv`, files under `insight_copilot/benchmarks/`)
  and confirm which to use.
- **Question**: the user's plain-English question.

## How to run it

Delegate to the `insight-analyst` agent, which owns the full flow. Give it the
dataset path and the question, e.g.:

> Use the insight-analyst agent on `<dataset>` to answer: "<question>".

Or run the flow inline with the engine (`py -3.13` on Windows):

1. **Profile** — `py -3.13 -m insight_copilot.cli profile <dataset>`; read the
   detected metrics / dimensions / date_fields.
2. **Clarify if ambiguous** — if the metric, time window, or which date column is
   unclear, ask ONE targeted question with options drawn from the profile before
   querying. Do not guess through real ambiguity.
3. **Generate + execute SQL** — write a single read-only DuckDB query against the
   table `data` (quote spaced names, cast text dates), then
   `py -3.13 -m insight_copilot.cli run-sql <dataset> --sql "<sql>"`.
4. **Chart** — `py -3.13 -m insight_copilot.cli chart <dataset> --sql "<sql>" --intent <trend|ranking|comparison|share|correlation|kpi|detail>`
   (add `--write out.html` to render).
5. **Insight + trust panel** — write a 2-4 sentence insight using only numbers from
   the result, then show the trust panel: SQL, columns used, filters, aggregation,
   assumptions, and confidence.

## Output format
Present: **Answer** (insight) → **Result** (table) → **Chart** (type + why) →
**How this was calculated** (SQL, columns, filters, aggregation, assumptions,
confidence). Flag low-confidence answers explicitly.

## Interactive UI
For a hands-on version, the Streamlit app wraps this same flow (upload → ask →
chart + trust panel): `py -3.13 -m streamlit run insight_copilot/app.py`. Its
NL→SQL step is `insight_copilot/nl2sql.py`, which uses Claude when
`ANTHROPIC_API_KEY` is set and a rule-based fallback otherwise.

## Guardrails
Only use columns from the profile. Every number in the insight must appear in the
result table. Prefer a clarification question over a confident guess. If a query
fails, explain why and propose a corrected question — never fabricate output.
