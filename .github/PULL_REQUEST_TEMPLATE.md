## Summary

What this change does and why. Link any related issue (`Closes #123`).

## Type of change

- [ ] Bug fix (`fix:`)
- [ ] New feature (`feat:`)
- [ ] Docs only (`docs:`)
- [ ] Refactor / internal (`refactor:`, `chore:`, `test:`, `ci:`)

## Checklist

- [ ] The local gate passes, all four steps green:
  - [ ] `uv run ruff check .`
  - [ ] `uv run black --check .`
  - [ ] `uv run pytest`
  - [ ] `uv build`
- [ ] Behavior changes are covered by a test that fails before the change and passes after.
- [ ] Tests use the mocked transport only — no real network call and no API key required.
- [ ] Commits follow Conventional Commits, one discrete change each, no attribution trailers.
- [ ] No new dependency (or it was discussed first, and `pyproject.toml` + `uv.lock` change together
      in their own commit).
- [ ] Docs updated where behavior changed: `README.md` and a `CHANGELOG.md` entry under
      `Unreleased`. Any change to `docs/PRD.md` or `docs/architecture.md` is flagged, not silent.
- [ ] No API key, real prompt data, or vendor/model name added to code, output, or docs.

## Notes for reviewers

Anything worth calling out: exit-code implications, JSON/JUnit report schema changes, or trade-offs
you want a second opinion on.
