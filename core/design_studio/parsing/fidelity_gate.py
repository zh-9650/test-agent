"""G0 输入保真门禁。"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping

from core.design_studio.contracts import (
    FidelityGateDecision,
    FidelityGatePolicy,
    ParseFidelityStatus,
    ParsedArtifact,
    SourceInput,
)
from core.design_studio.ingestion.inspection import inspect_source

from .base import finding, make_block


class ParseFidelityGate:
    """只根据合同和策略做确定性判断，不调用 LLM。"""

    def __init__(self, policy: FidelityGatePolicy | None = None) -> None:
        self.policy = policy or FidelityGatePolicy()

    def evaluate(
        self,
        artifacts: Iterable[ParsedArtifact],
        *,
        expected_sources: Iterable[SourceInput],
        current_source_hashes: Mapping[str, str] | None = None,
    ) -> FidelityGateDecision:
        blocked: set[str] = set()
        findings = []
        expected_list = list(expected_sources)
        artifact_list = list(artifacts)
        expected_by_id: dict[str, SourceInput] = {}
        duplicate_expected_ids: set[str] = set()
        for expected in expected_list:
            if expected.source_id in expected_by_id:
                duplicate_expected_ids.add(expected.source_id)
            expected_by_id[expected.source_id] = expected
        if duplicate_expected_ids:
            blocked.update(duplicate_expected_ids)
            findings.append(
                finding(
                    "input.duplicate_expected_source",
                    "来源清单存在重复 source_id: "
                    + ", ".join(sorted(duplicate_expected_ids)),
                )
            )

        artifacts_by_id: dict[str, ParsedArtifact] = {}
        duplicate_artifact_ids: set[str] = set()
        for parsed in artifact_list:
            source_id = parsed.source.source_id
            if source_id in artifacts_by_id:
                duplicate_artifact_ids.add(source_id)
            artifacts_by_id[source_id] = parsed
        if duplicate_artifact_ids:
            blocked.update(duplicate_artifact_ids)
            findings.append(
                finding(
                    "input.duplicate_source_version",
                    "同一 source_id 同时出现多个解析版本: "
                    + ", ".join(sorted(duplicate_artifact_ids)),
                )
            )

        if self.policy.require_at_least_one_source and not expected_list:
            blocked.add("__source_manifest__")
            findings.append(
                finding(
                    "input.empty_source_manifest",
                    "G0 必须绑定至少一份预期来源，不能对空输入判定通过。",
                )
            )

        for source_id, expected in expected_by_id.items():
            if source_id in artifacts_by_id:
                continue
            if expected.required:
                blocked.add(source_id)
                findings.append(
                    finding(
                        "input.required_source_missing",
                        f"必要来源 {source_id} 没有解析产物。",
                    )
                )
            else:
                findings.append(
                    finding(
                        "input.optional_source_missing",
                        f"可选来源 {source_id} 没有解析产物。",
                    )
                )

        for parsed in artifact_list:
            source = parsed.source
            report = parsed.fidelity_report
            integrity_failed = False
            expected = expected_by_id.get(source.source_id)
            if expected is None:
                integrity_failed = True
                findings.append(
                    finding(
                        "input.unexpected_source",
                        f"{source.source_id} 不在当前会话来源清单中。",
                    )
                )
            elif (
                expected.source_kind != source.source_kind
                or expected.authority != source.authority
                or expected.required != source.required
            ):
                integrity_failed = True
                findings.append(
                    finding(
                        "input.source_contract_mismatch",
                        f"{source.source_id} 的来源类型、权威角色或必要性已变化。",
                    )
                )
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
                block.parser_name != report.parser_name
                or block.parser_version != report.parser_version
                for block in parsed.blocks
            ):
                integrity_failed = True
                findings.append(
                    finding(
                        "input.parser_identity_mismatch",
                        f"{source.source_id} 的解析块与报告解析器身份不一致。",
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
                make_block(
                    source,
                    parser_name=block.parser_name,
                    parser_version=block.parser_version,
                    block_type=block.block_type,
                    locator=block.locator,
                    order=block.order,
                    text_content=block.text_content,
                    structured_content=block.structured_content,
                    parent_block_id=block.parent_block_id,
                    asset_refs=block.asset_refs,
                ).block_id
                != block.block_id
                for block in parsed.blocks
            ):
                integrity_failed = True
                findings.append(
                    finding(
                        "input.block_content_mismatch",
                        f"{source.source_id} 的 block_id 与块内容不一致。",
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
            status_is_inconsistent = (
                bool(report.errors)
                and report.status != ParseFidelityStatus.FAILED
            ) or (
                bool(report.unsupported_features)
                and report.status == ParseFidelityStatus.COMPLETE
            ) or (
                report.status == ParseFidelityStatus.FAILED
                and not report.errors
            ) or (
                report.status == ParseFidelityStatus.UNSUPPORTED
                and not report.unsupported_features
            )
            if status_is_inconsistent:
                integrity_failed = True
                findings.append(
                    finding(
                        "input.invalid_fidelity_status",
                        f"{source.source_id} 的状态与 errors/unsupported_features 不一致。",
                    )
                )
            if source.sha256:
                try:
                    current_artifact = inspect_source(
                        SourceInput(
                            source_id=source.source_id,
                            path=source.local_path,
                            source_kind=source.source_kind,
                            authority=source.authority,
                            required=source.required,
                            original_name=source.original_name,
                            origin_uri=source.origin_uri,
                            source_version=source.source_version,
                            secret_refs=source.secret_refs,
                        )
                    )
                except (OSError, ValueError) as exc:
                    integrity_failed = True
                    findings.append(
                        finding(
                            "input.source_recheck_failed",
                            f"{source.source_id} 无法重新校验原件: {type(exc).__name__}: {exc}",
                        )
                    )
                else:
                    if current_artifact.sha256 != source.sha256:
                        integrity_failed = True
                        findings.append(
                            finding(
                                "input.stale_source",
                                f"{source.source_id} 的当前原件 hash 已变化。",
                            )
                        )
            expected_current_hash = (current_source_hashes or {}).get(
                source.source_id
            )
            if (
                expected_current_hash is not None
                and expected_current_hash != source.sha256
            ):
                integrity_failed = True
                findings.append(
                    finding(
                        "input.stale_source",
                        f"{source.source_id} 不是会话当前登记的来源版本。",
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
