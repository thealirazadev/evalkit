"""Disk cache under .evalkit/cache/: key hash, read, write.

Responses are cached so an unchanged suite re-runs with zero provider calls. The key
is a SHA-256 over the canonical JSON of the request identity, so any change to model,
system/prompt text, params, or sample index produces a different key and a fresh call.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

CACHE_VERSION = 1


def cache_key(
    model: str,
    system: str | None,
    prompt: str,
    params: dict[str, Any],
    sample: int,
) -> str:
    """SHA-256 of the canonical request identity; stable across runs, sensitive to any change."""
    payload = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "params": params,
        "sample": sample,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
