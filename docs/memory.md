# Memory — evalkit

Running log for the implementation. Update after every meaningful chunk of work, and log every
non-obvious decision with its reason, so any agent can pick up where the last left off.

## Completed

- Planning documentation created (README, PRD, architecture, rules, design, phases, testing,
  memory, launch-checklist, .env.example).
- Scaffolding: git repo, pinned deps + committed `uv.lock`, `pyproject.toml` (hatchling, src
  layout, `evalkit` entry point), full package/test stub tree.
- Phase 1 COMPLETE and verified. Modules: `errors.py`, `config.py` (defaults < file < env < flags),
  `suite.py` (discovery, load, validation, rendering), `provider.py` (chat call, usage, retries +
  backoff, auth mapping), `assertions.py` (all seven deterministic types), `cache.py` (key +
  read/write, corrupt-as-miss), `cost.py`, `runner.py` (per-case exec, aggregation, exit-code map),
  `report_terminal.py`, `logging_setup.py`, `cli.py` (run command + error boundary). Verification:
  `uv run pytest` 106 passed, `ruff check .` clean, `black --check .` clean, `uv build` clean,
  `evalkit --version`/`run --help` work; manual exit-code checks pass (no-suites=2, missing-key=2,
  provider-unreachable retries then exit 2 with no traceback).

## In progress

- Phase 2: judge assertion, N-sample mode, JSON + JUnit reports, `--fail-on-cost`, non-TTY output.

## Decisions log

- Cost model (resolves an ambiguity in architecture.md's "cached contributes $0 to run spend"):
  per-case `cost_usd` is the modeled cost (tokens x pricing), computed for cached and fresh cases
  alike; the run total is the sum of per-case modeled costs. Caching savings are reported via the
  cache-hit count and wall time, not by zeroing a cached case's cost. This keeps one consistent cost
  number across the terminal summary, JSON totals, `--fail-on-cost`, and baseline diffs, and honors
  the hard requirement that cost is always visible. "Run spend" is read as "no new provider call."
- Owner instruction (mid-run): use fine-grained commits (one discrete change each). Applied from
  the assertions work onward; earlier commits left as-is. Tests still land with the code they cover.
- Phase 1 runs a single sample per case (samples fixed at 1). Full N-sample looping + range
  validation + ratio display is scheduled for the Phase 2 `n-sample` commit per `docs/phases.md`.
  Suite loader accepts and type-checks `samples`/`threshold` now; range checks come in Phase 2.
- `judge` is a known assertion type from Phase 1 (so unknown-type validation is honest), but its
  evaluation lives in `judge.py` and is wired in Phase 2; `assertions.evaluate_assertion` raises on
  `judge` by design.
- Test helpers imported via `from conftest import ...` (pytest prepends the tests dir); `tests/` is
  intentionally not a package to keep the src-layout import checks meaningful.

_Do not change `docs/PRD.md` or `docs/architecture.md` without flagging it here first._
