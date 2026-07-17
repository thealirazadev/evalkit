"""Rich terminal output: per-suite case lines, failure details, and the summary block.

All output goes through a single ``Console``. Color is semantic and never the only
signal: statuses are words (``pass``/``FAIL``/``ERROR``), warnings are prefixed
``Warning:``. The summary always prints, even under ``--quiet``.
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from evalkit.runner import CaseResult, RunResult

_STATUS = {
    "pass": ("pass", "green"),
    "fail": ("FAIL", "red"),
    "error": ("ERROR", "red"),
}


def _fmt_latency(ms: int) -> str:
    return f"{ms / 1000:.1f}s"


def _fmt_cost(cost: float | None) -> str:
    return f"${cost:.4f}" if cost is not None else "n/a"


def _ratio(case: CaseResult) -> str:
    if case.samples <= 1:
        return ""
    marker = "" if case.status == "pass" else f" < {case.threshold:g}"
    return f"{case.samples_passed}/{case.samples}{marker}"


def _case_line(case: CaseResult, name_width: int, ratio_width: int) -> Text:
    label, style = _STATUS[case.status]
    line = Text("  ")
    line.append(f"{label:<5}", style=style)
    line.append(" ")
    line.append(f"{case.name:<{name_width}}")
    if case.status == "error":
        line.append("  ")
        line.append(case.error or "error", style="red")
        return line
    if ratio_width:
        line.append("  ")
        line.append(f"{_ratio(case):<{ratio_width}}")
    line.append(f"  {_fmt_latency(case.latency_ms):>6}")
    line.append(f"  {_fmt_cost(case.cost_usd):>10}")
    if case.cached:
        line.append("   cached", style="dim")
    return line


def _print_suite(console: Console, name: str, file: str, cases: list[CaseResult]) -> None:
    console.print(Text(f"{name}  ({file})", style="bold"), soft_wrap=True)
    name_width = max((len(c.name) for c in cases), default=0)
    ratio_width = max((len(_ratio(c)) for c in cases), default=0)
    for case in cases:
        # soft_wrap keeps long reasons/messages on one line for CI log grepping.
        console.print(_case_line(case, name_width, ratio_width), soft_wrap=True)
        for failure in case.failures:
            suffix = f" (sample {failure.sample})" if case.samples > 1 else ""
            console.print(Text(f"        {failure.message}{suffix}", style="dim"), soft_wrap=True)
    console.print()


def print_liveness(console: Console, total_cases: int, *, quiet: bool = False) -> None:
    """Off a TTY, print one plain liveness line so CI logs show the run started.

    On a TTY a live progress display (a later phase) replaces this; under ``--quiet``
    nothing prints.
    """
    if quiet or console.is_terminal:
        return
    console.print(f"running {total_cases} cases...")


def render_report(console: Console, run: RunResult, *, quiet: bool = False) -> None:
    """Render the full run report: per-suite lines, warnings, and the summary block."""
    for suite in run.suites:
        cases = suite.cases if not quiet else [c for c in suite.cases if c.status != "pass"]
        if not cases:
            continue
        _print_suite(console, suite.name, suite.file, cases)

    totals = run.totals
    if not totals.cost_known and totals.partial_reason:
        console.print(Text(f"Warning: {totals.partial_reason}", style="yellow"))

    console.print("summary")
    counts = Text("  cases: ")
    counts.append(str(totals.cases))
    counts.append("   passed: ")
    counts.append(str(totals.passed), style="green" if totals.passed else None)
    counts.append("   failed: ")
    counts.append(str(totals.failed), style="red" if totals.failed else None)
    counts.append("   errors: ")
    counts.append(str(totals.errors), style="red" if totals.errors else None)
    console.print(counts)

    cost_part = f"cost: ${totals.cost_usd:.4f}"
    if not totals.cost_known and totals.partial_reason:
        cost_part += f" (partial: {totals.partial_reason})"
    elif totals.judge_cost_usd > 0:
        cost_part += f"  (judge: ${totals.judge_cost_usd:.4f})"
    tokens = f"tokens: {totals.prompt_tokens:,} in / {totals.completion_tokens:,} out"
    console.print(f"  {cost_part}   {tokens}")
    console.print(f"  cache: {totals.cache_hits}/{totals.cases} responses from cache")
    console.print(f"  wall time: {run.duration_ms / 1000:.1f}s")
