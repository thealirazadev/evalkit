"""Disk cache under .evalkit/cache/: key hash, read, write.

Responses are cached so an unchanged suite re-runs with zero provider calls. The key
is a SHA-256 over the canonical JSON of the request identity, so any change to model,
system/prompt text, params, or sample index produces a different key and a fresh call.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("evalkit")

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


@dataclass
class CacheEntry:
    """A stored provider response with the accounting captured at fetch time."""

    response_text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    created_at: str
    model: str
    version: int = CACHE_VERSION


def _entry_path(cache_root: Path, key: str) -> Path:
    return cache_root / key[:2] / f"{key}.json"


def read_cache(cache_root: Path, key: str) -> CacheEntry | None:
    """Return the stored entry, or None on a miss or a corrupt/version-mismatched file.

    Corruption is self-healing: a bad entry is treated as a miss so the caller refetches,
    and the run never crashes on cache damage.
    """
    path = _entry_path(cache_root, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
            return None
        return CacheEntry(
            response_text=data["response_text"],
            prompt_tokens=data.get("prompt_tokens"),
            completion_tokens=data.get("completion_tokens"),
            latency_ms=data["latency_ms"],
            created_at=data.get("created_at", ""),
            model=data.get("model", ""),
            version=CACHE_VERSION,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.debug("cache read treated as miss (corrupt) key=%s error=%s", key, exc)
        return None


def write_cache(cache_root: Path, key: str, entry: CacheEntry) -> None:
    """Write an entry atomically; a write failure degrades to no caching, never a crash."""
    path = _entry_path(cache_root, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(entry), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.debug("cache write failed key=%s error=%s", key, exc)
