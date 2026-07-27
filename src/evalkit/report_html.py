"""Self-contained HTML run-report writer.

Renders a single HTML document (inline CSS, no external requests) summarizing a run:
overall pass/fail, per-case status with assertion/judge reasons, cost and latency totals,
and the model/prompt metadata. Every interpolated value is escaped so control characters or
markup in model output can neither break the document nor inject into it, and the output is
deterministic for a given run (the reporter reads no wall clock and no environment).
"""

from __future__ import annotations

import html
from pathlib import Path

from evalkit import __version__
from evalkit.config import Config
from evalkit.errors import ReportError
from evalkit.report_junit import _xml_safe
from evalkit.runner import CaseResult, RunResult

RESPONSE_EXCERPT_CHARS = 300

_STATUS = {"pass": "pass", "fail": "fail", "error": "error"}

_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 2rem 1rem; background: #f5f5f7; color: #1d1d1f;
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 1.4rem; margin: 0; }
h2 { font-size: 1.05rem; margin: 1.75rem 0 0.5rem; }
.file { font-weight: normal; color: #6e6e73; font-size: 0.85rem; }
header { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1.5rem; }
.badge { font-weight: 700; letter-spacing: 0.03em; padding: 0.2rem 0.6rem; border-radius: 0.4rem;
  color: #fff; }
.badge.pass { background: #1a7f37; }
.badge.fail { background: #b3261e; }
dl.meta { display: grid; grid-template-columns: max-content 1fr; gap: 0.15rem 1rem; margin: 0; }
dl.meta dt { color: #6e6e73; }
dl.meta dd { margin: 0; font-variant-numeric: tabular-nums; }
.totals { margin: 1.25rem 0; padding: 0.75rem 1rem; background: #fff; border-radius: 0.5rem;
  border: 1px solid #e0e0e5; }
.totals span { margin-right: 1.25rem; font-variant-numeric: tabular-nums; }
.count.pass { color: #1a7f37; } .count.fail { color: #b3261e; }
table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e0e0e5;
  border-radius: 0.5rem; overflow: hidden; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-top: 1px solid #eee; }
th { background: #fafafa; color: #6e6e73; font-weight: 600; font-size: 0.8rem;
  text-transform: uppercase; letter-spacing: 0.03em; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.st { font-weight: 700; }
.st.pass { color: #1a7f37; } .st.fail, .st.error { color: #b3261e; }
tr.detail td { border-top: none; padding-top: 0; }
ul.reasons { margin: 0 0 0.35rem; padding-left: 1.1rem; color: #b3261e; }
pre.excerpt { margin: 0; padding: 0.5rem 0.6rem; background: #f5f5f7; border-radius: 0.4rem;
  font-size: 0.85rem; white-space: pre-wrap; word-break: break-word; color: #444; }
footer { margin-top: 2rem; color: #6e6e73; font-size: 0.8rem; }
@media (prefers-color-scheme: dark) {
  body { background: #1c1c1e; color: #f2f2f7; }
  .file, dl.meta dt, th, footer { color: #98989d; }
  .totals, table { background: #2c2c2e; border-color: #3a3a3c; }
  th { background: #262628; }
  th, td { border-top-color: #3a3a3c; }
  pre.excerpt { background: #1c1c1e; color: #c7c7cc; }
}
"""


def _safe(text: str) -> str:
    """Sanitize a value for HTML: strip characters XML/HTML forbid (the same discipline the
    JUnit reporter applies), then escape the markup-special characters. Model output can then
    neither break the document with control characters nor inject markup with ``<``/``&``/quotes.
    """
    return html.escape(_xml_safe(text), quote=True)


def _fmt_cost(cost: float | None) -> str:
    return f"${cost:.4f}" if cost is not None else "n/a"


def _fmt_latency(ms: int) -> str:
    return f"{ms / 1000:.1f}s"


def _overall(run: RunResult) -> tuple[str, str]:
    ok = run.totals.failed == 0 and run.totals.errors == 0
    return ("PASS", "pass") if ok else ("FAIL", "fail")


def _meta_rows(run: RunResult, config: Config) -> list[tuple[str, str]]:
    return [
        ("evalkit", __version__),
        ("model", config.model_for(None) or "n/a"),
        ("judge model", config.judge_model or "n/a"),
        ("concurrency", str(config.concurrency)),
        ("cache", "on" if config.cache else "off"),
        ("started", run.started_at),
        ("duration", _fmt_latency(run.duration_ms)),
    ]


def _totals_block(run: RunResult) -> list[str]:
    t = run.totals
    out = ['<div class="totals">']
    out.append(f"<span>cases: {t.cases}</span>")
    out.append(f'<span class="count pass">passed: {t.passed}</span>')
    fail_cls = "count fail" if t.failed else "count"
    out.append(f'<span class="{fail_cls}">failed: {t.failed}</span>')
    err_cls = "count fail" if t.errors else "count"
    out.append(f'<span class="{err_cls}">errors: {t.errors}</span>')
    cost = f"cost: ${t.cost_usd:.4f}"
    if not t.cost_known and t.partial_reason:
        cost += f" (partial: {_safe(t.partial_reason)})"
    elif t.judge_cost_usd > 0:
        cost += f" (judge: ${t.judge_cost_usd:.4f})"
    out.append(f"<span>{cost}</span>")
    out.append(f"<span>tokens: {t.prompt_tokens:,} in / {t.completion_tokens:,} out</span>")
    out.append(f"<span>cache: {t.cache_hits}/{t.cases}</span>")
    out.append(f"<span>wall: {_fmt_latency(run.duration_ms)}</span>")
    out.append("</div>")
    return out


def _case_rows(case: CaseResult) -> list[str]:
    label = case.status.upper() if case.status != "pass" else "pass"
    cls = _STATUS[case.status]
    ratio = f"{case.samples_passed}/{case.samples}" if case.samples > 1 else ""
    cached = "cached" if case.cached else ""
    rows = [
        "<tr>"
        f'<td class="st {cls}">{label}</td>'
        f'<td class="name">{_safe(case.name)}</td>'
        f"<td>{ratio}</td>"
        f'<td class="num">{_fmt_latency(case.latency_ms)}</td>'
        f'<td class="num">{_fmt_cost(case.cost_usd)}</td>'
        f'<td class="cached">{cached}</td>'
        "</tr>"
    ]
    reasons: list[str] = []
    if case.error:
        reasons.append(_safe(case.error))
    for f in case.failures:
        suffix = f" (sample {f.sample})" if case.samples > 1 else ""
        reasons.append(_safe(f.message) + _safe(suffix))
    if reasons or (case.status == "fail" and case.response_excerpt):
        detail = ['<tr class="detail"><td colspan="6">']
        if reasons:
            detail.append('<ul class="reasons">')
            detail.extend(f"<li>{r}</li>" for r in reasons)
            detail.append("</ul>")
        if case.status == "fail" and case.response_excerpt:
            excerpt = _safe(case.response_excerpt[:RESPONSE_EXCERPT_CHARS])
            detail.append(
                f'<pre class="excerpt">response (first {RESPONSE_EXCERPT_CHARS} chars):\n'
                f"{excerpt}</pre>"
            )
        detail.append("</td></tr>")
        rows.append("".join(detail))
    return rows


def build_html(run: RunResult, config: Config) -> str:
    """Build the full self-contained HTML document for a run (deterministic)."""
    label, cls = _overall(run)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>evalkit report: {label}</title>",
        f"<style>{_STYLE}</style>",
        "</head>",
        "<body>",
        "<main>",
        f'<header><h1>evalkit report</h1><span class="badge {cls}">{label}</span></header>',
        '<dl class="meta">',
    ]
    parts.extend(f"<dt>{_safe(k)}</dt><dd>{_safe(v)}</dd>" for k, v in _meta_rows(run, config))
    parts.append("</dl>")
    parts.extend(_totals_block(run))

    for suite in run.suites:
        parts.append(f'<h2>{_safe(suite.name)} <span class="file">{_safe(suite.file)}</span></h2>')
        parts.append("<table>")
        parts.append(
            "<thead><tr><th>status</th><th>case</th><th>samples</th>"
            "<th>latency</th><th>cost</th><th>cache</th></tr></thead>"
        )
        parts.append("<tbody>")
        for case in suite.cases:
            parts.extend(_case_rows(case))
        parts.append("</tbody></table>")

    parts.append(f"<footer>generated by evalkit {_safe(__version__)}</footer>")
    parts.append("</main>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts) + "\n"


def write_html_report(run: RunResult, config: Config, path: str) -> None:
    """Write the HTML report to ``path``; an I/O failure is a ReportError (exit 2)."""
    document = build_html(run, config)
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"Cannot write report {path}: {exc.strerror or exc}") from exc
