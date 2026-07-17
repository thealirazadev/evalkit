# Design — evalkit (terminal UX)

This document specifies the command-line user experience: commands, flags, output layout, color and
`NO_COLOR`, verbosity, error style, non-TTY behavior, and exit codes. Implement this exactly;
`docs/architecture.md` covers the internals.

## Command shape

```
evalkit run [OPTIONS] [SUITES...]
evalkit baseline [OPTIONS] [SUITES...]
evalkit --version | --help
```

`SUITES...` are suite files or directories (directories are searched for `*.yaml`/`*.yml`). With no
arguments, the `suites` glob from config applies (default `evals/**/*.yaml`).

There are **no interactive prompts anywhere** — evalkit is CI-first. Every decision comes from
flags, config, or the environment, on a TTY or off it.

## Flags

### `evalkit run`

| Flag              | Type   | Default                  | Behavior                                                                 |
| ----------------- | ------ | ------------------------ | ------------------------------------------------------------------------ |
| `--config PATH`   | path   | `./evalkit.yaml`         | Config file location. A missing default file is fine if env covers provider settings. |
| `--model TEXT`    | str    | resolved                 | Case model. Resolution: `--model` > suite `model` > `EVALKIT_MODEL` > config `provider.model`. |
| `--judge-model TEXT` | str | resolved                 | Judge model. Resolution: `--judge-model` > `EVALKIT_JUDGE_MODEL` > config `judge.model` > config `provider.model`. |
| `--no-cache`      | flag   | off                      | Skip cache reads; fresh calls still overwrite cache entries.             |
| `--concurrency N` | int    | 4                        | Worker pool size for provider calls. Keep modest; retries handle 429.    |
| `--json PATH`     | path   | none                     | Write the JSON run report to PATH.                                       |
| `--junit PATH`    | path   | none                     | Write JUnit XML to PATH.                                                 |
| `--fail-on-cost X`| float  | none                     | Exit 1 if total run cost (USD, including judge) exceeds X.               |
| `--baseline PATH` | path   | `.evalkit/baseline.json` | Baseline file to diff against when it exists.                            |
| `-k PATTERN`      | str    | none                     | Run only cases whose `suite/case` key contains PATTERN (plain substring).|
| `--quiet` / `-q`  | flag   | off                      | Failures, errors, and the summary only.                                  |
| `--verbose` / `-v`| flag   | off                      | Structured debug logs on stderr.                                         |
| `--no-color`      | flag   | off                      | Disable ANSI color; also automatic under `NO_COLOR` or non-TTY.          |

Notes:
- `--quiet` and `--verbose` together resolve to `--verbose` (more information wins); not an error.
- Unknown flags produce click's usage error, exit 2.

### `evalkit baseline`

Accepts the same execution flags (`--config`, `--model`, `--judge-model`, `--no-cache`,
`--concurrency`, `--baseline`, `--quiet`, `--verbose`, `--no-color`) and writes the baseline file
after a fully passing run.

- A run with any failure or error stores nothing: `Baseline not stored: 2 case(s) failing.`,
  exit 1 (or 2 for errors).
- An existing baseline file is overwritten without prompting (it is regenerable and the
  refuse-on-failure rule is the safety).
- `-k`, `--json`, and `--junit` are usage errors with `baseline` (exit 2): a partial baseline
  misleads, and baseline runs are not report runs.

## Output layout

All terminal output goes through one `rich.Console`. Layout, top to bottom: per-suite case lines,
failure details, baseline section (when a baseline exists), summary block.

```
checkout-support  (evals/checkout.yaml)
  pass  refund-request       3/3 samples   1.2s   $0.0021
  pass  order-status                       0.4s   $0.0008   cached
  FAIL  angry-customer       2/3 < 1.0     0.8s   $0.0019
        contains: "refund" not found in response (sample 2)
        judge: reply promises a refund outcome; rubric forbids it (sample 3)
  ERROR shipping-quote       provider: 503 after 3 attempts

baseline  (.evalkit/baseline.json, created 2026-07-01)
  regressions: checkout-support/angry-customer
  new: 1   removed: 0
  cost:  $0.0312 -> $0.0298  (-4.5%)
  mean latency:  840ms -> 1120ms  (+33%)

summary
  cases: 12   passed: 10   failed: 1   errors: 1
  cost: $0.0123  (judge: $0.0040)   tokens: 8,412 in / 2,306 out
  cache: 9/14 responses from cache
  wall time: 6.4s
```

Rules:
- One line per case: status, name, sample ratio (only when `samples > 1`), latency, cost, and a
  `cached` marker when every sample came from cache. Cost shows 4 decimals; `n/a` when pricing or
  usage is missing.
- Failure detail lines sit indented under the case, one per failed assertion, in file order,
  prefixed with the assertion type. Judge lines carry the judge's reason verbatim. When
  `samples > 1`, each detail names its sample.
- Error detail lines carry the mapped reason (`provider: ...`, `judge: ...`).
- The baseline section appears only when a baseline file exists; `regressions: none` when clean.
- The summary always prints, even under `--quiet`, and always includes cost, tokens, cache hits,
  and wall time — cost/latency visibility is a hard requirement, not decoration.
- When cost is partial, the summary line reads `cost: $0.0083 (partial: no pricing for model-x)`.

## Progress

- On a TTY (and not `--quiet`): a single-line progress display while cases run —
  `running 7/14  checkout-support/order-status` — cleared before results print.
- Off-TTY or `--quiet`: no animation. Off-TTY prints one plain line `running 14 cases...` so CI
  logs show liveness, then the results.

## Color

- Color only when stdout is a TTY and neither `--no-color` nor `NO_COLOR` is set.
- Semantic, never decorative: `pass` green, `FAIL` red, `ERROR` red on stderr summary count,
  warnings (`partial cost`, missing pricing) yellow, baseline regressions red, fixed green.
- Color is never the only signal: statuses are words (`pass`/`FAIL`/`ERROR`), warnings are
  prefixed `Warning:`, errors `Error:`. Uppercase FAIL/ERROR keeps failures scannable in
  monochrome CI logs.
- ASCII only; no Unicode glyphs carrying meaning, no emoji.

## Verbosity levels

- **Default:** progress, all case lines, failure/error details, baseline section, summary.
- **`--quiet`:** failed and errored case lines with details, baseline regressions, and the
  summary. Passing case lines and progress are suppressed. Logging at ERROR.
- **`--verbose`:** default output plus structured key=value logs on stderr per case (see
  `docs/rules.md` — Logging): cache hit/miss, HTTP status, attempt count, latency, tokens, cost.
  Never the API key; prompt/response excerpts truncated to 200 chars at debug only.

## Error message style

- One friendly line to stderr, prefixed `Error:`, red unless color is off. Detail behind
  `--verbose`. Never a raw traceback by default.
- Messages name the thing the user must fix and where: the file (`Invalid suite
  evals/checkout.yaml: case "refund-request": unknown assertion type "contain"`), the variable
  (`undefined variable {{product}}`), or the env var (`Set EVALKIT_API_KEY.`).
- Case-level provider errors do not abort the run (except auth, which always does); remaining
  cases still run, the errored case reports its reason, and the run exits 2.

## Exit codes

| Code | Meaning                                                                    |
| ---- | -------------------------------------------------------------------------- |
| 0    | Every case ran and passed; budget (if set) respected.                      |
| 1    | One or more cases failed assertions, cost budget exceeded, or `evalkit baseline` refused to store a failing run. |
| 2    | Config, usage, suite-validation, or provider error — including auth failure, any errored case, unenforceable `--fail-on-cost`, and click usage errors. |
| 130  | Aborted with Ctrl-C.                                                       |

Precedence: 2 beats 1 beats 0. These are the single source of truth and must match
`docs/rules.md`; CI gates on them, so changing any mapping is a breaking change.

## Accessibility

- `NO_COLOR` (any value), `--no-color`, and non-TTY stdout all disable ANSI styling entirely;
  output is verified free of escape codes in tests.
- No meaning by color alone; every state carries a word (`pass`, `FAIL`, `ERROR`, `cached`,
  `Warning:`).
- Tables degrade to plain aligned text without box-drawing characters when color is off.
- The summary block is stable, line-oriented, and grep-friendly (`^summary`, `cost:`,
  `cases:`) so scripts can scrape it, though the JSON report is the supported interface.
