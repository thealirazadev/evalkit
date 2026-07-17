"""httpx wrapper: one chat call, retries, error mapping, usage capture.

The only module that touches the network. The client is built from a transport so
tests inject ``httpx.MockTransport`` and never open a real connection. The API key is
set once as a Bearer header on the client and is never logged.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from evalkit.errors import ProviderError

logger = logging.getLogger("evalkit")

CHAT_PATH = "/chat/completions"
DEFAULT_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.5
AUTH_STATUS = frozenset({401, 403})
AUTH_MESSAGE = "API key missing or invalid. Set EVALKIT_API_KEY."


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


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _backoff(attempt: int, retry_after: float | None) -> float:
    """Delay before the next attempt: honor Retry-After, else exponential backoff."""
    if retry_after is not None:
        return retry_after
    return RETRY_BASE_DELAY * (2 ** (attempt - 1))


def complete_chat(
    client: httpx.Client,
    model: str,
    messages: list[dict[str, str]],
    params: dict[str, object],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> ProviderResponse:
    """Send one chat-completions request, retrying transient failures.

    401/403 raise ``ProviderError`` and abort the whole run. 429, 5xx, timeouts, and
    connection errors retry up to ``max_attempts`` with exponential backoff (honoring
    ``Retry-After``); if still failing, a ``ProviderCallError`` marks just this case.
    """
    body = {"model": model, "messages": messages, **params}
    reason = "unknown provider error"
    for attempt in range(1, max_attempts + 1):
        retry_after: float | None = None
        start = time.perf_counter()
        try:
            resp = client.post(CHAT_PATH, json=body)
        except httpx.TimeoutException:
            reason = "request timed out"
        except httpx.RequestError as exc:
            reason = f"connection error ({type(exc).__name__})"
        else:
            status = resp.status_code
            # Only the status and attempt are logged, never the Authorization header.
            logger.debug("event=request status_code=%d attempt=%d", status, attempt)
            if status in AUTH_STATUS:
                raise ProviderError(AUTH_MESSAGE)
            if status == 200:
                latency_ms = int((time.perf_counter() - start) * 1000)
                return _parse_success(resp, latency_ms)
            if status == 429 or status >= 500:
                reason = str(status)
                retry_after = _retry_after(resp)
            else:
                # Non-retryable client error (e.g. 400): fail this case immediately.
                raise ProviderCallError(str(status))

        if attempt < max_attempts:
            sleep(_backoff(attempt, retry_after))

    raise ProviderCallError(f"{reason} after {max_attempts} attempts")
