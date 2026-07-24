---
name: Feature request
about: Suggest a capability for evalkit
title: "feat: "
labels: enhancement
assignees: ""
---

## Problem

The concrete testing problem you are trying to solve. What can you not express or verify today with
evalkit's existing assertions, reporters, config, and flags?

## Proposed solution

What you would like evalkit to do. If it is a new assertion type, describe its fields and its
pass/fail rule and failure message. If it is a new reporter or flag, describe the output or behavior.

## Alternatives considered

Other ways to get the same result, including whether an existing assertion or an external step could
cover it.

## Scope check

evalkit stays deliberately small and dependency-light, and abstractions wait for the rule of three
(three real use cases). To help judge the fit:

- Does this need a new dependency? (Additions are avoided and require discussion.)
- Does it keep the provider to one chat-completions shape, with no provider SDK?
- Would it change an exit code, the JSON report schema, or another documented contract? If so, say so
  explicitly.
