# Contributing to evalkit

Thanks for your interest in improving evalkit. This project is a small, dependency-light CLI, and
the bar for changes is that they stay simple, tested, and honest about cost and exit codes.

## Development setup

evalkit uses [uv](https://docs.astral.sh/uv/). Python 3.12+ is required.

```sh
uv sync --extra dev          # install runtime + dev tools from the locked versions
uv run evalkit --version     # confirm the console entry point works
```

`--extra dev` pulls in the test and lint tools (`pytest`, `ruff`, `black`), which a plain
`uv sync` would leave out. If you do not use uv, `pip install -e ".[dev]"` installs the same set.

## The checks that must pass

CI runs exactly these steps, in this order, on every push and pull request. Run them locally before
you open a PR; a change is not done until all four are green:

```sh
uv run ruff check .          # lint (E, F, I, W, UP, B)
uv run black --check .       # formatting (line length 100)
uv run pytest                # full suite; the provider is mocked, so no network and no API key
uv build                     # the package must still build (wheel + sdist)
```

`uv run black .` and `uv run ruff check --fix .` apply the fixes rather than only reporting them.

### Tests never touch the network

The provider layer (`provider.py`) is the only module that makes HTTP calls, and every test drives
it through an injected `httpx.MockTransport` (see `tests/conftest.py`). Do not add a test that
reaches a real endpoint or requires an API key. New provider behavior is tested with the
`transport_factory` fixture, which records requests and lets a handler script the responses.

## Project layout

- `src/evalkit/` - the package. Each module has one responsibility: `config.py` (resolution),
  `suite.py` (load/validate/render), `provider.py` (HTTP), `assertions.py` (deterministic checks),
  `judge.py` (LLM-as-judge), `cache.py`, `cost.py`, `runner.py` (execution + aggregation), the
  `report_*.py` writers, and `cli.py` (the click entry point and the single error boundary).
- `tests/` - one test module per source module; `tests/` is intentionally not a package.
- `docs/` - `architecture.md` (suite format, request shape, cache, baseline, and report schemas)
  and `decisions.md` (the design decisions and their reasons) are the reference for how evalkit
  works; `design.md` covers terminal output and exit codes, `testing.md` the test strategy.
- `examples/` and `evals/` - runnable example suites.

## Code conventions

- **One CLI layer.** `click` with `CliRunner` in tests. All user-facing output goes through the
  single `rich.Console` created at startup and passed down; no bare `print()`. Machine-readable
  output (`--json`, `--junit`, `--html`) goes to files, never interleaved with terminal output.
- **Config once.** Configuration resolves once at startup (defaults, then `evalkit.yaml`, then
  env, then flags) into a frozen `Config`. Do not read environment variables elsewhere, and do not
  add global mutable state; pass `Config` and `Console` explicitly.
- **Network only in `provider.py`.** `httpx` is the only HTTP client. No provider SDKs.
- **No subprocesses and no prompts.** No `shell=True`, `os.system`, or subprocess calls, and no
  interactive prompt on any path; every decision comes from flags or config.
- **Errors.** Raise the typed exceptions in `errors.py`; only `cli.py` catches them. Users see one
  line per problem, extra detail goes behind `--verbose`, and raw tracebacks never print by default.
  The failure messages and exit codes are listed in `docs/design.md`.
- **Versioned files.** The cache entry and baseline formats carry a `version` field. When a format
  changes, bump the version and reject or migrate old files; never misread them silently.
- **Keep it small.** Prefer a function over a class and the standard library where it suffices
  (`hashlib`, `xml.etree`, `concurrent.futures`, `glob`). No abstraction (provider adapters,
  reporter base classes, assertion plugin registries) before three real use cases.
- **Naming.** `snake_case` verb-first functions (`load_suite`, `render_template`), `PascalCase`
  classes, `UPPER_SNAKE_CASE` constants. Cases are identified as `suite/case` everywhere: baseline,
  diff output, `-k` matching, and reports.

### Logging

- Stdlib `logging`, configured in `logging_setup.py`, to stderr only. Default level WARNING;
  `--verbose` sets DEBUG; `--quiet` sets ERROR.
- Under `--verbose`, emit structured `key=value` records per case: `event`, `suite`, `case`,
  `sample`, `cache` (hit or miss), `status_code`, `attempt`, `latency_ms`, `prompt_tokens`,
  `completion_tokens`, `cost_usd`.
- Never log the API key, full prompts, or full responses at info level or above. Debug may log
  truncated excerpts (first 200 characters) only.

### Security

- Never hardcode secrets. The key comes from `EVALKIT_API_KEY` or a gitignored `.env`;
  `.env.example` carries dummy values for every variable.
- Never log or persist the key: no log field, error detail, cache entry, or report may contain it.
  Redact `Authorization` headers if request debugging is ever added.
- Suite and config YAML are user input: load them with `yaml.safe_load` only, and validate
  structure, types, and assertion fields before any network call.
- Parse JSON from the provider and the judge defensively; never assume a field is present.
- `.evalkit/cache/` stores responses in plaintext and must stay gitignored. `baseline.json` must
  never contain response text, so it stays safe to commit.

## How to add an assertion type

Deterministic assertions are pure string/JSON logic with no network access. To add one, for example
`starts_with`:

1. Add the name to `KNOWN_ASSERTIONS` in `suite.py` so validation accepts it.
2. Add a branch to `_parse_assertion` in `suite.py` that validates the assertion's fields and builds
   an `Assertion`. Validate everything at load time (like `regex`, which is compiled up front) so a
   bad suite fails fast with a `SuiteError` (exit 2) before any provider call.
3. Register a handler in `assertions.py` with `@_register("starts_with")`. It receives
   `(assertion, response)` and returns `(passed, message)` - `message` is `None` on success and a
   specific one-line reason on failure.
4. Add tests in `tests/test_assertions.py` (pass, fail, and exact failure-message text) and, if you
   added new fields, validation tests in `tests/test_suite.py`.
5. Document it in the README suite-format section and the assertions table in `docs/architecture.md`.

`judge` is deliberately not a deterministic assertion: it lives in `judge.py`, is evaluated in the
runner, and has its own cost accounting. Follow that separation rather than routing a networked
check through `assertions.py`.

## How to add a reporter

Reporters consume a `RunResult` (defined in `runner.py`) and never call the provider. To add one:

1. Create `report_<format>.py` with a `build_<format>(run, ...)` that assembles the output and a
   `write_<format>_report(run, path, ...)` that writes it, raising `ReportError` (exit 2) on any
   I/O failure - copy the shape of `report_json.py`.
2. Sanitize any text derived from model output for the target format (see how `report_junit.py`
   strips characters XML 1.0 forbids).
3. Add a `--<format>` option to the `run` command in `cli.py`.
4. Add tests in `tests/test_reports.py`, including a write-failure case that asserts exit 2.

## Pull request expectations

- **One change per commit.** A migration, a model, a route, a reporter, its test - each is its own
  commit in a working state. Do not batch unrelated changes or split one change into noise commits.
- **Conventional Commits.** Short imperative subject: `type(scope): summary`. Types: `feat`, `fix`,
  `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- **No new dependency without discussion.** evalkit is intentionally lean. If a change needs one,
  raise it first; when agreed, `pyproject.toml` and `uv.lock` change together in their own commit.
- **Keep the docs honest.** If behavior changes, update the README and add a `CHANGELOG.md` entry
  under `Unreleased`. If the change alters a documented format or design decision, update
  `docs/architecture.md` or `docs/decisions.md` in the same pull request and say so in its
  description.
- **Match the style.** Type-hint public functions, keep functions small, and write comments only
  where the logic is non-obvious. No emoji anywhere. The provider is referred to as
  "the LLM provider API", never a specific vendor.

## Reporting bugs and requesting features

Use the issue templates. For a bug, include the evalkit version, the command, a minimal suite or
config that reproduces it, and the observed versus expected exit code and output. Never paste a real
API key or real prompt data - a redacted reproduction is enough. Security issues go through the
process in [SECURITY.md](SECURITY.md), not the public tracker.
