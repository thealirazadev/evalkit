"""Provider HTTP layer: request shape, usage capture, retries, and error mapping."""

import json

from conftest import chat_response

from evalkit.provider import ProviderCallError, build_client, complete_chat


def _client(transport_factory, handler):
    rec = transport_factory(handler)
    client = build_client("https://api.example.com/v1", "secret-key", 5.0, rec.transport)
    return client, rec


def test_request_shape_and_bearer_header(transport_factory):
    client, rec = _client(transport_factory, lambda req, n: chat_response("hello"))
    messages = [{"role": "user", "content": "hi"}]
    resp = complete_chat(client, "example-model-1", messages, {"temperature": 0, "max_tokens": 512})
    assert resp.text == "hello"

    sent = rec.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == "https://api.example.com/v1/chat/completions"
    assert sent.headers["Authorization"] == "Bearer secret-key"
    body = json.loads(sent.content)
    assert body["model"] == "example-model-1"
    assert body["messages"] == messages
    assert body["temperature"] == 0
    assert body["max_tokens"] == 512


def test_usage_captured(transport_factory):
    client, _ = _client(
        transport_factory,
        lambda req, n: chat_response("x", prompt_tokens=123, completion_tokens=45),
    )
    resp = complete_chat(client, "m", [{"role": "user", "content": "hi"}], {})
    assert resp.prompt_tokens == 123
    assert resp.completion_tokens == 45
    assert resp.latency_ms >= 0


def test_missing_usage_tolerated(transport_factory):
    client, _ = _client(transport_factory, lambda req, n: chat_response("x", include_usage=False))
    resp = complete_chat(client, "m", [{"role": "user", "content": "hi"}], {})
    assert resp.prompt_tokens is None
    assert resp.completion_tokens is None
    assert resp.text == "x"


def test_empty_content_is_valid(transport_factory):
    client, _ = _client(transport_factory, lambda req, n: chat_response(""))
    resp = complete_chat(client, "m", [{"role": "user", "content": "hi"}], {})
    assert resp.text == ""


def test_malformed_body_is_call_error(transport_factory):
    import httpx

    client, _ = _client(transport_factory, lambda req, n: httpx.Response(200, json={"nope": 1}))
    try:
        complete_chat(client, "m", [{"role": "user", "content": "hi"}], {})
        raise AssertionError("expected ProviderCallError")
    except ProviderCallError as exc:
        assert "malformed" in exc.reason
