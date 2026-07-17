"""Provider HTTP layer: request shape, usage capture, retries, and error mapping."""

import json

import httpx
import pytest
from conftest import chat_response

from evalkit.errors import ProviderError
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
    client, _ = _client(transport_factory, lambda req, n: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(ProviderCallError) as exc:
        complete_chat(client, "m", [{"role": "user", "content": "hi"}], {})
    assert "malformed" in exc.value.reason


def test_auth_failure_aborts(transport_factory):
    client, rec = _client(transport_factory, lambda req, n: httpx.Response(401))
    with pytest.raises(ProviderError) as exc:
        complete_chat(client, "m", [{"role": "user", "content": "hi"}], {})
    assert exc.value.message == "API key missing or invalid. Set EVALKIT_API_KEY."
    assert exc.value.exit_code == 2
    assert rec.call_count == 1  # no retries on auth failure


def test_retry_then_success(transport_factory):
    def handler(req, n):
        return httpx.Response(503) if n < 3 else chat_response("recovered")

    client, rec = _client(transport_factory, handler)
    resp = complete_chat(client, "m", [{"role": "user", "content": "hi"}], {}, sleep=lambda s: None)
    assert resp.text == "recovered"
    assert rec.call_count == 3


def test_retry_exhausted_is_call_error(transport_factory):
    client, rec = _client(transport_factory, lambda req, n: httpx.Response(503))
    with pytest.raises(ProviderCallError) as exc:
        complete_chat(client, "m", [{"role": "user", "content": "hi"}], {}, sleep=lambda s: None)
    assert "503 after 3 attempts" in exc.value.reason
    assert rec.call_count == 3


def test_timeout_retries(transport_factory):
    def handler(req, n):
        raise httpx.ConnectTimeout("slow")

    client, rec = _client(transport_factory, handler)
    with pytest.raises(ProviderCallError) as exc:
        complete_chat(client, "m", [{"role": "user", "content": "hi"}], {}, sleep=lambda s: None)
    assert "timed out" in exc.value.reason
    assert rec.call_count == 3


def test_retry_after_header_honored(transport_factory):
    delays = []

    def handler(req, n):
        return httpx.Response(429, headers={"Retry-After": "7"}) if n < 2 else chat_response("ok")

    client, rec = _client(transport_factory, handler)
    complete_chat(client, "m", [{"role": "user", "content": "hi"}], {}, sleep=delays.append)
    assert delays == [7.0]


def test_non_retryable_client_error(transport_factory):
    client, rec = _client(transport_factory, lambda req, n: httpx.Response(400))
    with pytest.raises(ProviderCallError) as exc:
        complete_chat(client, "m", [{"role": "user", "content": "hi"}], {}, sleep=lambda s: None)
    assert exc.value.reason == "400"
    assert rec.call_count == 1  # 400 is not retried
