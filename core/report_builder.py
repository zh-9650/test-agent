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
    <title>Intelligent Test Report - {{ task_id }}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        
        :root {
            --bg: #09090b;
            --card-bg: rgba(24, 24, 27, 0.6);
            --text-main: #f4f4f5;
            --text-muted: #a1a1aa;
            --border: rgba(255, 255, 255, 0.08);
            --pass-glow: rgba(16, 185, 129, 0.15);
            --pass-text: #34d399;
            --fail-glow: rgba(239, 68, 68, 0.15);
            --fail-text: #fb7185;
            --primary-glow: rgba(59, 130, 246, 0.15);
            --primary-text: #60a5fa;
            --glass-blur: blur(16px);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            background-image: 
                radial-gradient(circle at 15% 50%, rgba(59, 130, 246, 0.08), transparent 25%),
                radial-gradient(circle at 85% 30%, rgba(16, 185, 129, 0.08), transparent 25%);
            background-attachment: fixed;
            color: var(--text-main);
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
        }
        .container {
            max-width: 1100px;
            margin: 60px auto;
            padding: 0 24px;
        }
        h1 {
            font-size: 2.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, #ffffff 0%, #a1a1aa 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.2rem;
            letter-spacing: -0.02em;
        }
        .subtitle {
            color: var(--text-muted);
            font-size: 1rem;
            margin-bottom: 2.5rem;
            font-family: monospace;
        }
        .glass-card {
            background: var(--card-bg);
            backdrop-filter: var(--glass-blur);
            -webkit-backdrop-filter: var(--glass-blur);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            transition: transform 0.3s ease, border-color 0.3s ease;
        }
        .glass-card:hover {
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.15);
        }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 2.5rem;
        }
        .summary-card {
            text-align: center;
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding: 30px 20px;
        }
        .summary-card .number {
            font-size: 3.5rem;
            font-weight: 800;
            line-height: 1;
            margin-bottom: 8px;
            color: var(--primary-text);
            text-shadow: 0 0 20px var(--primary-glow);
        }
        .summary-card.pass .number { 
            color: var(--pass-text); 
            text-shadow: 0 0 20px var(--pass-glow);
        }
        .summary-card.fail .number { 
            color: var(--fail-text); 
            text-shadow: 0 0 20px var(--fail-glow);
        }
        .summary-card label {
            font-size: 0.9rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.1em;
            font-weight: 600;
        }
        .ai-summary {
            margin-bottom: 2.5rem;
            position: relative;
            overflow: hidden;
        }
        .ai-summary::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 1px;
            background: linear-gradient(90deg, transparent, rgba(59, 130, 246, 0.5), transparent);
        }
        .ai-summary h2 {
            font-size: 1.3rem;
            margin-top: 0;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 8px;
            color: #fff;
        }
        .ai-summary p {
            margin: 0;
            color: var(--text-muted);
            font-size: 1.05rem;
            line-height: 1.8;
        }
        .case-list {
            display: flex;
            flex-direction: column;
            gap: 24px;
        }
        .case-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 16px;
        }
        .case-title {
            font-size: 1.25rem;
            font-weight: 600;
            margin: 0 0 8px 0;
            color: #fff;
        }
        .case-status {
            padding: 6px 16px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            box-shadow: inset 0 0 0 1px rgba(255,255,255,0.1);
        }
        .case-status.passed {
            background: var(--pass-glow);
            color: var(--pass-text);
            box-shadow: inset 0 0 0 1px var(--pass-text);
        }
        .case-status.failed {
            background: var(--fail-glow);
            color: var(--fail-text);
            box-shadow: inset 0 0 0 1px var(--fail-text);
        }
        .case-status.skipped {
            background: rgba(245, 158, 11, 0.1);
            color: #fbbf24;
            box-shadow: inset 0 0 0 1px #fbbf24;
        }
        .case-status.incomplete {
            background: rgba(168, 85, 247, 0.1);
            color: #c084fc;
            box-shadow: inset 0 0 0 1px #c084fc;
        }
        .case-meta {
            font-size: 0.9rem;
            color: var(--text-muted);
            font-family: monospace;
        }
        .step-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin-top: 20px;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border);
        }
        .step-table th,
        .step-table td {
            text-align: left;
            padding: 14px 16px;
            font-size: 0.95rem;
            border-bottom: 1px solid var(--border);
        }
        .step-table th {
            font-weight: 600;
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.03);
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 0.05em;
        }
        .step-table tr:last-child td {
            border-bottom: none;
        }
        .step-table tbody tr {
            transition: background 0.2s;
        }
        .step-table tbody tr:hover {
            background: rgba(255, 255, 255, 0.02);
        }
        .assertion-pass { color: var(--pass-text); font-weight: 600; }
        .assertion-fail { color: var(--fail-text); font-weight: 600; }
        .progress-bar-bg {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            height: 8px;
            margin-top: 8px;
            overflow: hidden;
        }
        .progress-bar-fill {
            height: 100%;
            border-radius: 10px;
            transition: width 1s ease-in-out;
            box-shadow: 0 0 10px currentColor;
        }
        .l1-coverage-section { margin-bottom: 2.5rem; }
        .l1-stat-row {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }
        .l1-stat {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 14px 16px;
        }
        .l1-stat .label {
            font-size: 0.78rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 6px;
        }
        .l1-stat .value {
            font-size: 1.6rem;
            font-weight: 700;
        }
        .l1-stat.covered .value { color: var(--pass-text); }
        .l1-stat.missing .value { color: var(--fail-text); }
        .l1-stat.refined .value { color: var(--primary-text); }
        .l1-rule-list {
            list-style: none;
            padding: 0;
            margin: 0;
            max-height: 200px;
            overflow-y: auto;
        }
        .l1-rule-list li {
            padding: 8px 12px;
            font-size: 0.9rem;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border);
        }
        .l1-rule-list li:last-child { border-bottom: none; }
        .l1-rule-list li .marker {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 10px;
        }
        .l1-rule-list li.covered-rule .marker { background: var(--pass-text); }
        .l1-rule-list li.missing-rule .marker { background: var(--fail-text); }
        .l1-collapsible {
            margin-top: 12px;
            border-top: 1px solid var(--border);
            padding-top: 12px;
        }
        .l1-collapsible summary {
            cursor: pointer;
            color: var(--text-muted);
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            user-select: none;
        }
        .l1-collapsible summary:hover { color: var(--text-main); }
    </style>
</head>
<body>
    <div class="container">
        <h1>AI Test Intelligence Report</h1>
        <div class="subtitle">Task Execution ID: {{ task_id }}</div>

        <div class="summary-grid">
            <div class="summary-card glass-card">
                <div class="number">{{ total }}</div>
                <label>Total Cases</label>
            </div>
            <div class="summary-card glass-card pass">
                <div class="number">{{ passed }}</div>
                <label>Passed</label>
            </div>
            <div class="summary-card glass-card fail">
                <div class="number">{{ failed }}</div>
                <label>Failed</label>
            </div>
            <div class="summary-card glass-card">
                <div class="number">{{ duration|round(1) }}s</div>
                <label>Duration</label>
            </div>
        </div>

        <div class="ai-summary glass-card">
            <h2>✨ AI Executive Summary</h2>
            <p>{{ ai_summary or "Waiting for AI synthesis..." }}</p>
        </div>

        {% if l1_coverage %}
        <div class="l1-coverage-section glass-card">
            <h2>🧠 Layer 1 认知自检 (Use-Case Coverage)</h2>
            {% set cov = l1_coverage.covered_rules|length %}
            {% set mis = l1_coverage.missing_rules|length %}
            {% set ref = l1_coverage.added_use_cases|length %}
            {% set total = cov + mis %}
            {% set unknown_actors = l1_coverage.unknown_actor_count|default(0) %}
            <div class="l1-stat-row">
                <div class="l1-stat covered">
                    <div class="label">已覆盖规则</div>
                    <div class="value">{{ cov }} / {{ total }}</div>
                </div>
                <div class="l1-stat missing">
                    <div class="label">遗漏规则</div>
                    <div class="value">{{ mis }}</div>
                </div>
                <div class="l1-stat refined">
                    <div class="label">补全 / 修改用例</div>
                    <div class="value">{{ ref }}</div>
                </div>
                <div class="l1-stat {% if unknown_actors > 0 %}missing{% else %}covered{% endif %}">
                    <div class="label">未匹配角色</div>
                    <div class="value">{{ unknown_actors }}</div>
                </div>
            </div>
            {% if total > 0 %}
            <div style="margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; font-size: 0.95rem;">
                    <span style="color: var(--text-muted)">规则覆盖率</span>
                    <span style="font-weight: 600; color: var(--primary-text)">{{ ((cov / total) * 100)|round(0) }}%</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" style="background: var(--primary-text); width: {{ ((cov / total) * 100)|round(0) }}%;"></div>
                </div>
            </div>
            {% endif %}
            {% if cov > 0 or mis > 0 %}
            <details class="l1-collapsible" open>
                <summary>业务规则详情 ({{ cov + mis }} 条)</summary>
                <ul class="l1-rule-list">
                    {% for rule in l1_coverage.covered_rules %}
                    <li class="covered-rule"><span class="marker"></span>{{ rule }}</li>
                    {% endfor %}
                    {% for rule in l1_coverage.missing_rules %}
                    <li class="missing-rule"><span class="marker"></span>{{ rule }}</li>
                    {% endfor %}
                </ul>
            </details>
            {% endif %}
            {% if l1_coverage.added_use_cases %}
            <details class="l1-collapsible">
                <summary>自检补全 / 修改的用例 ({{ ref }} 个)</summary>
                <ul class="l1-rule-list">
                    {% for name in l1_coverage.added_use_cases %}
                    <li class="covered-rule"><span class="marker"></span>{{ name }}</li>
                    {% endfor %}
                </ul>
            </details>
            {% endif %}
            {% if l1_coverage.unknown_actor_names and l1_coverage.unknown_actor_count > 0 %}
            <details class="l1-collapsible">
                <summary>⚠️ Actor 幻觉 ({{ l1_coverage.unknown_actor_count }} 个)</summary>
                <p style="font-size: 0.85rem; color: var(--text-muted); margin: 8px 0;">
                    以下 use_case.actor 不在 N1 KnowledgeBase.roles 中,可能是 LLM 杜撰的角色:
                </p>
                <ul class="l1-rule-list">
                    {% for name in l1_coverage.unknown_actor_names %}
                    <li class="missing-rule"><span class="marker"></span>{{ name }}</li>
                    {% endfor %}
                </ul>
            </details>
            {% endif %}
        </div>
        {% endif %}

        {% if page_coverage %}
        <div class="ai-summary glass-card">
            <h2>📊 Coverage Metrics</h2>
            <div style="margin-bottom: 24px;">
                <div style="display: flex; justify-content: space-between; font-size: 0.95rem;">
                    <span style="color: var(--text-muted)">Page Discovery</span>
                    <span style="font-weight: 600; color: var(--primary-text)">{{ page_coverage.covered }}/{{ page_coverage.total }} ({{ (page_coverage.rate * 100)|round(0) }}%)</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" style="background: var(--primary-text); width: {{ (page_coverage.rate * 100)|round(0) }}%;"></div>
                </div>
            </div>
            {% if scenario_coverage and scenario_coverage.total > 0 %}
            <div>
                <div style="display: flex; justify-content: space-between; font-size: 0.95rem;">
                    <span style="color: var(--text-muted)">Business Scenarios Validated</span>
                    <span style="font-weight: 600; color: var(--pass-text)">{{ scenario_coverage.covered }}/{{ scenario_coverage.total }} ({{ (scenario_coverage.rate * 100)|round(0) }}%)</span>
                </div>
                <div class="progress-bar-bg" style="margin-bottom: 16px;">
                    <div class="progress-bar-fill" style="background: var(--pass-text); width: {{ (scenario_coverage.rate * 100)|round(0) }}%;"></div>
                </div>
                <table class="step-table">
                    <thead><tr><th>Scenario ID / Name</th><th>Status</th></tr></thead>
                    <tbody>
                    {% for s in scenario_coverage.details %}
                    <tr>
                        <td style="font-weight: 500;">{{ s.name }}</td>
                        <td>{% if s.covered %}<span class="assertion-pass">✓ Validated</span>{% else %}<span class="assertion-fail">✗ Pending</span>{% endif %}</td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
            {% endif %}
        </div>
        {% endif %}

        <div class="case-list">
            {% for result in results %}
            <div class="glass-card">
                <div class="case-header">
                    <div>
                        <h3 class="case-title">{{ result.test_case_id }} — {{ result.summary }}</h3>
                        <div class="case-meta">
                            Execution Time: {{ result.duration_seconds|round(2) }}s &nbsp;|&nbsp; Steps: {{ result.steps|length }}
                        </div>
                    </div>
                    <span class="case-status {{ result.status }}">{{ result.status }}</span>
                </div>
                {% if result.steps %}
                <table class="step-table">
                    <thead>
                        <tr>
                            <th style="width: 5%;">#</th>
                            <th style="width: 15%;">Action</th>
                            <th style="width: 25%;">Target</th>
                            <th style="width: 25%;">Result</th>
                            <th style="width: 30%;">AI Assertion</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for step in result.steps %}
                        <tr>
                            <td style="color: var(--text-muted); font-family: monospace;">{{ step.step_index }}</td>
                            <td><span style="background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 4px; font-size: 0.85rem; border: 1px solid rgba(255,255,255,0.1);">{{ step.action_type }}</span></td>
                            <td style="color: var(--text-muted);">{{ step.action_target }}</td>
                            <td style="font-size: 0.85rem; color: var(--text-muted);">{{ step.result }}</td>
                            <td style="font-size: 0.85rem;">
                                {% if step.assertion %}
                                    <div class="assertion-{{ 'pass' if step.assertion.status == 'pass' else 'fail' }}" style="margin-bottom: 4px; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em;">
                                        {{ step.assertion.status }}
                                    </div>
                                    <div style="color: var(--text-muted); line-height: 1.4;">{{ step.assertion.reasoning }}</div>
                                {% else %}
                                    <span style="color: var(--border);">—</span>
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
        self.coverage_data: dict | None = None
        self.l1_coverage: dict | None = None

    def add_result(self, result: TestResult) -> None:
        """Add a test case result."""
        self.results.append(result)

    def set_coverage(self, coverage_data: dict) -> None:
        """Set execution-time coverage tracking data for the report."""
        self.coverage_data = coverage_data

    def set_layer1_coverage(self, l1_coverage: dict) -> None:
        """Set Layer 1 (knowledge / use-case model) coverage report."""
        self.l1_coverage = l1_coverage

    def build_html(self, ai_summary: str = "") -> str:
        """Generate HTML report content using Jinja2 template."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "passed")
        failed = sum(1 for r in self.results if r.status == "failed")
        duration = sum(r.duration_seconds for r in self.results)

        page_coverage = None
        scenario_coverage = None
        if self.coverage_data:
            page_coverage = self.coverage_data.get("page_coverage")
            scenario_coverage = self.coverage_data.get("scenario_coverage")

        template = Template(_REPORT_TEMPLATE)
        return template.render(
            task_id=self.task_id,
            results=self.results,
            total=total,
            passed=passed,
            failed=failed,
            duration=duration,
            ai_summary=ai_summary or "",
            page_coverage=page_coverage,
            scenario_coverage=scenario_coverage,
            l1_coverage=self.l1_coverage,
        )

    def save(self, output_path: str, ai_summary: str = "") -> str:
        """Save report to filesystem, return relative path.

        Args:
            output_path: Path where the HTML file should be written.
            ai_summary: AI-generated summary text.

        Returns:
            The output_path argument (relative path).
        """
        html = self.build_html(ai_summary=ai_summary)
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
