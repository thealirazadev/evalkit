# Testing - evalkit

## Strategy

Two layers, no network anywhere in the automated suite.

### Unit and integration tests (pytest)

The provider is always mocked with `httpx.MockTransport` injected into `provider.py` (the client
is built from a transport parameter so tests never construct a real connection). The mock records
every request, which is how tests assert cache behavior ("second run makes zero calls"),
concurrency limits ("never more than N in flight"), and request shape (model, messages, params,
Bearer header present, key value never asserted into logs).

Per-module coverage:

- `test_config.py` - precedence defaults < file < env < flags; missing key detected before any
  call; malformed `evalkit.yaml` → friendly `ConfigError`.
- `test_suite.py` - the mini-spec: valid example loads; each validation error (bad YAML, unknown
  assertion type, missing case name, duplicate names, undefined `{{variable}}`, non-scalar var,
  invalid regex, bad `samples`/`threshold`) raises `SuiteError` with the documented message;
  template rendering including `{{ spaced }}` names and verbatim non-matches.
- `test_assertions.py` - pass and fail for all seven deterministic types, exact failure-message
  text, edge cases: empty response, whitespace-only response for `equals`/`json_valid`, unicode,
  `max_length` boundary (len == value passes).
- `test_judge.py` - verdict parsing (clean JSON, JSON with surrounding text, retry on garbage,
  error after second failure); judge model resolution order; reason propagated to the result.
- `test_provider.py` - request shape; 401/403 → `ProviderError` exit 2; 429/5xx/timeout retry
  then case error; `Retry-After` honored; malformed 2xx body → case error; usage captured;
  missing usage tolerated.
- `test_cache.py` - key stability (same inputs → same key; each of model/system/prompt/params/
  sample changes it); hit returns stored entry; `--no-cache` skips reads but writes; corrupt
  entry treated as a miss.
- `test_runner.py` - all-assertions-must-pass; N-sample threshold arithmetic (2/3 vs 0.67 passes,
  1/3 fails); exit-code precedence (error beats fail beats pass); results ordered by file
  position under concurrency.
- `test_cost.py` - hand-computed USD from tokens and the fixture price table; sum over samples;
  judge cost broken out; missing pricing → `n/a` + partial flag; `--fail-on-cost` over/under/
  unenforceable.
- `test_baseline.py` - snapshot write on pass; refusal on fail (file untouched); diff categories
  (regression, fixed, new, removed) and deltas; corrupt/version-mismatched file → exit 2.
- `test_reports.py` - JSON matches the documented schema (validated with `jsonschema` against a
  schema kept in the test); JUnit XML parses and maps suites/cases/failures/errors/time
  correctly; judge reasons present in both.
- `test_cli.py` - end-to-end through click's `CliRunner` with the mock transport: exit codes for
  pass/fail/error/usage paths, `--json`/`--junit` files written, `-k` filtering, baseline round
  trip, `NO_COLOR` output free of escape codes.

Fixtures in `conftest.py`: a factory for mock providers with scripted responses (including
sequences for retry tests), a temp working dir with `.evalkit/` isolation, sample suites and a
pricing config under `tests/fixtures/`.

### Manual checks against a live provider

Some behavior cannot be exercised with a mock: a real endpoint, real latency and cost numbers, TTY
progress and color, Ctrl-C, and CI ingestion of the JUnit file. These are checked by hand against a
real endpoint and are not part of the automated suite:

- A suite with a deliberately failing `contains` exits 1 with failure details; once fixed it exits
  0, and a second run reports `cached` with no fresh calls. `--no-cache` calls the provider again.
- An unknown assertion type or an undefined `{{variable}}` exits 2 naming the file and case, with
  no provider call. An unset `EVALKIT_API_KEY` exits 2 and the key never prints. A dead base URL
  retries, marks the case `error`, and exits 2.
- A model missing from `pricing` shows `n/a` cost with a `Warning:`; with `--fail-on-cost` it exits
  2. A tiny `--fail-on-cost` budget exits 1 naming the budget and the actual cost.
- A `judge` rubric that a real response violates fails the case with the judge's reason, and a
  re-run takes the verdict from the cache. A separate `judge.model` shows up in `--verbose` logs and
  in the judge cost line.
- `samples: 3, threshold: 0.67` at a high temperature shows the ratio, and a cached re-run
  reproduces it.
- `--json` and `--junit` files are well formed, and the JUnit file shows per-case results and times
  in a JUnit viewer. `evalkit run | cat` prints plain output with no escape codes.
- `evalkit baseline` stores a snapshot with no response text, refuses a failing run, and a later
  regression, new case, or corrupted snapshot is reported as documented.
- At `--concurrency 4` a suite of slow cases finishes faster than at `--concurrency 1`; `-k` filters
  cases and a pattern with no match exits 2; Ctrl-C prints `Aborted.` and exits 130 without
  corrupting the cache; the progress line appears on a TTY and never when piped.

## Exact commands

```sh
uv sync                        # or: pip install -e ".[dev]"

uv run pytest                  # full suite
uv run pytest -q               # quiet
uv run pytest tests/test_runner.py::test_threshold_pass   # a single test

uv run ruff check .            # lint
uv run black --check .         # format check
uv run black .                 # apply formatting

uv build                       # package sanity check
evalkit --version              # entry point works after install
```

## Gate

Every commit keeps the build green:

1. `uv run pytest` passes, with the provider mocked and zero network access.
2. `uv run ruff check .` passes.
3. `uv run black --check .` passes.
4. The package still builds and `evalkit --version` runs.

Tests for a feature land in the same commit as the feature.
