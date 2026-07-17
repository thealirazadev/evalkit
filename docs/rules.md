# Rules — evalkit

Binding for anyone implementing evalkit. When a habit conflicts with a rule here, follow the rule.

## Conventions

### Preferred libraries and patterns

- **CLI:** `click` with a group and two subcommands (`run`, `baseline`). Use `CliRunner` in tests.
  Do not add Typer, argparse, or a second CLI layer.
- **Output:** all user-facing output goes through a single `rich.Console` created at startup and
  passed down. Never mix bare `print()` with rich output. Machine-readable output (`--json`,
  `--junit`) goes to files, never interleaved with terminal output.
- **HTTP:** `httpx` only, and only inside `provider.py`. No `requests`, no provider SDKs, and no
  network calls from any other module. Tests use `httpx.MockTransport`; the suite never touches
  the network.
- **YAML:** `yaml.safe_load` exclusively. Never `yaml.load` with a permissive loader — suite files
  are user input.
- **JSON Schema:** the `jsonschema` library for the `json_schema` assertion. Do not hand-roll
  validation.
- **Config:** resolve once at startup into a frozen `Config` dataclass. Do not read env vars
  scattered through the code.
- **Errors:** raise typed exceptions from `errors.py`; catch them exactly once at the top level in
  `cli.py`.
- **Templating:** the `{{variable}}` renderer is a small regex-based function in `suite.py`. Do
  not add Jinja2 or any template engine; conditionals and loops are out of scope by design.

### What to avoid

- No global mutable state; pass `Config` and `Console` explicitly.
- No provider abstraction layer, adapter registry, or plugin system. One API shape (see
  `docs/architecture.md`); the rule of three gates any abstraction.
- No `shell=True`, no `os.system`, no subprocesses at all — evalkit shells out to nothing.
- No printing of the API key, raw tracebacks by default, or full responses at info level.
- No interactive prompts anywhere. evalkit is CI-first; every decision comes from flags or config.

### Naming

- **Modules:** `snake_case`, one responsibility each, as laid out in `docs/architecture.md`.
- **Functions:** `snake_case`, verb-first: `load_suite`, `render_template`, `complete_chat`,
  `evaluate_case`, `write_baseline`, `diff_against_baseline`.
- **Variables:** `snake_case`, descriptive (`rendered_prompt`, `cache_key`, `samples_passed`).
- **Constants:** `UPPER_SNAKE_CASE` (`DEFAULT_CONCURRENCY = 4`, `JUDGE_PROMPT`).
- **Classes/exceptions:** `PascalCase` (`Config`, `CaseResult`, `EvalkitError`, `ProviderError`).
- **Case keys:** `suite/case` (slash-joined names) everywhere a case is identified across runs —
  baseline, diff output, `-k` matching, JSON report.

### Commit format

- Conventional Commits, short imperative subject: `type(scope): summary`. Types: `feat`, `fix`,
  `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- ONE COMMIT PER FEATURE/TASK. The commit lists in `docs/phases.md` are the intended order; do not
  batch features together or split one feature into noise commits.
- No authorship attribution of any kind in commits — no "Generated with", no "Co-Authored-By".

### Dependencies and lockfile

- Pin exact versions (`==`) in `pyproject.toml`. Runtime: `click`, `rich`, `httpx`, `PyYAML`,
  `jsonschema`, `python-dotenv`. Dev: `pytest`, `ruff`, `black`. Starting pins are suggested in
  `docs/architecture.md`; verify each exists on PyPI at install time.
- Use `uv` and commit `uv.lock` (`uv lock` / `uv sync`). If `uv` is unavailable, commit a
  `requirements.lock` from pip-tools instead. Exactly one lockfile, kept in sync.
- Adding, removing, or bumping a dependency requires approval (see Boundaries) and its own commit.

### No database

There is no database. The disk cache and the baseline snapshot are plain JSON files, each carrying
a `version` field; when their format changes, bump the version and handle (or cleanly reject) old
files — never silently misread them.

## Error handling and logging

Two failure surfaces: the filesystem (suites, config, cache, reports) and the provider API. Users
see one friendly line per problem; `--verbose` adds detail; raw tracebacks never print by default.

### Failure classes, messages, and exit codes

| Situation                         | Detect                                    | User-facing message (one line)                                          | Exit |
| --------------------------------- | ----------------------------------------- | ----------------------------------------------------------------------- | ---- |
| Bad CLI flags                     | click usage error                         | click's own usage message                                               | 2    |
| Config file unreadable/invalid    | YAML error / schema check in `config.py`  | `Invalid config <path>: <reason>`                                       | 2    |
| No suites found                   | empty discovery result                    | `No suite files found. Pass paths or set 'suites' in evalkit.yaml.`     | 2    |
| Suite invalid                     | validation in `suite.py`                  | `Invalid suite <file>: <reason>` (names the case where relevant)        | 2    |
| Undefined template variable       | render step                               | `Suite <file>, case <name>: undefined variable {{x}}`                   | 2    |
| API key missing/invalid           | key unset before first call, or 401/403   | `API key missing or invalid. Set EVALKIT_API_KEY.`                      | 2    |
| Provider unreachable / persistent 429/5xx | retries exhausted in `provider.py` | case marked `error: <reason>`; summary explains                        | 2    |
| Malformed provider response       | missing `choices[0].message.content`      | case marked `error: malformed provider response`                        | 2    |
| Unparseable judge verdict         | after one JSON-only retry                 | case marked `error: judge returned an unparseable verdict`              | 2    |
| Assertion failure(s)              | `assertions.py` / `judge.py`              | per-case failure lines in the report                                    | 1    |
| Cost budget exceeded              | total > `--fail-on-cost`                  | `Cost budget exceeded: $<actual> > $<budget>`                           | 1    |
| Budget set but pricing missing    | model absent from price table             | `Cannot enforce --fail-on-cost: no pricing for model <id>`              | 2    |
| Baseline refused (failures)       | `evalkit baseline` with failing cases     | `Baseline not stored: <n> case(s) failing.`                             | 1    |
| Corrupt cache entry               | JSON/read error in `cache.py`             | treat as a miss, log at debug, refetch — never crash the run            | n/a  |
| Corrupt baseline file             | JSON/version error in `baseline.py`       | `Baseline <path> is unreadable; run 'evalkit baseline' to recreate.`    | 2    |
| Report file unwritable            | I/O error on `--json`/`--junit` path      | `Cannot write report <path>: <reason>`                                  | 2    |
| Ctrl-C                            | `KeyboardInterrupt` at top level          | `Aborted.`                                                              | 130  |
| Any other unexpected error        | uncaught in inner code                    | `Unexpected error. Re-run with --verbose for details.`                  | 1    |

Precedence when a run mixes outcomes: exit 2 (any errored case or config/provider problem) beats
exit 1 (failures/budget) beats 0. Exit 0 means every case ran and passed within budget.

### Style

- `EvalkitError` base in `errors.py` carries `message`, `exit_code`, optional `detail`.
  Subclasses: `ConfigError` (2), `SuiteError` (2), `ProviderError` (2), `ReportError` (2),
  `BudgetError` (1). Assertion failures are result data (`CaseResult`), not exceptions — a failing
  case is a normal outcome the reporters render.
- Inner modules raise; only `cli.py` catches `EvalkitError`, prints `message` to stderr (red
  unless color is off), logs `detail` at debug, and exits with `exit_code`. `KeyboardInterrupt`
  is caught at the same level (130).
- Every external touch handles failure: HTTP calls (timeouts, status), every file read/write
  (suites, config, cache, baseline, reports). Cache corruption is self-healing (miss + refetch);
  everything else fails loudly with the table above.

### Logging

- Stdlib `logging`, configured in `logging_setup.py`, to **stderr** only. Default WARNING;
  `--verbose` sets DEBUG; `--quiet` sets ERROR.
- With `--verbose`, emit structured key=value records per case: `event`, `suite`, `case`,
  `sample`, `cache` (hit/miss), `status_code`, `attempt`, `latency_ms`, `prompt_tokens`,
  `completion_tokens`, `cost_usd`.
- Never log the API key, full prompts, or full responses at info level and above. Debug may log
  truncated excerpts (first 200 chars) only.

## Security

- **Never hardcode secrets.** The API key lives in the environment (`EVALKIT_API_KEY`) or a local
  `.env`; `.env` is gitignored and `.env.example` carries dummies for every variable.
- **Never log or persist the key.** No structured field, error detail, or cache entry may include
  it. Redact `Authorization` headers if request debugging is ever added.
- **What leaves the machine:** rendered prompts (template plus case vars), suite params, and — for
  judge assertions — the model's response embedded in the judge prompt. Nothing else: no file
  contents, no environment, no repo metadata. Document this plainly in the README at
  implementation time, and warn users not to put secrets in suite vars.
- **What lands on disk:** `.evalkit/cache/` stores provider responses in plaintext. It is
  gitignored and must stay gitignored; treat cached responses with the same sensitivity as the
  prompts that produced them. `baseline.json` stores only statuses, token counts, cost, and
  latency — no response text — precisely so it is safe to commit.
- **Validate all input:** suite YAML and config YAML are user input — validate structure, types,
  and assertion fields before any network call; reject unknown assertion types and non-scalar
  vars. Regex patterns are compiled at load time so a bad pattern fails fast. JSON from the
  provider and the judge is parsed defensively (missing fields are handled, never assumed).
- **No protected routes to document** — evalkit is a local CLI with no server surface. Anyone who
  can run it with a key can do everything it does.

## Simplicity (YAGNI and KISS)

- Build only what the current phase requires. No speculative features, no config options that
  nothing reads today.
- Prefer a plain function over a class, a module over a package, a dataclass over a framework.
- No abstraction before three real use cases — this explicitly covers provider adapters (one
  shape in v1), reporter base classes (three concrete writers sharing an input dataclass is
  fine), and assertion plugin registries (a dict of type name to function is enough).
- No new wrapper classes, factories, managers, or utils files without owner approval.
- Before submitting, do a self-review pass: can this be done in fewer lines without hurting
  readability? If yes, rewrite first. If a solution exceeds ~150 lines, pause and justify it.
- Use the standard library where it suffices: `hashlib` for cache keys, `xml.etree` for JUnit,
  `concurrent.futures` for the worker pool, `glob` for suite discovery.

## Code style — no AI fingerprints

- NEVER mention any model vendor, assistant, or generation tool in code, comments, docstrings,
  commit messages, or docs. The provider is "the LLM provider API", full stop.
- No "Generated by...", "Co-authored-by: ..." or similar attribution anywhere.
- Comments like an experienced developer writes them: sparse, only where the logic is non-obvious
  (the cache-key canonicalization and the exit-code precedence deserve one; a loop does not).
- No emoji in code, output, comments, commit messages, or docs.
- Concise docstrings — one line stating intent and return; longer only when the contract is subtle
  (assertion semantics, cache-key composition).
- PEP 8 via `ruff` and `black`; type-hint public functions; keep functions small.

## Boundaries — never do without asking the owner first

- Never delete or rewrite a file wholesale; targeted edits only, and flag destructive changes
  first.
- Never modify `docs/PRD.md` or `docs/architecture.md` without flagging it — they are the source
  of truth. If implementation proves them wrong, stop, note it in `docs/memory.md` (Decisions
  log), and ask.
- Never add, remove, or bump a dependency without approval; when approved, `pyproject.toml` and
  the lockfile change together in their own commit.
- If a task is ambiguous or two designs are both defensible, ask instead of assuming.
- On an error you cannot fix in 2 genuine attempts, STOP, write what you tried and your current
  theory in `docs/memory.md` (In progress), and ask for direction.
- Mid-phase requests not in `docs/PRD.md`: ask whether to (a) add to the current phase, (b) create
  a new phase, or (c) log to the Backlog in `docs/phases.md`. Never silently absorb scope.
