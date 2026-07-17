"""Shared pytest fixtures: mocked provider transport, no network anywhere."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest


def chat_response(
    content: str = "ok",
    *,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    include_usage: bool = True,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a provider-shaped chat-completions HTTP response."""
    body: dict = {"choices": [{"message": {"content": content}}]}
    if include_usage:
        body["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    return httpx.Response(status, json=body, headers=headers)


class RecordingTransport:
    """Wraps httpx.MockTransport, recording each request and driving a handler.

    The handler is called as ``handler(request, call_number)`` (1-based) and must
    return an ``httpx.Response``; this makes retry sequences and call-count
    assertions straightforward without touching the network.
    """

    def __init__(self, handler: Callable[[httpx.Request, int], httpx.Response]) -> None:
        self._handler = handler
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._respond)

    def _respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        # httpx does not expose the request body on the recorded object unless read.
        request.read()
        return self._handler(request, len(self.requests))

    @property
    def call_count(self) -> int:
        return len(self.requests)


@pytest.fixture
def transport_factory():
    """Return a factory building a RecordingTransport from a response handler."""

    def make(handler: Callable[[httpx.Request, int], httpx.Response]) -> RecordingTransport:
        return RecordingTransport(handler)

    return make
