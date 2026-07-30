"""G0 输入保真门禁。"""

from __future__ import annotations

from collections.abc import Iterable

from core.design_studio.contracts import (
    FidelityGateDecision,
    FidelityGatePolicy,
    ParseFidelityStatus,
    ParsedArtifact,
)

from .base import finding


class ParseFidelityGate:
    """只根据合同和策略做确定性判断，不调用 LLM。"""

    def __init__(self, policy: FidelityGatePolicy | None = None) -> None:
        self.policy = policy or FidelityGatePolicy()

    def evaluate(
        self,
        artifacts: Iterable[ParsedArtifact],
    ) -> FidelityGateDecision:
        blocked: set[str] = set()
        findings = []
        for parsed in artifacts:
            source = parsed.source
            report = parsed.fidelity_report
            integrity_failed = False
            if (
                report.source_id != source.source_id
                or report.source_hash != source.sha256
            ):
                integrity_failed = True
                findings.append(
                    finding(
                        "input.report_source_mismatch",
                        f"{source.source_id} 的保真报告与来源身份不一致。",
                    )
                )
            if any(
                block.source_id != source.source_id
                or block.source_hash != source.sha256
                or not block.locator.strip()
                for block in parsed.blocks
            ):
                integrity_failed = True
                findings.append(
                    finding(
                        "input.block_traceability_broken",
                        f"{source.source_id} 存在无法回查原件的解析块。",
                    )
                )
            if any(
                report.detected_inventory.get(key, 0)
                != report.parsed_inventory.get(key, 0)
                for key in set(report.detected_inventory)
                | set(report.parsed_inventory)
            ):
                integrity_failed = True
                findings.append(
                    finding(
                        "input.inventory_mismatch",
                        f"{source.source_id} 的结构盘点与解析计数不一致。",
                    )
                )
            if integrity_failed:
                blocked.add(source.source_id)
                continue

            allowed_statuses = (
                self.policy.required_allowed_statuses
                if source.required
                else self.policy.optional_allowed_statuses
            )
            if report.status not in allowed_statuses:
                blocked.add(source.source_id)
                findings.append(
                    finding(
                        (
                            "input.required_source_not_complete"
                            if source.required
                            else "input.optional_source_not_allowed"
                        ),
                        (
                            f"{source.source_id} 是必要来源，解析状态为 "
                            f"{report.status.value}，门禁只接受 "
                            f"{sorted(item.value for item in allowed_statuses)}。"
                        ),
                    )
                )
            elif (
                not source.required
                and report.status != ParseFidelityStatus.COMPLETE
            ):
                findings.append(
                    finding(
                        "input.optional_source_degraded",
                        f"{source.source_id} 是可选来源，解析状态为 {report.status.value}。",
                    )
                )

        return FidelityGateDecision(
            passed=not blocked,
            blocked_source_ids=sorted(blocked),
            findings=findings,
        )
