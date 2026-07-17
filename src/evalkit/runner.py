"""Per-case execution, result assembly, and run aggregation.

Each case runs over its ``samples`` (default 1), serially. A sample renders the prompt,
obtains a response (cache or provider), and evaluates its assertions (deterministic plus
judge). The case passes when ``passed / samples >= threshold``; cost sums over samples and
latency is the mean of fresh (non-cached) samples. Concurrency arrives in a later phase.
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
from evalkit.judge import JUDGE_PARAMS, JudgeError, build_judge_messages, parse_verdict
from evalkit.provider import ProviderCallError, complete_chat
from evalkit.suite import Assertion, Case, Suite, render_case


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
    judge_model: str | None = None
    judge_cost_known: bool = True
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


def _error_case(suite: Suite, case: Case, model: str, reason: str, judge_cost: float) -> CaseResult:
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
        judge_cost_usd=judge_cost,
        error=reason,
    )


def _judge_call(
    assertion: Assertion,
    response_text: str,
    judge_model: str,
    config: Config,
    client: httpx.Client,
    cache_root: Path,
    sample: int,
) -> tuple[object, float | None, bool]:
    """Return (Verdict, cost, cached). Retry once with a JSON-only nudge; then raise JudgeError.

    The judge call is cached with the same mechanism as the case call. The key embeds the
    base (non-retry) judge prompt, which already contains the response and rubric, so the
    key changes whenever either does.
    """
    base_content = build_judge_messages(assertion.rubric or "", response_text)[0]["content"]
    key = cache_key(judge_model, None, base_content, JUDGE_PARAMS, sample)

    entry = read_cache(cache_root, key) if config.cache else None
    if entry is not None:
        verdict = parse_verdict(entry.response_text)
        if verdict is not None:
            cost = case_cost(
                config.pricing, judge_model, entry.prompt_tokens, entry.completion_tokens
            )
            return verdict, cost, True

    for attempt in range(2):
        messages = build_judge_messages(assertion.rubric or "", response_text, retry=attempt == 1)
        resp = complete_chat(client, judge_model, messages, JUDGE_PARAMS)
        cost = case_cost(config.pricing, judge_model, resp.prompt_tokens, resp.completion_tokens)
        verdict = parse_verdict(resp.text)
        if verdict is not None:
            write_cache(
                cache_root,
                key,
                CacheEntry(
                    resp.text,
                    resp.prompt_tokens,
                    resp.completion_tokens,
                    resp.latency_ms,
                    _now_iso(),
                    judge_model,
                ),
            )
            return verdict, cost, False
    raise JudgeError()


@dataclass
class _Eval:
    """Outcome of evaluating one case's assertions (deterministic plus judge)."""

    failures: list[Failure]
    judge_cost: float
    judge_cost_known: bool
    judge_model: str | None
    judge_cached: bool
    error: str | None


def _evaluate(
    case: Case, text: str, config: Config, client: httpx.Client, cache_root: Path, sample: int
) -> _Eval:
    """Evaluate all assertions for one sample. A non-None ``error`` means the case is an error."""
    failures: list[Failure] = []
    judge_cost = 0.0
    judge_cost_known = True
    judge_model: str | None = None
    judge_cached = True
    label = sample + 1
    for assertion in case.assertions:
        if assertion.type == "judge":
            judge_model = config.judge_model or config.default_model or ""
            try:
                verdict, cost, cached = _judge_call(
                    assertion, text, judge_model, config, client, cache_root, sample
                )
            except JudgeError:
                return _Eval(
                    failures,
                    judge_cost,
                    judge_cost_known,
                    judge_model,
                    judge_cached,
                    "judge: returned an unparseable verdict",
                )
            except ProviderCallError as exc:
                return _Eval(
                    failures,
                    judge_cost,
                    judge_cost_known,
                    judge_model,
                    judge_cached,
                    f"judge: {exc.reason}",
                )
            judge_cached = judge_cached and cached
            if cost is None:
                judge_cost_known = False
            else:
                judge_cost += cost
            if not verdict.passed:
                failures.append(Failure("judge", f"judge: {verdict.reason}", sample=label))
        else:
            passed, message = evaluate_assertion(assertion, text)
            if not passed:
                failures.append(Failure(assertion.type, message, sample=label))
    return _Eval(failures, judge_cost, judge_cost_known, judge_model, judge_cached, None)


@dataclass
class _Sample:
    """The outcome of one sample of a case."""

    passed: bool
    failures: list[Failure]
    cached: bool
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    judge_cost: float
    judge_cost_known: bool
    judge_model: str | None
    error: str | None


def _mean(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _meets_threshold(passed: int, samples: int, threshold: float) -> bool:
    """True when the passing fraction meets the threshold.

    Thresholds are written to about two decimals (e.g. 0.67 for two-of-three), so the
    fraction is compared at that precision; otherwise 2/3 = 0.6667 would miss 0.67.
    """
    return round(passed / samples, 2) >= round(threshold, 2)


def _sum_tokens(values: object) -> int | None:
    counts = [v for v in values if v is not None]
    return sum(counts) if counts else None


def _run_sample(
    suite: Suite,
    case: Case,
    config: Config,
    client: httpx.Client,
    cache_root: Path,
    model: str,
    system: str | None,
    prompt: str,
    params: dict,
    sample: int,
) -> _Sample:
    """Run one sample: obtain the response (cache or provider) and evaluate its assertions."""
    key = cache_key(model, system, prompt, params, sample)
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
            return _Sample(
                False, [], False, 0, None, None, None, 0.0, True, None, f"provider: {exc.reason}"
            )
        text, prompt_tokens, completion_tokens, latency_ms = (
            resp.text,
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

    ev = _evaluate(case, text, config, client, cache_root, sample)
    return _Sample(
        passed=ev.error is None and not ev.failures,
        failures=ev.failures,
        cached=cached and ev.judge_cached,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=case_cost(config.pricing, model, prompt_tokens, completion_tokens),
        judge_cost=ev.judge_cost,
        judge_cost_known=ev.judge_cost_known,
        judge_model=ev.judge_model,
        error=ev.error,
    )


def run_case(
    suite: Suite, case: Case, config: Config, client: httpx.Client, cache_root: Path
) -> CaseResult:
    """Execute a case over its ``samples`` and combine them against the pass threshold."""
    model = config.model_for(suite.model) or ""
    system, prompt = render_case(suite, case)
    params = _merged_params(suite.params)

    samples = [
        _run_sample(suite, case, config, client, cache_root, model, system, prompt, params, s)
        for s in range(case.samples)
    ]

    error = next((s.error for s in samples if s.error is not None), None)
    judge_cost = sum(s.judge_cost for s in samples)
    if error is not None:
        return _error_case(suite, case, model, error, judge_cost)

    passed = sum(s.passed for s in samples)
    status = "pass" if _meets_threshold(passed, case.samples, case.threshold) else "fail"
    failures = [] if status == "pass" else [f for s in samples for f in s.failures]

    fresh_latencies = [s.latency_ms for s in samples if not s.cached]
    all_latencies = [s.latency_ms for s in samples]
    latency_ms = int(_mean(fresh_latencies if fresh_latencies else all_latencies))

    sample_costs = [s.cost_usd for s in samples]
    cost_usd = sum(sample_costs) if all(c is not None for c in sample_costs) else None

    return CaseResult(
        suite=suite.name,
        name=case.name,
        key=f"{suite.name}/{case.name}",
        model=model,
        status=status,
        samples=case.samples,
        samples_passed=passed,
        threshold=case.threshold,
        latency_ms=latency_ms,
        cached=all(s.cached for s in samples),
        prompt_tokens=_sum_tokens(s.prompt_tokens for s in samples),
        completion_tokens=_sum_tokens(s.completion_tokens for s in samples),
        cost_usd=cost_usd,
        judge_cost_usd=judge_cost,
        judge_model=next((s.judge_model for s in samples if s.judge_model), None),
        judge_cost_known=all(s.judge_cost_known for s in samples),
        failures=failures,
    )


def _aggregate(suite_results: list[SuiteResult], config: Config) -> RunTotals:
    cases = [c for sr in suite_results for c in sr.cases]
    ran = [c for c in cases if c.status != "error"]

    missing_pricing = sorted(
        {c.model for c in ran if not has_pricing(config.pricing, c.model)}
        | {
            c.judge_model
            for c in ran
            if c.judge_model and not has_pricing(config.pricing, c.judge_model)
        }
    )
    missing_usage = any(
        c.cost_usd is None and has_pricing(config.pricing, c.model) for c in ran
    ) or any(
        not c.judge_cost_known and c.judge_model and has_pricing(config.pricing, c.judge_model)
        for c in ran
    )
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
