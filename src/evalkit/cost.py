"""Price table lookup and per-case USD cost.

Pricing is USD per 1,000,000 tokens, per model id, taken only from the config table;
there is no price discovery. A model absent from the table (or a response without usage)
yields ``None`` cost, which surfaces as ``n/a`` and marks the run's cost as partial.
"""

from __future__ import annotations

TOKENS_PER_UNIT = 1_000_000


def has_pricing(pricing: dict[str, dict[str, float]], model: str) -> bool:
    """True when the price table has an entry for ``model``."""
    return model in pricing


def case_cost(
    pricing: dict[str, dict[str, float]],
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    """USD cost for one call, or None when pricing or token usage is unavailable."""
    entry = pricing.get(model)
    if entry is None or prompt_tokens is None or completion_tokens is None:
        return None
    return (
        prompt_tokens / TOKENS_PER_UNIT * entry["input"]
        + completion_tokens / TOKENS_PER_UNIT * entry["output"]
    )
