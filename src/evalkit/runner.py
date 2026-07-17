"""Per-case execution, result assembly, and run aggregation.

Phase 1 runs one sample per case, serially. Each case renders its prompt, obtains a
response (cache or provider), evaluates the deterministic assertions, and records cost
and latency. N-sample looping, the judge, and concurrency arrive in later phases.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from evalkit.assertions import evaluate_assertion
from evalkit.cache import CacheEntry, cache_key, read_cache, write_cache
from evalkit.config import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, Config
from evalkit.cost import case_cost, has_pricing
from evalkit.provider import ProviderCallError, complete_chat
from evalkit.suite import Case, Suite, render_case


@dataclass
class Failure:
    """One failed assertion within a case, tagged with its 1-based sample index."""

    assertion: str
    message: str
    sample: int = 1


@dataclass
class CaseResult:
    """The outcome of running one case: status, accounting, and any failures."""

    suite: str
    name: str
    key: str
    model: str
    status: str  # "pass" | "fail" | "error"
    samples: int
    samples_passed: int
    threshold: float
    latency_ms: int
    cached: bool
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    judge_cost_usd: float
    failures: list[Failure] = field(default_factory=list)
    error: str | None = None


@dataclass
class SuiteResult:
    name: str
    file: str
    cases: list[CaseResult]


@dataclass
class RunTotals:
    cases: int
    passed: int
    failed: int
    errors: int
    cost_usd: float
    judge_cost_usd: float
    cost_known: bool
    partial_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    cache_hits: int
    mean_latency_ms: float


@dataclass
class RunResult:
    suites: list[SuiteResult]
    totals: RunTotals
    started_at: str
    duration_ms: int


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _merged_params(suite_params: dict) -> dict:
    params = {"temperature": DEFAULT_TEMPERATURE, "max_tokens": DEFAULT_MAX_TOKENS}
    params.update(suite_params)
    return params


def _build_messages(system: str | None, prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def run_case(
    suite: Suite, case: Case, config: Config, client: httpx.Client, cache_root: Path
) -> CaseResult:
    """Execute one case (single sample) and return its result."""
    model = config.model_for(suite.model) or ""
    system, prompt = render_case(suite, case)
    params = _merged_params(suite.params)
    key = cache_key(model, system, prompt, params, 0)

    entry = read_cache(cache_root, key) if config.cache else None
    if entry is not None:
        text = entry.response_text
        prompt_tokens, completion_tokens, latency_ms = (
            entry.prompt_tokens,
            entry.completion_tokens,
            entry.latency_ms,
        )
        cached = True
    else:
        try:
            resp = complete_chat(client, model, _build_messages(system, prompt), params)
        except ProviderCallError as exc:
            return CaseResult(
                suite=suite.name,
                name=case.name,
                key=f"{suite.name}/{case.name}",
                model=model,
                status="error",
                samples=1,
                samples_passed=0,
                threshold=case.threshold,
                latency_ms=0,
                cached=False,
                prompt_tokens=None,
                completion_tokens=None,
                cost_usd=None,
                judge_cost_usd=0.0,
                error=f"provider: {exc.reason}",
            )
        text = resp.text
        prompt_tokens, completion_tokens, latency_ms = (
            resp.prompt_tokens,
            resp.completion_tokens,
            resp.latency_ms,
        )
        cached = False
        write_cache(
            cache_root,
            key,
            CacheEntry(text, prompt_tokens, completion_tokens, latency_ms, _now_iso(), model),
        )

    failures = [
        Failure(a.type, message, sample=1)
        for a in case.assertions
        for passed, message in [evaluate_assertion(a, text)]
        if not passed
    ]
    status = "pass" if not failures else "fail"
    return CaseResult(
        suite=suite.name,
        name=case.name,
        key=f"{suite.name}/{case.name}",
        model=model,
        status=status,
        samples=1,
        samples_passed=1 if status == "pass" else 0,
        threshold=case.threshold,
        latency_ms=latency_ms,
        cached=cached,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=case_cost(config.pricing, model, prompt_tokens, completion_tokens),
        judge_cost_usd=0.0,
        failures=failures,
    )


def _aggregate(suite_results: list[SuiteResult], config: Config) -> RunTotals:
    cases = [c for sr in suite_results for c in sr.cases]
    ran = [c for c in cases if c.status != "error"]

    missing_pricing = sorted({c.model for c in ran if not has_pricing(config.pricing, c.model)})
    missing_usage = any(c.cost_usd is None and has_pricing(config.pricing, c.model) for c in ran)
    cost_known = not missing_pricing and not missing_usage
    partial_reason = None
    if missing_pricing:
        partial_reason = f"no pricing for {missing_pricing[0]}"
    elif missing_usage:
        partial_reason = "missing token usage"

    latencies = [c.latency_ms for c in cases if c.status != "error"]
    return RunTotals(
        cases=len(cases),
        passed=sum(c.status == "pass" for c in cases),
        failed=sum(c.status == "fail" for c in cases),
        errors=sum(c.status == "error" for c in cases),
        cost_usd=sum(c.cost_usd or 0.0 for c in cases),
        judge_cost_usd=sum(c.judge_cost_usd for c in cases),
        cost_known=cost_known,
        partial_reason=partial_reason,
        prompt_tokens=sum(c.prompt_tokens or 0 for c in cases),
        completion_tokens=sum(c.completion_tokens or 0 for c in cases),
        cache_hits=sum(c.cached for c in cases),
        mean_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
    )


def exit_code(run: RunResult) -> int:
    """Map run outcomes to an exit code. Precedence: 2 (errors) beats 1 (failures) beats 0."""
    if run.totals.errors:
        return 2
    if run.totals.failed:
        return 1
    return 0


def run_suites(
    suites: list[Suite], config: Config, client: httpx.Client, cache_root: Path
) -> RunResult:
    """Run every case in every suite (serially) and assemble the run result."""
    start = time.perf_counter()
    started_at = _now_iso()
    suite_results = [
        SuiteResult(
            name=suite.name,
            file=suite.file,
            cases=[run_case(suite, case, config, client, cache_root) for case in suite.cases],
        )
        for suite in suites
    ]
    totals = _aggregate(suite_results, config)
    duration_ms = int((time.perf_counter() - start) * 1000)
    return RunResult(suite_results, totals, started_at, duration_ms)
