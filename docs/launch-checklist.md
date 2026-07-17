# Launch checklist — evalkit

Work top to bottom before the first public release. Leave items unchecked until genuinely done.

## Packaging and versioning

- [ ] Dependency versions pinned exactly (`==`) in `pyproject.toml`; lockfile committed and in
      sync.
- [ ] `__version__` defined once and matching the `pyproject.toml` version.
- [ ] Python floor (`>=3.12`) declared and correct.
- [ ] Entry point works after install: `pipx install .` then `evalkit --version` in a clean shell.
- [ ] Runnable both as `evalkit` and `python -m evalkit`.

## Functionality

- [ ] Happy path: a real suite runs against a real provider endpoint; report, cost, and latency
      look sane; exit 0.
- [ ] All seven deterministic assertions plus `judge` behave per the mini-spec.
- [ ] N-sample threshold arithmetic verified by hand on a real case.
- [ ] Cache: second run reports `cached` with zero provider calls; `--no-cache` refreshes.
- [ ] Baseline round trip: store, regress a case, see it under regressions with deltas.
- [ ] `--json` and `--junit` files accepted by a real CI system.

## Errors and robustness

- [ ] Every row of the failure table in `docs/rules.md` produces its message and exit code.
- [ ] Exit-code precedence (2 over 1 over 0) verified with a mixed run.
- [ ] `--fail-on-cost` over-budget and unenforceable-pricing paths both verified.
- [ ] No raw traceback on any default-mode failure path.
- [ ] Ctrl-C mid-run: `Aborted.`, exit 130, cache not corrupted.

## Output and accessibility

- [ ] `NO_COLOR`, `--no-color`, and piped stdout each produce zero ANSI escape codes.
- [ ] No meaning by color alone; `pass`/`FAIL`/`ERROR`/`Warning:` labels present.
- [ ] `--quiet` and `--verbose` behave per `docs/design.md`; verbose logs never contain the key.
- [ ] Summary always includes cost, tokens, cache hits, and wall time.

## Security

- [ ] Key read only from env/`.env`; never hardcoded, logged, cached, or written to reports.
- [ ] `.env` and `.evalkit/cache/` gitignored; `.env.example` current with dummy values.
- [ ] `baseline.json` confirmed to contain no response text.
- [ ] README documents exactly what is sent to the provider and what the cache stores on disk.

## Docs and help

- [ ] `evalkit run --help` and `evalkit baseline --help` list every flag accurately.
- [ ] README install/run/test sections replaced with real instructions (no TBD left).
- [ ] `docs/` matches shipped behavior; suite mini-spec verified against the implementation.
- [ ] LICENSE file present (MIT) and referenced.

## Quality gates

- [ ] `pytest` passes with the provider mocked and no network.
- [ ] `ruff check .` and `black --check .` pass.
- [ ] Manual QA checklists in `docs/phases.md` completed for all phases.

## Publish to PyPI

- [ ] `pyproject.toml` metadata complete: name, version, description, license, readme,
      requires-python, classifiers, URLs.
- [ ] Package name `evalkit` available on PyPI (or an alternative chosen and reflected
      everywhere, including the env-var prefix decision).
- [ ] `uv build` produces a clean sdist and wheel; `twine check dist/*` passes.
- [ ] Test install from TestPyPI in a clean environment; `evalkit --version` works.
- [ ] Tag the release matching `__version__` and publish; verify `pipx install evalkit` end to
      end.
