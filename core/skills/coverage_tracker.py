"""core/skills/coverage_tracker.py — 覆盖率追踪器。

追踪两个维度的覆盖率：
1. 页面覆盖率 = 测试触及的页面数 / 探索发现的总页面数
2. 业务场景覆盖率 = 实际测试的场景数 / PRD 提取的总场景数
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


class CoverageTracker:
    """无状态覆盖率追踪工具。在 Runtime 中创建，贯穿整个测试会话。"""

    def __init__(
        self,
        explored_urls: list[str] | None = None,
        scenarios: list[dict[str, Any]] | None = None,
    ):
        self.explored_urls: set[str] = set(explored_urls or [])
        self.scenarios: list[dict[str, Any]] = scenarios or []
        self.covered_urls: set[str] = set()
        self.covered_scenarios: set[str] = set()

    def mark_url_covered(self, url: str) -> None:
        """标记一个 URL 已被测试覆盖。自动归一化为去掉 fragment 和 query 的基础路径。"""
        if url:
            parsed = urlparse(url)
            # Normalize: scheme + netloc + path (strip query & fragment)
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            self.covered_urls.add(normalized)

    def mark_scenario_covered(self, scenario_id: str) -> None:
        """标记一个业务场景已被测试覆盖。"""
        if scenario_id:
            self.covered_scenarios.add(scenario_id)

    def auto_match_scenario(self, test_case_title: str) -> None:
        """根据测试用例标题自动匹配业务场景（模糊匹配）。"""
        title_lower = test_case_title.lower()
        for scenario in self.scenarios:
            name = scenario.get("name", "").lower()
            if name and (name in title_lower or title_lower in name):
                self.mark_scenario_covered(scenario.get("id", ""))

    def get_page_coverage(self) -> dict[str, Any]:
        """返回页面覆盖率统计。"""
        # Normalize explored URLs too for fair comparison
        normalized_explored = set()
        for url in self.explored_urls:
            parsed = urlparse(url)
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            normalized_explored.add(normalized)

        total = len(normalized_explored) if normalized_explored else 1
        covered = len(self.covered_urls & normalized_explored)
        uncovered = list(normalized_explored - self.covered_urls)

        return {
            "total": len(normalized_explored),
            "covered": covered,
            "rate": round(covered / total, 2) if total > 0 else 0,
            "uncovered": uncovered[:10],  # limit for report display
        }

    def get_scenario_coverage(self) -> dict[str, Any]:
        """返回业务场景覆盖率统计。"""
        if not self.scenarios:
            return {"total": 0, "covered": 0, "rate": 0, "details": []}

        total = len(self.scenarios)
        covered = len(self.covered_scenarios)

        details = []
        for s in self.scenarios:
            sid = s.get("id", "")
            details.append({
                "id": sid,
                "name": s.get("name", ""),
                "covered": sid in self.covered_scenarios,
            })

        return {
            "total": total,
            "covered": covered,
            "rate": round(covered / total, 2) if total > 0 else 0,
            "details": details,
        }

    def get_coverage_report(self) -> dict[str, Any]:
        """返回完整的覆盖率报告数据，供 ReportBuilder 使用。"""
        report = {
            "page_coverage": self.get_page_coverage(),
            "scenario_coverage": self.get_scenario_coverage(),
        }
        print(f"[CoverageTracker] Page: {report['page_coverage']['covered']}/{report['page_coverage']['total']} "
              f"({report['page_coverage']['rate']*100:.0f}%) | "
              f"Scenarios: {report['scenario_coverage']['covered']}/{report['scenario_coverage']['total']} "
              f"({report['scenario_coverage']['rate']*100:.0f}%)")
        return report
