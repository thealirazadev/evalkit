"""Runner: pass/fail/error status, all-assertions-must-pass, caching, cost."""

import time

from conftest import chat_response

from evalkit.config import Config
from evalkit.provider import build_client
from evalkit.runner import _meets_threshold, exit_code, run_suites
from evalkit.suite import load_suite

PRICING = {"example-model-1": {"input": 3.00, "output": 15.00}}


def make_config(cache=True, pricing=None, base_url="https://api.example.com/v1"):
    return Config(
        base_url=base_url,
        api_key="secret-key",
        default_model="example-model-1",
        cli_model=None,
        judge_model="example-model-1",
        concurrency=4,
        timeout_seconds=5,
        cache=cache,
        suites_glob="evals/**/*.yaml",
        pricing=PRICING if pricing is None else pricing,
        no_color=True,
        config_path=None,
    )


SUITE_YAML = """
suite: demo
model: example-model-1
prompt: "Say something about {{topic}}"
cases:
  - name: good
    vars: {topic: refunds}
    assert:
      - type: contains
        value: reply
  - name: bad
    vars: {topic: shipping}
    assert:
      - type: contains
        value: NOTPRESENT
"""


def _suite(tmp_path, text=SUITE_YAML, name="s.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return load_suite(path, cwd=tmp_path)


def _client(transport_factory, handler):
    rec = transport_factory(handler)
    return build_client("https://api.example.com/v1", "secret-key", 5.0, rec.transport), rec


def test_pass_and_fail_statuses(tmp_path, transport_factory):
    client, _ = _client(transport_factory, lambda req, n: chat_response('{"reply": "ok"}'))
    suite = _suite(tmp_path)
    result = run_suites([suite], make_config(), client, tmp_path / "cache")
    cases = result.suites[0].cases
    assert cases[0].status == "pass"
    assert cases[1].status == "fail"
    assert cases[1].failures[0].assertion == "contains"
    assert result.totals.passed == 1
    assert result.totals.failed == 1


def test_all_assertions_must_pass(tmp_path, transport_factory):
    text = """
suite: demo
model: example-model-1
prompt: hi
cases:
  - name: c
    assert:
      - type: contains
        value: reply
      - type: contains
        value: MISSING
"""
    client, _ = _client(transport_factory, lambda req, n: chat_response("reply only"))
    result = run_suites([_suite(tmp_path, text)], make_config(), client, tmp_path / "cache")
    case = result.suites[0].cases[0]
    assert case.status == "fail"
    assert len(case.failures) == 1  # only the MISSING assertion failed


def test_provider_error_marks_case_error(tmp_path, transport_factory):
    import httpx

    client, _ = _client(transport_factory, lambda req, n: httpx.Response(503))
    cfg = make_config()
    # Speed: the runner uses default retries; a 503 always fails after 3 attempts.
    result = run_suites([_suite(tmp_path)], cfg, client, tmp_path / "cache")
    case = result.suites[0].cases[0]
    assert case.status == "error"
    assert case.error.startswith("provider: 503")
    assert result.totals.errors == 2  # both cases in the suite hit 503


def test_second_run_uses_cache_zero_calls(tmp_path, transport_factory):
    client, rec = _client(transport_factory, lambda req, n: chat_response('{"reply": "ok"}'))
    suite = _suite(tmp_path)
    cache_root = tmp_path / "cache"
    run_suites([suite], make_config(), client, cache_root)
    first_calls = rec.call_count
    run_suites([suite], make_config(), client, cache_root)
    assert rec.call_count == first_calls  # no new provider calls
    result = run_suites([suite], make_config(), client, cache_root)
    assert all(c.cached for c in result.suites[0].cases)


def test_different_base_url_does_not_reuse_cache(tmp_path, transport_factory):
    # Same model id and prompt at two different endpoints must not share a cache
    # entry, or one endpoint would silently serve the other's response.
    suite = _suite(tmp_path)
    cache_root = tmp_path / "cache"

    client_a, rec_a = _client(transport_factory, lambda req, n: chat_response('{"reply": "A"}'))
    run_suites([suite], make_config(base_url="https://a.example.com/v1"), client_a, cache_root)
    assert rec_a.call_count == 2

    client_b, rec_b = _client(transport_factory, lambda req, n: chat_response('{"reply": "B"}'))
    result_b = run_suites(
        [suite], make_config(base_url="https://b.example.com/v1"), client_b, cache_root
    )
    # Endpoint B must make its own fresh calls, not read A's cached responses.
    assert rec_b.call_count == 2
    assert all(not c.cached for c in result_b.suites[0].cases)
    assert result_b.suites[0].cases[0].response_excerpt == '{"reply": "B"}'


def test_no_cache_bypasses_reads_but_writes(tmp_path, transport_factory):
    client, rec = _client(transport_factory, lambda req, n: chat_response('{"reply": "ok"}'))
    suite = _suite(tmp_path)
    cache_root = tmp_path / "cache"
    run_suites([suite], make_config(cache=False), client, cache_root)
    calls_after_first = rec.call_count
    assert calls_after_first == 2  # both cases called fresh
    # A cached run afterwards reads what the no-cache run wrote.
    result = run_suites([suite], make_config(cache=True), client, cache_root)
    assert rec.call_count == calls_after_first  # writes from run 1 are now hits
    assert all(c.cached for c in result.suites[0].cases)


def test_cost_computed_and_partial_flag(tmp_path, transport_factory):
    client, _ = _client(
        transport_factory,
        lambda req, n: chat_response('{"reply": "ok"}', prompt_tokens=1000, completion_tokens=500),
    )
    suite = _suite(tmp_path)
    result = run_suites([suite], make_config(), client, tmp_path / "cache")
    case = result.suites[0].cases[0]
    assert round(case.cost_usd, 4) == 0.0105
    assert result.totals.cost_known is True

    # No pricing -> partial with the model named.
    result2 = run_suites([suite], make_config(pricing={}), client, tmp_path / "cache2")
    assert result2.totals.cost_known is False
    assert "no pricing for example-model-1" in result2.totals.partial_reason


def test_progress_callback_invoked_per_case(tmp_path, transport_factory):
    client, _ = _client(transport_factory, lambda req, n: chat_response('{"reply": "ok"}'))
    suite = _suite(tmp_path)  # SUITE_YAML has 2 cases
    seen = []
    run_suites(
        [suite],
        make_config(),
        client,
        tmp_path / "cache",
        progress=lambda d, k: seen.append((d, k)),
    )
    assert [d for d, _ in seen] == [1, 2]  # done count increments once per case
    assert all("/" in k for _, k in seen)  # keys are suite/case


def test_concurrency_bounds_in_flight_and_orders_results(tmp_path, transport_factory):
    import threading

    cases = "\n".join(
        f"  - name: c{i}\n    vars: {{topic: t{i}}}\n    assert: [{{type: contains, value: reply}}]"
        for i in range(8)
    )
    text = f"suite: demo\nmodel: example-model-1\nprompt: 'p {{{{topic}}}}'\ncases:\n{cases}\n"

    lock = threading.Lock()
    state = {"active": 0, "max": 0}

    def handler(req, n):
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        time.sleep(0.02)  # hold the slot so requests overlap
        with lock:
            state["active"] -= 1
        return chat_response('{"reply": "ok"}')

    cfg = Config(
        base_url="https://api.example.com/v1",
        api_key="k",
        default_model="example-model-1",
        cli_model=None,
        judge_model="example-model-1",
        concurrency=4,
        timeout_seconds=5,
        cache=False,
        suites_glob="x",
        pricing=PRICING,
        no_color=True,
        config_path=None,
    )
    client, _ = _client(transport_factory, handler)
    result = run_suites([_suite(tmp_path, text)], cfg, client, tmp_path / "cache")
    names = [c.name for c in result.suites[0].cases]
    assert names == [f"c{i}" for i in range(8)]  # file order preserved
    assert state["max"] <= 4  # never more than 4 in flight
    assert state["max"] >= 2  # actually ran in parallel


NSAMPLE_SUITE = """
suite: demo
model: example-model-1
prompt: "generate {{topic}}"
cases:
  - name: c
    vars: {topic: x}
    samples: 3
    threshold: 0.67
    assert:
      - type: contains
        value: reply
"""


def test_meets_threshold_rounding():
    # Intended: 2/3 = 0.6667 rounds to 0.67 and meets a 0.67 threshold.
    assert _meets_threshold(2, 3, 0.67) is True
    assert _meets_threshold(3, 3, 1.0) is True
    # A stricter three-decimal threshold above 0.67 must NOT be met by 2/3: 0.6667 is
    # genuinely below it. Rounding the threshold to 0.67 would be a false pass.
    assert _meets_threshold(2, 3, 0.674) is False
    assert _meets_threshold(2, 3, 0.671) is False
    # A ratio below the bar still fails.
    assert _meets_threshold(1, 3, 0.67) is False


def test_nsample_threshold_pass(tmp_path, transport_factory):
    # 2 of 3 samples pass, threshold 0.67 -> case passes with ratio 2/3.
    def handler(req, n):
        return chat_response('{"reply": "x"}') if n in (1, 2) else chat_response('{"no": 1}')

    client, rec = _client(transport_factory, handler)
    result = run_suites(
        [_suite(tmp_path, NSAMPLE_SUITE)], make_config(), client, tmp_path / "cache"
    )
    case = result.suites[0].cases[0]
    assert case.samples == 3
    assert case.samples_passed == 2
    assert case.status == "pass"
    assert rec.call_count == 3  # one provider call per sample (distinct cache keys)


def test_nsample_threshold_fail(tmp_path, transport_factory):
    def handler(req, n):
        return chat_response('{"reply": "x"}') if n == 1 else chat_response('{"no": 1}')

    client, _ = _client(transport_factory, handler)
    result = run_suites(
        [_suite(tmp_path, NSAMPLE_SUITE)], make_config(), client, tmp_path / "cache"
    )
    case = result.suites[0].cases[0]
    assert case.samples_passed == 1
    assert case.status == "fail"


def test_nsample_cost_sums_over_samples(tmp_path, transport_factory):
    client, _ = _client(
        transport_factory,
        lambda req, n: chat_response('{"reply": "x"}', prompt_tokens=1000, completion_tokens=500),
    )
    result = run_suites(
        [_suite(tmp_path, NSAMPLE_SUITE)], make_config(), client, tmp_path / "cache"
    )
    case = result.suites[0].cases[0]
    # 0.0105 per sample x 3 samples.
    assert round(case.cost_usd, 4) == round(0.0105 * 3, 4)


def test_nsample_cached_replays_identically(tmp_path, transport_factory):
    def handler(req, n):
        return chat_response('{"reply": "x"}') if n in (1, 2) else chat_response('{"no": 1}')

    client, rec = _client(transport_factory, handler)
    cache_root = tmp_path / "cache"
    first = run_suites([_suite(tmp_path, NSAMPLE_SUITE)], make_config(), client, cache_root)
    calls = rec.call_count
    second = run_suites([_suite(tmp_path, NSAMPLE_SUITE)], make_config(), client, cache_root)
    assert rec.call_count == calls  # zero new calls
    case = second.suites[0].cases[0]
    assert case.samples_passed == first.suites[0].cases[0].samples_passed == 2
    assert case.cached is True


def test_exit_code_precedence(tmp_path, transport_factory):
    import json

    import httpx

    # Dispatch by request content so the outcome is deterministic under concurrency:
    # the "refunds" case errors (persistent 503); the "shipping" case fails its contains.
    def handler(req, n):
        content = json.loads(req.content)["messages"][-1]["content"]
        return httpx.Response(503) if "refunds" in content else chat_response('{"reply": "ok"}')

    client, _ = _client(transport_factory, handler)
    result = run_suites([_suite(tmp_path)], make_config(), client, tmp_path / "cache")
    assert result.totals.errors >= 1
    assert exit_code(result) == 2


def test_exit_code_failure_and_pass(tmp_path, transport_factory):
    client, _ = _client(transport_factory, lambda req, n: chat_response('{"reply": "ok"}'))
    result = run_suites([_suite(tmp_path)], make_config(), client, tmp_path / "cache")
    assert result.totals.failed == 1 and result.totals.errors == 0
    assert exit_code(result) == 1

    passing = """
suite: demo
model: example-model-1
prompt: hi
cases:
  - name: ok
    assert: [{type: contains, value: reply}]
"""
    result2 = run_suites(
        [_suite(tmp_path, passing, "p.yaml")], make_config(), client, tmp_path / "c2"
    )
    assert exit_code(result2) == 0
