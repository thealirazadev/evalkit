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
    for flag in ("--config", "--model", "--judge-model", "--no-cache", "--no-color", "--json"):
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


def test_off_tty_liveness_and_plain_output(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run"])  # CliRunner stdout is not a TTY
    assert result.exit_code == 0
    assert "running 1 cases..." in result.output
    assert "\x1b" not in result.output  # no escape codes when piped


def test_quiet_shows_only_failures_and_summary(project):
    project.write_suite(TWO_CASE_SUITE)  # both cases pass
    result = project(["run", "--quiet"])
    assert result.exit_code == 0
    assert "refund-flow" not in result.output  # passing case line suppressed
    assert "running 2 cases..." not in result.output  # no liveness under quiet
    assert "summary" in result.output  # summary always prints


def test_verbose_emits_structured_logs_without_key(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run", "--verbose"])
    assert result.exit_code == 0
    assert "event=sample" in result.output
    assert "cache=miss" in result.output
    assert "secret-key" not in result.output  # the key is never logged


def test_quiet_and_verbose_resolve_to_verbose(project):
    project.write_suite(PASSING_SUITE)
    result = project(["run", "--quiet", "--verbose"])
    assert result.exit_code == 0
    assert "event=sample" in result.output  # verbose wins
    assert "pass  ok" in result.output  # not quiet


def test_baseline_store_then_diff_shows_regression(project):
    project.write_suite(PASSING_SUITE)
    stored = project(["baseline"])
    assert stored.exit_code == 0
    assert "Baseline stored" in stored.output
    assert (project.tmp_path / ".evalkit" / "baseline.json").exists()

    # Same prompt (cached response), stricter assertion -> the case regresses.
    project.write_suite(FAILING_SUITE)
    result = project(["run"])
    assert result.exit_code == 1
    assert "regressions: demo/ok" in result.output


def test_baseline_refuses_failing_run(project):
    project.write_suite(FAILING_SUITE)
    result = project(["baseline"])
    assert result.exit_code == 1
    assert "Baseline not stored: 1 case(s) failing." in result.output
    assert not (project.tmp_path / ".evalkit" / "baseline.json").exists()


def test_baseline_allow_failures_stores_and_reports_fixed(project):
    import json as _json

    # Store a baseline from a failing run; the failing case is recorded as "fail".
    project.write_suite(FAILING_SUITE)
    stored = project(["baseline", "--allow-failures"])
    assert stored.exit_code == 0
    assert "Baseline stored" in stored.output
    assert "1 failing" in stored.output
    bpath = project.tmp_path / ".evalkit" / "baseline.json"
    assert bpath.exists()
    snap = _json.loads(bpath.read_text(encoding="utf-8"))
    assert snap["cases"]["demo/ok"]["status"] == "fail"

    # Same prompt (cached response), a passing assertion -> the case flips to "fixed".
    project.write_suite(PASSING_SUITE)
    result = project(["run", "--json", "out.json"])
    assert result.exit_code == 0
    assert "fixed: demo/ok" in result.output
    report = _json.loads((project.tmp_path / "out.json").read_text(encoding="utf-8"))
    assert report["baseline"]["fixed"] == ["demo/ok"]


def test_baseline_allow_failures_still_refuses_errors(project):
    import httpx

    project.write_suite(PASSING_SUITE)
    result = project(["baseline", "--allow-failures"], handler=lambda req, n: httpx.Response(503))
    assert result.exit_code == 2
    assert "Baseline not stored" in result.output
    assert not (project.tmp_path / ".evalkit" / "baseline.json").exists()


def test_run_with_corrupt_baseline_exits_2(project):
    project.write_suite(PASSING_SUITE)
    bpath = project.tmp_path / ".evalkit" / "baseline.json"
    bpath.parent.mkdir(parents=True, exist_ok=True)
    bpath.write_text("{ corrupt", encoding="utf-8")
    result = project(["run"])
    assert result.exit_code == 2
    assert "run 'evalkit baseline' to recreate" in result.output


def test_baseline_rejects_report_flags(project):
    project.write_suite(PASSING_SUITE)
    result = project(["baseline", "--json", "x.json"])
    assert result.exit_code == 2  # --json is not a baseline option


TWO_CASE_SUITE = """
suite: demo
model: example-model-1
prompt: "Reply about {{topic}}"
cases:
  - name: refund-flow
    vars: {topic: refunds}
    assert: [{type: contains, value: reply}]
  - name: checkout-flow
    vars: {topic: checkout}
    assert: [{type: contains, value: reply}]
"""


def test_k_filter_runs_matching_cases(project):
    project.write_suite(TWO_CASE_SUITE)
    result = project(["run", "-k", "refund"])
    assert result.exit_code == 0
    assert "refund-flow" in result.output
    assert "checkout-flow" not in result.output
    assert "cases: 1" in result.output  # summary reflects the filtered set


def test_k_filter_no_match_exits_2(project):
    project.write_suite(TWO_CASE_SUITE)
    result = project(["run", "-k", "nomatch"])
    assert result.exit_code == 2
    assert "No cases match '-k nomatch'." in result.output


def test_baseline_rejects_k_filter(project):
    project.write_suite(TWO_CASE_SUITE)
    result = project(["baseline", "-k", "refund"])
    assert result.exit_code == 2  # -k is not a baseline option


def test_cache_clear_removes_entries_and_forces_fresh_calls(project):
    project.write_suite(PASSING_SUITE)
    first = project(["run"])
    assert first.exit_code == 0
    assert project.state["rec"].call_count == 1  # one fresh call filled the cache

    cleared = project(["cache", "clear"])
    assert cleared.exit_code == 0
    assert "Removed 1 cache entry." in cleared.output

    # The cache is gone, so the next run calls the provider again.
    again = project(["run"])
    assert again.exit_code == 0
    assert project.state["rec"].call_count == 1


def test_cache_clear_empty_is_zero(project):
    result = project(["cache", "clear"])
    assert result.exit_code == 0
    assert "Removed 0 cache entries." in result.output


def test_cache_clear_bad_duration_exits_2(project):
    result = project(["cache", "clear", "--older-than", "bogus"])
    assert result.exit_code == 2
    assert "Invalid --older-than 'bogus'" in result.output


def test_json_report_includes_baseline(project):
    project.write_suite(PASSING_SUITE)
    project(["baseline"])
    project.write_suite(FAILING_SUITE)
    result = project(["run", "--json", "out.json"])
    assert result.exit_code == 1
    import json as _json

    report = _json.loads((project.tmp_path / "out.json").read_text(encoding="utf-8"))
    assert report["baseline"] is not None
    assert report["baseline"]["regressions"] == ["demo/ok"]
