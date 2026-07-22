"""Deterministic assertions: pass/fail and exact failure-message text."""

import re

from evalkit.assertions import evaluate_assertion
from evalkit.suite import Assertion


def _regex(pattern):
    return Assertion(type="regex", pattern=pattern, compiled=re.compile(pattern))


def test_contains_pass():
    assert evaluate_assertion(Assertion(type="contains", value="refund"), "a refund here") == (
        True,
        None,
    )


def test_contains_fail_message():
    passed, message = evaluate_assertion(Assertion(type="contains", value="refund"), "nothing")
    assert passed is False
    assert message == 'contains: "refund" not found in response'


def test_contains_case_sensitive():
    passed, _ = evaluate_assertion(Assertion(type="contains", value="Refund"), "refund")
    assert passed is False


def test_not_contains_pass():
    assert evaluate_assertion(Assertion(type="not_contains", value="error"), "all good") == (
        True,
        None,
    )


def test_not_contains_fail_message():
    passed, message = evaluate_assertion(Assertion(type="not_contains", value="error"), "an error")
    assert passed is False
    assert message == 'not_contains: "error" found in response'


def test_equals_pass_strips_whitespace():
    assert evaluate_assertion(Assertion(type="equals", value="yes"), "  yes\n") == (True, None)


def test_equals_fail_message():
    passed, message = evaluate_assertion(Assertion(type="equals", value="yes"), "no")
    assert passed is False
    assert message == 'equals: response does not equal "yes"'


def test_equals_on_empty_response():
    passed, _ = evaluate_assertion(Assertion(type="equals", value="yes"), "   ")
    assert passed is False


def test_regex_pass():
    assert evaluate_assertion(_regex(r"\d{4}"), "order 1234") == (True, None)


def test_regex_case_insensitive_flag():
    assert evaluate_assertion(_regex(r"(?i)refund"), "REFUND")[0] is True


def test_regex_fail_message():
    passed, message = evaluate_assertion(_regex(r"\d{4}"), "no digits")
    assert passed is False
    assert message == r"regex: /\d{4}/ did not match response"


def test_json_valid_pass():
    assert evaluate_assertion(Assertion(type="json_valid"), '{"a": 1}') == (True, None)


def test_json_valid_fail_message():
    passed, message = evaluate_assertion(Assertion(type="json_valid"), "not json")
    assert passed is False
    assert message == "json_valid: response is not valid JSON"


def test_json_valid_empty_response_fails():
    passed, _ = evaluate_assertion(Assertion(type="json_valid"), "   ")
    assert passed is False


SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "escalate": {"type": "boolean"}},
    "required": ["reply", "escalate"],
}


def test_json_schema_pass():
    resp = '{"reply": "hi", "escalate": false}'
    assert evaluate_assertion(Assertion(type="json_schema", schema=SCHEMA), resp) == (True, None)


def test_json_schema_not_json():
    passed, message = evaluate_assertion(Assertion(type="json_schema", schema=SCHEMA), "nope")
    assert passed is False
    assert message == "json_schema: response is not valid JSON"


def test_json_schema_validation_failure():
    resp = '{"reply": "hi"}'  # missing required "escalate"
    passed, message = evaluate_assertion(Assertion(type="json_schema", schema=SCHEMA), resp)
    assert passed is False
    assert message.startswith("json_schema: ")
    assert "escalate" in message


FENCED_JSON = 'Here you go:\n```json\n{"reply": "hi", "escalate": false}\n```\nThanks!'


def test_json_valid_strict_rejects_fenced_by_default():
    passed, message = evaluate_assertion(Assertion(type="json_valid"), FENCED_JSON)
    assert passed is False
    assert message == "json_valid: response is not valid JSON"


def test_json_valid_extract_fenced_passes():
    passed, _ = evaluate_assertion(Assertion(type="json_valid", extract_fenced=True), FENCED_JSON)
    assert passed is True


def test_json_schema_extract_fenced_validates_inner():
    assertion = Assertion(type="json_schema", schema=SCHEMA, extract_fenced=True)
    assert evaluate_assertion(assertion, FENCED_JSON) == (True, None)


def test_extract_fenced_plain_json_still_passes():
    # No fence present: opting in must not break a response that is already plain JSON.
    passed, _ = evaluate_assertion(Assertion(type="json_valid", extract_fenced=True), '{"a": 1}')
    assert passed is True


def test_extract_fenced_generic_fence_without_language_tag():
    resp = '```\n{"a": 1}\n```'
    passed, _ = evaluate_assertion(Assertion(type="json_valid", extract_fenced=True), resp)
    assert passed is True


def test_max_length_boundary_passes():
    # len == limit passes.
    assert evaluate_assertion(Assertion(type="max_length", value=5), "12345") == (True, None)


def test_max_length_fail_message():
    passed, message = evaluate_assertion(Assertion(type="max_length", value=3), "12345")
    assert passed is False
    assert message == "max_length: response length 5 exceeds 3"


def test_max_length_unicode_counts_characters():
    assert evaluate_assertion(Assertion(type="max_length", value=3), "áéí") == (True, None)


def test_unknown_type_raises():
    import pytest

    with pytest.raises(ValueError):
        evaluate_assertion(Assertion(type="judge", rubric="x"), "resp")
