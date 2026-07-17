"""Typed error hierarchy. Raised by inner modules, caught once in cli.py."""

from __future__ import annotations


class EvalkitError(Exception):
    """Expected, user-facing failure carrying a friendly message and an exit code."""

    exit_code = 1

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ConfigError(EvalkitError):
    """Bad config file, missing provider settings, or missing API key."""

    exit_code = 2


class SuiteError(EvalkitError):
    """Suite discovery, YAML, or validation failure."""

    exit_code = 2


class ProviderError(EvalkitError):
    """Provider auth failure or other run-aborting provider problem."""

    exit_code = 2


class ReportError(EvalkitError):
    """A report file could not be written."""

    exit_code = 2


class BudgetError(EvalkitError):
    """A cost budget was exceeded or cannot be enforced."""

    exit_code = 1


class BaselineError(EvalkitError):
    """The baseline snapshot file is corrupt or a version we cannot read."""

    exit_code = 2
