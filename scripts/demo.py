"""Run the evalkit CLI against a mocked provider transport, for the README examples.

No network and no API key: an ``httpx.MockTransport`` stands in for the LLM provider API
and returns fixed, content-keyed responses, so a command such as

    python scripts/demo.py run examples/demo.yaml

reproduces exactly the terminal output shown in the README. Everything after the script
name is passed straight through to the evalkit CLI, so ``--json``, ``--junit``, ``-k``,
and the rest behave normally. The only thing replaced is the HTTP transport.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from evalkit import cli as cli_module  # noqa: E402
from evalkit.provider import build_client as real_build_client  # noqa: E402

# Fixed case responses, chosen so one case passes and two fail in distinct ways.
CASE_RESPONSES = {
    "1234": (
        '{"reply": "Thanks for reaching out about order 1234. I have logged your '
        'refund request and our team will review it shortly.", "escalate": false}'
    ),
    "8899": (
        '{"reply": "Order 8899 shipped on Monday and is out for delivery.", '
        '"status": "in_transit"}'
    ),
    "broken": (
        '{"reply": "Absolutely, I am issuing your full refund right now and the '
        'money will be back on your card today.", "escalate": false}'
    ),
}

JUDGE_PASS = '{"pass": true, "reason": "The reply is polite and makes no specific refund promise."}'
JUDGE_FAIL = (
    '{"pass": false, "reason": "The reply promises a specific refund outcome '
    '(a full refund today)."}'
)


def _chat(content: str, prompt_tokens: int, completion_tokens: int) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


def _handler(request: httpx.Request) -> httpx.Response:
    body = request.read().decode("utf-8")
    if "grading a model response" in body:
        # Judge call: decide from the response text embedded in the judge prompt.
        if "issuing your full refund right now" in body:
            return _chat(JUDGE_FAIL, 182, 24)
        return _chat(JUDGE_PASS, 176, 18)
    for key, content in CASE_RESPONSES.items():
        if key in body:
            return _chat(content, 62, 41)
    return _chat('{"reply": "ok", "escalate": false}', 50, 10)


def _mock_build_client(base_url: str, api_key: str | None, timeout: float) -> httpx.Client:
    return real_build_client(base_url, api_key, timeout, httpx.MockTransport(_handler))


def main() -> None:
    os.environ.setdefault("EVALKIT_API_KEY", "mock-key-not-a-real-secret")
    os.environ["NO_COLOR"] = "1"
    cli_module.build_client = _mock_build_client
    cli_module.cli()


if __name__ == "__main__":
    main()
