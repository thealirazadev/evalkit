"""HTML report: standalone document, pass/fail, surfaced reasons, escaping, determinism."""

import json
from html.parser import HTMLParser

import pytest
from conftest import chat_response

from evalkit.config import Config
from evalkit.errors import ReportError
from evalkit.provider import build_client
from evalkit.report_html import build_html, write_html_report
from evalkit.runner import run_suites
from evalkit.suite import load_suite

PRICING = {
    "example-model-1": {"input": 3.0, "output": 15.0},
    "example-judge-1": {"input": 0.5, "output": 1.5},
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


def _run(tmp_path, transport_factory, *, judge_pass=False, judge_reason="promises a refund"):
    path = tmp_path / "s.yaml"
    path.write_text(SUITE, encoding="utf-8")
    suite = load_suite(path, cwd=tmp_path)

    def handler(req, n):
        body = json.loads(req.content)
        if body["model"] == "example-judge-1":
            verdict = (
                {"pass": True, "reason": "ok"}
                if judge_pass
                else {"pass": False, "reason": judge_reason}
            )
            return chat_response(json.dumps(verdict))
        return chat_response('{"reply": "hi"}')

    rec = transport_factory(handler)
    client = build_client("https://api.example.com/v1", "secret-key", 5.0, rec.transport)
    return run_suites([suite], _config(), client, tmp_path / "cache")


def _parses(document: str) -> None:
    """Feeding the document to the stdlib HTML parser must not raise."""
    HTMLParser().feed(document)


def test_html_is_valid_standalone_document(tmp_path, transport_factory):
    doc = build_html(_run(tmp_path, transport_factory), _config())
    assert doc.startswith("<!DOCTYPE html>")
    for marker in (
        "<html",
        "</html>",
        "<head>",
        "</head>",
        "<body>",
        "</body>",
        "<title",
        "<style",
    ):
        assert marker in doc
    _parses(doc)


def test_html_is_self_contained_no_external_requests(tmp_path, transport_factory):
    doc = build_html(_run(tmp_path, transport_factory), _config())
    # No stylesheet links, no external resource loads, no CDN/font imports: the file is
    # everything the browser needs. base_url is deliberately never rendered into the report.
    for forbidden in ("<link", "src=", "http://", "https://", "@import", "<script"):
        assert forbidden not in doc


def test_html_contains_overall_fail_and_case_statuses(tmp_path, transport_factory):
    doc = build_html(_run(tmp_path, transport_factory), _config())
    assert '<span class="badge fail">FAIL</span>' in doc
    assert "good" in doc and "bad" in doc
    assert "failed: 1" in doc
    assert "passed: 1" in doc


def test_html_all_pass_shows_pass_badge(tmp_path, transport_factory):
    # A judge that passes makes every case pass, so the overall badge is PASS.
    run = _run(tmp_path, transport_factory, judge_pass=True)
    assert run.totals.failed == 0 and run.totals.errors == 0
    doc = build_html(run, _config())
    assert '<span class="badge pass">PASS</span>' in doc


def test_html_surfaces_judge_reason(tmp_path, transport_factory):
    doc = build_html(_run(tmp_path, transport_factory), _config())
    assert "judge: promises a refund" in doc


def test_html_escapes_markup(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory, judge_reason="<script>alert('xss')</script> \"q\"")
    doc = build_html(run, _config())
    assert "<script>alert" not in doc  # raw markup never survives
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in doc
    assert "&quot;q&quot;" in doc
    _parses(doc)


def test_html_is_deterministic(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    config = _config()
    assert build_html(run, config) == build_html(run, config)


def test_write_html_file_round_trip(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    out = tmp_path / "out" / "report.html"
    write_html_report(run, _config(), str(out))
    written = out.read_text(encoding="utf-8")
    assert written.startswith("<!DOCTYPE html>")
    assert "judge: promises a refund" in written


def test_unwritable_path_raises_report_error(tmp_path, transport_factory):
    run = _run(tmp_path, transport_factory)
    with pytest.raises(ReportError) as exc:
        write_html_report(run, _config(), str(tmp_path))  # a directory, not a file
    assert exc.value.exit_code == 2
    assert "Cannot write report" in exc.value.message
