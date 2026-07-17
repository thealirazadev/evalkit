"""End-to-end CLI tests through CliRunner with the provider mocked."""

import pytest
from click.testing import CliRunner
from conftest import chat_response

from evalkit.cli import cli
from evalkit.provider import build_client as real_build_client

CONFIG_YAML = """
provider:
  base_url: https://api.example.com/v1
  model: example-model-1
pricing:
  example-model-1: {input: 3.0, output: 15.0}
"""

PASSING_SUITE = """
suite: demo
model: example-model-1
prompt: "Reply about {{topic}}"
cases:
  - name: ok
    vars: {topic: refunds}
    assert:
      - type: contains
        value: reply
"""

FAILING_SUITE = PASSING_SUITE.replace("value: reply", "value: NOTPRESENT")


@pytest.fixture
def project(monkeypatch, tmp_path, transport_factory):
    monkeypatch.chdir(tmp_path)
    for var in (
        "EVALKIT_API_KEY",
        "EVALKIT_BASE_URL",
        "EVALKIT_MODEL",
        "EVALKIT_JUDGE_MODEL",
        "NO_COLOR",
    ):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "evalkit.yaml").write_text(CONFIG_YAML, encoding="utf-8")
    (tmp_path / "evals").mkdir()

    state: dict = {}

    def write_suite(text, name="demo.yaml"):
        (tmp_path / "evals" / name).write_text(text, encoding="utf-8")

    def invoke(args, handler=None, env=None):
        handler = handler or (lambda req, n: chat_response('{"reply": "ok"}'))
        rec = transport_factory(handler)
        state["rec"] = rec
        monkeypatch.setattr(
            "evalkit.cli.build_client",
            lambda base_url, api_key, timeout: real_build_client(
                base_url, api_key, timeout, rec.transport
            ),
        )
        merged = {"EVALKIT_API_KEY": "secret-key"}
        if env is not None:
            merged = env
        return CliRunner().invoke(cli, args, env=merged)

    invoke.write_suite = write_suite
    invoke.state = state
    invoke.tmp_path = tmp_path
    return invoke


def test_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_run_help_lists_flags():
    result = CliRunner().invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    for flag in ("--config", "--model", "--no-cache", "--no-color"):
        assert flag in result.output


def test_passing_run_exits_0(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run"])
    assert result.exit_code == 0
    assert "pass  ok" in result.output
    assert "summary" in result.output


def test_failing_run_exits_1(project):
    project.write_suite(FAILING_SUITE)
    result = project(["run"])
    assert result.exit_code == 1
    assert "FAIL  ok" in result.output
    assert 'contains: "NOTPRESENT" not found in response' in result.output


def test_provider_error_exits_2(project):
    import httpx

    project.write_suite(PASSING_SUITE)
    result = project(["run"], handler=lambda req, n: httpx.Response(503))
    assert result.exit_code == 2
    assert "ERROR ok" in result.output
    assert "provider: 503" in result.output


def test_missing_key_exits_2_and_never_prints_key(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run"], env={})  # no EVALKIT_API_KEY
    assert result.exit_code == 2
    assert "API key missing or invalid. Set EVALKIT_API_KEY." in result.output
    assert "secret-key" not in result.output


def test_unknown_assertion_exits_2(project):
    project.write_suite(FAILING_SUITE.replace("type: contains", "type: contain"))
    result = project(["run"])
    assert result.exit_code == 2
    assert 'unknown assertion type "contain"' in result.output


def test_undefined_variable_exits_2_without_calls(project):
    project.write_suite(PASSING_SUITE.replace("{{topic}}", "{{missing}}"))
    result = project(["run"])
    assert result.exit_code == 2
    assert "undefined variable {{missing}}" in result.output
    assert project.state["rec"].call_count == 0


def test_no_suites_found_exits_2(project):
    # evals/ exists but is empty.
    result = project(["run"])
    assert result.exit_code == 2
    assert "No suite files found" in result.output


def test_second_run_is_cached(project):
    project.write_suite(PASSING_SUITE)
    first = project(["run"])
    assert first.exit_code == 0
    calls = project.state["rec"].call_count
    second = project(["run"])
    assert second.exit_code == 0
    assert project.state["rec"].call_count == 0  # fresh transport, zero calls this run
    assert "cached" in second.output
    assert calls == 1


def test_json_report_written(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run", "--json", "out.json"])
    assert result.exit_code == 0
    import json as _json

    report = _json.loads((project.tmp_path / "out.json").read_text(encoding="utf-8"))
    assert report["totals"]["cases"] == 1
    assert report["totals"]["passed"] == 1


def test_json_report_unwritable_exits_2(project):
    project.write_suite(PASSING_SUITE)
    (project.tmp_path / "adir").mkdir()
    result = project(["run", "--json", "adir"])  # a directory, not writable as a file
    assert result.exit_code == 2
    assert "Cannot write report" in result.output


def test_junit_report_written(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run", "--junit", "out.xml"])
    assert result.exit_code == 0
    import xml.etree.ElementTree as ET

    tree = ET.parse(project.tmp_path / "out.xml")
    assert tree.getroot().tag == "testsuites"
    assert tree.getroot().attrib["tests"] == "1"


def test_fail_on_cost_over_budget_exits_1(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run", "--fail-on-cost", "0.000001"])
    assert result.exit_code == 1
    assert "Cost budget exceeded" in result.output
    assert "0.000001" in result.output


def test_fail_on_cost_under_budget_exits_0(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run", "--fail-on-cost", "100"])
    assert result.exit_code == 0
    assert "Cost budget exceeded" not in result.output


def test_fail_on_cost_unenforceable_exits_2(project):
    # A config without pricing makes cost unknown; the budget cannot be enforced.
    (project.tmp_path / "evalkit.yaml").write_text(
        "provider:\n  base_url: https://api.example.com/v1\n  model: example-model-1\n",
        encoding="utf-8",
    )
    project.write_suite(PASSING_SUITE)
    result = project(["run", "--fail-on-cost", "0.01"])
    assert result.exit_code == 2
    assert "Cannot enforce --fail-on-cost" in result.output


def test_no_color_output_has_no_escape_codes(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run"], env={"EVALKIT_API_KEY": "secret-key", "NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "\x1b" not in result.output
