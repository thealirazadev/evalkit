"""Suite discovery, YAML load, validation, and {{variable}} rendering.

A suite is one YAML document: a prompt template plus a list of cases, each carrying
variable values and assertions. Validation is strict and happens before any provider
call, so a bad suite fails fast with a one-line, file-named message (exit 2).
"""

from __future__ import annotations

import glob as globlib
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from evalkit.errors import SuiteError

KNOWN_ASSERTIONS = frozenset(
    {
        "contains",
        "not_contains",
        "regex",
        "equals",
        "json_valid",
        "json_schema",
        "max_length",
        "judge",
    }
)

# A template variable: {{ name }} where name is a Python-identifier-like token.
VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

_SCALAR_TYPES = (str, int, float, bool)


@dataclass(frozen=True)
class Assertion:
    """A single assertion. Only the fields relevant to ``type`` are populated."""

    type: str
    value: Any = None
    pattern: str | None = None
    compiled: re.Pattern[str] | None = None
    schema: dict[str, Any] | None = None
    rubric: str | None = None


@dataclass(frozen=True)
class Case:
    """One test case: variable values plus the assertions its response must satisfy."""

    name: str
    vars: dict[str, Any]
    assertions: tuple[Assertion, ...]
    samples: int = 1
    threshold: float = 1.0


@dataclass(frozen=True)
class Suite:
    """A loaded, validated suite ready to run."""

    name: str
    file: str
    description: str | None
    model: str | None
    params: dict[str, Any]
    system_template: str | None
    prompt_template: str
    cases: tuple[Case, ...]


def discover_suites(paths: Sequence[str], glob: str, cwd: Path) -> list[Path]:
    """Resolve suite file paths from explicit args or the config glob (deterministic order)."""
    found: list[Path] = []
    if paths:
        for raw in paths:
            path = Path(raw)
            if not path.is_absolute():
                path = cwd / path
            if path.is_dir():
                for pattern in ("*.yaml", "*.yml"):
                    found.extend(path.rglob(pattern))
            elif path.is_file():
                found.append(path)
            else:
                raise SuiteError(f"Suite path not found: {raw}")
    else:
        pattern = str(cwd / glob)
        found = [Path(m) for m in globlib.glob(pattern, recursive=True) if Path(m).is_file()]

    unique = sorted({p.resolve() for p in found})
    if not unique:
        raise SuiteError("No suite files found. Pass paths or set 'suites' in evalkit.yaml.")
    return unique


def _display_path(path: Path, cwd: Path) -> str:
    try:
        return os.path.relpath(path, cwd)
    except ValueError:
        return str(path)


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else text


def _read_yaml(path: Path, file: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SuiteError(f"Invalid suite {file}: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        reason = _first_line(str(getattr(exc, "problem", None) or exc))
        raise SuiteError(f"Invalid suite {file}: {reason}") from exc
    if data is None:
        raise SuiteError(f"Invalid suite {file}: file is empty")
    if not isinstance(data, Mapping):
        raise SuiteError(f"Invalid suite {file}: top level must be a mapping")
    return dict(data)


def _require_str(value: Any, file: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SuiteError(f"Invalid suite {file}: '{field_name}' must be a non-empty string")
    return value


def _parse_assertion(raw: Any, file: str, case_name: str) -> Assertion:
    where = f'case "{case_name}"'
    if not isinstance(raw, Mapping) or "type" not in raw:
        raise SuiteError(f"Invalid suite {file}: {where}: each assertion needs a 'type'")
    atype = raw["type"]
    if atype not in KNOWN_ASSERTIONS:
        raise SuiteError(f'Invalid suite {file}: {where}: unknown assertion type "{atype}"')

    if atype in ("contains", "not_contains", "equals"):
        if "value" not in raw:
            raise SuiteError(f"Invalid suite {file}: {where}: {atype} requires 'value'")
        return Assertion(type=atype, value=str(raw["value"]))

    if atype == "regex":
        if "pattern" not in raw:
            raise SuiteError(f"Invalid suite {file}: {where}: regex requires 'pattern'")
        pattern = raw["pattern"]
        if not isinstance(pattern, str):
            raise SuiteError(f"Invalid suite {file}: {where}: regex 'pattern' must be a string")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise SuiteError(
                f"Invalid suite {file}: {where}: invalid regex '{pattern}': {exc}"
            ) from exc
        return Assertion(type=atype, pattern=pattern, compiled=compiled)

    if atype == "json_valid":
        return Assertion(type=atype)

    if atype == "json_schema":
        schema = raw.get("schema")
        if not isinstance(schema, Mapping):
            raise SuiteError(f"Invalid suite {file}: {where}: json_schema requires a 'schema' map")
        return Assertion(type=atype, schema=dict(schema))

    if atype == "max_length":
        value = raw.get("value")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SuiteError(
                f"Invalid suite {file}: {where}: max_length 'value' must be a non-negative integer"
            )
        return Assertion(type=atype, value=value)

    # judge
    rubric = raw.get("rubric")
    if not isinstance(rubric, str) or not rubric.strip():
        raise SuiteError(f"Invalid suite {file}: {where}: judge requires a non-empty 'rubric'")
    return Assertion(type=atype, rubric=rubric)


def _parse_case(raw: Any, file: str, seen: set[str]) -> Case:
    if not isinstance(raw, Mapping):
        raise SuiteError(f"Invalid suite {file}: each case must be a mapping")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SuiteError(f"Invalid suite {file}: a case is missing 'name'")
    if name in seen:
        raise SuiteError(f'Invalid suite {file}: duplicate case name "{name}"')
    seen.add(name)

    where = f'case "{name}"'
    variables = raw.get("vars") or {}
    if not isinstance(variables, Mapping):
        raise SuiteError(f"Invalid suite {file}: {where}: 'vars' must be a mapping")
    for key, val in variables.items():
        if not isinstance(val, _SCALAR_TYPES):
            raise SuiteError(
                f"Invalid suite {file}: {where}: var '{key}' must be a string, number, or bool"
            )

    asserts_raw = raw.get("assert")
    if not isinstance(asserts_raw, Sequence) or isinstance(asserts_raw, str) or not asserts_raw:
        raise SuiteError(f"Invalid suite {file}: {where}: 'assert' must be a non-empty list")
    assertions = tuple(_parse_assertion(a, file, name) for a in asserts_raw)

    samples = raw.get("samples", 1)
    if not isinstance(samples, int) or isinstance(samples, bool):
        raise SuiteError(f"Invalid suite {file}: {where}: 'samples' must be an integer")
    threshold = raw.get("threshold", 1.0)
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        raise SuiteError(f"Invalid suite {file}: {where}: 'threshold' must be a number")

    return Case(
        name=name,
        vars=dict(variables),
        assertions=assertions,
        samples=samples,
        threshold=float(threshold),
    )


def load_suite(path: Path, cwd: Path | None = None) -> Suite:
    """Load and validate one suite file, returning a ready-to-run ``Suite``."""
    cwd = cwd or Path.cwd()
    file = _display_path(path, cwd)
    data = _read_yaml(path, file)

    name = _require_str(data.get("suite"), file, "suite")
    prompt = _require_str(data.get("prompt"), file, "prompt")

    description = data.get("description")
    if description is not None and not isinstance(description, str):
        raise SuiteError(f"Invalid suite {file}: 'description' must be a string")

    model = data.get("model")
    if model is not None and not isinstance(model, str):
        raise SuiteError(f"Invalid suite {file}: 'model' must be a string")

    system = data.get("system")
    if system is not None and not isinstance(system, str):
        raise SuiteError(f"Invalid suite {file}: 'system' must be a string")

    params = data.get("params") or {}
    if not isinstance(params, Mapping):
        raise SuiteError(f"Invalid suite {file}: 'params' must be a mapping")

    cases_raw = data.get("cases")
    if not isinstance(cases_raw, Sequence) or isinstance(cases_raw, str) or not cases_raw:
        raise SuiteError(f"Invalid suite {file}: 'cases' must be a non-empty list")

    seen: set[str] = set()
    cases = tuple(_parse_case(c, file, seen) for c in cases_raw)

    suite = Suite(
        name=name,
        file=file,
        description=description,
        model=model,
        params=dict(params),
        system_template=system,
        prompt_template=prompt,
        cases=cases,
    )

    # Render every case now so an undefined {{variable}} fails validation before any call.
    for case in cases:
        render_case(suite, case)
    return suite


def referenced_variables(template: str) -> set[str]:
    """Return the set of {{variable}} names referenced in a template."""
    return set(VARIABLE_RE.findall(template))


def render_template(
    template: str, variables: Mapping[str, Any], *, file: str, case_name: str
) -> str:
    """Substitute {{name}} tokens from ``variables``; unknown names are a load-time error.

    Only ``{{name}}`` (optionally spaced) with an identifier-like name is a variable;
    anything else is left verbatim. Values render with ``str()``.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise SuiteError(f"Suite {file}, case {case_name}: undefined variable {{{{{name}}}}}")
        return str(variables[name])

    return VARIABLE_RE.sub(replace, template)


def render_case(suite: Suite, case: Case) -> tuple[str | None, str]:
    """Render (system, prompt) for a case, raising on any undefined variable."""
    system = (
        render_template(suite.system_template, case.vars, file=suite.file, case_name=case.name)
        if suite.system_template is not None
        else None
    )
    prompt = render_template(suite.prompt_template, case.vars, file=suite.file, case_name=case.name)
    return system, prompt
