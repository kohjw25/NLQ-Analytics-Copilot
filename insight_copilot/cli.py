"""Command-line entrypoint for the Insight Copilot engine.

Skills and agents call these subcommands so behaviour is deterministic and
identical whether invoked by a human or by Claude. All commands print JSON.

    python -m insight_copilot.cli profile <file>
    python -m insight_copilot.cli run-sql <file> --sql "SELECT ..."
    python -m insight_copilot.cli chart  <file> --sql "SELECT ..." [--intent ranking]
    python -m insight_copilot.cli eval   [--cases benchmarks/cases.yaml]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_profile(args) -> int:
    from .profiler import profile_dataset

    _print(profile_dataset(args.file))
    return 0


def cmd_run_sql(args) -> int:
    from .engine import run_sql

    result = run_sql(args.file, args.sql)
    _print(result.to_dict())
    return 0 if result.ok else 1


def cmd_chart(args) -> int:
    from .engine import run_sql
    from .charts import recommend_chart
    import pandas as pd

    result = run_sql(args.file, args.sql)
    if not result.ok:
        _print(result.to_dict())
        return 1
    df = pd.DataFrame(result.rows)
    spec = recommend_chart(args.intent, df)
    out = {"query_result": result.to_dict(), "chart_spec": spec}
    if args.write:
        from .charts import build_figure

        fig = build_figure(spec, df)
        fig.write_html(args.write)
        out["chart_html"] = args.write
    _print(out)
    return 0


def cmd_eval(args) -> int:
    from .evaluate import run_suite

    cases = args.cases or os.path.join(
        os.path.dirname(__file__), "benchmarks", "cases.yaml"
    )
    report = run_suite(cases)
    _print(report)
    return 0 if report["pass_rate"] == 1.0 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="insight_copilot", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("profile", help="Profile a dataset (schema, roles, questions)")
    sp.add_argument("file")
    sp.set_defaults(func=cmd_profile)

    sr = sub.add_parser("run-sql", help="Run read-only SQL against a dataset")
    sr.add_argument("file")
    sr.add_argument("--sql", required=True)
    sr.set_defaults(func=cmd_run_sql)

    sc = sub.add_parser("chart", help="Run SQL and recommend a chart")
    sc.add_argument("file")
    sc.add_argument("--sql", required=True)
    sc.add_argument("--intent", default=None,
                    help="trend|ranking|comparison|share|correlation|kpi|detail")
    sc.add_argument("--write", default=None, help="Write chart HTML to this path")
    sc.set_defaults(func=cmd_chart)

    se = sub.add_parser("eval", help="Run the benchmark evaluation suite")
    se.add_argument("--cases", default=None, help="Path to cases.yaml")
    se.set_defaults(func=cmd_eval)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
