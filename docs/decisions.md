# Design decisions

## 1. One provider shape, one HTTP module

evalkit speaks the common chat-completions JSON shape at a configurable base URL, so any compatible
hosted or local endpoint works without an SDK or an adapter registry. A second shape waits until
three real cases show what actually varies. All HTTP goes through `httpx` inside `provider.py`; no
other module touches the network. That single seam is what lets every test inject an
`httpx.MockTransport` and assert on the exact requests sent. Requests are non-streaming because
assertions need the complete response text.

## 2. The cache key is the full request identity

A response is cached under a hash of the base URL, model, rendered system and user prompt, params,
and sample index. The base URL is included because the same model id at two endpoints can return
different responses, and without it one endpoint could silently serve the other's cached result.
Invalidation is purely key based, with no TTL: anything that can change the output changes the key.
Judge calls use the same mechanism, and their key embeds the response and the rubric. A corrupt or
unreadable entry is treated as a miss and refetched, because the cache is regenerable and should
never be the reason a run fails.

## 3. Cached cases still carry their modeled cost

Per-case cost is tokens times the configured price table, computed the same way for cached and
fresh samples. The run total is the sum of those modeled costs. Zeroing cached cases would make the
same suite report a different cost depending on cache state, which would break `--fail-on-cost`
and baseline cost deltas. Cache savings show up in the cache-hit count and wall time instead.

## 4. Sample ratios are rounded, thresholds are not

A case with `samples: k` passes when `round(passed / k, 2) >= threshold`. Rounding the ratio lets a
two-decimal threshold mean what it says: 2 of 3 (0.6667) meets `threshold: 0.67`. The threshold is
compared unrounded, because rounding both sides let a stricter bar such as 0.674 be met by 2 of 3.

## 5. A broken judge is an error, not a failing prompt

The `judge` assertion calls a separately resolved judge model at temperature 0 and expects
`{"pass": bool, "reason": str}`. If the verdict cannot be parsed, evalkit retries once with a
JSON-only instruction, then marks the case as an error (exit 2) rather than a failure (exit 1). A
judge that returns garbage says nothing about the prompt under test. The judge's reason is shown
verbatim in every report, and judge cost is tracked as its own total. That total counts every
attempt: a bug found in review kept only the last attempt's cost, so a retried verdict
under-reported spend and an errored judge reported none. The cache entry now stores the summed usage
of both attempts, so a cached replay models the same cost as the fresh run (decision 3).

## 6. Exit code 2 always wins

Exit 0 means every case ran and passed within budget. Exit 1 means a prompt regressed: an assertion
failed or the cost budget was exceeded. Exit 2 means the run cannot be trusted: bad config or suite,
auth failure, an errored case, or a usage error. Precedence is 2 over 1 over 0, so one errored case
is never hidden by surrounding passes. `--fail-on-cost` follows the same logic: when any executed
model has no price entry, the budget cannot be enforced honestly, so the run exits 2 instead of
guessing. An exceeded budget raises the exit code to at least 1 but never lowers an existing 2.

## 7. Validate everything before the first network call

Suite and config files are user input. They are parsed with `yaml.safe_load`, and every structural
problem is caught at load time: unknown assertion types, missing case names, non-scalar variables,
undefined `{{variables}}`, invalid regex patterns (compiled up front), and malformed JSON Schemas
(checked against the draft 2020-12 meta-schema). Before the schema check, a bad schema passed
validation and only failed when the assertion first ran, surfacing as an unexpected error. Now
every one of these is a one-line `SuiteError` with exit 2 and zero provider calls. The template
renderer is a small regex, not a template engine, because conditionals and loops are out of scope.

## 8. Typed errors with a single boundary

Inner modules raise subclasses of `EvalkitError`, each carrying a message, an exit code, and an
optional detail. Only `cli.py` catches them: it prints one friendly line to stderr, logs the detail
at debug level, and exits with the code. Raw tracebacks never print by default. Assertion failures
are deliberately not exceptions; a failing case is a normal outcome stored in the run result and
rendered by the reporters.

## 9. The baseline is committed and holds no response text

`evalkit baseline` writes `.evalkit/baseline.json`, which is meant to travel with the repository so
CI can diff against it. It stores statuses, sample ratios, tokens, cost, and latency, but no
response text, so it is safe to commit. By default it refuses to store a run with failing cases,
because a baseline that records a regression makes the next diff look clean. `--allow-failures`
stores such a run and exits 0, since recording the baseline is the command's job. A run with an
errored case is always refused (exit 2), because an error has no honest outcome to record.

## 10. On-disk formats are versioned

Cache entries and the baseline each carry a `version` field. A cache entry with the wrong version is
a miss. A baseline with the wrong version, or one that cannot be parsed, exits 2 with a hint to
recreate it. Neither file is ever silently misread after a format change.

## 11. Reports treat model output as hostile text

Model responses and judge reasons end up in report files that other tools parse. The JUnit writer
strips characters that XML 1.0 forbids, because a single control character in a judge reason or
response excerpt made the report unreadable to standard consumers. The HTML report reuses that same
stripper, so the two writers cannot drift, and then applies `html.escape` with quoting so markup in
model output renders as inert text. The HTML report is one self-contained file with inline CSS and
no external requests, so it opens offline as a CI artifact. It reads no clock or environment of its
own, so the same run result always produces the same document.

## 12. Age-based cache clearing uses file modification time

`evalkit cache clear --older-than 7d` compares each entry's file modification time, not the
`created_at` stored inside it. The filesystem already tracks that time, and parsing every entry's
JSON to find a timestamp would be slower for no gain.

## 13. The API key never leaves the environment

The key is read from `EVALKIT_API_KEY` or a local `.env`, sent only as the Bearer header, and never
logged, cached, or written to a report. A regression test asserts it never reaches verbose logs or
the JSON and JUnit reports. What leaves the machine is the rendered prompt, the suite params, and, for judge
assertions, the model's response inside the judge prompt. The response cache is plaintext and
gitignored, and should be treated with the same care as the prompts that produced it.

## 14. CI needs no secrets

Because the provider is always mocked, the test suite needs no credentials and no repository
secret. CI installs with `uv sync --locked --extra dev`: the dev tools live in an optional extra,
and `--locked` fails the job if `uv.lock` has drifted from `pyproject.toml` instead of silently
re-resolving. Checks against a real endpoint are run by hand and are described in
`docs/testing.md`.
