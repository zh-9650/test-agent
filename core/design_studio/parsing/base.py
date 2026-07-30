"""解析器公共协议和确定性保真核对。"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Protocol

from core.design_studio.contracts import (
    ParseFidelityReport,
    ParseFidelityStatus,
    ParseFinding,
    ParsedArtifact,
    ParsedBlock,
    SourceArtifact,
    SourceInput,
)


class SourceParser(Protocol):
    """格式解析器协议。"""

    parser_name: str
    parser_version: str

    def supports(self, source: SourceInput, artifact: SourceArtifact) -> bool: ...

    def parse(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> ParsedArtifact: ...

def make_block(
    artifact: SourceArtifact,
    *,
    parser_name: str,
    parser_version: str,
    block_type: str,
    locator: str,
    order: int,
    text_content: str = "",
    structured_content: dict[str, Any] | None = None,
    parent_block_id: str | None = None,
    asset_refs: list[str] | None = None,
) -> ParsedBlock:
    """创建内容寻址的解析块。

    source hash 或块内容变化都会生成新 ID，从而触发下游失效；未变化的来源重复解析
    会得到相同 ID。
    """

    structured = structured_content or {}
    identity = json.dumps(
        {
            "source_id": artifact.source_id,
            "source_hash": artifact.sha256,
            "parser": f"{parser_name}@{parser_version}",
            "type": block_type,
            "locator": locator,
            "parent_block_id": parent_block_id,
            "order": order,
            "text": text_content,
            "structured": structured,
            "asset_refs": asset_refs or [],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    block_id = "BLK-" + sha256(identity.encode("utf-8")).hexdigest()[:20].upper()
    return ParsedBlock(
        block_id=block_id,
        source_id=artifact.source_id,
        source_hash=artifact.sha256,
        parser_name=parser_name,
        parser_version=parser_version,
        block_type=block_type,
        text_content=text_content,
        structured_content=structured,
        parent_block_id=parent_block_id,
        order=order,
        locator=locator,
        asset_refs=asset_refs or [],
    )


def finding(code: str, message: str, locator: str | None = None) -> ParseFinding:
    return ParseFinding(code=code, message=message, locator=locator)


def finalize_artifact(
    *,
    artifact: SourceArtifact,
    parser_name: str,
    parser_version: str,
    blocks: list[ParsedBlock],
    detected_inventory: dict[str, int],
    parsed_inventory: dict[str, int],
    unsupported_features: list[ParseFinding] | None = None,
    warnings: list[ParseFinding] | None = None,
    errors: list[ParseFinding] | None = None,
    related_sources: list[SourceArtifact] | None = None,
    forced_status: ParseFidelityStatus | None = None,
) -> ParsedArtifact:
    """根据盘点差异、定位和错误确定报告状态，解析器不能自报 complete。"""

    unsupported = list(unsupported_features or [])
    report_warnings = list(warnings or [])
    report_errors = list(errors or [])

    for key in sorted(set(detected_inventory) | set(parsed_inventory)):
        detected = detected_inventory.get(key, 0)
        parsed = parsed_inventory.get(key, 0)
        if detected != parsed:
            report_warnings.append(
                finding(
                    "input.inventory_mismatch",
                    f"{key}: detected={detected}, parsed={parsed}",
                )
            )

    if any(not block.locator.strip() for block in blocks):
        report_errors.append(
            finding("input.missing_locator", "解析块存在空 locator。")
        )
    if any(
        block.source_id != artifact.source_id
        or block.source_hash != artifact.sha256
        for block in blocks
    ):
        report_errors.append(
            finding("input.source_identity_mismatch", "解析块与来源身份不一致。")
        )
    if len({block.block_id for block in blocks}) != len(blocks):
        report_errors.append(
            finding("input.duplicate_block_id", "解析结果存在重复 block_id。")
        )

    if forced_status is not None:
        status = forced_status
    elif report_errors:
        status = ParseFidelityStatus.FAILED
    elif unsupported or any(
        item.code == "input.inventory_mismatch" for item in report_warnings
    ):
        status = ParseFidelityStatus.PARTIAL
    else:
        status = ParseFidelityStatus.COMPLETE

    report_identity = json.dumps(
        {
            "source_id": artifact.source_id,
            "source_hash": artifact.sha256,
            "parser_name": parser_name,
            "parser_version": parser_version,
            "status": status.value,
            "detected": detected_inventory,
            "parsed": parsed_inventory,
            "unsupported": [
                item.model_dump(mode="json") for item in unsupported
            ],
            "warnings": [
                item.model_dump(mode="json") for item in report_warnings
            ],
            "errors": [
                item.model_dump(mode="json") for item in report_errors
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    report = ParseFidelityReport(
        report_id="PFR-" + sha256(report_identity.encode("utf-8")).hexdigest()[:20].upper(),
        source_id=artifact.source_id,
        source_hash=artifact.sha256,
        status=status,
        parser_name=parser_name,
        parser_version=parser_version,
        detected_inventory=detected_inventory,
        parsed_inventory=parsed_inventory,
        unsupported_features=unsupported,
        warnings=report_warnings,
        errors=report_errors,
    )
    return ParsedArtifact(
        source=artifact,
        blocks=blocks,
        related_sources=related_sources or [],
        fidelity_report=report,
    )
