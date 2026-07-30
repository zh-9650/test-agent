"""原始资料、解析产物和输入保真门禁合同。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Authority(str, Enum):
    """来源在设计阶段的证据角色。"""

    NORMATIVE = "normative"
    OBSERVED = "observed"
    TECHNICAL = "technical"
    HISTORICAL = "historical"


class ParseFidelityStatus(str, Enum):
    """单个来源的解析保真结论。"""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class SourceInput(BaseModel):
    """调用方登记的一份原始资料。

    ``entry_points`` 用于目录或 ZIP 类输入，显式限定目标页面/文件；为空时由格式解析器
    选择该格式下全部可识别入口。
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    path: Path
    source_kind: str = Field(min_length=1)
    authority: Authority
    required: bool = True
    original_name: str | None = None
    origin_uri: str | None = None
    source_version: str | None = None
    entry_points: list[str] = Field(default_factory=list)
    secret_refs: list[str] = Field(default_factory=list)


class SourceArtifact(BaseModel):
    """不可被解析文本替代的来源快照元数据。"""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_kind: str
    authority: Authority
    required: bool
    media_type: str
    original_name: str
    origin_uri: str | None = None
    local_path: str
    sha256: str
    byte_size: int = Field(ge=0)
    source_version: str
    captured_at: datetime
    secret_refs: list[str] = Field(default_factory=list)


class ParsedBlock(BaseModel):
    """一段可稳定回查原件的解析结果。"""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    source_id: str
    source_hash: str
    parser_name: str
    parser_version: str
    block_type: str
    text_content: str = ""
    structured_content: dict[str, Any] = Field(default_factory=dict)
    parent_block_id: str | None = None
    order: int = Field(ge=0)
    locator: str
    asset_refs: list[str] = Field(default_factory=list)


class ParseFinding(BaseModel):
    """稳定错误码和可读说明。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    locator: str | None = None


class ParseFidelityReport(BaseModel):
    """格式盘点与解析结果之间的机器可检查核对报告。"""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    source_id: str
    source_hash: str
    status: ParseFidelityStatus
    parser_name: str
    parser_version: str
    detected_inventory: dict[str, int] = Field(default_factory=dict)
    parsed_inventory: dict[str, int] = Field(default_factory=dict)
    unsupported_features: list[ParseFinding] = Field(default_factory=list)
    warnings: list[ParseFinding] = Field(default_factory=list)
    errors: list[ParseFinding] = Field(default_factory=list)


class ParsedArtifact(BaseModel):
    """一份来源的元数据、解析块和保真报告。"""

    model_config = ConfigDict(extra="forbid")

    source: SourceArtifact
    blocks: list[ParsedBlock] = Field(default_factory=list)
    related_sources: list[SourceArtifact] = Field(default_factory=list)
    fidelity_report: ParseFidelityReport


class FidelityGatePolicy(BaseModel):
    """G0 默认策略。

    必要来源必须 complete；可选来源允许 partial，但仍产生非阻断 finding。
    """

    model_config = ConfigDict(extra="forbid")

    required_allowed_statuses: set[ParseFidelityStatus] = Field(
        default_factory=lambda: {ParseFidelityStatus.COMPLETE}
    )
    optional_allowed_statuses: set[ParseFidelityStatus] = Field(
        default_factory=lambda: {
            ParseFidelityStatus.COMPLETE,
            ParseFidelityStatus.PARTIAL,
            ParseFidelityStatus.FAILED,
            ParseFidelityStatus.UNSUPPORTED,
        }
    )


class FidelityGateDecision(BaseModel):
    """G0 的确定性通过或阻断结论。"""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    blocked_source_ids: list[str] = Field(default_factory=list)
    findings: list[ParseFinding] = Field(default_factory=list)
