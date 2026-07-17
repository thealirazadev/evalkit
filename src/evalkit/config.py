"""Resolve configuration: defaults < evalkit.yaml < env < flags.

Resolved once at startup into a frozen ``Config``. Inner modules read the resolved
values only; they never touch environment variables directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from evalkit.errors import ConfigError

DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_SUITES_GLOB = "evals/**/*.yaml"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0
DEFAULT_CONFIG_FILENAME = "evalkit.yaml"


@dataclass(frozen=True)
class Config:
    """Fully resolved run configuration. The API key is held here but never logged."""

    base_url: str | None
    api_key: str | None
    default_model: str | None
    cli_model: str | None
    judge_model: str | None
    concurrency: int
    timeout_seconds: int
    cache: bool
    suites_glob: str
    pricing: dict[str, dict[str, float]]
    no_color: bool
    config_path: Path | None

    def model_for(self, suite_model: str | None) -> str | None:
        """Effective case model: --model > suite model > env/config default."""
        return self.cli_model or suite_model or self.default_model


def _require_mapping(value: Any, path: Path, section: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"Invalid config {path}: '{section}' must be a mapping")
    return dict(value)


def _parse_pricing(raw: Any, path: Path) -> dict[str, dict[str, float]]:
    pricing_section = _require_mapping(raw, path, "pricing")
    pricing: dict[str, dict[str, float]] = {}
    for model, entry in pricing_section.items():
        if not isinstance(entry, Mapping) or "input" not in entry or "output" not in entry:
            raise ConfigError(
                f"Invalid config {path}: pricing for '{model}' needs 'input' and 'output'"
            )
        try:
            pricing[str(model)] = {
                "input": float(entry["input"]),
                "output": float(entry["output"]),
            }
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"Invalid config {path}: pricing for '{model}' must be numeric"
            ) from exc
    return pricing


def _load_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Invalid config {path}: {exc.strerror or exc}") from exc
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        reason = str(getattr(exc, "problem", None) or exc).splitlines()[0]
        raise ConfigError(f"Invalid config {path}: {reason}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ConfigError(f"Invalid config {path}: top level must be a mapping")
    return dict(loaded)


def _positive_int(value: Any, path: Path, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid config {path}: '{field_name}' must be an integer") from exc
    if parsed < 1:
        raise ConfigError(f"Invalid config {path}: '{field_name}' must be >= 1")
    return parsed


def load_config(
    *,
    config_path: str | None = None,
    cli_model: str | None = None,
    cli_judge_model: str | None = None,
    cli_no_cache: bool = False,
    cli_concurrency: int | None = None,
    cli_no_color: bool = False,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Config:
    """Resolve the effective ``Config`` from file, environment, and CLI flags."""
    env = env if env is not None else {}
    cwd = cwd or Path.cwd()

    explicit_path = config_path is not None
    path = Path(config_path) if config_path else cwd / DEFAULT_CONFIG_FILENAME

    file_data: dict[str, Any] = {}
    resolved_path: Path | None = None
    if path.exists():
        file_data = _load_file(path)
        resolved_path = path
    elif explicit_path:
        raise ConfigError(f"Invalid config {path}: file not found")

    provider = _require_mapping(file_data.get("provider"), path, "provider")
    judge = _require_mapping(file_data.get("judge"), path, "judge")
    run = _require_mapping(file_data.get("run"), path, "run")
    pricing = _parse_pricing(file_data.get("pricing"), path)

    file_base_url = provider.get("base_url")
    file_provider_model = provider.get("model")
    file_judge_model = judge.get("model")

    base_url = env.get("EVALKIT_BASE_URL") or file_base_url
    api_key = env.get("EVALKIT_API_KEY")
    default_model = env.get("EVALKIT_MODEL") or file_provider_model
    judge_model = (
        cli_judge_model
        or env.get("EVALKIT_JUDGE_MODEL")
        or file_judge_model
        or file_provider_model
        or default_model
    )

    if cli_concurrency is not None:
        concurrency = _positive_int(cli_concurrency, path, "concurrency")
    elif "concurrency" in run:
        concurrency = _positive_int(run["concurrency"], path, "run.concurrency")
    else:
        concurrency = DEFAULT_CONCURRENCY

    timeout_seconds = (
        _positive_int(run["timeout_seconds"], path, "run.timeout_seconds")
        if "timeout_seconds" in run
        else DEFAULT_TIMEOUT_SECONDS
    )

    file_cache = bool(run.get("cache", True))
    cache = file_cache and not cli_no_cache

    suites_glob = file_data.get("suites") or DEFAULT_SUITES_GLOB
    if not isinstance(suites_glob, str):
        raise ConfigError(f"Invalid config {path}: 'suites' must be a string glob")

    no_color = bool(cli_no_color or env.get("NO_COLOR"))

    return Config(
        base_url=base_url,
        api_key=api_key,
        default_model=default_model,
        cli_model=cli_model,
        judge_model=judge_model,
        concurrency=concurrency,
        timeout_seconds=timeout_seconds,
        cache=cache,
        suites_glob=suites_glob,
        pricing=pricing,
        no_color=no_color,
        config_path=resolved_path,
    )
