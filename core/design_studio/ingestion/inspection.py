"""原始资料的确定性盘点和身份计算。"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import mimetypes
from pathlib import Path

from core.design_studio.contracts import SourceArtifact, SourceInput


def _directory_manifest(path: Path) -> tuple[bytes, int]:
    rows: list[str] = []
    total_size = 0
    symlinks = [candidate for candidate in path.rglob("*") if candidate.is_symlink()]
    if symlinks:
        relative = symlinks[0].relative_to(path).as_posix()
        raise ValueError(f"资料目录包含符号链接，拒绝越界读取: {relative}")
    for item in sorted(
        (candidate for candidate in path.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(path).as_posix().casefold(),
    ):
        data = item.read_bytes()
        total_size += len(data)
        relative = item.relative_to(path).as_posix()
        rows.append(f"{relative}\t{len(data)}\t{sha256(data).hexdigest().upper()}")
    return "\n".join(rows).encode("utf-8"), total_size


def inspect_source(source: SourceInput) -> SourceArtifact:
    """读取原件元数据；目录 hash 是确定性文件清单的 hash。"""

    path = source.path.resolve()
    if source.path.is_symlink():
        raise ValueError("原始资料路径不能是符号链接")
    if path.is_dir():
        payload, byte_size = _directory_manifest(path)
        media_type = "inode/directory"
    else:
        payload = path.read_bytes()
        byte_size = len(payload)
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    digest = sha256(payload).hexdigest().upper()
    return SourceArtifact(
        source_id=source.source_id,
        source_kind=source.source_kind,
        authority=source.authority,
        required=source.required,
        media_type=media_type,
        original_name=source.original_name or path.name,
        origin_uri=source.origin_uri,
        local_path=str(path),
        sha256=digest,
        byte_size=byte_size,
        source_version=source.source_version or digest,
        captured_at=datetime.now(timezone.utc),
        secret_refs=list(source.secret_refs),
    )


def unavailable_source(source: SourceInput) -> SourceArtifact:
    """为无法读取的输入保留可报告的来源身份。"""

    return SourceArtifact(
        source_id=source.source_id,
        source_kind=source.source_kind,
        authority=source.authority,
        required=source.required,
        media_type="application/octet-stream",
        original_name=source.original_name or source.path.name,
        origin_uri=source.origin_uri,
        local_path=str(source.path),
        sha256="",
        byte_size=0,
        source_version=source.source_version or "unavailable",
        captured_at=datetime.now(timezone.utc),
        secret_refs=list(source.secret_refs),
    )
