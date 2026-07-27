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
- `docs/` - `PRD.md` and `architecture.md` are the source of truth; `rules.md` binds contributors.
- `examples/` and `evals/` - runnable example suites.

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
  under `Unreleased`. `docs/PRD.md` and `docs/architecture.md` are the source of truth - flag a
  change to them rather than editing them silently.
- **Match the style.** Type-hint public functions, keep functions small, and write comments only
  where the logic is non-obvious. No emoji anywhere. The provider is referred to as
  "the LLM provider API", never a specific vendor.

## Reporting bugs and requesting features

Use the issue templates. For a bug, include the evalkit version, the command, a minimal suite or
config that reproduces it, and the observed versus expected exit code and output. Never paste a real
API key or real prompt data - a redacted reproduction is enough. Security issues go through the
process in [SECURITY.md](SECURITY.md), not the public tracker.
