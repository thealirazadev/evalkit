"""Cache key stability and sensitivity, plus read/write round trips."""

import os
import time

import pytest

from evalkit.cache import (
    CacheEntry,
    cache_key,
    clear_cache,
    parse_duration,
    read_cache,
    write_cache,
)


def _key(**over):
    base = dict(
        base_url="https://api.example.com/v1",
        model="m",
        system="sys",
        prompt="hello",
        params={"temperature": 0, "max_tokens": 10},
        sample=0,
    )
    base.update(over)
    return cache_key(**base)


def test_key_is_stable():
    assert _key() == _key()


def test_base_url_changes_key():
    # Same model id at two endpoints must not collide: one endpoint's cached
    # response must never be served for a request aimed at another.
    assert _key() != _key(base_url="https://other.example.com/v1")


def test_model_changes_key():
    assert _key() != _key(model="other")


def test_system_changes_key():
    assert _key() != _key(system="different")


def test_prompt_changes_key():
    assert _key() != _key(prompt="hi")


def test_params_change_key():
    assert _key() != _key(params={"temperature": 1, "max_tokens": 10})


def test_param_order_does_not_change_key():
    assert cache_key("u", "m", "s", "p", {"a": 1, "b": 2}, 0) == cache_key(
        "u", "m", "s", "p", {"b": 2, "a": 1}, 0
    )


def test_sample_changes_key():
    assert _key(sample=0) != _key(sample=1)


def _entry():
    return CacheEntry(
        response_text="hello",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=120,
        created_at="2026-07-18T10:00:00Z",
        model="m",
    )


def test_read_miss_returns_none(tmp_path):
    assert read_cache(tmp_path, "deadbeef") is None


def test_write_then_read_round_trip(tmp_path):
    write_cache(tmp_path, "abcd1234", _entry())
    loaded = read_cache(tmp_path, "abcd1234")
    assert loaded is not None
    assert loaded.response_text == "hello"
    assert loaded.prompt_tokens == 10
    assert loaded.latency_ms == 120
    # Sharded by the first two hex chars.
    assert (tmp_path / "ab" / "abcd1234.json").exists()


def test_corrupt_entry_is_a_miss(tmp_path):
    path = tmp_path / "ff" / "ffee.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    assert read_cache(tmp_path, "ffee") is None


def test_version_mismatch_is_a_miss(tmp_path):
    write_cache(tmp_path, "ab00", _entry())
    path = tmp_path / "ab" / "ab00.json"
    path.write_text('{"version": 99, "response_text": "x", "latency_ms": 1}', encoding="utf-8")
    assert read_cache(tmp_path, "ab00") is None


def test_parse_duration_units():
    assert parse_duration("45s") == 45
    assert parse_duration("30m") == 1800
    assert parse_duration("12h") == 43200
    assert parse_duration("7d") == 604800
    assert parse_duration("1w") == 604800
    assert parse_duration("2H") == 7200  # case-insensitive unit


@pytest.mark.parametrize("bad", ["", "7", "d", "7x", "-1d", "1.5h", "7 days"])
def test_parse_duration_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)


def test_clear_cache_removes_all_entries(tmp_path):
    write_cache(tmp_path, "aa11", _entry())
    write_cache(tmp_path, "bb22", _entry())
    assert clear_cache(tmp_path) == 2
    assert read_cache(tmp_path, "aa11") is None
    assert read_cache(tmp_path, "bb22") is None
    # Empty shard directories are pruned.
    assert not (tmp_path / "aa").exists()


def test_clear_cache_missing_dir_is_zero(tmp_path):
    assert clear_cache(tmp_path / "nope") == 0


def test_clear_cache_older_than_filters_by_age(tmp_path):
    write_cache(tmp_path, "aa11", _entry())  # backdated below
    old_path = tmp_path / "aa" / "aa11.json"
    old_time = time.time() - 3600
    os.utime(old_path, (old_time, old_time))
    write_cache(tmp_path, "bb22", _entry())  # fresh

    # Remove only entries older than 30 minutes: the backdated one goes, the fresh stays.
    assert clear_cache(tmp_path, older_than_seconds=1800) == 1
    assert read_cache(tmp_path, "aa11") is None
    assert read_cache(tmp_path, "bb22") is not None
