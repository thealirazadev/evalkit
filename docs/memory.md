# Memory — evalkit

Running log for the implementation. Update after every meaningful chunk of work, and log every
non-obvious decision with its reason, so any agent can pick up where the last left off.

## Completed

- Planning documentation created (README, PRD, architecture, rules, design, phases, testing,
  memory, launch-checklist, .env.example).
- Scaffolding: git repo, pinned deps + committed `uv.lock`, `pyproject.toml` (hatchling, src
  layout, `evalkit` entry point), full package/test stub tree.
- Phase 1 in progress. Done so far: `errors.py` (EvalkitError hierarchy), `config.py` (defaults <
  file < env < flags), `suite.py` (discovery, YAML load, validation, `{{variable}}` rendering),
  `provider.py` (chat call, usage capture, retries + backoff, auth mapping), `assertions.py` (all
  seven deterministic types with dispatch registry). Each has unit tests; suite is green, ruff and
  black clean.

## In progress

- Phase 1 remaining: cache, cost, runner, terminal report, exit-code mapping, end-to-end CLI wiring
  and tests.

## Decisions log

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
