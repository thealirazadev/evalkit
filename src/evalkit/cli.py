"""click command group with run/baseline subcommands and top-level error handling.

Inner modules raise typed ``EvalkitError``; this module catches them exactly once, prints
one friendly line to stderr, and exits with the mapped code. Raw tracebacks never print by
default. No interactive prompts exist on any path.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from evalkit import __version__
from evalkit.baseline import diff_against_baseline, load_baseline, write_baseline
from evalkit.cache import clear_cache, parse_duration
from evalkit.config import Config, load_config
from evalkit.errors import ConfigError, EvalkitError, SuiteError
from evalkit.logging_setup import LOGGER_NAME, configure_logging
from evalkit.provider import build_client
from evalkit.report_json import write_json_report
from evalkit.report_junit import write_junit_report
from evalkit.report_terminal import ProgressLine, print_liveness, render_report
from evalkit.runner import RunResult, exit_code, run_suites
from evalkit.suite import Suite, discover_suites, load_suite

logger = logging.getLogger(LOGGER_NAME)

CACHE_SUBDIR = Path(".evalkit") / "cache"
BASELINE_DEFAULT = ".evalkit/baseline.json"


def _stderr_console() -> Console:
    return Console(stderr=True, no_color=bool(os.environ.get("NO_COLOR")))


def _fail(message: str) -> None:
    # soft_wrap keeps the one-line message intact for CI log grepping.
    _stderr_console().print(message, style="red", soft_wrap=True)


def _fmt_money(value: float) -> str:
    """Format a USD amount, keeping small budgets legible (e.g. 0.000001, not 0.0000)."""
    text = f"{value:.6f}".rstrip("0")
    return text + "00" if text.endswith(".") else text


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


def _resolve_config(
    config_path: str | None,
    model: str | None,
    judge_model: str | None,
    no_cache: bool,
    no_color: bool,
    cwd: Path,
    concurrency: int | None = None,
    quiet: bool = False,
    verbose: bool = False,
) -> Config:
    load_dotenv()
    configure_logging(quiet=quiet, verbose=verbose)
    return load_config(
        config_path=config_path,
        cli_model=model,
        cli_judge_model=judge_model,
        cli_no_cache=no_cache,
        cli_no_color=no_color,
        cli_concurrency=concurrency,
        env=os.environ,
        cwd=cwd,
    )


def _load_suites(config: Config, suites: tuple[str, ...], cwd: Path) -> list[Suite]:
    paths = discover_suites(list(suites), config.suites_glob, cwd)
    return [load_suite(path, cwd=cwd) for path in paths]


def _filter_suites(loaded: list[Suite], pattern: str) -> list[Suite]:
    """Keep only cases whose ``suite/case`` key contains ``pattern`` (plain substring)."""
    filtered = []
    for suite in loaded:
        cases = tuple(c for c in suite.cases if pattern in f"{suite.name}/{c.name}")
        if cases:
            filtered.append(replace(suite, cases=cases))
    if not filtered:
        raise SuiteError(f"No cases match '-k {pattern}'.")
    return filtered


def _require_provider(config: Config) -> None:
    if not config.api_key:
        raise ConfigError("API key missing or invalid. Set EVALKIT_API_KEY.")
    if not config.base_url:
        raise ConfigError(
            "No provider base URL. Set EVALKIT_BASE_URL or provider.base_url in evalkit.yaml."
        )


def _execute(
    config: Config, loaded: list[Suite], cwd: Path, *, quiet: bool = False
) -> tuple[RunResult, Console]:
    console = Console(no_color=config.no_color)
    total = sum(len(s.cases) for s in loaded)
    print_liveness(console, total, quiet=quiet)  # off-TTY plain line (inert on a TTY)
    show_progress = console.is_terminal and not quiet
    client = build_client(config.base_url, config.api_key, config.timeout_seconds)
    try:
        with ProgressLine(console, total, enabled=show_progress) as progress:
            result = run_suites(
                loaded,
                config,
                client,
                cwd / CACHE_SUBDIR,
                progress=progress.update if show_progress else None,
            )
    finally:
        client.close()
    return result, console


def _run_impl(
    suites: tuple[str, ...],
    config_path: str | None,
    model: str | None,
    judge_model: str | None,
    no_cache: bool,
    no_color: bool,
    concurrency: int | None,
    pattern: str | None,
    quiet: bool,
    verbose: bool,
    json_path: str | None,
    junit_path: str | None,
    fail_on_cost: float | None,
    baseline_path: str,
) -> int:
    quiet = quiet and not verbose  # more information wins
    cwd = Path.cwd()
    config = _resolve_config(
        config_path, model, judge_model, no_cache, no_color, cwd, concurrency, quiet, verbose
    )
    loaded = _load_suites(config, suites, cwd)
    if pattern:
        loaded = _filter_suites(loaded, pattern)
    _require_provider(config)
    result, console = _execute(config, loaded, cwd, quiet=quiet)

    baseline = load_baseline(baseline_path)
    diff = diff_against_baseline(baseline, result, baseline_path) if baseline else None
    render_report(console, result, baseline=baseline, diff=diff, quiet=quiet)
    if json_path:
        write_json_report(result, config, json_path, diff)
    if junit_path:
        write_junit_report(result, junit_path)

    code = exit_code(result)
    if fail_on_cost is not None:
        if not result.totals.cost_known:
            reason = result.totals.partial_reason or "cost is partial"
            raise ConfigError(f"Cannot enforce --fail-on-cost: {reason}")
        total = result.totals.cost_usd + result.totals.judge_cost_usd
        if total > fail_on_cost:
            _fail(
                f"Error: Cost budget exceeded: ${_fmt_money(total)} > ${_fmt_money(fail_on_cost)}"
            )
            code = max(code, 1)
    return code


def _baseline_impl(
    suites: tuple[str, ...],
    config_path: str | None,
    model: str | None,
    judge_model: str | None,
    no_cache: bool,
    no_color: bool,
    concurrency: int | None,
    quiet: bool,
    verbose: bool,
    baseline_path: str,
) -> int:
    quiet = quiet and not verbose
    cwd = Path.cwd()
    config = _resolve_config(
        config_path, model, judge_model, no_cache, no_color, cwd, concurrency, quiet, verbose
    )
    loaded = _load_suites(config, suites, cwd)
    _require_provider(config)
    result, console = _execute(config, loaded, cwd, quiet=quiet)
    render_report(console, result, quiet=quiet)

    code = exit_code(result)
    if code != 0:
        failing = result.totals.failed + result.totals.errors
        _fail(f"Error: Baseline not stored: {failing} case(s) failing.")
        return code
    write_baseline(result, config, baseline_path)
    console.print(f"Baseline stored to {baseline_path} ({result.totals.cases} cases).")
    return 0


@click.group()
@click.version_option(__version__, prog_name="evalkit")
def cli() -> None:
    """evalkit: a command-line prompt regression tester."""


@cli.command()
@click.argument("suites", nargs=-1)
@click.option("--config", "config_path", type=click.Path(), default=None, help="Config file path.")
@click.option("--model", default=None, help="Override the case model.")
@click.option("--judge-model", "judge_model", default=None, help="Override the judge model.")
@click.option("--no-cache", is_flag=True, default=False, help="Skip cache reads (still writes).")
@click.option("--no-color", is_flag=True, default=False, help="Disable ANSI color output.")
@click.option("--concurrency", type=int, default=None, help="Worker pool size (default 4).")
@click.option("-k", "pattern", default=None, help="Run only cases whose suite/case key matches.")
@click.option("--json", "json_path", type=click.Path(), default=None, help="Write JSON report.")
@click.option("--junit", "junit_path", type=click.Path(), default=None, help="Write JUnit XML.")
@click.option(
    "--fail-on-cost",
    type=float,
    default=None,
    help="Exit 1 if total run cost (USD, incl. judge) exceeds this budget.",
)
@click.option("--quiet", "-q", is_flag=True, default=False, help="Failures and summary only.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Debug logs on stderr.")
@click.option(
    "--baseline",
    "baseline_path",
    type=click.Path(),
    default=BASELINE_DEFAULT,
    help="Baseline file to diff against when it exists.",
)
def run(
    suites: tuple[str, ...],
    config_path: str | None,
    model: str | None,
    judge_model: str | None,
    no_cache: bool,
    no_color: bool,
    concurrency: int | None,
    pattern: str | None,
    quiet: bool,
    verbose: bool,
    json_path: str | None,
    junit_path: str | None,
    fail_on_cost: float | None,
    baseline_path: str,
) -> None:
    """Run suites and report pass/fail with cost and latency."""
    code = _boundary(
        lambda: _run_impl(
            suites,
            config_path,
            model,
            judge_model,
            no_cache,
            no_color,
            concurrency,
            pattern,
            quiet,
            verbose,
            json_path,
            junit_path,
            fail_on_cost,
            baseline_path,
        )
    )
    raise SystemExit(code)


@cli.command()
@click.argument("suites", nargs=-1)
@click.option("--config", "config_path", type=click.Path(), default=None, help="Config file path.")
@click.option("--model", default=None, help="Override the case model.")
@click.option("--judge-model", "judge_model", default=None, help="Override the judge model.")
@click.option("--no-cache", is_flag=True, default=False, help="Skip cache reads (still writes).")
@click.option("--no-color", is_flag=True, default=False, help="Disable ANSI color output.")
@click.option("--concurrency", type=int, default=None, help="Worker pool size (default 4).")
@click.option("--quiet", "-q", is_flag=True, default=False, help="Failures and summary only.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Debug logs on stderr.")
@click.option(
    "--baseline",
    "baseline_path",
    type=click.Path(),
    default=BASELINE_DEFAULT,
    help="Where to write the baseline snapshot.",
)
def baseline(
    suites: tuple[str, ...],
    config_path: str | None,
    model: str | None,
    judge_model: str | None,
    no_cache: bool,
    no_color: bool,
    concurrency: int | None,
    quiet: bool,
    verbose: bool,
    baseline_path: str,
) -> None:
    """Store a passing run as the baseline snapshot; refuse if any case fails."""
    code = _boundary(
        lambda: _baseline_impl(
            suites,
            config_path,
            model,
            judge_model,
            no_cache,
            no_color,
            concurrency,
            quiet,
            verbose,
            baseline_path,
        )
    )
    raise SystemExit(code)


def _cache_clear_impl(older_than: str | None) -> int:
    seconds: int | None = None
    if older_than is not None:
        try:
            seconds = parse_duration(older_than)
        except ValueError as exc:
            raise ConfigError(f"Invalid --older-than '{older_than}': {exc}") from exc
    removed = clear_cache(Path.cwd() / CACHE_SUBDIR, seconds)
    console = Console(no_color=bool(os.environ.get("NO_COLOR")))
    noun = "entry" if removed == 1 else "entries"
    console.print(f"Removed {removed} cache {noun}.")
    return 0


@cli.group("cache")
def cache_cmd() -> None:
    """Manage the on-disk response cache."""


@cache_cmd.command("clear")
@click.option(
    "--older-than",
    "older_than",
    default=None,
    help="Only remove entries older than this age (e.g. 7d, 12h, 30m).",
)
def cache_clear(older_than: str | None) -> None:
    """Remove cached provider responses under .evalkit/cache/."""
    code = _boundary(lambda: _cache_clear_impl(older_than))
    raise SystemExit(code)


def main() -> None:
    """Console entry point."""
    cli()


if __name__ == "__main__":
    main()
