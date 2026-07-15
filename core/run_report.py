"""HTML reporting from authoritative execution records."""

from __future__ import annotations

from html import escape
from pathlib import Path

from core.interfaces import TestAssetPackage
from core.runtime_tool_contract import (
    is_runtime_tool_failure_status,
    tool_error_taxon_for_code,
)
from database.models import (
    CaseResultRecord,
    ExecutionRunRecord,
    HumanReviewRequestRecord,
    TaskStep,
)


def build_run_report(
    run: ExecutionRunRecord,
    results: list[CaseResultRecord],
    steps: list[TaskStep],
    package: TestAssetPackage | None = None,
    human_reviews: list[HumanReviewRequestRecord] | None = None,
) -> str:
    by_case: dict[str, list[TaskStep]] = {}
    for step in steps:
        by_case.setdefault(step.test_case_id, []).append(step)
    assets_by_case = {
        case.id: case
        for case in (package.candidate_cases if package is not None else [])
    }

    summary = run.summary or {}
    asset_count = (
        len(package.candidate_cases)
        if package is not None
        else summary.get("planned", 0)
    )
    tool_error_summary = _tool_error_summary(steps)
    tool_error_summary_html = _render_tool_error_summary(tool_error_summary)
    memory_context_html = _render_memory_context(package)
    human_review_html = _render_human_reviews(human_reviews or [])
    cards = "".join(
        f"<div class='card'><strong>{escape(label)}</strong><span>{summary.get(key, 0)}</span></div>"
        for key, label in (
            ("planned", "Planned"),
            ("passed", "Passed"),
            ("failed", "Failed"),
            ("incomplete", "Incomplete"),
            ("skipped", "Skipped"),
            ("human_review_required", "Human review"),
        )
    )
    cases = []
    for result in results:
        asset = assets_by_case.get(result.candidate_case_id)
        attempt_steps = sorted(
            by_case.get(result.candidate_case_id, []),
            key=lambda item: (item.attempt_no, item.step_index),
        )
        primary_error = _primary_tool_error(attempt_steps)
        step_rows = "".join(
            _render_step_row(step)
            for step in attempt_steps
        )
        tool_error_html = ""
        if result.terminal_status != "passed" and primary_error:
            tool_error_html = (
                "<p><strong>Primary tool error:</strong> "
                f"{escape(primary_error)}</p>"
            )
        asset_html = ""
        if asset is not None:
            asset_html = (
                f"<h3>{escape(asset.title)}</h3>"
                f"<p><strong>Goal:</strong> {escape(asset.goal)}</p>"
                f"<p><strong>Expected:</strong> "
                f"{escape(asset.expected_result)}</p>"
                f"<p><strong>Trace:</strong> "
                f"{escape(', '.join(asset.trace_references))}</p>"
            )
        cases.append(
            "<section>"
            f"<h2>{escape(result.candidate_case_id)} "
            f"<span class='status {escape(result.terminal_status)}'>"
            f"{escape(result.terminal_status)}</span></h2>"
            f"{asset_html}"
            f"<p>{escape(result.summary)}</p>"
            f"<p class='muted'>{escape(result.failure_reason or '')}</p>"
            f"{tool_error_html}"
            f"<p><strong>Evidence:</strong> "
            f"{escape(', '.join(result.evidence_refs))}</p>"
            "<table><thead><tr><th>Attempt</th><th>Step</th><th>Action</th>"
            "<th>Target</th><th>Status</th><th>Error code</th><th>Result</th>"
            "</tr></thead>"
            f"<tbody>{step_rows}</tbody></table></section>"
        )

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Run report</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1200px;margin:auto;padding:24px;background:#f5f7fb;color:#172033}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.card,section{{background:white;padding:18px;border-radius:10px;margin-bottom:16px}}
.card span{{display:block;font-size:28px;margin-top:8px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}
.summary-table td:first-child{{font-family:Consolas,monospace}}
.status{{font-size:14px;padding:4px 8px;border-radius:8px;background:#e9edf5}}.passed{{color:#147a42}}.failed{{color:#b42318}}.muted{{color:#667085}}
.tool-success{{color:#147a42}}.tool-blocked,.tool-failed,.tool-timeout,.tool-not_found,.tool-completion_rejected{{color:#b42318}}.tool-noop{{color:#8a6116}}
</style></head><body>
<h1>Execution Run {escape(run.run_id)}</h1>
<p>Status: {escape(run.status)}</p>
<p>完整候选资产池: {asset_count}，本轮实际执行: {summary.get("planned", 0)}</p>
<div class="grid">{cards}</div>
{tool_error_summary_html}
{memory_context_html}
{human_review_html}
{''.join(cases)}
</body></html>"""


def _render_step_row(step: TaskStep) -> str:
    status = _change_value(step, "status") or ""
    error_code = _change_value(step, "error_code") or ""
    return (
        "<tr>"
        f"<td>{step.attempt_no}</td><td>{step.step_index}</td>"
        f"<td>{escape(step.action_type)}</td>"
        f"<td>{escape(step.action_target)}</td>"
        f"<td class='tool-{escape(status)}'>{escape(status)}</td>"
        f"<td>{escape(error_code)}</td>"
        f"<td>{escape(step.result)}</td>"
        "</tr>"
    )


def _primary_tool_error(steps: list[TaskStep]) -> str:
    for step in steps:
        status = _change_value(step, "status")
        error_code = _change_value(step, "error_code")
        if is_runtime_tool_failure_status(status) and error_code:
            return error_code
    return ""


def _tool_error_summary(steps: list[TaskStep]) -> list[dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for step in steps:
        status = _change_value(step, "status")
        error_code = _change_value(step, "error_code")
        if not error_code or not is_runtime_tool_failure_status(status):
            continue
        taxon = tool_error_taxon_for_code(error_code)
        row = summary.setdefault(
            error_code,
            {
                "error_code": error_code,
                "category": taxon.label,
                "description": taxon.description,
                "remediation": taxon.remediation,
                "count": 0,
                "case_ids": set(),
            },
        )
        row["count"] = int(row["count"]) + 1
        case_ids = row["case_ids"]
        if isinstance(case_ids, set):
            case_ids.add(step.test_case_id)

    rows: list[dict[str, object]] = []
    for row in summary.values():
        case_ids = row.get("case_ids", set())
        rows.append({
            **row,
            "case_ids": sorted(case_ids) if isinstance(case_ids, set) else [],
        })
    return sorted(
        rows,
        key=lambda item: (-int(item["count"]), str(item["error_code"])),
    )


def _render_tool_error_summary(rows: list[dict[str, object]]) -> str:
    if not rows:
        return (
            "<section><h2>Tool error summary</h2>"
            "<p class='muted'>No failed tool calls recorded.</p></section>"
        )
    body = "".join(
        "<tr>"
        f"<td>{escape(str(row['error_code']))}</td>"
        f"<td>{escape(str(row['category']))}</td>"
        f"<td>{int(row['count'])}</td>"
        f"<td>{escape(', '.join(str(item) for item in row['case_ids']))}</td>"
        f"<td>{escape(str(row['description']))}</td>"
        f"<td>{escape(str(row.get('remediation', '')))}</td>"
        "</tr>"
        for row in rows
    )


def _render_memory_context(package: TestAssetPackage | None) -> str:
    refs = []
    if package is not None:
        raw_refs = package.runtime_hints.get("memory_context_refs")
        if isinstance(raw_refs, list):
            refs = [item for item in raw_refs if isinstance(item, dict)]
    if not refs:
        return (
            "<section><h2>Memory context</h2>"
            "<p class='muted'>No MemoryContext hints were used.</p></section>"
        )
    body = "".join(
        "<tr>"
        f"<td>{escape(str(ref.get('memory_key', '')))}</td>"
        f"<td>{escape(str(ref.get('scope_type', '')))}</td>"
        f"<td>{escape(str(ref.get('source_domain') or ref.get('scope_value') or ''))}</td>"
        f"<td>{escape(str(ref.get('provenance', '')))}</td>"
        "</tr>"
        for ref in refs
    )
    return (
        "<section><h2>Memory context</h2>"
        "<p class='muted'>Memory is hint-only and is not treated as a requirement source.</p>"
        "<table><thead><tr><th>Key</th><th>Scope</th><th>Domain</th>"
        "<th>Provenance</th></tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def _render_human_reviews(rows: list[HumanReviewRequestRecord]) -> str:
    if not rows:
        return (
            "<section><h2>Human review</h2>"
            "<p class='muted'>No human review requests were recorded.</p></section>"
        )
    body = "".join(
        "<tr>"
        f"<td>{row.id}</td>"
        f"<td>{escape(row.phase)}</td>"
        f"<td>{escape(row.candidate_case_id or '-')}</td>"
        f"<td>{escape(row.status)}</td>"
        f"<td>{escape(row.blocked_tool or '')}</td>"
        f"<td>{escape(row.reason)}</td>"
        "</tr>"
        for row in rows
    )
    return (
        "<section><h2>Human review</h2>"
        "<table><thead><tr><th>ID</th><th>Phase</th><th>Case</th>"
        "<th>Status</th><th>Tool</th><th>Reason</th></tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )
    return (
        "<section><h2>Tool error summary</h2>"
        "<table class='summary-table'><thead><tr>"
        "<th>Error code</th><th>Category</th><th>Count</th>"
        "<th>Cases</th><th>Description</th><th>Remediation</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def _change_value(step: TaskStep, key: str) -> str:
    value = None
    if isinstance(step.change_report, dict):
        value = step.change_report.get(key)
    if value in (None, "") and isinstance(step.tool_result, dict):
        value = step.tool_result.get(key)
    return str(value) if value not in (None, "") else ""


def save_run_report(run_id: str, html: str) -> str:
    path = Path("data") / "reports" / f"report_{run_id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path)
