# PRD — evalkit

## What we're building

evalkit is a command-line prompt regression tester. A developer keeps YAML suites next to their
code: each suite defines a prompt template with `{{variables}}` and a list of test cases, where each
case supplies variable values and a list of assertions. `evalkit run` renders every case, sends it
to the configured LLM provider API, evaluates the assertions, and prints pass/fail with cost and
latency per case and per run. Responses are cached on disk so re-runs are cheap and deterministic.
`evalkit baseline` stores a passing run; later runs diff against it and report which cases flipped
and how cost and latency moved. Exit codes, a JSON report, and JUnit XML make it usable in CI
without wrappers.

## Target user

Developers who ship LLM-backed features and treat prompts as code: prompts live in the repo, change
in pull requests, and need tests like any other code path. They want to know, before merging, that a
prompt edit or a model change did not break the cases they care about — and what it costs. They are
comfortable in a terminal, keep an API key in their environment, and run checks in CI where exit
codes and machine-readable reports matter more than pretty output.

## Core features (prioritized)

### P0 — the tool is useless without these

1. **YAML suite format.** Load suite files, validate them with precise error messages (bad YAML,
   unknown assertion type, undefined template variable), and render the prompt template with each
   case's variables. The format is a documented mini-spec (see `docs/architecture.md`).
2. **Provider call.** Send each rendered case to the LLM provider API (one chat-completions-shaped
   endpoint; base URL, model, and key from env/config). Handle auth, network, rate-limit, and
   server errors with retries where appropriate and friendly messages otherwise.
3. **Deterministic assertions.** `contains`, `not_contains`, `regex`, `equals`, `json_valid`,
   `json_schema`, `max_length`. All assertions on a case must pass; each failure carries a specific
   message.
4. **Response caching.** Cache responses on disk under `.evalkit/cache/`, keyed by a hash of
   (model, rendered prompt, params, sample index). Re-running an unchanged suite makes zero
   provider calls. `--no-cache` bypasses cache reads.
5. **Cost and latency accounting.** Token usage from the provider response times a per-model price
   table from config yields per-case and per-run cost in USD; latency is measured per call. Both
   appear in the terminal summary and in every report format.
6. **CI exit codes.** 0 all cases passed; 1 one or more cases failed (including a blown cost
   budget); 2 config, usage, or provider error. No interactive prompts anywhere.

### P1 — what makes it a regression tester rather than a script

7. **LLM-as-judge assertion.** A `judge` assertion holds rubric text; a separately configurable
   judge model returns pass/fail plus a reason, and the reason is surfaced in the terminal output
   and reports. Judge cost is counted and broken out from the total.
8. **N-sample mode.** A case can run `samples: k` times with a pass `threshold` (fraction of
   samples that must pass). This is the honest way to test non-deterministic prompts at
   temperature above zero.
9. **JSON report.** `--json PATH` writes a machine-readable run report with per-case status,
   failures, cost, latency, and cache info (schema in `docs/architecture.md`).
10. **JUnit XML report.** `--junit PATH` writes JUnit XML so CI systems render results natively.
11. **Cost budget.** `--fail-on-cost USD` fails the run (exit 1) when total run cost exceeds the
    budget, even if every assertion passed.
12. **Baseline snapshot and diff.** `evalkit baseline` stores a passing run to
    `.evalkit/baseline.json`. Subsequent `evalkit run` invocations diff against it: cases that
    flipped, new/removed cases, and cost/latency deltas.

### P2 — polish

13. **Concurrency.** Run cases through a bounded worker pool (default 4) so suites finish quickly
    without hammering the provider.
14. **Case filter.** `-k PATTERN` runs only cases whose `suite/case` name contains the pattern.
15. **Output controls.** `--quiet`, `--verbose` (structured logs on stderr), `NO_COLOR` /
    `--no-color`, progress display on a TTY.

## Non-goals

- No hosted dashboard, web UI, or server component. Terminal and report files only.
- No multi-provider adapter matrix in v1. One provider API shape (the common chat-completions JSON
  shape), pointed at any compatible endpoint via the base URL. Abstraction waits for the rule of
  three.
- No prompt auto-optimization, rewriting, or suggestion features. evalkit judges outputs; it does
  not edit prompts.
- No dataset generation or synthetic test-case creation.
- No multi-turn conversation cases in v1: one rendered prompt, one response, per sample.
- No streaming responses; assertions need the complete text, so requests are non-streaming.
- No assertion plugin system. The built-in assertion set is the v1 surface.
- No secret storage. The API key lives in the environment; evalkit never writes it anywhere.

## Success criteria per core feature

1. **Suite format** — A documented example suite loads without warnings. A file with bad YAML, an
   unknown assertion type, a case missing `name`, or a `{{variable}}` not defined in the case's
   `vars` each produce a distinct one-line error naming the file (and case where relevant), exit
   code 2, and no provider calls.
2. **Provider call** — With the provider mocked, a rendered case produces exactly one HTTP request
   with the documented shape (model, messages, params) and a Bearer key header. 401/403 abort the
   run with exit 2 and a message naming `EVALKIT_API_KEY`. 429/5xx/timeouts retry up to 3 attempts
   with backoff, then mark the case as an error; any errored case makes the run exit 2. The key
   never appears in output or logs.
3. **Deterministic assertions** — Each of the seven assertion types has unit tests covering pass
   and fail; failure messages name the assertion and the reason (e.g. `contains: "refund" not found
   in response`). A case passes only when every assertion passes.
4. **Caching** — Running the same suite twice makes zero provider calls on the second run
   (asserted via the mock) and produces identical results. `--no-cache` forces fresh calls and
   overwrites the cached entries. Changing the model, prompt text, a variable value, or any param
   changes the cache key and forces a fresh call.
5. **Cost/latency** — For a mocked response with known token usage and a configured price table,
   the per-case cost equals the hand-computed value to four decimal places; the run summary total
   equals the sum of cases plus judge calls. A model missing from the price table shows `n/a` cost
   with a warning and marks the run's cost as partial in the JSON report.
6. **Exit codes** — All-pass run exits 0; a run with an assertion failure exits 1; bad flags, bad
   config, invalid suite, and provider auth failure each exit 2. Errors take precedence over
   failures. Verified end-to-end in CLI tests.
7. **Judge** — With a mocked judge returning `{"pass": false, "reason": "..."}`, the case fails
   and the reason appears verbatim in terminal output, JSON, and JUnit failure text. The judge
   model resolves separately from the case model. An unparseable judge verdict (after one retry)
   marks the case as an error, not a failure.
8. **N-sample** — A case with `samples: 3, threshold: 0.67` passes with 2 of 3 passing samples and
   fails with 1 of 3; the report shows `2/3` explicitly. Each sample has its own cache entry, so a
   cached N-sample case replays identically.
9. **JSON report** — `--json out.json` writes a file matching the documented schema; a CI script
   can read totals, per-case status, failures, cost, and latency without parsing terminal output.
10. **JUnit XML** — `--junit out.xml` produces XML that a standard JUnit consumer accepts: one
    testsuite per suite, one testcase per case, `time` set from latency, failures carrying
    assertion messages and judge reasons.
11. **Budget** — With a total cost above the `--fail-on-cost` value, the run exits 1 and prints the
    budget and actual cost. If a model in the run has no pricing entry while the flag is set, the
    run exits 2 (budget cannot be enforced honestly).
12. **Baseline** — `evalkit baseline` on a fully passing run writes the snapshot; on a run with
    failures it refuses with exit 1 and writes nothing. A later `evalkit run` with an introduced
    failure lists that case under regressions and shows cost/latency deltas against the snapshot.
13. **Concurrency** — With concurrency 4 and 8 slow mocked cases, wall time is roughly half the
    serial time and never more than 4 requests are in flight (asserted via the mock).
14. **Filter** — `-k checkout` runs only matching cases; the summary counts reflect the filtered
    set. `-k` combined with `evalkit baseline` is a usage error (exit 2).
15. **Output controls** — With `NO_COLOR` set or stdout not a TTY, output contains no ANSI escape
    codes and no progress animation. `--quiet` prints only failures and the summary; `--verbose`
    adds structured logs on stderr and never prints the key.
