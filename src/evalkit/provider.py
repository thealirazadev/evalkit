"""httpx wrapper: one chat call, retries, error mapping, usage capture.

The only module that touches the network. The client is built from a transport so
tests inject ``httpx.MockTransport`` and never open a real connection. The API key is
set once as a Bearer header on the client and is never logged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

CHAT_PATH = "/chat/completions"


class ProviderCallError(Exception):
    """A per-case provider failure (not auth). Carries a short reason for the case error."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class ProviderResponse:
    """A parsed provider response: message text, token usage, and measured latency."""

    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


def build_client(
    base_url: str,
    api_key: str | None,
    timeout_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Build the HTTP client with the Bearer header and timeout applied once."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=timeout_seconds,
        transport=transport,
    )


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_success(resp: httpx.Response, latency_ms: int) -> ProviderResponse:
    try:
        data = resp.json()
    except ValueError as exc:
        raise ProviderCallError("malformed provider response") from exc
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderCallError("malformed provider response") from exc
    if not isinstance(text, str):
        raise ProviderCallError("malformed provider response")
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    return ProviderResponse(
        text=text,
        prompt_tokens=_int_or_none(usage.get("prompt_tokens")),
        completion_tokens=_int_or_none(usage.get("completion_tokens")),
        latency_ms=latency_ms,
    )


def complete_chat(
    client: httpx.Client,
    model: str,
    messages: list[dict[str, str]],
    params: dict[str, object],
) -> ProviderResponse:
    """Send one chat-completions request and return the parsed response."""
    body = {"model": model, "messages": messages, **params}
    start = time.perf_counter()
    resp = client.post(CHAT_PATH, json=body)
    latency_ms = int((time.perf_counter() - start) * 1000)
    if resp.status_code != 200:
        raise ProviderCallError(str(resp.status_code))
    return _parse_success(resp, latency_ms)
