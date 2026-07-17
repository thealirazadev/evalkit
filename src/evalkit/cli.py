"""click command group with run/baseline subcommands and top-level error handling."""

import click

from evalkit import __version__


@click.group()
@click.version_option(__version__, prog_name="evalkit")
def cli() -> None:
    """evalkit: a command-line prompt regression tester."""


@cli.command()
def run() -> None:
    """Run suites and report results."""
    raise click.ClickException("run is not implemented yet")


@cli.command()
def baseline() -> None:
    """Store a passing run as the baseline snapshot."""
    raise click.ClickException("baseline is not implemented yet")


def main() -> None:
    """Console entry point."""
    cli()


if __name__ == "__main__":
    main()
