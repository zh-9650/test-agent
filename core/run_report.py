"""HTML reporting from authoritative execution records."""

from __future__ import annotations

from html import escape
from pathlib import Path

from core.interfaces import TestAssetPackage
from database.models import CaseResultRecord, ExecutionRunRecord, TaskStep


def build_run_report(
    run: ExecutionRunRecord,
    results: list[CaseResultRecord],
    steps: list[TaskStep],
    package: TestAssetPackage | None = None,
) -> str:
    by_case: dict[str, list[TaskStep]] = {}
    for step in steps:
        by_case.setdefault(step.test_case_id, []).append(step)
    assets_by_case = {
        case.id: case
        for case in (package.candidate_cases if package is not None else [])
    }

    summary = run.summary or {}
    asset_count = len(package.candidate_cases) if package is not None else summary.get("planned", 0)
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
        step_rows = "".join(
            "<tr>"
            f"<td>{step.attempt_no}</td><td>{step.step_index}</td>"
            f"<td>{escape(step.action_type)}</td>"
            f"<td>{escape(step.action_target)}</td>"
            f"<td>{escape(step.result)}</td>"
            "</tr>"
            for step in attempt_steps
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
            f"<p><strong>Evidence:</strong> "
            f"{escape(', '.join(result.evidence_refs))}</p>"
            "<table><thead><tr><th>Attempt</th><th>Step</th><th>Action</th>"
            "<th>Target</th><th>Result</th></tr></thead>"
            f"<tbody>{step_rows}</tbody></table></section>"
        )

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Run report</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1200px;margin:auto;padding:24px;background:#f5f7fb;color:#172033}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.card,section{{background:white;padding:18px;border-radius:10px;margin-bottom:16px}}
.card span{{display:block;font-size:28px;margin-top:8px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}
.status{{font-size:14px;padding:4px 8px;border-radius:8px;background:#e9edf5}}.passed{{color:#147a42}}.failed{{color:#b42318}}.muted{{color:#667085}}
</style></head><body>
<h1>Execution Run {escape(run.run_id)}</h1>
<p>Status: {escape(run.status)}</p>
<p>完整候选资产池: {asset_count}，本轮实际执行: {summary.get("planned", 0)}</p>
<div class="grid">{cards}</div>
{''.join(cases)}
</body></html>"""


def save_run_report(run_id: str, html: str) -> str:
    path = Path("data") / "reports" / f"report_{run_id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path)
