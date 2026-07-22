"""Suite loading, validation, and discovery per the mini-spec."""

from pathlib import Path

import pytest

from evalkit.errors import SuiteError
from evalkit.suite import discover_suites, load_suite, referenced_variables, render_template

FIXTURES = Path(__file__).parent / "fixtures"

VALID = """
suite: demo
prompt: |
  Hello {{name}}
cases:
  - name: greet
    vars:
      name: World
    assert:
      - type: contains
        value: Hi
"""


def _write(tmp_path, text, filename="s.yaml"):
    path = tmp_path / filename
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_fixture_loads():
    suite = load_suite(FIXTURES / "checkout.yaml", cwd=FIXTURES)
    assert suite.name == "checkout-support"
    assert suite.model == "example-model-1"
    assert len(suite.cases) == 2
    assert suite.cases[0].name == "refund-request"
    assert suite.cases[0].assertions[0].type == "json_valid"
    assert suite.cases[0].assertions[1].type == "contains"
    assert suite.params["max_tokens"] == 512


def test_minimal_suite_loads(tmp_path):
    suite = load_suite(_write(tmp_path, VALID), cwd=tmp_path)
    assert suite.name == "demo"
    assert suite.cases[0].samples == 1
    assert suite.cases[0].threshold == 1.0


def test_bad_yaml(tmp_path):
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, "suite: x\nprompt: [unclosed\n"), cwd=tmp_path)
    assert exc.value.message.startswith("Invalid suite")
    assert exc.value.exit_code == 2


def test_unknown_assertion_type(tmp_path):
    text = VALID.replace("type: contains", "type: contain")
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, text), cwd=tmp_path)
    assert 'unknown assertion type "contain"' in exc.value.message
    assert 'case "greet"' in exc.value.message


def test_missing_case_name(tmp_path):
    text = VALID.replace("  - name: greet\n", "  - vars: {}\n")
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, text), cwd=tmp_path)
    assert "missing 'name'" in exc.value.message


def test_duplicate_case_names(tmp_path):
    text = """
suite: demo
prompt: hi
cases:
  - name: a
    assert: [{type: json_valid}]
  - name: a
    assert: [{type: json_valid}]
"""
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, text), cwd=tmp_path)
    assert 'duplicate case name "a"' in exc.value.message


def test_non_scalar_var(tmp_path):
    text = """
suite: demo
prompt: "{{name}}"
cases:
  - name: a
    vars:
      name: [1, 2, 3]
    assert: [{type: json_valid}]
"""
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, text), cwd=tmp_path)
    assert "must be a string, number, or bool" in exc.value.message


def test_bad_regex(tmp_path):
    text = """
suite: demo
prompt: hi
cases:
  - name: a
    assert:
      - type: regex
        pattern: "("
"""
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, text), cwd=tmp_path)
    assert "invalid regex" in exc.value.message


def test_missing_prompt(tmp_path):
    text = "suite: demo\ncases:\n  - name: a\n    assert: [{type: json_valid}]\n"
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, text), cwd=tmp_path)
    assert "'prompt'" in exc.value.message


def test_empty_cases(tmp_path):
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, "suite: demo\nprompt: hi\ncases: []\n"), cwd=tmp_path)
    assert "'cases' must be a non-empty list" in exc.value.message


def test_empty_assert_list(tmp_path):
    text = "suite: demo\nprompt: hi\ncases:\n  - name: a\n    assert: []\n"
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, text), cwd=tmp_path)
    assert "'assert' must be a non-empty list" in exc.value.message


def test_discovery_from_directory(tmp_path):
    (tmp_path / "evals").mkdir()
    _write(tmp_path / "evals", VALID, "one.yaml")
    _write(tmp_path / "evals", VALID, "two.yml")
    found = discover_suites([], "evals/**/*.yaml", cwd=tmp_path)
    assert len(found) == 1  # glob only matches .yaml
    found_dir = discover_suites(["evals"], "unused", cwd=tmp_path)
    assert len(found_dir) == 2  # directory arg picks up .yaml and .yml


def test_discovery_empty_is_error(tmp_path):
    with pytest.raises(SuiteError) as exc:
        discover_suites([], "evals/**/*.yaml", cwd=tmp_path)
    assert "No suite files found" in exc.value.message


def test_discovery_missing_path(tmp_path):
    with pytest.raises(SuiteError) as exc:
        discover_suites(["nope.yaml"], "x", cwd=tmp_path)
    assert "Suite path not found" in exc.value.message


def test_render_basic_and_spaced():
    out = render_template(
        "Hi {{name}} and {{ other }}", {"name": "A", "other": "B"}, file="f", case_name="c"
    )
    assert out == "Hi A and B"


def test_render_numbers_and_bools():
    out = render_template("{{n}}/{{flag}}", {"n": 3, "flag": True}, file="f", case_name="c")
    assert out == "3/True"


def test_render_leaves_non_variables_verbatim():
    template = "{{a.b}} {single} {{123}} {{ok}}"
    out = render_template(template, {"ok": "X"}, file="f", case_name="c")
    assert out == "{{a.b}} {single} {{123}} X"


def test_render_undefined_variable_raises():
    with pytest.raises(SuiteError) as exc:
        render_template("Hi {{missing}}", {}, file="evals/x.yaml", case_name="c")
    assert exc.value.message == "Suite evals/x.yaml, case c: undefined variable {{missing}}"


def test_load_suite_catches_undefined_variable(tmp_path):
    text = """
suite: demo
prompt: "Hello {{typo}}"
cases:
  - name: a
    vars:
      name: World
    assert: [{type: json_valid}]
"""
    path = tmp_path / "s.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SuiteError) as exc:
        load_suite(path, cwd=tmp_path)
    assert "undefined variable {{typo}}" in exc.value.message


def test_referenced_variables():
    assert referenced_variables("{{a}} and {{ b }} and {{a}}") == {"a", "b"}


def _suite_with(field_line, tmp_path):
    text = f"""
suite: demo
prompt: hi
cases:
  - name: c
    {field_line}
    assert: [{{type: json_valid}}]
"""
    path = tmp_path / "s.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_samples_must_be_positive_int(tmp_path):
    with pytest.raises(SuiteError) as exc:
        load_suite(_suite_with("samples: 0", tmp_path), cwd=tmp_path)
    assert "'samples' must be an integer >= 1" in exc.value.message


def test_threshold_must_be_in_range(tmp_path):
    with pytest.raises(SuiteError) as exc:
        load_suite(_suite_with("threshold: 1.5", tmp_path), cwd=tmp_path)
    assert "'threshold' must be in (0, 1]" in exc.value.message
    with pytest.raises(SuiteError):
        load_suite(_suite_with("threshold: 0", tmp_path), cwd=tmp_path)


def test_valid_samples_and_threshold_load(tmp_path):
    suite = load_suite(_suite_with("samples: 3\n    threshold: 0.67", tmp_path), cwd=tmp_path)
    assert suite.cases[0].samples == 3
    assert suite.cases[0].threshold == 0.67


def test_suite_level_defaults_inherited_and_overridable(tmp_path):
    text = """
suite: demo
prompt: hi
samples: 3
threshold: 0.67
cases:
  - name: inherits
    assert: [{type: json_valid}]
  - name: overrides
    samples: 1
    assert: [{type: json_valid}]
"""
    suite = load_suite(_write(tmp_path, text), cwd=tmp_path)
    # The first case inherits both suite-level defaults.
    assert suite.cases[0].samples == 3
    assert suite.cases[0].threshold == 0.67
    # The second overrides samples but still inherits the suite threshold.
    assert suite.cases[1].samples == 1
    assert suite.cases[1].threshold == 0.67


_CASE_TAIL = "cases:\n  - name: a\n    assert: [{type: json_valid}]\n"


def test_suite_level_samples_validated(tmp_path):
    text = f"suite: demo\nprompt: hi\nsamples: 0\n{_CASE_TAIL}"
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, text), cwd=tmp_path)
    # No case prefix: the message points at the suite-level default.
    assert exc.value.message == "Invalid suite s.yaml: 'samples' must be an integer >= 1"


def test_suite_level_threshold_validated(tmp_path):
    text = f"suite: demo\nprompt: hi\nthreshold: 2\n{_CASE_TAIL}"
    with pytest.raises(SuiteError) as exc:
        load_suite(_write(tmp_path, text), cwd=tmp_path)
    assert exc.value.message == "Invalid suite s.yaml: 'threshold' must be in (0, 1]"
