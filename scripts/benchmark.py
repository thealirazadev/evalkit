"""Benchmark evalkit's own per-case overhead: uncached vs cached, no real network.

The provider is an ``httpx.MockTransport`` that returns a fixed response with zero
latency, so what is measured is evalkit's orchestration cost per case (render, dispatch,
assertion evaluation, accounting, cache read/write) and the difference between the
fresh-call path and the cache-hit path. It is NOT a measure of network savings: against a
real endpoint the wall-clock is dominated by provider latency (often seconds per call),
which this benchmark deliberately excludes to isolate framework overhead.

Run: ``uv run python scripts/benchmark.py`` (optionally ``--cases N --reps R``).
"""

from __future__ import annotations

import argparse
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from evalkit.config import Config  # noqa: E402
from evalkit.provider import build_client  # noqa: E402
from evalkit.runner import run_suites  # noqa: E402
from evalkit.suite import load_suite  # noqa: E402

RESPONSE = httpx.Response(
    200,
    json={
        "choices": [{"message": {"content": '{"reply": "ok"}'}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    },
)


def _mock_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: RESPONSE)


def _config() -> Config:
    return Config(
        base_url="https://api.example.com/v1",
        api_key="benchmark-key",
        default_model="example-model-1",
        cli_model=None,
        judge_model="example-model-1",
        concurrency=1,  # single worker so wall / cases is a clean per-case figure
        timeout_seconds=30,
        cache=True,
        suites_glob="evals/**/*.yaml",
        pricing={"example-model-1": {"input": 3.0, "output": 15.0}},
        no_color=True,
        config_path=None,
    )


def _write_suite(dir_path: Path, cases: int) -> Path:
    lines = [
        "suite: benchmark",
        "model: example-model-1",
        'prompt: "Answer about {{topic}}"',
        "cases:",
    ]
    for i in range(cases):
        lines.append(f"  - name: case-{i}")
        lines.append(f"    vars: {{topic: t{i}}}")
        lines.append("    assert:")
        lines.append("      - type: contains")
        lines.append("        value: reply")
        lines.append("      - type: json_valid")
    path = dir_path / "bench.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _time_run(suite, config, cache_root: Path) -> float:
    client = build_client(
        config.base_url, config.api_key, config.timeout_seconds, _mock_transport()
    )
    try:
        start = time.perf_counter()
        run_suites([suite], config, client, cache_root)
        return (time.perf_counter() - start) * 1000.0
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=500)
    parser.add_argument("--reps", type=int, default=7)
    args = parser.parse_args()
    config = _config()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        suite = load_suite(_write_suite(tmp_path, args.cases), cwd=tmp_path)

        # Warm up interpreter, import graph, and filesystem caches; discard the result.
        warm = tmp_path / "cache-warmup"
        _time_run(suite, config, warm)
        _time_run(suite, config, warm)

        uncached_ms: list[float] = []
        cached_ms: list[float] = []
        for rep in range(args.reps):
            cache_root = tmp_path / f"cache-{rep}"  # fresh cache => every call is a miss
            uncached_ms.append(_time_run(suite, config, cache_root))
            cached_ms.append(_time_run(suite, config, cache_root))  # same cache => all hits

    unc = statistics.median(uncached_ms)
    cac = statistics.median(cached_ms)
    n = args.cases

    print(f"platform: {platform.platform()}")
    print(f"python:   {platform.python_version()} ({platform.machine()})")
    print(f"cpu:      {platform.processor() or 'unknown'}")
    print(f"cases:    {n}   reps: {args.reps} after warm-up   transport: mocked, 0 latency")
    print()
    print(f"{'run':<22}{'median (ms)':>13}{'per-case':>14}{'min-max (ms)':>20}")
    print("-" * 69)
    for label, series, med in (
        ("uncached (all miss)", uncached_ms, unc),
        ("cached (all hit)", cached_ms, cac),
    ):
        spread = f"{min(series):.1f} - {max(series):.1f}"
        print(f"{label:<22}{med:>13.1f}{med / n * 1000:>11.1f} us{spread:>20}")
    print("-" * 69)
    print(f"cache-hit path is {unc / cac:.2f}x faster than the fresh-call path (mocked transport)")


if __name__ == "__main__":
    main()
