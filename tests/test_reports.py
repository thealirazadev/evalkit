"""JSON report: documented schema, judge reasons, and write errors."""

import json
import xml.etree.ElementTree as ET

import jsonschema
import pytest
from conftest import chat_response

from evalkit.config import Config
from evalkit.errors import ReportError
from evalkit.provider import build_client
from evalkit.report_json import build_report, write_json_report
from evalkit.report_junit import build_junit, write_junit_report
from evalkit.runner import run_suites
from evalkit.suite import load_suite

PRICING = {
    "example-model-1": {"input": 3.0, "output": 15.0},
    "example-judge-1": {"input": 0.5, "output": 1.5},
}

REPORT_SCHEMA = {
    "type": "object",
    "required": ["evalkit_version", "started_at", "duration_ms", "config", "totals", "suites"],
    "properties": {
        "evalkit_version": {"type": "string"},
        "started_at": {"type": "string"},
        "duration_ms": {"type": "integer"},
        "config": {
            "type": "object",
            "required": ["model", "judge_model", "concurrency", "cache"],
            "properties": {
                "model": {"type": ["string", "null"]},
                "judge_model": {"type": ["string", "null"]},
                "concurrency": {"type": "integer"},
                "cache": {"type": "boolean"},
            },
        },
        "totals": {
            "type": "object",
            "required": [
                "cases",
                "passed",
                "failed",
                "errors",
                "cost_usd",
                "judge_cost_usd",
                "cost_known",
                "prompt_tokens",
                "completion_tokens",
                "cache_hits",
            ],
            "properties": {
                "cases": {"type": "integer"},
                "passed": {"type": "integer"},
                "failed": {"type": "integer"},
                "errors": {"type": "integer"},
                "cost_usd": {"type": ["number", "null"]},
                "judge_cost_usd": {"type": ["number", "null"]},
                "cost_known": {"type": "boolean"},
                "cache_hits": {"type": "integer"},
            },
        },
        "baseline": {"type": ["object", "null"]},
        "suites": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "file", "cases"],
                "properties": {
                    "name": {"type": "string"},
                    "file": {"type": "string"},
                    "cases": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "name",
                                "status",
                                "samples",
                                "samples_passed",
                                "threshold",
                                "latency_ms",
                                "cached",
                                "cost_usd",
                                "failures",
                            ],
                            "properties": {
                                "status": {"enum": ["pass", "fail", "error"]},
                                "failures": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["assertion", "message"],
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}

SUITE = """
suite: demo
model: example-model-1
prompt: "Answer about {{topic}}"
cases:
  - name: good
    vars: {topic: a}
    assert:
      - type: contains
        value: reply
  - name: bad
    vars: {topic: b}
    assert:
      - type: judge
        rubric: The reply must not promise a refund.
"""


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


def _run(tmp_path, transport_factory):
    path = tmp_path / "s.yaml"
    path.write_text(SUITE, encoding="utf-8")
    suite = load_suite(path, cwd=tmp_path)

    def handler(req, n):
        body = json.loads(req.content)
        if body["model"] == "example-judge-1":
            return chat_response('{"pass": false, "reason": "promises a refund"}')
        return chat_response('{"reply": "hi"}')

    rec = transport_factory(handler)
    client = build_client("https://api.example.com/v1", "secret-key", 5.0, rec.transport)
    return run_suites([suite], _config(), client, tmp_path / "cache")


def test_report_matches_schema(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    report = build_report(run, _config())
    jsonschema.validate(report, REPORT_SCHEMA)
    assert report["baseline"] is None
    assert report["config"]["judge_model"] == "example-judge-1"


def test_totals_and_judge_reason_present(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    report = build_report(run, _config())
    assert report["totals"]["cases"] == 2
    assert report["totals"]["passed"] == 1
    assert report["totals"]["failed"] == 1
    assert report["totals"]["judge_cost_usd"] > 0
    bad = [c for s in report["suites"] for c in s["cases"] if c["name"] == "bad"][0]
    assert bad["status"] == "fail"
    messages = [f["message"] for f in bad["failures"]]
    assert "judge: promises a refund" in messages


def test_write_json_file_round_trip(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    out = tmp_path / "out" / "report.json"
    write_json_report(run, _config(), str(out))
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["totals"]["cases"] == 2


def test_unwritable_path_raises_report_error(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    # Point at an existing directory: writing there fails.
    with pytest.raises(ReportError) as exc:
        write_json_report(run, _config(), str(tmp_path))
    assert exc.value.exit_code == 2
    assert "Cannot write report" in exc.value.message


def test_junit_structure_and_judge_reason(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    root = build_junit(run)
    assert root.tag == "testsuites"
    assert root.attrib["tests"] == "2"
    assert root.attrib["failures"] == "1"

    testsuite = root.find("testsuite")
    assert testsuite.attrib["name"] == "demo"
    cases = {tc.attrib["name"]: tc for tc in testsuite.findall("testcase")}
    assert cases["good"].attrib["classname"] == "demo"
    assert "time" in cases["good"].attrib
    assert cases["good"].find("failure") is None

    failure = cases["bad"].find("failure")
    assert failure is not None
    assert "judge: promises a refund" in failure.attrib["message"]
    assert "judge: promises a refund" in failure.text


def test_junit_error_element(tmp_path, transport_factory):
    import httpx

    path = tmp_path / "s.yaml"
    path.write_text(SUITE, encoding="utf-8")
    suite = load_suite(path, cwd=tmp_path)
    rec = transport_factory(lambda req, n: httpx.Response(503))
    client = build_client("https://api.example.com/v1", "secret-key", 5.0, rec.transport)
    run = run_suites([suite], _config(), client, tmp_path / "cache")
    root = build_junit(run)
    error = root.find("testsuite/testcase/error")
    assert error is not None
    assert "provider: 503" in error.attrib["message"]


def test_junit_file_parses(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    out = tmp_path / "junit.xml"
    write_junit_report(run, str(out))
    tree = ET.parse(out)  # a standard JUnit consumer parses valid XML
    assert tree.getroot().tag == "testsuites"


def test_junit_unwritable_path_raises(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    with pytest.raises(ReportError):
        write_junit_report(run, str(tmp_path))
