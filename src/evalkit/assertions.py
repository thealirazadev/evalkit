"""The deterministic assertion implementations.

Each assertion runs against the provider response text and returns ``(passed, message)``
where ``message`` is ``None`` on success and a specific one-line reason on failure.
Assertions are pure string/JSON logic with no network access; the ``judge`` assertion
lives in ``judge.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import jsonschema

from evalkit.suite import Assertion

AssertionResult = tuple[bool, str | None]
Handler = Callable[[Assertion, str], AssertionResult]

_HANDLERS: dict[str, Handler] = {}


def _register(atype: str) -> Callable[[Handler], Handler]:
    def wrap(func: Handler) -> Handler:
        _HANDLERS[atype] = func
        return func

    return wrap


@_register("contains")
def _contains(assertion: Assertion, response: str) -> AssertionResult:
    value = str(assertion.value)
    if value in response:
        return True, None
    return False, f'contains: "{value}" not found in response'


@_register("not_contains")
def _not_contains(assertion: Assertion, response: str) -> AssertionResult:
    value = str(assertion.value)
    if value not in response:
        return True, None
    return False, f'not_contains: "{value}" found in response'


@_register("equals")
def _equals(assertion: Assertion, response: str) -> AssertionResult:
    value = str(assertion.value)
    if response.strip() == value:
        return True, None
    return False, f'equals: response does not equal "{value}"'


@_register("regex")
def _regex(assertion: Assertion, response: str) -> AssertionResult:
    # Compiled at load time in suite.py, so it is always present and valid here.
    assert assertion.compiled is not None
    if assertion.compiled.search(response):
        return True, None
    return False, f"regex: /{assertion.pattern}/ did not match response"


@_register("json_valid")
def _json_valid(assertion: Assertion, response: str) -> AssertionResult:
    try:
        json.loads(response)
    except (ValueError, TypeError):
        return False, "json_valid: response is not valid JSON"
    return True, None


@_register("json_schema")
def _json_schema(assertion: Assertion, response: str) -> AssertionResult:
    try:
        instance = json.loads(response)
    except (ValueError, TypeError):
        return False, "json_schema: response is not valid JSON"
    validator = jsonschema.Draft202012Validator(assertion.schema)
    error = next(iter(validator.iter_errors(instance)), None)
    if error is None:
        return True, None
    return False, f"json_schema: {error.message}"


@_register("max_length")
def _max_length(assertion: Assertion, response: str) -> AssertionResult:
    limit = int(assertion.value)
    if len(response) <= limit:
        return True, None
    return False, f"max_length: response length {len(response)} exceeds {limit}"


def evaluate_assertion(assertion: Assertion, response: str) -> AssertionResult:
    """Evaluate one deterministic assertion against the response text."""
    handler = _HANDLERS.get(assertion.type)
    if handler is None:
        raise ValueError(f"no deterministic handler for assertion type {assertion.type!r}")
    return handler(assertion, response)
