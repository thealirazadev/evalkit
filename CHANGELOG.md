# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

evalkit has not yet been tagged or published; everything below is the initial, in-development
feature set on `main`.

### Added

- `evalkit run` command: discovers YAML suites (explicit paths or the config glob), renders each
  case's `{{variable}}` template, calls the LLM provider API, evaluates assertions, and reports
  pass/fail with per-case latency and cost.
- Deterministic assertions: `contains`, `not_contains`, `equals`, `regex`, `json_valid`,
  `json_schema`, and `max_length`, each with a specific one-line failure message.
- `judge` assertion: a separately configured judge model returns a pass/fail verdict with a reason;
  its cost is tracked separately, and an unparseable verdict (after one JSON-only retry) is an error,
  not a failure.
- Opt-in `extract_fenced` on `json_valid` / `json_schema` to pull JSON out of a Markdown code fence
  before validating; the strict default is unchanged.
- N-sample execution with a pass `threshold`, and suite-level `samples` / `threshold` defaults that
  a case may override.
- On-disk response cache under `.evalkit/cache/`, keyed by a hash of the request identity (base URL,
  model, rendered system/prompt, params, and sample index) so unchanged suites re-run with no
  provider calls. Corrupt entries self-heal as a miss.
- `evalkit cache clear` with an optional `--older-than` age filter (`s`, `m`, `h`, `d`, `w`).
- `evalkit baseline`: stores a known-good snapshot (statuses, sample ratios, cost, latency - no
  response text) and refuses to store a failing run; `--allow-failures` records a failing baseline so
  a later fix shows up as `fixed`. `evalkit run` diffs against the baseline when present.
- Cost accounting from a per-model price table, with `--fail-on-cost` to exit `1` over budget and
  exit `2` when the budget cannot be honestly enforced.
- Reports: a rich terminal summary, `--json` (machine-readable), `--junit` (JUnit XML for CI
  test-report UIs, sanitized of characters XML 1.0 forbids), and `--html` (a single self-contained
  HTML summary with inline CSS and no external requests, escaped the same way and deterministic for
  a given run).
- CLI ergonomics: `-k` case filter, `--concurrency`, `--model` / `--judge-model` overrides,
  `--no-cache`, `--no-color` (and `NO_COLOR`), `--quiet` / `--verbose`, and a TTY progress line.
- Configuration resolved once with the precedence defaults < `evalkit.yaml` < environment < flags;
  the API key comes only from the environment and is never logged or persisted.
- Exit-code contract for CI: `0` all passed, `1` failures or over-budget, `2` config/suite/provider
  errors, `130` on Ctrl-C, with `2` beating `1` beating `0`.

[Unreleased]: https://github.com/thealirazadev/evalkit/commits/main
