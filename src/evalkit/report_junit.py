"""JUnit XML report writer (stdlib xml.etree).

One ``<testsuite>`` per suite wrapped in ``<testsuites>`` with run totals; one
``<testcase>`` per case with ``time`` from latency. Failed cases carry a ``<failure>``
whose body lists every failed assertion message (judge reasons verbatim) plus a response
excerpt; errored cases carry an ``<error>`` with the mapped reason.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from evalkit.errors import ReportError
from evalkit.runner import CaseResult, RunResult

RESPONSE_EXCERPT_CHARS = 300

# Characters XML 1.0 forbids: control chars other than tab/newline/return, plus a few
# permanently-invalid code points. Judge reasons and response excerpts are model output
# and may contain them; left raw they yield XML no standard consumer can parse.
_INVALID_XML_CHARS = re.compile("[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]")


def _xml_safe(text: str) -> str:
    """Drop characters XML 1.0 forbids so the report always parses (ET escapes the rest)."""
    return _INVALID_XML_CHARS.sub("", text)


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def _add_case(parent: ET.Element, suite_name: str, case: CaseResult) -> None:
    testcase = ET.SubElement(
        parent,
        "testcase",
        {"classname": suite_name, "name": case.name, "time": _seconds(case.latency_ms)},
    )
    if case.status == "fail":
        messages = [_xml_safe(f.message) for f in case.failures]
        failure = ET.SubElement(
            testcase, "failure", {"message": messages[0] if messages else "assertion failed"}
        )
        body = list(messages)
        if case.response_excerpt:
            body.append(f"\nresponse (first {RESPONSE_EXCERPT_CHARS} chars):")
            body.append(_xml_safe(case.response_excerpt[:RESPONSE_EXCERPT_CHARS]))
        failure.text = "\n".join(body)
    elif case.status == "error":
        reason = _xml_safe(case.error or "error")
        error = ET.SubElement(testcase, "error", {"message": reason})
        error.text = reason


def build_junit(run: RunResult) -> ET.Element:
    """Build the JUnit ``<testsuites>`` element tree for a run."""
    totals = run.totals
    root = ET.Element(
        "testsuites",
        {
            "tests": str(totals.cases),
            "failures": str(totals.failed),
            "errors": str(totals.errors),
            "time": _seconds(run.duration_ms),
        },
    )
    for suite in run.suites:
        failures = sum(c.status == "fail" for c in suite.cases)
        errors = sum(c.status == "error" for c in suite.cases)
        suite_time = sum(c.latency_ms for c in suite.cases)
        testsuite = ET.SubElement(
            root,
            "testsuite",
            {
                "name": suite.name,
                "tests": str(len(suite.cases)),
                "failures": str(failures),
                "errors": str(errors),
                "time": _seconds(suite_time),
            },
        )
        for case in suite.cases:
            _add_case(testsuite, suite.name, case)
    return root


def write_junit_report(run: RunResult, path: str) -> None:
    """Write the JUnit XML report to ``path``; an I/O failure is a ReportError (exit 2)."""
    root = build_junit(run)
    ET.indent(root)
    xml = ET.tostring(root, encoding="unicode")
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('<?xml version="1.0" encoding="utf-8"?>\n' + xml + "\n", encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"Cannot write report {path}: {exc.strerror or exc}") from exc
