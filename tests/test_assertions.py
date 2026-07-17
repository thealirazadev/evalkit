"""Deterministic assertions: pass/fail and exact failure-message text."""

from evalkit.assertions import evaluate_assertion
from evalkit.suite import Assertion


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
