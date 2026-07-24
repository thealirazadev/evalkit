---
name: Bug report
about: Something in evalkit behaves incorrectly
title: "bug: "
labels: bug
assignees: ""
---

## What happened

A clear description of the incorrect behavior.

## What you expected

What you expected instead, including the **exit code** you expected. evalkit's exit codes are the
CI contract: `0` all passed, `1` a failure or a blown `--fail-on-cost` budget, `2` a
config/usage/suite/provider error, `130` Ctrl-C.

## Steps to reproduce

The exact command you ran:

```sh
evalkit run ...
```

A minimal suite or config that triggers it (redact any real prompt data — **never paste a real API
key**):

```yaml
suite: repro
prompt: ...
cases:
  - name: ...
    assert:
      - type: ...
```

## Output

The terminal output (or the relevant part of `--json` / `--junit`). Re-run with `--verbose` and
include the structured logs if the problem is in a provider call or the runner. The API key is never
logged, so `--verbose` output is safe to paste.

## Environment

- evalkit version (`evalkit --version`):
- Python version (`python --version`):
- OS:
- Installed with (`uv sync --extra dev`, `pip install -e ".[dev]"`, or a published wheel):

## Notes

Anything else that helps, e.g. whether it reproduces with `--no-cache`, or only against a live
endpoint versus the mocked transport.
