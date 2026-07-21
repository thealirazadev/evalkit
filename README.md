# evalkit

[![CI](https://github.com/thealirazadev/evalkit/actions/workflows/ci.yml/badge.svg)](https://github.com/thealirazadev/evalkit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

evalkit is a command-line tool for prompt regression testing. You keep YAML suites in your repo —
each one a prompt template plus test cases with variables and assertions — and `evalkit run` renders
every case, calls the configured LLM provider API, checks the assertions, and reports pass/fail with
per-case cost and latency. Responses are cached on disk so re-runs are cheap and deterministic. A
stored baseline lets later runs diff against a known-good state, and exit codes plus JSON/JUnit
reports make it drop into CI without ceremony.

## Stack

- Python 3.12+, packaged with `pyproject.toml` and a console entry point `evalkit`.
- [click](https://click.palletsprojects.com/) for the CLI (subcommands `run` and `baseline`).
- [rich](https://rich.readthedocs.io/) for terminal output; honors `NO_COLOR` and non-TTY.
- [httpx](https://www.python-httpx.org/) for the LLM provider API (one chat-completions shape,
  base URL and key from env/config).
- [PyYAML](https://pyyaml.org/) for suites and config; [jsonschema](https://pypi.org/project/jsonschema/)
  for the `json_schema` assertion.
- pytest for tests (the provider is mocked; no network in the suite), ruff + black for lint/format.

## Install

```sh
uv sync --extra dev          # or: pip install -e ".[dev]"
evalkit --version
```

## Configure

Point evalkit at any endpoint that speaks the common chat-completions JSON shape. Provider settings
come from `evalkit.yaml` and/or the environment; the API key only ever comes from the environment.

```sh
export EVALKIT_API_KEY=...            # required; sent as a Bearer token, never logged or stored
export EVALKIT_BASE_URL=https://...   # optional; overrides provider.base_url
```

See `evalkit.yaml` in this repo for a documented example (base URL, models, concurrency, timeout,
cache, suite glob, and a per-model price table). `.env.example` lists every environment variable;
copy it to `.env` for local development. Precedence is defaults < `evalkit.yaml` < environment <
CLI flags.

## Run

```sh
evalkit run                          # discover suites via the config glob (evals/**/*.yaml)
evalkit run evals/support-bot.yaml   # or pass files/directories explicitly
evalkit run -k refund                # only cases whose suite/case key contains "refund"
evalkit run --json out.json --junit out.xml
evalkit run --fail-on-cost 0.50      # exit 1 if the run costs more than $0.50
```

Exit codes (single source of truth for CI): `0` all cases passed; `1` one or more failed or the
cost budget was exceeded; `2` config/usage/suite/provider error (auth failure, any errored case,
unenforceable budget, bad flags); `130` Ctrl-C. Precedence: 2 beats 1 beats 0.

### Baseline

```sh
evalkit baseline                     # store the current (fully passing) run as the baseline
evalkit run                          # later runs diff against .evalkit/baseline.json
```

`evalkit baseline` writes `.evalkit/baseline.json` only when every case passes; otherwise it stores
nothing and exits non-zero. The snapshot holds statuses, sample ratios, cost, and latency — no
response text — so it is safe to commit. Subsequent runs report regressions, new/removed cases, and
cost/latency deltas.

## Suite format

A suite is one YAML document: a prompt template with `{{variables}}` and a list of cases. Each case
supplies `vars` and a non-empty list of `assert`ions; all assertions must pass for the case to pass.

```yaml
suite: support-bot
model: example-model-1            # optional; --model beats suite beats env/config
prompt: |
  Customer message: {{message}}
cases:
  - name: refund-request
    vars:
      message: I want a refund for order 1234.
    assert:
      - type: json_valid
      - type: contains
        value: reply
      - type: judge
        rubric: The reply must not promise a refund outcome.
    samples: 3                     # optional (default 1)
    threshold: 0.67                # optional fraction of samples that must pass (default 1.0)
```

Assertion types: `contains`, `not_contains`, `regex`, `equals`, `json_valid`, `json_schema`,
`max_length`, and `judge` (a separately configured judge model returns a pass/fail verdict with a
reason). The full mini-spec — templating rules, assertion fields, and N-sample semantics — lives in
[`docs/architecture.md`](docs/architecture.md).

## What leaves your machine, and what lands on disk

- **Sent to the provider:** the rendered prompt (template plus case vars), your suite params, and —
  for `judge` assertions — the model's response embedded in the judge prompt. Nothing else: no file
  contents, no environment, no repo metadata. Do not put secrets in suite vars.
- **On disk:** `.evalkit/cache/` stores provider responses in plaintext and is gitignored; treat
  cached responses with the same sensitivity as the prompts that produced them. `baseline.json`
  stores only statuses, token counts, cost, and latency, so it is safe to commit.
- **Never stored:** the API key. It is read from the environment, sent only as the Bearer header,
  and never logged or written.

## Design decisions

The trade-offs that shaped evalkit, and the alternatives they were chosen over.

- **Caching makes a non-deterministic system reproducible.** An LLM endpoint is not a pure
  function, yet a regression test has to be stable and cheap to re-run in CI. Responses are cached
  on disk keyed by a hash of the request identity — endpoint base URL, model, rendered
  system/prompt, params, and sample index — so an unchanged suite re-runs with zero provider calls
  and identical results. The base URL is part of the key on purpose: the same model id served by
  two endpoints can return different responses, and keying without it would let one endpoint
  silently serve another's cached result. Invalidation is purely key-based (no TTL): if anything
  that affects the output changes, the key changes and the call is fresh; otherwise the cache
  answers. Rejected: a time-based cache (a TTL either serves stale results or defeats the point of
  caching) and no cache at all (CI would be slow, costly, and flaky).

- **N-sample with a pass threshold, instead of a single call.** A prompt tested at temperature
  above zero is non-deterministic; a single sample makes a green/red test a coin flip. A case may
  set `samples: k` with a `threshold` (the fraction that must pass), which is the honest way to
  assert on a stochastic output. The measured pass ratio is rounded to two decimals so a threshold
  written to two decimals is met by its intended ratio (2/3 = 0.6667 satisfies `threshold: 0.67`),
  while the threshold itself is compared unrounded so a stricter bar is never met by a lower ratio.
  Rejected: asserting on one sample (flaky) and hiding the ratio (the report always shows `2/3`).

- **Judge assertions are quarantined from deterministic ones.** Every assertion except `judge` is
  pure string/JSON logic with no network access and a stable verdict. The `judge` assertion calls a
  second model, so it is kept visibly separate: reports label it `judge`, its failure message is
  the judge's own reason verbatim, and its cost is tracked under a separate judge total rather than
  folded into the model spend. An unparseable judge verdict (after one JSON-only retry) is an
  infrastructure error, not an assertion failure — a broken judge must not read as a failing prompt.
  Rejected: treating the judge like any other assertion (it would blur deterministic signal with a
  probabilistic one and hide where the money and the flakiness come from).

- **Exit 2 for infrastructure, exit 1 for regressions.** CI needs to tell "the harness or
  environment broke" apart from "a prompt regressed." So configuration, suite-validation, auth, and
  provider errors — anything that means the run could not be trusted — exit 2, while assertion
  failures and a blown cost budget exit 1, and a clean run exits 0. Precedence is 2 beats 1 beats 0,
  so a single errored case is never masked by surrounding passes. Rejected: collapsing every problem
  into one non-zero code (a missing API key would be indistinguishable from a genuine regression).

- **The baseline refuses to store a failing run.** A baseline is a known-good reference that later
  runs diff against; `evalkit baseline` writes it only when every case passes and otherwise refuses
  and writes nothing. Storing whatever happened to run would let a broken state quietly become the
  norm, so the next regression diffs clean. The snapshot holds only statuses, sample ratios, cost,
  and latency — no response text — so it is safe to commit and travels with the repo. Rejected:
  storing failing baselines (enshrines a regression) and a cache-like gitignored baseline (the diff
  is only useful in CI if the snapshot is versioned with the code).

- **One provider shape until the rule of three.** evalkit speaks a single widely deployed
  chat-completions JSON shape at a configurable base URL, with no provider SDK and no adapter
  registry. One real driver does not justify an abstraction; the seam for a second shape waits until
  three concrete cases exist and show what actually varies. Rejected: a speculative multi-provider
  adapter matrix in v1 (an abstraction guessed from one example is usually the wrong one).

## Benchmark

`scripts/benchmark.py` measures evalkit's own per-case overhead against a mocked transport that
returns a fixed response with zero latency. It isolates framework cost — render, dispatch,
assertion evaluation, accounting, and cache read/write — and the difference between the fresh-call
path and the cache-hit path.

**This is not a measure of network savings.** Against a real endpoint, wall-clock is dominated by
provider latency (often seconds per call), which the mock deliberately removes. What the table
shows is that evalkit's own overhead stays far below the cost of the call it wraps.

| run                 | total (500 cases) | per case | observed range   |
| ------------------- | ----------------- | -------- | ---------------- |
| uncached (all miss) | 223 ms            | 446 us   | 354–849 us/case  |
| cached (all hit)    | 52 ms             | 105 us   | 84–190 us/case   |

Cache-hit path is **4.2x faster** than the fresh-call path on identical work (observed 3.8x–4.5x
across nine invocations). The ratio is the stable figure; the absolute per-case numbers track
machine load and frequency scaling, so the observed range is given rather than a single best run.

Conditions: 500 cases, 2 deterministic assertions each, `concurrency: 1` so wall-clock divided by
case count is a clean per-case figure; 9 repetitions after a discarded warm-up, median per
invocation, then median across 9 invocations. Hardware: 12th Gen Intel Core i5-1235U (12 threads),
Linux 6.8.0 (glibc 2.39), CPython 3.12.13, x86_64, on an otherwise-active laptop. Reproduce with:

```sh
uv run python scripts/benchmark.py --cases 500 --reps 9
```

## Test

```sh
uv run pytest                 # full suite, provider mocked, zero network
uv run ruff check .
uv run black --check .
```

## License

MIT — see [LICENSE](LICENSE).
