"""JSON run-report writer.

Emits the machine-readable report documented in ``docs/architecture.md`` so CI can read
totals, per-case status, failures, cost, latency, and cache info without parsing terminal
output. ``baseline`` is null until a baseline exists (added in a later phase).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalkit import __version__
from evalkit.config import Config
from evalkit.errors import ReportError
from evalkit.runner import CaseResult, RunResult


def _round(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None else None


def _case_dict(case: CaseResult) -> dict[str, Any]:
    return {
        "name": case.name,
        "status": case.status,
        "samples": case.samples,
        "samples_passed": case.samples_passed,
        "threshold": case.threshold,
        "latency_ms": case.latency_ms,
        "cached": case.cached,
        "prompt_tokens": case.prompt_tokens,
        "completion_tokens": case.completion_tokens,
        "cost_usd": _round(case.cost_usd),
        "failures": [{"assertion": f.assertion, "message": f.message} for f in case.failures],
        "error": case.error,
    }


def build_report(
    run: RunResult, config: Config, baseline: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Assemble the JSON report as a plain dict."""
    totals = run.totals
    return {
        "evalkit_version": __version__,
        "started_at": run.started_at,
        "duration_ms": run.duration_ms,
        "config": {
            "model": config.model_for(None),
            "judge_model": config.judge_model,
            "concurrency": config.concurrency,
            "cache": config.cache,
        },
        "totals": {
            "cases": totals.cases,
            "passed": totals.passed,
            "failed": totals.failed,
            "errors": totals.errors,
            "cost_usd": _round(totals.cost_usd),
            "judge_cost_usd": _round(totals.judge_cost_usd),
            "cost_known": totals.cost_known,
            "prompt_tokens": totals.prompt_tokens,
            "completion_tokens": totals.completion_tokens,
            "cache_hits": totals.cache_hits,
        },
        "baseline": baseline,
        "suites": [
            {
                "name": sr.name,
                "file": sr.file,
                "cases": [_case_dict(c) for c in sr.cases],
            }
            for sr in run.suites
        ],
    }


def write_json_report(
    run: RunResult, config: Config, path: str, baseline: dict[str, Any] | None = None
) -> None:
    """Write the JSON report to ``path``; an I/O failure is a ReportError (exit 2)."""
    report = build_report(run, config, baseline)
    target = Path(path)
    try:
        if target.parent != Path(""):
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"Cannot write report {path}: {exc.strerror or exc}") from exc
