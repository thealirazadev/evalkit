"""Judge verdict parsing, prompt build, model resolution, and runner integration."""

import json

from conftest import chat_response

from evalkit.config import Config, load_config
from evalkit.judge import build_judge_messages, parse_verdict
from evalkit.provider import build_client
from evalkit.runner import run_suites
from evalkit.suite import load_suite

PRICING = {
    "example-model-1": {"input": 3.0, "output": 15.0},
    "example-judge-1": {"input": 0.5, "output": 1.5},
}


def _config():
    return Config(
        base_url="https://api.example.com/v1",
        api_key="secret-key",
        default_model="example-model-1",
        cli_model=None,
        judge_model="example-judge-1",
        concurrency=4,
        timeout_seconds=5,
        cache=True,
        suites_glob="evals/**/*.yaml",
        pricing=PRICING,
        no_color=True,
        config_path=None,
    )


JUDGE_SUITE = """
suite: demo
model: example-model-1
prompt: "Answer about {{topic}}"
cases:
  - name: c
    vars: {topic: refunds}
    assert:
      - type: contains
        value: reply
      - type: judge
        rubric: The reply must not promise a refund outcome.
"""


def _suite(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(JUDGE_SUITE, encoding="utf-8")
    return load_suite(path, cwd=tmp_path)


def _client(transport_factory, handler):
    rec = transport_factory(handler)
    return build_client("https://api.example.com/v1", "secret-key", 5.0, rec.transport), rec


# -- unit: verdict parsing --------------------------------------------------


def test_parse_clean_json():
    v = parse_verdict('{"pass": true, "reason": "looks good"}')
    assert v.passed is True
    assert v.reason == "looks good"


def test_parse_json_with_surrounding_prose():
    v = parse_verdict('Sure! Here is my verdict: {"pass": false, "reason": "nope"} Thanks.')
    assert v.passed is False
    assert v.reason == "nope"


def test_parse_garbage_returns_none():
    assert parse_verdict("I think it passes.") is None
    assert parse_verdict('{"reason": "no pass key"}') is None


def test_build_messages_includes_rubric_and_response():
    messages = build_judge_messages("RUBRIC-X", "RESPONSE-Y")
    content = messages[0]["content"]
    assert "RUBRIC-X" in content
    assert "RESPONSE-Y" in content
    retry = build_judge_messages("R", "S", retry=True)
    assert "only the JSON object" in retry[0]["content"]


def test_judge_model_resolution_order(tmp_path):
    (tmp_path / "evalkit.yaml").write_text(
        "provider: {model: pm}\njudge: {model: jm}\n", encoding="utf-8"
    )
    assert load_config(env={}, cwd=tmp_path).judge_model == "jm"
    assert load_config(env={"EVALKIT_JUDGE_MODEL": "em"}, cwd=tmp_path).judge_model == "em"
    assert load_config(env={}, cwd=tmp_path, cli_judge_model="fm").judge_model == "fm"
    # Falls back to provider.model when no judge configured.
    (tmp_path / "evalkit.yaml").write_text("provider: {model: pm}\n", encoding="utf-8")
    assert load_config(env={}, cwd=tmp_path).judge_model == "pm"


# -- integration: judge in the runner --------------------------------------


def _handler(judge_body):
    def handler(req, n):
        body = json.loads(req.content)
        if body["model"] == "example-judge-1":
            return chat_response(judge_body)
        return chat_response('{"reply": "hi"}')

    return handler


def test_judge_pass(tmp_path, transport_factory):
    client, _ = _client(transport_factory, _handler('{"pass": true, "reason": "fine"}'))
    result = run_suites([_suite(tmp_path)], _config(), client, tmp_path / "cache")
    case = result.suites[0].cases[0]
    assert case.status == "pass"
    assert case.judge_cost_usd > 0
    assert result.totals.judge_cost_usd > 0


def test_judge_fail_surfaces_reason(tmp_path, transport_factory):
    reason = "reply promises a refund outcome; rubric forbids it"
    client, _ = _client(transport_factory, _handler(f'{{"pass": false, "reason": "{reason}"}}'))
    result = run_suites([_suite(tmp_path)], _config(), client, tmp_path / "cache")
    case = result.suites[0].cases[0]
    assert case.status == "fail"
    judge_failure = [f for f in case.failures if f.assertion == "judge"][0]
    assert judge_failure.message == f"judge: {reason}"


def test_judge_call_is_cached_on_rerun(tmp_path, transport_factory):
    client, rec = _client(transport_factory, _handler('{"pass": true, "reason": "fine"}'))
    suite = _suite(tmp_path)
    cache_root = tmp_path / "cache"
    run_suites([suite], _config(), client, cache_root)
    calls = rec.call_count  # one case call + one judge call
    result = run_suites([suite], _config(), client, cache_root)
    assert rec.call_count == calls  # no new calls: both case and judge replayed from cache
    case = result.suites[0].cases[0]
    assert case.cached is True
    assert case.judge_cost_usd > 0  # modeled judge cost still attributed on a cached replay


def test_unparseable_verdict_is_error(tmp_path, transport_factory):
    client, rec = _client(transport_factory, _handler("not json at all"))
    result = run_suites([_suite(tmp_path)], _config(), client, tmp_path / "cache")
    case = result.suites[0].cases[0]
    assert case.status == "error"
    assert "unparseable verdict" in case.error
    # One case call + two judge attempts (original + JSON-only retry).
    assert rec.call_count == 3
