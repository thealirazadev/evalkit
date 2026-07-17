# evalkit

evalkit is a command-line tool for prompt regression testing. You keep YAML suites in your repo —
each one a prompt template plus test cases with variables and assertions — and `evalkit run` renders
every case, calls the configured LLM provider API, checks the assertions, and reports pass/fail with
per-case cost and latency. A stored baseline lets later runs diff against a known-good state, and
exit codes plus JSON/JUnit reports make it drop into CI without ceremony.

Status: planning — docs under review

## Planned stack

- Python 3.12+, packaged with `pyproject.toml` and a console entry point `evalkit`.
- [click](https://click.palletsprojects.com/) for the CLI (subcommands `run` and `baseline`).
- [rich](https://rich.readthedocs.io/) for terminal output; honors `NO_COLOR` and non-TTY.
- [httpx](https://www.python-httpx.org/) for calls to the LLM provider API (one chat-completions
  shape, base URL and key from env/config).
- [PyYAML](https://pyyaml.org/) for suite and config files; [jsonschema](https://pypi.org/project/jsonschema/)
  for the `json_schema` assertion.
- pytest for tests (the provider is mocked; no network in the suite), ruff + black for lint/format.

See `docs/PRD.md` for scope, `docs/architecture.md` for the design and the suite-file mini-spec,
and `docs/phases.md` for the build order.

## Install

TBD until implementation starts.

## Run

TBD until implementation starts.

## Test

TBD until implementation starts.
