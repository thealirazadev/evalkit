# Phases — evalkit

Phase N+1 does not start until the owner approves phase N. Each phase is independently shippable
and leaves the tool working. One commit per feature/task, in the listed order, Conventional Commits
(see `docs/rules.md`); tests land in the same commit as the feature they cover. Anything extra goes
to the Backlog at the bottom.

The senior differentiators land early by design: caching for reproducibility, cost/latency
accounting, and CI exit codes are Phase 1; the judge assertion with surfaced reasons, N-sample
mode, JUnit/JSON reports, `--fail-on-cost`, and non-TTY behavior are Phase 2. None of these are
stretch goals.

---

## Phase 1 — Run suites with deterministic assertions, cache, and cost accounting

Goal: `evalkit run` loads and validates suites, renders templates, calls the provider (mocked in
tests), evaluates the seven deterministic assertions, caches responses, and prints the terminal
report with per-case and per-run cost and latency. Exit codes 0/1/2 are correct from day one.
Execution is serial in this phase.

### Definition of done

- The package installs and exposes `evalkit` (`uv sync` or `pip install -e ".[dev]"`, then
  `evalkit --version` works); `pyproject.toml` pins deps exactly, Python `>=3.12`, lockfile
  committed.
- Config resolves per `docs/architecture.md`: defaults < `evalkit.yaml` < env < flags; a missing
  key produces `API key missing or invalid. Set EVALKIT_API_KEY.` before any call, exit 2.
- Suite discovery from args or the config glob; every validation error in the `docs/rules.md`
  table (bad YAML, unknown assertion, missing case name, undefined `{{variable}}`, non-scalar
  var, bad regex) produces its documented one-line message, exit 2, and zero provider calls.
- The provider call matches the documented request shape; 401/403 aborts with exit 2; 429/5xx/
  timeout retries 3 attempts with backoff then marks the case `error`; latency and token usage
  are captured per call.
- All seven deterministic assertions implemented with the exact semantics in the mini-spec; a
  case fails if any assertion fails; failure messages match the documented style.
- Cache under `.evalkit/cache/` keyed per the architecture doc: a second identical run makes zero
  provider calls (asserted via the mock) and reports `cached`; `--no-cache` bypasses reads but
  still writes; a corrupt cache entry is treated as a miss, never a crash.
- Cost per case from usage tokens and the config price table; missing pricing shows `n/a` plus a
  `Warning:`; the terminal report matches the layout in `docs/design.md` (case lines, failure
  details, summary with cost, tokens, cache hits, wall time).
- Exit codes: all-pass 0; any assertion failure 1; any errored case or config/suite/provider
  problem 2; Ctrl-C 130. No raw traceback by default.
- `pytest`, `ruff check .`, and `black --check .` pass; the suite makes no network calls.

### Manual test checklist

- [ ] Write a two-case suite against a real provider endpoint; `evalkit run` prints case lines,
      failure details for a deliberately failing `contains`, and the summary. Exit 1.
- [ ] Fix the case; run again. Exit 0, and the second run says `cached` with 0 fresh calls.
- [ ] `evalkit run --no-cache` re-calls the provider (fresh latency, cache overwritten).
- [ ] Break the YAML (unknown assertion type); exit 2 with the file and case named.
- [ ] Reference `{{typo}}` in the prompt; exit 2 naming the variable, no provider call.
- [ ] Unset `EVALKIT_API_KEY`; exit 2 with the documented message; the key never prints.
- [ ] Point `EVALKIT_BASE_URL` at a dead port; retries, then the case shows `error`, run exits 2.
- [ ] Remove the model from `pricing`; cost shows `n/a` with a `Warning:`, run still completes.
- [ ] `evalkit --version` and `evalkit run --help` work.

### Commits

1. `chore: scaffold package with pyproject and evalkit entry point`
2. `chore: pin dependencies and commit lockfile`
3. `feat: resolve config from evalkit.yaml, env, and flags`
4. `feat: load and validate suite yaml files`
5. `feat: render prompt templates with case variables`
6. `feat: call the provider chat endpoint with retries and error mapping`
7. `feat: implement the seven deterministic assertions`
8. `feat: cache provider responses on disk with --no-cache bypass`
9. `feat: compute per-case cost and latency from usage and pricing`
10. `feat: render terminal report with case lines and run summary`
11. `feat: map run outcomes to exit codes 0, 1, and 2`
12. `test: cover evalkit run end to end with a mocked provider`

---

## Phase 2 — Judge assertion, N-sample mode, and CI-grade reports

Goal: the non-deterministic testing story and the CI story. `judge` assertions run against a
separately configured judge model and surface their reasons; cases can run k samples against a
pass threshold; runs emit JSON and JUnit reports; `--fail-on-cost` enforces a budget; output is
plain and non-interactive off-TTY.

### Definition of done

- `judge` assertion per the mini-spec: judge model resolves flag > env > `judge.model` >
  `provider.model`, temperature 0, verdict parsed as `{"pass": bool, "reason": str}`; one JSON-only retry,
  then the case is an `error`. The reason appears verbatim in terminal failure details, JSON
  `failures[].message`, and JUnit failure text. Judge calls are cached and their cost is counted
  and broken out (`judge: $x` in the summary, `judge_cost_usd` in JSON).
- N-sample mode: `samples`/`threshold` validated (k >= 1, threshold in (0, 1]); per-sample cache
  keys; case passes when `passed/k >= threshold`; reports show the ratio; cost sums over samples,
  latency is the mean of fresh samples.
- `--json PATH` writes exactly the schema in `docs/architecture.md`; `--junit PATH` writes the
  documented JUnit mapping; both include cost, latency, tokens, and cache info; unwritable paths
  exit 2.
- `--fail-on-cost X`: total over budget exits 1 with budget and actual printed; set while any
  executed model lacks pricing exits 2 with the documented message.
- Off-TTY: no ANSI codes, no animation, one plain liveness line; `NO_COLOR` and `--no-color`
  honored; confirmed no interactive prompt exists on any path.
- `pytest`, `ruff check .`, `black --check .` pass; JUnit output validated against a JUnit
  consumer or schema in tests.

### Manual test checklist

- [ ] Add a `judge` assertion with a rubric a real response violates; the case fails and the
      judge's reason prints under it. Re-run: judge verdict comes from cache.
- [ ] Set `judge.model` to a different model; `--verbose` shows judge calls using it, and the
      summary breaks out judge cost.
- [ ] Give a case `samples: 3, threshold: 0.67` at `temperature: 0.9`; the report shows the
      ratio; a cached re-run reproduces the identical outcome.
- [ ] `evalkit run --json out.json --junit out.xml`; inspect both; upload `out.xml` to the CI
      system (or a local JUnit viewer) and see per-case results with times.
- [ ] `evalkit run --fail-on-cost 0.000001` exits 1 naming budget and actual.
- [ ] Remove a model's pricing and pass `--fail-on-cost`; exit 2.
- [ ] `evalkit run | cat` — plain output, no escape codes, no hang, correct exit code preserved.

### Commits

1. `feat: add judge assertion with separately configured judge model`
2. `feat: surface judge reasons in failure details and cache judge calls`
3. `feat: add n-sample mode with per-case pass threshold`
4. `feat: write json run report via --json`
5. `feat: write junit xml report via --junit`
6. `feat: enforce cost budget via --fail-on-cost`
7. `feat: emit plain non-interactive output when stdout is not a tty`

---

## Phase 3 — Baseline snapshot and regression diff

Goal: `evalkit baseline` stores a passing run; `evalkit run` diffs against it and reports flipped
cases and cost/latency deltas.

### Definition of done

- `evalkit baseline` runs the pipeline and writes `.evalkit/baseline.json` per the schema in
  `docs/architecture.md`, overwriting any previous snapshot without prompting; with any failure
  or error it writes nothing and exits 1 (or 2 for errors) with the documented message.
- `-k`, `--json`, `--junit` with `baseline` are usage errors, exit 2.
- `evalkit run` loads the baseline when present: the baseline section renders regressions, fixed,
  new, removed, and cost/mean-latency deltas per `docs/design.md`; the JSON report carries the
  `baseline` object; no baseline file means no section and `"baseline": null`.
- A corrupt or version-mismatched baseline exits 2 with the recreate hint.
- The diff never changes exit codes by itself (a regressed case already fails).
- `pytest`, `ruff check .`, `black --check .` pass.

### Manual test checklist

- [ ] On a passing run, `evalkit baseline` writes the file; inspect it: statuses, cost, latency,
      no response text.
- [ ] `evalkit baseline` with a failing case refuses, exit 1, file untouched.
- [ ] Break a case's prompt; `evalkit run` lists it under regressions with deltas, exit 1.
- [ ] Add a new case; the diff counts it under `new`.
- [ ] Corrupt `baseline.json` by hand; exit 2 with the recreate message.
- [ ] `--json` output includes the populated `baseline` object.

### Commits

1. `feat: store baseline snapshot via evalkit baseline`
2. `feat: refuse to store a baseline from a failing run`
3. `feat: diff runs against the baseline in the terminal report`
4. `feat: include baseline comparison in the json report`

---

## Phase 4 — Concurrency and output controls

Goal: runs are fast and polite, and the CLI grows the remaining ergonomics: case filtering,
quiet/verbose, and progress.

### Definition of done

- Cases execute through `concurrent.futures.ThreadPoolExecutor` sized by `--concurrency` /
  `run.concurrency` (default 4); results render in suite-file order regardless of completion
  order; at most N requests in flight (asserted via the mock); Ctrl-C mid-run exits 130 cleanly.
- `-k PATTERN` filters on the `suite/case` key; summary counts reflect the filtered set; no
  matches is exit 2 with `No cases match '-k PATTERN'.`.
- `--quiet` and `--verbose` behave per `docs/design.md`; verbose emits the structured fields from
  `docs/rules.md` and never the key.
- TTY progress line per `docs/design.md`, cleared before results; absent off-TTY and under
  `--quiet`.
- `pytest`, `ruff check .`, `black --check .` pass.

### Manual test checklist

- [ ] A suite of 8+ slow cases finishes visibly faster at `--concurrency 4` than `--concurrency 1`.
- [ ] `--verbose` shows interleaved case logs on stderr while the final report stays ordered.
- [ ] Ctrl-C mid-run prints `Aborted.`, exit 130, no traceback, no corrupt cache entries.
- [ ] `-k refund` runs only matching cases; `-k nomatch` exits 2.
- [ ] `--quiet` shows only failures and the summary; `NO_COLOR=1` output has no escape codes.
- [ ] The progress line appears on a TTY and never in `evalkit run | cat`.

### Commits

1. `feat: run cases concurrently with a bounded worker pool`
2. `feat: add -k substring filter for case selection`
3. `feat: add --quiet and --verbose output levels`
4. `feat: show a progress line during tty runs`

---

## Phase verification (run after every phase)

- [ ] `uv run pytest` passes with the provider mocked and no network access.
- [ ] `ruff check .` and `black --check .` pass.
- [ ] `uv sync` / `pip install -e ".[dev]"` succeeds and `evalkit --version` runs in a clean shell.
- [ ] Happy path: a real (or locally served) provider run reaches the phase's intended outcome.
- [ ] Exit codes match `docs/design.md` for every path exercised; verify `echo $?` on each.
- [ ] Console output shows no warnings, stray logs, or escape codes under `NO_COLOR`.

Unhappy paths (exercise those the phase implements):

- [ ] Invalid YAML, unknown assertion, undefined variable — exit 2, file and case named.
- [ ] Missing `EVALKIT_API_KEY` — exit 2, key never printed.
- [ ] Provider unreachable — retries, case `error`, exit 2, no traceback.
- [ ] Empty suites glob / no suite files — exit 2 with the hint, not a crash.
- [ ] Empty or whitespace-only provider response — assertions evaluate it (fails `json_valid`
      etc.), no crash.
- [ ] Very long response — `max_length` fails cleanly; terminal output stays readable; excerpts
      truncated in JUnit.
- [ ] Duplicate run mid-cache (two evalkit processes) — no crash; worst case a redundant fetch.
- [ ] Re-run after deleting `.evalkit/cache/` — identical results, fresh calls.

## Backlog

_Empty. Record out-of-scope ideas here with a one-line rationale; do not implement without
promoting to a phase. Candidates already known: suite-level default `samples`/`threshold`, a
`--allow-failures` flag for baselines (would make "fixed" diffs reachable), lenient JSON
extraction from fenced responses, a cache TTL or `evalkit cache clear` subcommand._
