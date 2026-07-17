"""LLM-as-judge assertion: prompt build, verdict parsing, judge-model resolution.

A judge assertion holds rubric text; a separately configured judge model returns a
JSON verdict ``{"pass": bool, "reason": str}``. The judge model is resolved in
``config.py`` (flag > env > judge.model > provider.model). This module builds the fixed
internal prompt and parses the verdict defensively; the runner makes the actual call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

JUDGE_PARAMS: dict[str, object] = {"temperature": 0, "max_tokens": 512}

JUDGE_PROMPT = (
    "You are grading a model response against a rubric.\n"
    "Decide whether the response satisfies the rubric.\n"
    'Return ONLY a JSON object of the form {{"pass": true|false, "reason": "..."}} '
    "and nothing else.\n\n"
    "Rubric:\n{rubric}\n\n"
    "Response:\n{response}\n"
)

_RETRY_NUDGE = "\nReturn only the JSON object with keys 'pass' (boolean) and 'reason' (string)."


@dataclass
class Verdict:
    """A parsed judge verdict."""

    passed: bool
    reason: str


class JudgeError(Exception):
    """The judge returned an unparseable verdict after a retry; the case is an error."""


def build_judge_messages(
    rubric: str, response: str, *, retry: bool = False
) -> list[dict[str, str]]:
    """Build the judge chat messages presenting the rubric and the response."""
    content = JUDGE_PROMPT.format(rubric=rubric, response=response)
    if retry:
        content += _RETRY_NUDGE
    return [{"role": "user", "content": content}]


def parse_verdict(text: str) -> Verdict | None:
    """Parse a verdict from the judge text, tolerating surrounding prose. None if unparseable."""
    stripped = text.strip()
    candidates = [stripped]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("pass"), bool):
            reason = data.get("reason", "")
            return Verdict(passed=data["pass"], reason="" if reason is None else str(reason))
    return None
