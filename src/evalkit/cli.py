"""click command group with run/baseline subcommands and top-level error handling.

Inner modules raise typed ``EvalkitError``; this module catches them exactly once, prints
one friendly line to stderr, and exits with the mapped code. Raw tracebacks never print by
default. No interactive prompts exist on any path.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from evalkit import __version__
from evalkit.config import load_config
from evalkit.errors import ConfigError, EvalkitError
from evalkit.logging_setup import LOGGER_NAME, configure_logging
from evalkit.provider import build_client
from evalkit.report_json import write_json_report
from evalkit.report_junit import write_junit_report
from evalkit.report_terminal import render_report
from evalkit.runner import exit_code, run_suites
from evalkit.suite import discover_suites, load_suite

logger = logging.getLogger(LOGGER_NAME)

CACHE_SUBDIR = Path(".evalkit") / "cache"


def _stderr_console() -> Console:
    return Console(stderr=True, no_color=bool(os.environ.get("NO_COLOR")))


def _fail(message: str) -> None:
    # soft_wrap keeps the one-line message intact for CI log grepping.
    _stderr_console().print(message, style="red", soft_wrap=True)


def _boundary(work: Callable[[], int]) -> int:
    """Run a command body, translating exceptions into friendly messages and exit codes."""
    try:
        return work()
    except EvalkitError as exc:
        logger.debug("error detail: %s", exc.detail)
        _fail(f"Error: {exc.message}")
        return exc.exit_code
    except KeyboardInterrupt:
        _fail("Aborted.")
        return 130
    except Exception:  # noqa: BLE001 - last-resort guard; detail only under --verbose
        logger.debug("unexpected error", exc_info=True)
        _fail("Error: Unexpected error. Re-run with --verbose for details.")
        return 1


def _run_impl(
    suites: tuple[str, ...],
    config_path: str | None,
    model: str | None,
    no_cache: bool,
    no_color: bool,
    json_path: str | None,
    junit_path: str | None,
) -> int:
    load_dotenv()
    configure_logging()
    cwd = Path.cwd()
    config = load_config(
        config_path=config_path,
        cli_model=model,
        cli_no_cache=no_cache,
        cli_no_color=no_color,
        env=os.environ,
        cwd=cwd,
    )
    suite_paths = discover_suites(list(suites), config.suites_glob, cwd)
    loaded = [load_suite(path, cwd=cwd) for path in suite_paths]

    if not config.api_key:
        raise ConfigError("API key missing or invalid. Set EVALKIT_API_KEY.")
    if not config.base_url:
        raise ConfigError(
            "No provider base URL. Set EVALKIT_BASE_URL or provider.base_url in evalkit.yaml."
        )

    console = Console(no_color=config.no_color)
    client = build_client(config.base_url, config.api_key, config.timeout_seconds)
    try:
        result = run_suites(loaded, config, client, cwd / CACHE_SUBDIR)
    finally:
        client.close()
    render_report(console, result)
    if json_path:
        write_json_report(result, config, json_path)
    if junit_path:
        write_junit_report(result, junit_path)
    return exit_code(result)


@click.group()
@click.version_option(__version__, prog_name="evalkit")
def cli() -> None:
    """evalkit: a command-line prompt regression tester."""


@cli.command()
@click.argument("suites", nargs=-1)
@click.option("--config", "config_path", type=click.Path(), default=None, help="Config file path.")
@click.option("--model", default=None, help="Override the case model.")
@click.option("--no-cache", is_flag=True, default=False, help="Skip cache reads (still writes).")
@click.option("--no-color", is_flag=True, default=False, help="Disable ANSI color output.")
@click.option("--json", "json_path", type=click.Path(), default=None, help="Write JSON report.")
@click.option("--junit", "junit_path", type=click.Path(), default=None, help="Write JUnit XML.")
def run(
    suites: tuple[str, ...],
    config_path: str | None,
    model: str | None,
    no_cache: bool,
    no_color: bool,
    json_path: str | None,
    junit_path: str | None,
) -> None:
    """Run suites and report pass/fail with cost and latency."""
    code = _boundary(
        lambda: _run_impl(suites, config_path, model, no_cache, no_color, json_path, junit_path)
    )
    raise SystemExit(code)


@cli.command()
def baseline() -> None:
    """Store a passing run as the baseline snapshot (implemented in a later phase)."""
    _fail("Error: baseline is not implemented yet.")
    raise SystemExit(2)


def main() -> None:
    """Console entry point."""
    cli()


if __name__ == "__main__":
    main()
