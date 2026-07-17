"""Runner: pass/fail/error status, all-assertions-must-pass, caching, cost."""

from conftest import chat_response

from evalkit.config import Config
from evalkit.provider import build_client
from evalkit.runner import exit_code, run_suites
from evalkit.suite import load_suite

PRICING = {"example-model-1": {"input": 3.00, "output": 15.00}}


def make_config(cache=True, pricing=None):
    return Config(
        base_url="https://api.example.com/v1",
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


def test_exit_code_precedence(tmp_path, transport_factory):
    import httpx

    # First case (calls 1-3, all retries) errors; second case fails contains -> error wins.
    def handler(req, n):
        return httpx.Response(503) if n <= 3 else chat_response('{"reply": "ok"}')

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
