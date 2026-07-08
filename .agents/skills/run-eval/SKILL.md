---
name: run-eval
description: >
  Run the Insight Copilot evaluation harness over benchmark questions and report
  query/insight accuracy with a failure-type breakdown across the PRD's 7
  evaluation dimensions. Use when the user wants to "run the eval", "score the
  copilot", "check for regressions", or add/verify a benchmark case. Optional arg:
  a path to a custom cases.yaml.
---

# Run the Evaluation Harness

Score generated queries and insights against benchmark cases (`Insight_PRD.md` 7.9)
using `insight_copilot/evaluate.py`.

## How to run it

Prefer delegating to the `insight-evaluator` agent for interpretation, or run
directly (`py -3.13` on Windows):

```
py -3.13 -m insight_copilot.cli eval                      # default benchmark suite
py -3.13 -m insight_copilot.cli eval --cases <path.yaml>  # custom cases
```

A non-zero exit code means at least one case failed (pass_rate < 1.0) — expected
when the suite includes deliberately-wrong candidates or a real regression.

## Reporting
Summarize:
- **Pass rate** and which of the 7 dimensions (query_validity, column_mapping,
  aggregation_accuracy, filter_accuracy, result_accuracy, chart_relevance,
  insight_faithfulness) are weakest.
- Each failing case with its classified failure type (wrong date column, missing
  filter, wrong aggregation, wrong sort order, wrong chart, unsupported insight)
  and a concrete fix.

## Adding cases
Edit `insight_copilot/benchmarks/cases.yaml`. Encode ground truth as
`reference_sql` (not hard-coded numbers) so cases survive dataset regeneration;
add `candidate_sql` (query under test), `expected_columns`, `expected_chart`,
`candidate_chart`, and an optional `insight` for faithfulness checking. Re-run the
suite after editing.
