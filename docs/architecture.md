# Architecture — evalkit

evalkit is a single-process CLI. It loads YAML suites, renders each case, obtains a response for it
(from the disk cache or the LLM provider API), evaluates assertions, and reports. State on disk is
limited to the cache, the baseline snapshot, and any report files the user asks for.

## Flow

```
evalkit run [SUITES...]
        |
        v
[config.py]  resolve config: defaults < evalkit.yaml < env < flags
        |            bad config / missing key --------> friendly error, exit 2
        v
[suite.py]   discover + load + validate suites, render {{variables}}
        |            bad YAML / unknown assertion /
        |            undefined variable --------------> friendly error, exit 2
        v
[runner.py]  for each case, for each sample 1..k:
        |
        |    [cache.py]  hit? --> reuse stored response (unless --no-cache)
        |    [provider.py]  miss --> POST chat completion, measure latency,
        |            capture token usage; 429/5xx/timeout: retry w/ backoff;
        |            auth failure -> abort run, exit 2
        |
        |    [assertions.py]  deterministic checks
        |    [judge.py]       judge assertion -> second provider call
        |                     (judge model), verdict {pass, reason}
        |
        v
[cost.py]    tokens x price table -> per-case and per-run USD
        |
        v
[baseline.py]  if baseline file exists: diff statuses, cost, latency
        |
        v
[report_terminal.py]  always      [report_json.py]  --json PATH
[report_junit.py]     --junit PATH
        |
        v
exit code: 2 if any case errored or config/provider failed
           1 if any case failed or --fail-on-cost exceeded
           0 otherwise
```

`evalkit baseline` runs the same pipeline, then writes `.evalkit/baseline.json` — but only when
every case passed; otherwise it refuses (exit 1) and writes nothing.

## Proposed folder / file tree

```
evalkit/
  README.md
  pyproject.toml            packaging, pinned deps, [project.scripts] evalkit = "evalkit.cli:main"
  uv.lock                   committed lockfile
  .env.example
  .gitignore                ignores .env and .evalkit/cache/ (baseline.json stays committable)
  docs/                     this documentation set
  src/
    evalkit/
      __init__.py           __version__ defined here
      __main__.py           enables `python -m evalkit`
      cli.py                click group with run/baseline subcommands; top-level error handling
      config.py             Config frozen dataclass; evalkit.yaml + env + flag resolution
      suite.py              suite discovery, YAML load, validation, {{variable}} rendering
      assertions.py         the seven deterministic assertion implementations
      judge.py              judge prompt build, verdict parsing, judge-model resolution
      provider.py           httpx wrapper: one chat call, retries, error mapping, usage capture
      cache.py              disk cache under .evalkit/cache/: key hash, read, write
      runner.py             per-case execution, N-sample logic, worker pool, result assembly
      cost.py               price table lookup, per-case and per-run USD totals
      baseline.py           snapshot write/load, diff against the current run
      report_terminal.py    rich output: per-suite tables, summary block, baseline section
      report_json.py        JSON report writer (schema below)
      report_junit.py       JUnit XML writer (stdlib xml.etree)
      errors.py             EvalkitError hierarchy carrying (message, exit_code, detail)
      logging_setup.py      stderr logging; quiet/verbose levels; structured fields
  tests/
    conftest.py             fixtures: httpx MockTransport provider, tmp cache dir, sample suites
    fixtures/
      checkout.yaml         a representative suite reused across tests
      pricing.yaml          a config file with a price table
    test_config.py
    test_suite.py
    test_assertions.py
    test_judge.py
    test_provider.py
    test_cache.py
    test_runner.py
    test_cost.py
    test_baseline.py
    test_reports.py
    test_cli.py             end-to-end via click CliRunner, provider mocked
```

`src/` layout for the same reason as the other CLIs in this portfolio: tests import the installed
package, which catches packaging mistakes early.

## Tech stack with rationale

- **Python 3.12+** — the other CLIs here target 3.10+, but evalkit is a developer/CI tool where
  current interpreters are the norm; 3.12 keeps typing modern and drops every back-compat shim
  (the 3.10 `tomllib` gap already bit a sibling project). Documented deviation, not an accident.
- **click** — same CLI library as the sibling CLIs: mature, small surface, native subcommand
  groups (`run`, `baseline`), and `CliRunner` for end-to-end tests.
- **rich** — tables and summary output through a single `Console`; handles `NO_COLOR` and non-TTY
  detection so CI logs stay plain.
- **httpx** — direct HTTP client for the provider call. There is no provider SDK dependency
  because evalkit targets one neutral API shape (below) at a configurable base URL; a hand-rolled
  SDK-alike would be speculative. Timeouts and connection pooling are built in, and
  `httpx.MockTransport` makes tests airtight without a mocking library.
- **PyYAML** — suites and config are YAML; `yaml.safe_load` only.
- **jsonschema** — implements the `json_schema` assertion correctly (draft 2020-12) instead of a
  hand-rolled validator.
- **python-dotenv** — loads a local `.env` for development convenience, matching the sibling
  projects. CI sets real environment variables.
- **pytest**, **ruff**, **black** — same test and lint toolchain as the rest of the portfolio.

Suggested starting pins (verify each on PyPI at install time; exact versions are pinned in
`pyproject.toml` and the committed `uv.lock`): `click==8.1.*`, `rich==13.9.*`, `httpx==0.28.*`,
`PyYAML==6.0.*`, `jsonschema==4.23.*`, `python-dotenv==1.2.*`; dev `pytest==9.*`, `ruff`, `black`.
The `python-dotenv` and `pytest` floors were raised from `1.0.*` and `8.*` by security advisories
GHSA-mf9w-mj56-hr94 and GHSA-6w46-j5rx-g56g; `pyproject.toml` and `uv.lock` remain authoritative.

## Suite file mini-spec

A suite is one YAML document. Reference example:

```yaml
suite: checkout-support            # required; unique per run; [a-z0-9-] recommended
description: Support-bot answers   # optional, shown in reports
model: example-model-1             # optional; beats the configured default (--model beats both)
params:                            # optional; passed through to the provider request
  temperature: 0                   # default 0 (deterministic + cache-friendly)
  max_tokens: 512                  # default 1024
system: |                          # optional system message; templated like prompt
  You are a support agent for {{product}}.
prompt: |                          # required user message template
  Customer message: {{message}}
  Reply with JSON: {"reply": "...", "escalate": true|false}
cases:
  - name: refund-request           # required; unique within the suite
    vars:                          # values for every {{variable}} used above
      product: Acme Store
      message: I want a refund for order 1234.
    assert:                        # required, non-empty; ALL must pass
      - type: json_valid
      - type: contains
        value: refund
      - type: judge
        rubric: >
          The reply acknowledges the refund request and does not promise a
          refund outcome.
    samples: 3                     # optional; run the case k times (default 1)
    threshold: 0.67                # optional; fraction of samples that must pass (default 1.0)
```

### Templating

- A variable is `{{name}}` (whitespace inside the braces is tolerated: `{{ name }}`), where `name`
  matches `[A-Za-z_][A-Za-z0-9_]*`. Anything else is left verbatim — there are no conditionals,
  loops, or filters. This is deliberately not a template language.
- Every variable referenced in `system` or `prompt` must be defined in the case's `vars`, or the
  suite fails validation (exit 2) before any provider call. Unused vars are allowed (a `--verbose`
  note, not an error).
- Var values must be scalars (string, number, bool); numbers and bools are rendered with `str()`.
  Lists and mappings are a validation error in v1.

### Assertions

All assertions run against the response text (the provider message content). All assertions on a
case must pass for the sample to pass. Order in the file is the order of evaluation and reporting.

| type          | fields    | passes when                                                            |
| ------------- | --------- | ---------------------------------------------------------------------- |
| `contains`    | `value`   | `value` occurs in the response (case-sensitive; use regex `(?i)` for case-insensitive) |
| `not_contains`| `value`   | `value` does not occur in the response                                  |
| `regex`       | `pattern` | `re.search(pattern, response)` matches (Python syntax; invalid pattern is a load-time error) |
| `equals`      | `value`   | the response, stripped of leading/trailing whitespace, equals `value` exactly |
| `json_valid`  | —         | the stripped response parses with `json.loads` (no code-fence extraction in v1) |
| `json_schema` | `schema`  | response parses as JSON and validates against the inline schema (implies `json_valid`) |
| `max_length`  | `value`   | `len(response) <= value` (characters)                                   |
| `judge`       | `rubric`  | the judge model returns `pass: true` for the response against the rubric |

The `judge` assertion is the only non-deterministic one and is kept visibly separate: reports label
it `judge`, its failure message is the judge's own `reason` text, and its cost is accounted under a
separate judge total. Every other assertion is pure string/JSON logic with no network access.

### N-sample semantics

`samples: k` (k >= 1) runs the case k times; each sample gets its own provider call (and its own
cache entry, keyed with the sample index). A sample passes when all its assertions pass. The case
passes when `passed_samples / k >= threshold` (threshold in (0, 1], default 1.0). Reports always
show the raw ratio (`2/3`) next to the outcome. Case cost is the sum over samples; case latency is
the mean over fresh (non-cached) samples.

## Provider API

One endpoint shape in v1 — the widely deployed chat-completions JSON shape — so any hosted or local
server exposing it works by setting the base URL. A second shape waits for the rule of three.

```
POST {EVALKIT_BASE_URL}/chat/completions
Authorization: Bearer {EVALKIT_API_KEY}
Content-Type: application/json

{
  "model": "example-model-1",
  "messages": [
    {"role": "system", "content": "..."},     # omitted when the suite has no system template
    {"role": "user", "content": "..."}
  ],
  "temperature": 0,
  "max_tokens": 1024                          # plus any other suite params, passed through
}
```

Expected response fields (anything extra is ignored):

```json
{
  "choices": [{"message": {"content": "response text"}}],
  "usage": {"prompt_tokens": 123, "completion_tokens": 45}
}
```

Error policy, implemented once in `provider.py`:

- 401/403 — abort the whole run immediately: `API key missing or invalid. Set EVALKIT_API_KEY.`,
  exit 2.
- 429, 5xx, timeouts, connection errors — retry up to 3 attempts total with exponential backoff
  (honor `Retry-After` when present). If still failing, the case gets status `error` with the
  reason; any errored case makes the run exit 2.
- A 2xx response missing `choices[0].message.content` — case status `error` (malformed response).
- Missing `usage` — the response still evaluates, but tokens/cost show `n/a` for that case and the
  run's cost is marked partial.

Judge calls go through the same client and policy with the judge model, `temperature: 0`, and a
fixed internal prompt that presents the rubric and the response and demands a JSON verdict
`{"pass": true|false, "reason": "..."}`. An unparseable verdict is retried once with a
JSON-only nudge; if still unparseable, the case is an `error` (infrastructure problem), not a
`fail` (prompt problem).

## Caching

- Location: `.evalkit/cache/<hh>/<hash>.json` under the working directory, where `hash` is the
  SHA-256 hex of the canonical JSON of `{base_url, model, system, prompt, params, sample}`
  (rendered text, params sorted by key) and `<hh>` its first two characters. `base_url` is part of
  the identity because the same model id served by two endpoints can return different responses;
  keying without it would let one endpoint silently serve another's cached result.
- Entry contents: `{version: 1, response_text, prompt_tokens, completion_tokens, latency_ms,
  created_at, model}`.
- Read path: on a hit, the stored response is used with zero provider calls; the case is marked
  `cached`, contributes $0 to run spend, and reuses the stored latency for baseline comparison
  display only.
- `--no-cache` skips reads but still writes, so the next run benefits from fresh entries.
- Judge calls are cached with the same mechanism (the judge prompt embeds the response and rubric,
  so the key changes whenever either does).
- Invalidation is purely key-based; there is no TTL. Clearing the cache is `rm -rf .evalkit/cache`
  — no subcommand for it in v1.
- The cache stores provider responses in plaintext; `.evalkit/cache/` is gitignored and must stay
  that way (see `docs/rules.md` — Security).

## Baseline snapshot

`evalkit baseline` writes `.evalkit/baseline.json` (path overridable with `--baseline`). Unlike the
cache, this file is meant to be committed — the diff is only useful in CI if the snapshot travels
with the repo, which is why `.gitignore` covers `.evalkit/cache/` and not the whole directory.

```json
{
  "version": 1,
  "created_at": "2026-07-18T10:00:00Z",
  "evalkit_version": "0.1.0",
  "model": "example-model-1",
  "cases": {
    "checkout-support/refund-request": {
      "status": "pass", "samples": 3, "samples_passed": 3,
      "cost_usd": 0.0021, "latency_ms": 812
    }
  },
  "totals": {"cases": 14, "cost_usd": 0.0312, "mean_latency_ms": 840}
}
```

On every `evalkit run`, if the baseline file exists it is loaded and the report gains a baseline
section: regressions (baseline pass, now fail), fixed (baseline fail, now pass — reachable only if
a future flag permits storing failing baselines), new and removed case keys, and total cost / mean
latency deltas. The diff never changes the exit code by itself; a regressed case is already a
failure.

## Reports

Terminal output is specified in `docs/design.md`. The two file reporters:

### JSON report (`--json PATH`)

```json
{
  "evalkit_version": "0.1.0",
  "started_at": "2026-07-18T10:00:00Z",
  "duration_ms": 6400,
  "config": {"model": "example-model-1", "judge_model": "example-judge-1",
             "concurrency": 4, "cache": true},
  "totals": {"cases": 12, "passed": 11, "failed": 1, "errors": 0,
             "cost_usd": 0.0123, "judge_cost_usd": 0.0040, "cost_known": true,
             "prompt_tokens": 8412, "completion_tokens": 2306, "cache_hits": 9},
  "baseline": {
    "path": ".evalkit/baseline.json",
    "regressions": ["checkout-support/refund-request"],
    "fixed": [], "new": [], "removed": [],
    "cost_delta_usd": -0.0014, "mean_latency_delta_ms": 280
  },
  "suites": [
    {"name": "checkout-support", "file": "evals/checkout.yaml",
     "cases": [
       {"name": "refund-request", "status": "fail",
        "samples": 3, "samples_passed": 2, "threshold": 0.67,
        "latency_ms": 812, "cached": false,
        "prompt_tokens": 640, "completion_tokens": 120, "cost_usd": 0.0021,
        "failures": [
          {"assertion": "contains", "message": "contains: \"refund\" not found in response"},
          {"assertion": "judge", "message": "reply promises a refund outcome; rubric forbids it"}
        ]}
     ]}
  ]
}
```

`baseline` is `null` when no baseline file exists. `cost_known` is false whenever any executed
model lacks a pricing entry or a response lacked `usage`.

### JUnit XML (`--junit PATH`)

- One `<testsuite>` per suite (`name`, `tests`, `failures`, `errors`, `time`), wrapped in
  `<testsuites>` with run totals.
- One `<testcase>` per case: `classname` = suite name, `name` = case name, `time` = latency in
  seconds.
- A failed case gets `<failure message="first assertion message">` whose text body lists every
  failed assertion message (judge reasons verbatim) plus the first 300 characters of the response.
- An errored case gets `<error>` with the provider/judge error reason.

## Configuration

Resolved once at startup into a frozen `Config` dataclass. Precedence: built-in defaults <
`evalkit.yaml` < environment < CLI flags.

`evalkit.yaml` (in the working directory; `--config` overrides the path; the file is optional if
env supplies the provider settings):

```yaml
provider:
  base_url: https://api.example.com/v1
  model: example-model-1
judge:
  model: example-judge-1        # default: provider.model
run:
  concurrency: 4
  timeout_seconds: 60           # per HTTP request
  cache: true
suites: evals/**/*.yaml         # default suite glob when no paths are given
pricing:                        # USD per 1M tokens, per model id
  example-model-1: {input: 3.00, output: 15.00}
  example-judge-1: {input: 0.50, output: 1.50}
```

Cost is computed only from this table; there is no price discovery. A model absent from the table
yields `n/a` cost for its cases, a warning, `cost_known: false` in the JSON report — and exit 2 if
`--fail-on-cost` was requested, because the budget cannot be enforced honestly.

## Where state lives

- **In memory:** the resolved `Config`, loaded suites, and the run result tree that all three
  reporters consume.
- **Disk, gitignored:** `.evalkit/cache/` (response cache) and `.env` (local secrets).
- **Disk, committable:** `.evalkit/baseline.json`, suite files under `evals/`, `evalkit.yaml`,
  and any `--json` / `--junit` report files (typically CI artifacts, not committed).
- **Never stored:** the API key. It is read from the environment, sent only as the Bearer header,
  and never logged or written.

## External dependencies and required environment variables

External systems: the LLM provider API at the configured base URL — the only network dependency,
used for case responses and judge verdicts.

| Variable             | Required | Purpose                                                             |
| -------------------- | -------- | ------------------------------------------------------------------- |
| `EVALKIT_API_KEY`    | Yes      | Bearer token for the provider API. Never logged or persisted.       |
| `EVALKIT_BASE_URL`   | No       | Provider base URL; overrides `provider.base_url` in `evalkit.yaml`. |
| `EVALKIT_MODEL`      | No       | Default model id; overrides `provider.model`. `--model` beats both. |
| `EVALKIT_JUDGE_MODEL`| No       | Judge model id; overrides `judge.model`. `--judge-model` beats both.|
| `NO_COLOR`           | No       | If set (any value), disables ANSI color output.                     |

A `.env` in the working directory is loaded via python-dotenv for local development; CI should set
real environment variables. `.env.example` documents all of the above with dummy values.
