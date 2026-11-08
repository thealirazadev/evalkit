import json
from pathlib import Path

import httpx
import pytest

from evalkit.assertions import evaluate_assertion
from evalkit.cache import CacheEntry, read_cache, write_cache
from evalkit.errors import SuiteError
from evalkit.provider import ProviderCallError, _parse_success
from evalkit.suite import Assertion, _parse_assertion

CALLS = [
    {"name": "search_catalog", "arguments": {"query": "warm hat", "limit": 5}},
    {"name": "get_product", "arguments": {"product_id": "p1", "options": {"size": "M"}}},
]


def tool_reply(content: str | None, calls: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": content,
                        "tool_calls": [{"type": "function", "function": call} for call in calls],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def test_tool_calls_are_parsed_and_a_tool_only_reply_has_empty_text() -> None:
    resp = _parse_success(
        tool_reply(None, [{"name": "search_catalog", "arguments": '{"query": "hat"}'}]), 12
    )

    assert resp.text == ""
    assert resp.tool_calls == ({"name": "search_catalog", "arguments": {"query": "hat"}},)


def test_unparseable_arguments_are_kept_rather_than_crashing() -> None:
    resp = _parse_success(tool_reply("", [{"name": "x", "arguments": "{not json"}]), 1)

    assert resp.tool_calls[0]["arguments"] == {"_unparsed": "{not json"}


def test_a_tool_call_without_a_name_is_a_provider_error() -> None:
    with pytest.raises(ProviderCallError):
        _parse_success(tool_reply("", [{"arguments": "{}"}]), 1)


@pytest.mark.parametrize(
    ("assertion", "passed"),
    [
        (Assertion(type="tool_called", value="get_product"), True),
        (Assertion(type="tool_called", value="refund_order"), False),
        (Assertion(type="tool_not_called", value="refund_order"), True),
        (Assertion(type="tool_not_called", value="search_catalog"), False),
        (Assertion(type="tool_args", value="search_catalog", args={"query": "warm hat"}), True),
        (Assertion(type="tool_args", value="get_product", args={"options": {"size": "M"}}), True),
        (Assertion(type="tool_args", value="get_product", args={"options": {"size": "L"}}), False),
        (Assertion(type="tool_args", value="refund_order", args={"amount": 1}), False),
    ],
)
def test_tool_assertions(assertion: Assertion, passed: bool) -> None:
    ok, message = evaluate_assertion(assertion, "", CALLS)

    assert ok is passed
    assert (message is None) is passed


def test_failure_messages_name_what_was_called() -> None:
    _, message = evaluate_assertion(Assertion(type="tool_called", value="refund_order"), "", CALLS)

    assert message == "expected a call to refund_order, called: search_catalog, get_product"


def test_suite_validation_of_tool_assertions() -> None:
    parsed = _parse_assertion(
        {"type": "tool_args", "value": "search_catalog", "args": {"query": "hat"}}, "s.yaml", "c"
    )
    assert parsed.args == {"query": "hat"}

    with pytest.raises(SuiteError, match="tool name"):
        _parse_assertion({"type": "tool_called"}, "s.yaml", "c")
    with pytest.raises(SuiteError, match="'args' map"):
        _parse_assertion({"type": "tool_args", "value": "x"}, "s.yaml", "c")


def test_tool_calls_survive_the_cache(tmp_path: Path) -> None:
    entry = CacheEntry("", 1, 2, 3, "2026-11-08T00:00:00Z", "m", tool_calls=CALLS)
    write_cache(tmp_path, "ab" + "0" * 62, entry)

    restored = read_cache(tmp_path, "ab" + "0" * 62)

    assert restored is not None
    assert restored.tool_calls == CALLS
    assert json.loads(json.dumps(restored.tool_calls)) == CALLS
