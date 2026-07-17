"""Baseline snapshot build/write/load and the regression diff."""

import json

import pytest

from evalkit.baseline import (
    BASELINE_VERSION,
    build_snapshot,
    diff_against_baseline,
    load_baseline,
    write_baseline,
)
from evalkit.config import Config
from evalkit.errors import BaselineError
from evalkit.runner import CaseResult, RunResult, RunTotals, SuiteResult


def _config():
    return Config(
        base_url="u",
        api_key="k",
        default_model="example-model-1",
        cli_model=None,
        judge_model="example-model-1",
        concurrency=4,
        timeout_seconds=5,
        cache=True,
        suites_glob="x",
        pricing={},
        no_color=True,
        config_path=None,
    )


def _case(name, status, cost=0.001, latency=800, samples=1, samples_passed=1):
    return CaseResult(
        suite="demo",
        name=name,
        key=f"demo/{name}",
        model="example-model-1",
        status=status,
        samples=samples,
        samples_passed=samples_passed,
        threshold=1.0,
        latency_ms=latency,
        cached=False,
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=cost,
        judge_cost_usd=0.0,
    )


def _run(cases, cost=0.002, mean_latency=800.0):
    totals = RunTotals(
        cases=len(cases),
        passed=sum(c.status == "pass" for c in cases),
        failed=sum(c.status == "fail" for c in cases),
        errors=sum(c.status == "error" for c in cases),
        cost_usd=cost,
        judge_cost_usd=0.0,
        cost_known=True,
        partial_reason=None,
        prompt_tokens=0,
        completion_tokens=0,
        cache_hits=0,
        mean_latency_ms=mean_latency,
    )
    return RunResult(
        suites=[SuiteResult(name="demo", file="evals/demo.yaml", cases=cases)],
        totals=totals,
        started_at="2026-07-18T10:00:00Z",
        duration_ms=1000,
    )


def test_snapshot_shape_and_no_response_text():
    run = _run([_case("a", "pass"), _case("b", "pass")])
    snap = build_snapshot(run, _config())
    assert snap["version"] == BASELINE_VERSION
    assert set(snap["cases"]) == {"demo/a", "demo/b"}
    entry = snap["cases"]["demo/a"]
    assert entry["status"] == "pass"
    assert "cost_usd" in entry and "latency_ms" in entry
    # No response text is stored anywhere.
    assert "response" not in json.dumps(snap)
    assert snap["totals"]["cases"] == 2


def test_write_and_load_round_trip(tmp_path):
    run = _run([_case("a", "pass")])
    path = tmp_path / ".evalkit" / "baseline.json"
    write_baseline(run, _config(), str(path))
    loaded = load_baseline(str(path))
    assert loaded["cases"]["demo/a"]["status"] == "pass"


def test_load_missing_returns_none(tmp_path):
    assert load_baseline(str(tmp_path / "nope.json")) is None


def test_corrupt_baseline_raises(tmp_path):
    path = tmp_path / "b.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(BaselineError) as exc:
        load_baseline(str(path))
    assert exc.value.exit_code == 2
    assert "run 'evalkit baseline' to recreate" in exc.value.message


def test_version_mismatch_raises(tmp_path):
    path = tmp_path / "b.json"
    path.write_text('{"version": 99, "cases": {}}', encoding="utf-8")
    with pytest.raises(BaselineError):
        load_baseline(str(path))


def test_diff_categories_and_deltas(tmp_path):
    baseline_run = _run(
        [_case("keep", "pass"), _case("gone", "pass")], cost=0.0300, mean_latency=800.0
    )
    baseline = build_snapshot(baseline_run, _config())

    current = _run(
        [_case("keep", "fail"), _case("added", "pass")], cost=0.0280, mean_latency=1000.0
    )
    diff = diff_against_baseline(baseline, current, ".evalkit/baseline.json")
    assert diff["regressions"] == ["demo/keep"]
    assert diff["new"] == ["demo/added"]
    assert diff["removed"] == ["demo/gone"]
    assert diff["fixed"] == []
    assert diff["cost_delta_usd"] == round(0.0280 - 0.0300, 6)
    assert diff["mean_latency_delta_ms"] == 200.0
