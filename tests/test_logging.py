"""Logging level selection from quiet/verbose flags."""

import logging
import sys

from evalkit.logging_setup import configure_logging


def test_default_level_is_warning():
    assert configure_logging().level == logging.WARNING


def test_verbose_is_debug():
    assert configure_logging(verbose=True).level == logging.DEBUG


def test_quiet_is_error():
    assert configure_logging(quiet=True).level == logging.ERROR


def test_verbose_wins_over_quiet():
    assert configure_logging(quiet=True, verbose=True).level == logging.DEBUG


def test_logs_go_to_stderr():
    logger = configure_logging()
    assert logger.handlers
    assert logger.handlers[0].stream is sys.stderr
    assert logger.propagate is False
