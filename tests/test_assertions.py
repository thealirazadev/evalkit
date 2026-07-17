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
