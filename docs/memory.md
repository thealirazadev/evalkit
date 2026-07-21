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

- Phase 2 COMPLETE and verified. Added: `judge.py` (prompt build, verdict parsing, JSON-only
  retry), judge evaluation wired into the runner with judge-model resolution, judge-call caching,
  and cost broken out; N-sample looping with per-sample cache keys and threshold; `report_json.py`
  (`--json`) and `report_junit.py` (`--junit`) with response excerpts and judge reasons; budget
  enforcement (`--fail-on-cost`, exit 1 over budget, exit 2 when unenforceable); off-TTY plain
  liveness line. Verified `uv run pytest` 140 passed, ruff + black clean; manual end-to-end against a
  local mock HTTP server confirmed judge failure with surfaced reason, JSON/JUnit output, judge cost
  breakout, caching (incl. judge) on re-run, and budget exit 1.

- Phase 3 COMPLETE and verified. Added `baseline.py` (build_snapshot, write_baseline, load_baseline
  with corrupt/version guard, diff_against_baseline), the `evalkit baseline` command (stores on a
  fully-passing run, refuses on failure/error with exit 1/2), `--baseline` on both commands, the
  terminal baseline section, and the JSON `baseline` object (the diff dict). CLI refactored to share
  `_resolve_config`/`_load_suites`/`_require_provider`/`_execute` helpers. Verified `uv run pytest`
  153 passed, ruff + black clean; manual e2e against the local mock confirmed store-on-pass,
  refuse-on-fail, regression diff with deltas, and cached-response reuse driving the flip.

- Phase 4 COMPLETE and verified. Runner executes cases through a `ThreadPoolExecutor` sized by
  `--concurrency`/`run.concurrency` (default 4); results render in suite-file order; Ctrl-C cancels
  pending futures (boundary exits 130). Added `-k` substring filter (exit 2 with the documented
  message on no match; a usage error for `baseline`), `--quiet`/`--verbose` (verbose wins; structured
  per-sample and per-request key=value debug logs to stderr that never include the key), and a
  transient TTY progress line (`ProgressLine`, inert off-TTY/under `--quiet`). Verified `uv run
  pytest` 163 passed, ruff + black clean.

- Finalization COMPLETE. Added MIT `LICENSE`, an example `evalkit.yaml` and `evals/support-bot.yaml`
  (validated: json_valid/json_schema/contains/not_contains/max_length/judge + samples/threshold),
  and rewrote `README.md` with install/configure/run/baseline, the suite mini-spec, exit codes, and
  the security note (what leaves the machine, what lands on disk, key never stored). Removed a stray
  `.evalkit/baseline.json` that an earlier manual `evalkit baseline` run wrote into the repo.
- Final verification: `uv run pytest` 163 passed (provider mocked, zero network), `ruff check .`
  clean, `black --check .` clean, `uv build` clean, `evalkit --version` and `python -m evalkit`
  work. Manual end-to-end against a local mock server confirmed pass/fail/error, judge with surfaced
  reason + cost breakout, N-sample, caching (incl. judge), JSON + JUnit reports, baseline
  store/refuse/diff, `-k`, `--quiet`/`--verbose` (key never printed), `--fail-on-cost`
  over-budget (exit 1) and unenforceable (exit 2), and every documented unhappy path/exit code.

- Continuous integration: `.github/workflows/ci.yml` runs the `docs/testing.md` gate on every push
  and pull request to `main` — `uv sync --locked --extra dev`, `uv run ruff check .`,
  `uv run black --check .`, `uv run pytest`, `uv build`, `uv run evalkit --version`. First run on
  `main` was green (163 passed, 32 files unchanged, both artifacts built).

## In progress

_Nothing in progress. All four phases plus finalization are complete and verified._

## Decisions log

- Quality pass (2026-07-22): cache-key correctness fix. The key now includes `base_url` as part of
  the request identity. Previously `{model, system, prompt, params, sample}` excluded it, so the
  same model id pointed at two different endpoints collided and one endpoint could silently serve
  the other's cached response (a reproducibility/correctness bug). Flagged change to
  `docs/architecture.md` Caching section to match. Existing cache entries are keyed differently now,
  but the cache is regenerable and gitignored, so no migration is needed.


- Added `BaselineError` (exit 2) to the error hierarchy for corrupt/version-mismatched baseline
  files. `docs/rules.md` enumerates five subclasses; this sixth is a small, consistent addition (the
  boundary catches any `EvalkitError`) needed for the documented "Baseline ... is unreadable" path.
- N-sample threshold comparison: the passing fraction is compared to the threshold at 2-decimal
  precision (`round(passed/samples, 2) >= round(threshold, 2)`). Required so that 2/3 = 0.6667 passes
  the documented `threshold: 0.67` (PRD success criterion 8); a naive float compare would fail it.
- `--fail-on-cost` uses modeled total cost (case + judge). When cost is partial (missing pricing or
  usage) the budget cannot be enforced honestly, so the run exits 2 (`Cannot enforce --fail-on-cost:
  ...`). Over-budget prints the message and raises the exit code to at least 1 without overriding a
  pre-existing exit 2 (error precedence preserved).
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
- CI installs with `uv sync --locked --extra dev`: the dev tools (pytest, ruff, black) are a
  `[project.optional-dependencies]` extra, which a plain `uv sync` would not install, and `--locked`
  makes the job fail rather than silently re-resolve if `uv.lock` drifts from `pyproject.toml`.
  uv itself is pinned to the version used locally so CI and local runs agree.
- The suite needs no credentials in CI: the provider is driven through an injected
  `httpx.MockTransport`, so no repository secret is configured. The manual QA checklists in
  `docs/phases.md` (real endpoint, TTY colour/progress, Ctrl-C, CI ingestion of the JUnit file)
  stay out of CI by design, since they require a live endpoint and a terminal.

_Do not change `docs/PRD.md` or `docs/architecture.md` without flagging it here first._
