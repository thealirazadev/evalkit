# Testing — evalkit

## Strategy

Two layers, no network anywhere in the automated suite.

### Unit and integration tests (pytest)

The provider is always mocked with `httpx.MockTransport` injected into `provider.py` (the client
is built from a transport parameter so tests never construct a real connection). The mock records
every request, which is how tests assert cache behavior ("second run makes zero calls"),
concurrency limits ("never more than N in flight"), and request shape (model, messages, params,
Bearer header present, key value never asserted into logs).

Per-module coverage:

- `test_config.py` — precedence defaults < file < env < flags; missing key detected before any
  call; malformed `evalkit.yaml` → friendly `ConfigError`.
- `test_suite.py` — the mini-spec: valid example loads; each validation error (bad YAML, unknown
  assertion type, missing case name, duplicate names, undefined `{{variable}}`, non-scalar var,
  invalid regex, bad `samples`/`threshold`) raises `SuiteError` with the documented message;
  template rendering including `{{ spaced }}` names and verbatim non-matches.
- `test_assertions.py` — pass and fail for all seven deterministic types, exact failure-message
  text, edge cases: empty response, whitespace-only response for `equals`/`json_valid`, unicode,
  `max_length` boundary (len == value passes).
- `test_judge.py` — verdict parsing (clean JSON, JSON with surrounding text, retry on garbage,
  error after second failure); judge model resolution order; reason propagated to the result.
- `test_provider.py` — request shape; 401/403 → `ProviderError` exit 2; 429/5xx/timeout retry
  then case error; `Retry-After` honored; malformed 2xx body → case error; usage captured;
  missing usage tolerated.
- `test_cache.py` — key stability (same inputs → same key; each of model/system/prompt/params/
  sample changes it); hit returns stored entry; `--no-cache` skips reads but writes; corrupt
  entry treated as a miss.
- `test_runner.py` — all-assertions-must-pass; N-sample threshold arithmetic (2/3 vs 0.67 passes,
  1/3 fails); exit-code precedence (error beats fail beats pass); results ordered by file
  position under concurrency.
- `test_cost.py` — hand-computed USD from tokens and the fixture price table; sum over samples;
  judge cost broken out; missing pricing → `n/a` + partial flag; `--fail-on-cost` over/under/
  unenforceable.
- `test_baseline.py` — snapshot write on pass; refusal on fail (file untouched); diff categories
  (regression, fixed, new, removed) and deltas; corrupt/version-mismatched file → exit 2.
- `test_reports.py` — JSON matches the documented schema (validated with `jsonschema` against a
  schema kept in the test); JUnit XML parses and maps suites/cases/failures/errors/time
  correctly; judge reasons present in both.
- `test_cli.py` — end-to-end through click's `CliRunner` with the mock transport: exit codes for
  pass/fail/error/usage paths, `--json`/`--junit` files written, `-k` filtering, baseline round
  trip, `NO_COLOR` output free of escape codes.

Fixtures in `conftest.py`: a factory for mock providers with scripted responses (including
sequences for retry tests), a temp working dir with `.evalkit/` isolation, sample suites and a
pricing config under `tests/fixtures/`.

### Manual QA

The checklists in `docs/phases.md`. They cover what mocks cannot: a real provider endpoint, real
latency and cost numbers, TTY progress and color, CI ingestion of the JUnit file, and Ctrl-C
behavior. Manual QA is required before a phase is done but is not part of the automated suite.

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

Build and tests must pass before a feature is reported done. For every commit:

1. `uv run pytest` passes — mocked provider, zero network.
2. `uv run ruff check .` passes.
3. `uv run black --check .` passes.
4. The package still installs and `evalkit --version` runs.

Fix all errors before reporting done. Do not commit red tests or a broken build. Tests for a
feature land in the same commit as the feature.
