# Security policy

## Supported versions

evalkit is pre-1.0. Security fixes land on the latest released minor version and on `main`.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |
| < 0.1   | No        |

## Reporting a vulnerability

Report privately through GitHub Security Advisories:
[Report a vulnerability](https://github.com/thealirazadev/evalkit/security/advisories/new).

Please do not open a public issue for a security problem, and do not include a real API key or any
real prompt data in the report — a redacted reproduction is enough.

Include where practical: the version or commit, the command and configuration that triggered it, a
minimal suite or config that reproduces it, and what you observed versus expected.

Expect an acknowledgement within 7 days and a status update within 30 days. Fixed issues are
credited in the advisory unless you ask otherwise.

## Threat model

evalkit is a local command-line tool. It has no server, no network listener, and no multi-user
surface: anyone who can run it with your key can already do everything it does. The security
boundary is what it reads, what it sends, and what it writes to disk.

**Credentials.** The provider API key is read from `EVALKIT_API_KEY` (or a local, gitignored
`.env`). It is sent only as a Bearer header. It is never logged at any verbosity, never written to
the cache, the baseline, or any report, and never persisted anywhere. A regression test asserts the
key is absent from verbose logs and from both report formats.

**What leaves the machine.** The rendered prompt (template plus case vars), suite params, and — for
`judge` assertions — the model's response embedded in the judge prompt. Nothing else: no file
contents, no environment, no repository metadata. Do not put secrets in suite vars; they would be
sent to the provider and stored in the cache.

**What lands on disk.** `.evalkit/cache/` holds provider responses in plaintext and is gitignored;
treat cached responses with the same sensitivity as the prompts that produced them. Clear it with
`rm -rf .evalkit/cache`. `.evalkit/baseline.json` stores only statuses, sample ratios, token counts,
cost, and latency — never response text — which is why it is safe to commit.

**Untrusted input.** Suite and config YAML are user input: they are parsed with `yaml.safe_load`
only and validated (structure, types, assertion fields, regex compilation) before any network call.
Provider and judge JSON are parsed defensively; missing or malformed fields are handled, never
assumed. Report text derived from model output is sanitized for the format it is written into.
evalkit never shells out — there is no `subprocess`, `os.system`, or `shell=True` anywhere.

## Scope

In scope: key disclosure, writing secrets to disk, code execution via a crafted suite or config
file, and cache or baseline poisoning that changes a run's verdict.

Out of scope: the security of the provider endpoint you configure, anything requiring an attacker
who already controls your machine or environment, and the content or quality of model responses.
