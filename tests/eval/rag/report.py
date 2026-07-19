"""Report writer — JSON + HTML output for a scored run.

JSON is the canonical artifact: it's diffable, machine-readable, and
the source of truth for the aggregate numbers. HTML is the human-
friendly version with per-prompt details so you can click into a low
score and see which claims weren't supported / which chunks weren't
relevant.

The HTML is a single file with inline CSS — no external assets, easy
to email or scp.
"""
from __future__ import annotations

import html
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write_reports(*, scored, reports_dir: Path) -> None:
    """Write scored-<run_id>.json + scored-<run_id>.html to reports_dir.

    Both files are overwritten if they exist; runs use a unique run_id
    in their name so overwrites only happen on intentional re-runs.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"scored-{scored.run_id}.json"
    html_path = reports_dir / f"scored-{scored.run_id}.html"

    json_path.write_text(
        json.dumps(scored.to_dict(), indent=2),
        encoding="utf-8",
    )
    html_path.write_text(_render_html(scored), encoding="utf-8")
    logger.info(
        "wrote reports run_id=%s json=%s html=%s",
        scored.run_id,
        json_path,
        html_path,
    )


# ── HTML rendering ────────────────────────────────────────────────────


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; color: #1f2937; }
h1, h2, h3 { color: #111827; }
.aggregates { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 1rem; margin: 1.5rem 0; }
.metric-card { padding: 1rem; border-radius: 8px; background: #f9fafb; border: 1px solid #e5e7eb; }
.metric-card .name { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7280; }
.metric-card .score { font-size: 2rem; font-weight: 600; }
.metric-card .score.good { color: #059669; }
.metric-card .score.medium { color: #d97706; }
.metric-card .score.bad { color: #dc2626; }
table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
th, td { padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
th { background: #f3f4f6; font-weight: 600; }
tr:hover { background: #f9fafb; }
.cell-score { font-variant-numeric: tabular-nums; text-align: right; }
.cell-score.good { color: #059669; }
.cell-score.medium { color: #d97706; }
.cell-score.bad { color: #dc2626; }
details { margin: 0.5rem 0; }
summary { cursor: pointer; font-weight: 500; color: #2563eb; }
pre { background: #f3f4f6; padding: 0.75rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; }
.meta { color: #6b7280; font-size: 0.85rem; }
.route { font-family: ui-monospace, monospace; font-size: 0.85rem; }
.route.hit { color: #059669; }
.route.miss { color: #dc2626; }
.error { color: #dc2626; font-style: italic; }
"""


def _render_html(scored) -> str:
    aggregates = scored.aggregates()
    parts: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>RAG eval — {html.escape(scored.run_id)}</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
        f"<h1>RAG eval — {html.escape(scored.run_id)}</h1>",
        "<div class='meta'>",
        f"<div>Target: {html.escape(scored.target)}</div>",
        f"<div>Workspace: {html.escape(scored.workspace_uuid)}</div>",
        f"<div>Started: {html.escape(scored.run_started_at)}</div>",
        f"<div>Prompts: {len(scored.entries)}</div>",
        "</div>",
        "<h2>Aggregates</h2>",
        "<div class='aggregates'>",
    ]
    metric_labels = {
        "faithfulness": "Faithfulness",
        "answer_relevancy": "Answer Relevancy",
        "context_precision": "Context Precision",
        "context_recall": "Context Recall",
        "routing_accuracy": "Routing Accuracy",
    }
    for key, label in metric_labels.items():
        score = aggregates.get(key, 0.0)
        cls = _score_class(score)
        parts.append(
            "<div class='metric-card'>"
            f"<div class='name'>{html.escape(label)}</div>"
            f"<div class='score {cls}'>{score:.2f}</div>"
            "</div>"
        )
    parts.append("</div>")

    parts.append("<h2>Per-prompt</h2>")
    parts.append("<table>")
    parts.append(
        "<thead><tr>"
        "<th>ID</th><th>Question</th><th>Category</th>"
        "<th>Routed → Expected</th>"
        "<th class='cell-score'>Faith</th>"
        "<th class='cell-score'>AnsRel</th>"
        "<th class='cell-score'>CtxPrec</th>"
        "<th class='cell-score'>CtxRec</th>"
        "<th></th>"
        "</tr></thead><tbody>"
    )
    for entry in scored.entries:
        routed = ", ".join(entry.routed_specialists) or "—"
        expected = entry.expected_specialist or "—"
        hit = entry.expected_specialist in (entry.routed_specialists or []) if entry.expected_specialist else None
        route_cls = "hit" if hit is True else ("miss" if hit is False else "")
        f = entry.metrics.get("faithfulness")
        a = entry.metrics.get("answer_relevancy")
        cp = entry.metrics.get("context_precision")
        cr = entry.metrics.get("context_recall")
        parts.append(
            "<tr>"
            f"<td>{html.escape(entry.prompt_id)}</td>"
            f"<td>{html.escape(entry.question)}</td>"
            f"<td>{html.escape(entry.category)}</td>"
            f"<td class='route {route_cls}'>{html.escape(routed)} → {html.escape(expected)}</td>"
            f"{_score_cell(f)}{_score_cell(a)}{_score_cell(cp)}{_score_cell(cr)}"
            "<td>"
            f"<details><summary>detail</summary>{_render_entry_detail(entry)}</details>"
            "</td>"
            "</tr>"
        )
    parts.append("</tbody></table>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _score_class(score: float) -> str:
    if score >= 0.75:
        return "good"
    if score >= 0.5:
        return "medium"
    return "bad"


def _score_cell(metric) -> str:
    if metric is None:
        return "<td class='cell-score'>—</td>"
    cls = _score_class(metric.score)
    return f"<td class='cell-score {cls}'>{metric.score:.2f}</td>"


def _render_entry_detail(entry) -> str:
    parts = ["<div>"]
    if entry.error:
        parts.append(f"<div class='error'>Error: {html.escape(entry.error)}</div>")
    parts.append(f"<div class='meta'>Retrieved chunks: {entry.retrieved_chunks_count}</div>")
    parts.append("<h4>Answer</h4>")
    parts.append(f"<pre>{html.escape(entry.answer)}</pre>")
    for name, metric in entry.metrics.items():
        parts.append(f"<h4>{html.escape(name)} = {metric.score:.2f}</h4>")
        parts.append(f"<pre>{html.escape(json.dumps(metric.detail, indent=2))}</pre>")
    parts.append("</div>")
    return "".join(parts)
