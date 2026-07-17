"""Terminal report layout and monochrome (no escape codes) output."""

import io

from rich.console import Console

from evalkit.report_terminal import print_liveness, render_report
from evalkit.runner import CaseResult, Failure, RunResult, RunTotals, SuiteResult


def _case(name, status, **over):
    base = dict(
        suite="demo",
        name=name,
        key=f"demo/{name}",
        model="example-model-1",
        status=status,
        samples=1,
        samples_passed=1 if status == "pass" else 0,
        threshold=1.0,
        latency_ms=1200,
        cached=False,
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.0021,
        judge_cost_usd=0.0,
        failures=[],
        error=None,
    )
    base.update(over)
    return CaseResult(**base)


def _run(cases, totals):
    return RunResult(
        suites=[SuiteResult(name="demo", file="evals/demo.yaml", cases=cases)],
        totals=totals,
        started_at="2026-07-18T10:00:00Z",
        duration_ms=6400,
    )


def _totals(**over):
    base = dict(
        cases=3,
        passed=1,
        failed=1,
        errors=1,
        cost_usd=0.0123,
        judge_cost_usd=0.0,
        cost_known=True,
        partial_reason=None,
        prompt_tokens=8412,
        completion_tokens=2306,
        cache_hits=1,
        mean_latency_ms=840.0,
    )
    base.update(over)
    return RunTotals(**base)


def _render(run, **kw):
    buf = io.StringIO()
    console = Console(file=buf, no_color=True, width=100)
    render_report(console, run, **kw)
    return buf.getvalue()


def test_layout_and_no_escape_codes():
    cases = [
        _case("good", "pass", cached=True, cost_usd=0.0008),
        _case(
            "bad",
            "fail",
            failures=[Failure("contains", 'contains: "refund" not found in response')],
        ),
        _case("broke", "error", error="provider: 503 after 3 attempts"),
    ]
    out = _render(_run(cases, _totals()))
    assert "\x1b" not in out  # no ANSI escape codes
    assert "pass  good" in out
    assert "FAIL  bad" in out
    assert "ERROR broke" in out
    assert "cached" in out
    assert 'contains: "refund" not found in response' in out
    assert "provider: 503 after 3 attempts" in out
    assert "summary" in out
    assert "cases: 3" in out
    assert "passed: 1" in out
    assert "cost: $0.0123" in out
    assert "tokens: 8,412 in / 2,306 out" in out
    assert "cache: 1/3 responses from cache" in out
    assert "wall time: 6.4s" in out


def test_partial_cost_warning_and_summary():
    cases = [_case("c", "pass", cost_usd=None)]
    totals = _totals(
        cases=1,
        passed=1,
        failed=0,
        errors=0,
        cost_known=False,
        partial_reason="no pricing for example-model-1",
    )
    out = _render(_run(cases, totals))
    assert "Warning: no pricing for example-model-1" in out
    assert "cost: $0.0123 (partial: no pricing for example-model-1)" in out
    assert "n/a" in out  # the case line shows n/a cost


def test_sample_ratio_shown_when_samples_gt_one():
    passing = _case("p", "pass", samples=3, samples_passed=3)
    failing = _case("f", "fail", samples=3, samples_passed=1, threshold=0.67)
    out = _render(_run([passing, failing], _totals()))
    assert "3/3" in out
    assert "1/3 < 0.67" in out


def test_quiet_hides_passing_cases_but_keeps_summary():
    cases = [_case("good", "pass"), _case("bad", "fail", failures=[Failure("contains", "x")])]
    out = _render(_run(cases, _totals()), quiet=True)
    assert "good" not in out
    assert "FAIL  bad" in out
    assert "summary" in out


def test_liveness_line_off_tty():
    buf = io.StringIO()
    console = Console(file=buf, no_color=True, width=100)  # a file is not a terminal
    print_liveness(console, 14)
    assert buf.getvalue().strip() == "running 14 cases..."


def test_liveness_suppressed_under_quiet():
    buf = io.StringIO()
    console = Console(file=buf, no_color=True, width=100)
    print_liveness(console, 14, quiet=True)
    assert buf.getvalue() == ""
