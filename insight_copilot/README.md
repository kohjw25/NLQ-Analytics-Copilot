# Insight Copilot — engine

Deterministic Python core for the **Insight Copilot** natural-language analytics
tool described in [`../Insight_PRD.md`](../Insight_PRD.md). It packages the PRD's
layers as reusable, testable functions and a CLI, so the LLM-driven parts (NL→SQL,
clarification, insight writing) stay thin and the numeric parts stay reproducible.

The reusable Claude Code **agents** (`insight-analyst`, `insight-evaluator`) and
**skills** (`ask-insight`, `run-eval`) live under `../.claude/` and drive this
engine.

## Layers (→ PRD sections)

| Module | Responsibility | PRD |
|--------|----------------|-----|
| `profiler.py` | Load CSV/Excel, detect dtypes, classify metric/dimension/date, missing values, summary, starter questions | 7.1 |
| `engine.py` | DuckDB execution against a `data` table with a read-only (SELECT/WITH-only) safety guard | 7.3–7.4, 12 |
| `charts.py` | Rule-based chart recommendation + Plotly figure builder | 7.5 |
| `trust.py` | Trust-panel payload + insight faithfulness check (numbers must trace to results) | 7.8 |
| `evaluate.py` | Benchmark harness: score 7 dimensions, classify failures | 7.9 |
| `nl2sql.py` | NL question -> SQL query plan; Claude-backed with a rule-based fallback | 7.2, 11 |
| `app.py` | Streamlit UI: upload/profile, ask-to-insight, trust panel, eval dashboard | 10, 11 |
| `cli.py` | `profile` / `run-sql` / `chart` / `eval` subcommands (JSON output) | — |

## Install

```bash
py -3.13 -m pip install -r insight_copilot/requirements.txt   # Windows
# or: python -m pip install -r insight_copilot/requirements.txt
```

## Usage

```bash
# 1. Profile a dataset
py -3.13 -m insight_copilot.cli profile insight_copilot/benchmarks/sample_ecommerce.csv

# 2. Run a read-only query (table registered as `data`)
py -3.13 -m insight_copilot.cli run-sql insight_copilot/benchmarks/sample_ecommerce.csv \
  --sql 'SELECT Region, SUM(Revenue) r FROM data GROUP BY Region ORDER BY r DESC'

# 3. Recommend + render a chart
py -3.13 -m insight_copilot.cli chart insight_copilot/benchmarks/sample_ecommerce.csv \
  --sql 'SELECT Region, SUM(Revenue) r FROM data GROUP BY Region ORDER BY r DESC' \
  --intent ranking --write chart.html

# 4. Run the evaluation suite
py -3.13 -m insight_copilot.cli eval
```

## The Streamlit app

The full prototype (PRD §10) ties the layers together in a UI with three screens:
**Upload & Profile**, **Ask** (question -> table + chart + insight + trust panel),
and an **Evaluation** dashboard.

```bash
py -3.13 -m streamlit run insight_copilot/app.py
```

The **Ask** screen's natural-language -> SQL step (`nl2sql.py`) picks a backend
automatically, and the sidebar shows which one is active. Load `ab_data.csv` or
the sample e-commerce dataset from the sidebar, or upload your own CSV/Excel.

### Choosing an LLM backend

| Backend | Enable it | Default model |
|---------|-----------|---------------|
| **OpenRouter** (cheap/free models) | set `OPENROUTER_API_KEY` | `meta-llama/llama-3.3-70b-instruct:free` |
| **Anthropic** (Claude) | set `ANTHROPIC_API_KEY` | `claude-opus-4-8` |
| **Rule-based** (offline) | set neither | — |

Selection order is OpenRouter → Anthropic → rule-based; force one with
`INSIGHT_COPILOT_PROVIDER=openrouter|anthropic|heuristic`. Override the model with
`INSIGHT_COPILOT_MODEL`.

**Free models via OpenRouter** — get a key at <https://openrouter.ai/keys>, then:

```bash
export OPENROUTER_API_KEY=sk-or-...
# optional: pick any free model (they end in ':free'); browse the current list at
# https://openrouter.ai/models?max_price=0
export INSIGHT_COPILOT_MODEL="deepseek/deepseek-chat-v3-0324:free"
py -3.13 -m streamlit run insight_copilot/app.py
```

Free models have low rate limits and vary in quality; if one returns an unusable
answer, the app falls back to the rule-based generator (noted in the trust panel).

Or use the library directly:

```python
from insight_copilot import profile_dataset, run_sql, recommend_chart, run_suite
```

## Benchmarks

`benchmarks/sample_ecommerce.csv` is a synthetic, self-contained dataset matching
the PRD examples (Order Date, Ship Date, Region, Product Category, Customer Segment,
Revenue, Orders, Quantity). `benchmarks/cases.yaml` holds benchmark questions whose
ground truth is a `reference_sql` (not hard-coded numbers), so cases remain valid if
the dataset is regenerated. Two cases ship a deliberately-wrong `candidate_sql` /
`candidate_chart` to demonstrate failure classification.
