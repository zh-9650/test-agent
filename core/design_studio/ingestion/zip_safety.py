"""ZIP 类输入的资源上限和路径安全检查。"""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from zipfile import ZipFile


MAX_ZIP_ENTRIES = 20_000
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 1_073_741_824
MAX_ZIP_SINGLE_FILE_BYTES = 268_435_456
MAX_ZIP_OVERALL_COMPRESSION_RATIO = 500
MAX_ZIP_SINGLE_FILE_COMPRESSION_RATIO = 2_000


def validate_zip_safety(package: ZipFile, *, label: str) -> None:
    infos = [info for info in package.infolist() if not info.is_dir()]
    if len(infos) > MAX_ZIP_ENTRIES:
        raise ValueError(
            f"{label} 文件数超过上限: {len(infos)} > {MAX_ZIP_ENTRIES}"
        )

    total_uncompressed = 0
    total_compressed = 0
    for info in infos:
        normalized = info.filename.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or ".." in path.parts
            or re.match(r"^[A-Za-z]:", normalized)
        ):
            raise ValueError(f"{label} 包含越界路径: {info.filename}")
        unix_mode = (info.external_attr >> 16) & 0o170000
        if unix_mode == 0o120000:
            raise ValueError(f"{label} 包含符号链接条目: {info.filename}")
        if info.flag_bits & 0x1:
            raise ValueError(f"{label} 包含加密条目: {info.filename}")
        if info.file_size > MAX_ZIP_SINGLE_FILE_BYTES:
            raise ValueError(
                f"{label} 单文件解压大小超过上限: {info.filename}"
            )
        if info.file_size and not info.compress_size:
            raise ValueError(f"{label} 条目压缩大小异常: {info.filename}")
        if info.compress_size:
            ratio = info.file_size / info.compress_size
            if ratio > MAX_ZIP_SINGLE_FILE_COMPRESSION_RATIO:
                raise ValueError(
                    f"{label} 单文件压缩比异常: {info.filename} ({ratio:.1f})"
                )
        total_uncompressed += info.file_size
        total_compressed += info.compress_size

    if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
        raise ValueError(
            f"{label} 总解压大小超过上限: {total_uncompressed}"
        )
    if total_uncompressed and not total_compressed:
        raise ValueError(f"{label} 总压缩大小异常")
    if total_compressed:
        overall_ratio = total_uncompressed / total_compressed
        if overall_ratio > MAX_ZIP_OVERALL_COMPRESSION_RATIO:
            raise ValueError(
                f"{label} 总压缩比异常: {overall_ratio:.1f}"
            )
