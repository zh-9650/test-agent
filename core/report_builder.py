"""core/report_builder.py — Generates HTML test reports with AI-generated summary.

Uses Jinja2 for HTML templating and calls the LLM (haiku model) to produce
a human-readable summary of test results.
"""

from __future__ import annotations

import os
from pathlib import Path

from jinja2 import Template

from core.interfaces import TestResult
from core.llm_client import get_llm_client


# ---------------------------------------------------------------------------
# Jinja2 HTML template
# ---------------------------------------------------------------------------

_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>测试报告 - {{ task_id }}</title>
    <style>
        :root {
            --bg: #f4f6f8;
            --card-bg: #ffffff;
            --text: #1a1a1a;
            --muted: #6b7280;
            --border: #e5e7eb;
            --pass: #10b981;
            --fail: #ef4444;
            --primary: #3b82f6;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }
        .container {
            max-width: 960px;
            margin: 40px auto;
            padding: 0 20px;
        }
        h1 {
            font-size: 1.8rem;
            margin-bottom: 0.5rem;
        }
        .subtitle {
            color: var(--muted);
            font-size: 0.95rem;
            margin-bottom: 1.5rem;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 16px;
            margin-bottom: 2rem;
        }
        .summary-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        }
        .summary-card .number {
            font-size: 2rem;
            font-weight: 700;
            color: var(--primary);
        }
        .summary-card.pass .number { color: var(--pass); }
        .summary-card.fail .number { color: var(--fail); }
        .summary-card label {
            display: block;
            margin-top: 4px;
            font-size: 0.85rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .ai-summary {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        }
        .ai-summary h2 {
            font-size: 1.1rem;
            margin-top: 0;
            margin-bottom: 0.75rem;
        }
        .ai-summary p {
            margin: 0;
            color: var(--muted);
        }
        .case-list {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .case-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        }
        .case-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .case-title {
            font-size: 1.1rem;
            font-weight: 600;
            margin: 0;
        }
        .case-status {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
        }
        .case-status.passed {
            background: #d1fae5;
            color: #065f46;
        }
        .case-status.failed {
            background: #fee2e2;
            color: #991b1b;
        }
        .case-status.skipped {
            background: #fef3c7;
            color: #92400e;
        }
        .case-status.incomplete {
            background: #e0e7ff;
            color: #3730a3;
        }
        .case-meta {
            font-size: 0.9rem;
            color: var(--muted);
            margin-bottom: 8px;
        }
        .step-table {
            width: 100%%;
            border-collapse: collapse;
            margin-top: 12px;
        }
        .step-table th,
        .step-table td {
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid var(--border);
            font-size: 0.9rem;
        }
        .step-table th {
            font-weight: 600;
            color: var(--muted);
            background: #f9fafb;
        }
        .step-table tr:last-child td {
            border-bottom: none;
        }
        .screenshot {
            max-width: 200px;
            max-height: 120px;
            border-radius: 6px;
            border: 1px solid var(--border);
            margin-top: 4px;
        }
        .assertion-pass { color: var(--pass); font-weight: 600; }
        .assertion-fail { color: var(--fail); font-weight: 600; }
    </style>
</head>
<body>
    <div class="container">
        <h1>测试报告</h1>
        <div class="subtitle">任务 ID: {{ task_id }}</div>

        <div class="summary-grid">
            <div class="summary-card">
                <div class="number">{{ total }}</div>
                <label>Total</label>
            </div>
            <div class="summary-card pass">
                <div class="number">{{ passed }}</div>
                <label>Passed</label>
            </div>
            <div class="summary-card fail">
                <div class="number">{{ failed }}</div>
                <label>Failed</label>
            </div>
            <div class="summary-card">
                <div class="number">{{ duration|round(1) }}s</div>
                <label>Duration</label>
            </div>
        </div>

        <div class="ai-summary">
            <h2>AI 总结</h2>
            <p>{{ ai_summary or "暂无总结" }}</p>
        </div>

        <div class="case-list">
            {% for result in results %}
            <div class="case-card">
                <div class="case-header">
                    <h3 class="case-title">{{ result.test_case_id }} — {{ result.summary }}</h3>
                    <span class="case-status {{ result.status }}">{{ result.status }}</span>
                </div>
                <div class="case-meta">
                    耗时: {{ result.duration_seconds|round(2) }}s | 步骤数: {{ result.steps|length }}
                </div>
                {% if result.steps %}
                <table class="step-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Action</th>
                            <th>Target</th>
                            <th>Result</th>
                            <th>Assertion</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for step in result.steps %}
                        <tr>
                            <td>{{ step.step_index }}</td>
                            <td>{{ step.action_type }}</td>
                            <td>{{ step.action_target }}</td>
                            <td>{{ step.result }}</td>
                            <td>
                                {% if step.assertion %}
                                    <span class="assertion-{{ 'pass' if step.assertion.status == 'pass' else 'fail' }}">
                                        {{ step.assertion.status }}
                                    </span>
                                    <br><small>{{ step.assertion.reasoning }}</small>
                                {% else %}
                                    —
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% endif %}
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""


class ReportBuilder:
    """Report generator for test sessions."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.results: list[TestResult] = []

    def add_result(self, result: TestResult) -> None:
        """Add a test case result."""
        self.results.append(result)

    def build_html(self) -> str:
        """Generate HTML report content using Jinja2 template."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "passed")
        failed = sum(1 for r in self.results if r.status == "failed")
        duration = sum(r.duration_seconds for r in self.results)

        template = Template(_REPORT_TEMPLATE)
        return template.render(
            task_id=self.task_id,
            results=self.results,
            total=total,
            passed=passed,
            failed=failed,
            duration=duration,
            ai_summary="",
        )

    def save(self, output_path: str) -> str:
        """Save report to filesystem, return relative path.

        Args:
            output_path: Path where the HTML file should be written.

        Returns:
            The output_path argument (relative path).
        """
        html = self.build_html()
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return output_path

    async def generate_summary(self, results: list[TestResult]) -> str:
        """Use LLM (haiku model) to generate test summary.

        Args:
            results: List of TestResult objects to summarize.

        Returns:
            AI-generated summary string.
        """
        total = len(results)
        passed = sum(1 for r in results if r.status == "passed")
        failed = sum(1 for r in results if r.status == "failed")

        prompt = f"""你是一个测试报告分析助手。请根据以下测试结果生成一段简短的测试总结（不超过200字）。

测试统计：
- 总用例数：{total}
- 通过：{passed}
- 失败：{failed}

各用例结果：
"""
        for r in results:
            prompt += f"- {r.test_case_id}: {r.status} — {r.summary}\n"

        prompt += "\n请用中文生成总结。"

        llm = get_llm_client("haiku")
        response = await llm.ainvoke(prompt)
        return response.content if response and hasattr(response, "content") else ""  # type: ignore[return-value]
