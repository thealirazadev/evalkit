"""stderr logging setup; quiet/verbose levels; structured fields.

Logging always goes to stderr so machine-readable stdout stays clean. Default level is
WARNING; ``--verbose`` raises it to DEBUG, ``--quiet`` lowers it to ERROR. The API key is
never logged; only ``--verbose`` reveals per-case structured detail.
"""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "evalkit"


def configure_logging(*, quiet: bool = False, verbose: bool = False) -> logging.Logger:
    """Configure the evalkit logger to stderr at the level implied by the flags."""
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    else:
        level = logging.WARNING

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
