# evalkit

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

## Test

```sh
uv run pytest                 # full suite, provider mocked, zero network
uv run ruff check .
uv run black --check .
```

## License

MIT — see [LICENSE](LICENSE).
