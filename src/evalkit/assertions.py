"""The deterministic assertion implementations.

Each assertion runs against the provider response text and returns ``(passed, message)``
where ``message`` is ``None`` on success and a specific one-line reason on failure.
Assertions are pure string/JSON logic with no network access; the ``judge`` assertion
lives in ``judge.py``.
"""

from __future__ import annotations

from collections.abc import Callable

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


def evaluate_assertion(assertion: Assertion, response: str) -> AssertionResult:
    """Evaluate one deterministic assertion against the response text."""
    handler = _HANDLERS.get(assertion.type)
    if handler is None:
        raise ValueError(f"no deterministic handler for assertion type {assertion.type!r}")
    return handler(assertion, response)
