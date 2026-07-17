"""Baseline snapshot write/load and diff against the current run.

The baseline stores only statuses, sample ratios, cost, and latency (no response text),
so it is safe to commit. ``evalkit run`` loads it when present and reports which cases
flipped plus cost and latency deltas; the diff never changes the exit code by itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalkit import __version__
from evalkit.config import Config
from evalkit.errors import BaselineError, ReportError
from evalkit.runner import RunResult

BASELINE_VERSION = 1


def _case_cost(cost_usd: float | None, judge_cost_usd: float) -> float | None:
    return None if cost_usd is None else round(cost_usd + judge_cost_usd, 6)


def build_snapshot(run: RunResult, config: Config) -> dict[str, Any]:
    """Build the baseline snapshot dict for a run (no response text is stored)."""
    cases = {
        case.key: {
            "status": case.status,
            "samples": case.samples,
            "samples_passed": case.samples_passed,
            "cost_usd": _case_cost(case.cost_usd, case.judge_cost_usd),
            "latency_ms": case.latency_ms,
        }
        for suite in run.suites
        for case in suite.cases
    }
    totals = run.totals
    return {
        "version": BASELINE_VERSION,
        "created_at": run.started_at,
        "evalkit_version": __version__,
        "model": config.model_for(None),
        "cases": cases,
        "totals": {
            "cases": totals.cases,
            "cost_usd": round(totals.cost_usd + totals.judge_cost_usd, 6),
            "mean_latency_ms": round(totals.mean_latency_ms, 1),
        },
    }


def write_baseline(run: RunResult, config: Config, path: str) -> None:
    """Write the baseline snapshot to ``path``; an I/O failure is a ReportError (exit 2)."""
    snapshot = build_snapshot(run, config)
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"Cannot write baseline {path}: {exc.strerror or exc}") from exc


def load_baseline(path: str) -> dict[str, Any] | None:
    """Load the baseline snapshot, or None if the file does not exist.

    A corrupt or version-mismatched file raises ``BaselineError`` (exit 2) rather than
    silently misreading it.
    """
    target = Path(path)
    if not target.exists():
        return None
    unreadable = f"Baseline {path} is unreadable; run 'evalkit baseline' to recreate."
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BaselineError(unreadable) from exc
    if not isinstance(data, dict) or data.get("version") != BASELINE_VERSION:
        raise BaselineError(unreadable)
    return data


def diff_against_baseline(baseline: dict[str, Any], run: RunResult, path: str) -> dict[str, Any]:
    """Compare a run to the baseline: flipped cases and cost/latency deltas."""
    base_cases = baseline.get("cases", {})
    current = {case.key: case for suite in run.suites for case in suite.cases}

    regressions, fixed, new = [], [], []
    for key, case in current.items():
        base = base_cases.get(key)
        if base is None:
            new.append(key)
        elif base.get("status") == "pass" and case.status != "pass":
            regressions.append(key)
        elif base.get("status") != "pass" and case.status == "pass":
            fixed.append(key)
    removed = [key for key in base_cases if key not in current]

    base_totals = baseline.get("totals", {})
    current_cost = run.totals.cost_usd + run.totals.judge_cost_usd
    current_latency = run.totals.mean_latency_ms
    return {
        "path": path,
        "regressions": sorted(regressions),
        "fixed": sorted(fixed),
        "new": sorted(new),
        "removed": sorted(removed),
        "cost_delta_usd": round(current_cost - base_totals.get("cost_usd", 0.0), 6),
        "mean_latency_delta_ms": round(
            current_latency - base_totals.get("mean_latency_ms", 0.0), 1
        ),
    }
