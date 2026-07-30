"""原型源码目录/ZIP 的非执行式静态盘点。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from zipfile import BadZipFile, ZipFile

from core.design_studio.contracts import ParsedArtifact, SourceArtifact, SourceInput
from core.design_studio.ingestion.zip_safety import validate_zip_safety

from .base import finalize_artifact, finding, make_block


_IGNORED_DIRECTORIES = {
    ".git",
    ".idea",
    ".next",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "venv",
}
_TEXT_SUFFIXES = {
    ".cjs",
    ".css",
    ".html",
    ".htm",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".scss",
    ".ts",
    ".tsx",
    ".vue",
    ".yaml",
    ".yml",
}
_ROUTE_PATTERNS = [
    re.compile(r"<Route\b[^>]*\bpath\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE),
    re.compile(r"\bpath\s*:\s*[\"']([^\"']+)[\"']", re.IGNORECASE),
]
_COMPONENT_PATTERNS = [
    re.compile(r"\bfunction\s+([A-Z][A-Za-z0-9_]*)\s*\("),
    re.compile(r"\b(?:const|let)\s+([A-Z][A-Za-z0-9_]*)\s*=\s*(?:\([^)]*\)|\w+)\s*=>"),
    re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]*)\s+extends\s+(?:React\.)?Component"),
]
_FORM_PATTERNS = [
    re.compile(r"<form\b", re.IGNORECASE),
    re.compile(r"<Form\b"),
    re.compile(r"\buseForm\s*\("),
]
_API_PATTERNS = [
    re.compile(r"\bfetch\s*\(\s*[\"']([^\"']+)[\"']"),
    re.compile(
        r"\baxios\.(?:get|post|put|patch|delete)\s*\(\s*[\"']([^\"']+)[\"']"
    ),
    re.compile(r"\burl\s*:\s*[\"']([^\"']+)[\"']"),
]


class _SourceBundle:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._zip: ZipFile | None = None
        if self.path.is_dir():
            self.root = self.path
            self.names = {
                item.relative_to(self.root).as_posix()
                for item in self.root.rglob("*")
                if item.is_file()
            }
        elif self.path.suffix.casefold() == ".zip":
            self.root = None
            self._zip = ZipFile(self.path)
            validate_zip_safety(self._zip, label="源码 ZIP")
            unsafe = [
                name
                for name in self._zip.namelist()
                if name
                and (
                    PurePosixPath(name).is_absolute()
                    or ".." in PurePosixPath(name).parts
                )
            ]
            if unsafe:
                raise ValueError(f"ZIP 包含越界路径: {unsafe[0]}")
            self.names = {
                name.rstrip("/")
                for name in self._zip.namelist()
                if name and not name.endswith("/")
            }
        else:
            raise ValueError("源码输入必须是目录或 ZIP")

    def read(self, relative: str) -> bytes:
        if self._zip is not None:
            return self._zip.read(relative)
        assert self.root is not None
        return (self.root / PurePosixPath(relative)).read_bytes()

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()


def _decode_source(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


class SourceTreeParser:
    parser_name = "prototype_source_tree_static"
    parser_version = "1.0.0"

    def supports(self, source: SourceInput, artifact: SourceArtifact) -> bool:
        del artifact
        return source.source_kind.casefold() in {
            "prototype_source",
            "prototype_source_tree",
            "source_tree",
        } and (
            source.path.is_dir() or source.path.suffix.casefold() == ".zip"
        )

    def parse(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> ParsedArtifact:
        bundle: _SourceBundle | None = None
        try:
            bundle = _SourceBundle(source.path)
            return self._parse_bundle(artifact, bundle)
        except (BadZipFile, KeyError, OSError, UnicodeError, ValueError) as exc:
            return finalize_artifact(
                artifact=artifact,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                blocks=[],
                detected_inventory={},
                parsed_inventory={},
                errors=[
                    finding(
                        "input.source_tree_unreadable",
                        f"{type(exc).__name__}: {exc}",
                        artifact.original_name,
                    )
                ],
            )
        finally:
            if bundle is not None:
                bundle.close()

    def _parse_bundle(
        self,
        artifact: SourceArtifact,
        bundle: _SourceBundle,
    ) -> ParsedArtifact:
        ignored = sorted(
            (
                name
                for name in bundle.names
                if _IGNORED_DIRECTORIES.intersection(PurePosixPath(name).parts)
            ),
            key=str.casefold,
        )
        ignored_set = set(ignored)
        included = sorted(bundle.names - ignored_set, key=str.casefold)
        blocks = []
        order = 0
        occurrences: dict[str, list[tuple[str, int, str]]] = {
            "route": [],
            "component": [],
            "form": [],
            "api_call": [],
        }

        for relative in included:
            data = bundle.read(relative)
            order += 1
            blocks.append(
                make_block(
                    artifact,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    block_type="source_file",
                    locator=relative,
                    order=order,
                    structured_content={
                        "byte_size": len(data),
                        "sha256": sha256(data).hexdigest().upper(),
                        "suffix": PurePosixPath(relative).suffix.casefold(),
                    },
                )
            )
            if PurePosixPath(relative).suffix.casefold() not in _TEXT_SUFFIXES:
                continue
            text = _decode_source(data)
            if text is None:
                continue
            for pattern in _ROUTE_PATTERNS:
                for match in pattern.finditer(text):
                    occurrences["route"].append(
                        (relative, _line_number(text, match.start()), match.group(1))
                    )
            for pattern in _COMPONENT_PATTERNS:
                for match in pattern.finditer(text):
                    occurrences["component"].append(
                        (relative, _line_number(text, match.start()), match.group(1))
                    )
            form_matches = {
                match.start()
                for pattern in _FORM_PATTERNS
                for match in pattern.finditer(text)
            }
            for offset in sorted(form_matches):
                occurrences["form"].append(
                    (relative, _line_number(text, offset), "form")
                )
            for pattern in _API_PATTERNS:
                for match in pattern.finditer(text):
                    occurrences["api_call"].append(
                        (relative, _line_number(text, match.start()), match.group(1))
                    )

        for relative in ignored:
            order += 1
            blocks.append(
                make_block(
                    artifact,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    block_type="ignored_file",
                    locator=relative,
                    order=order,
                    structured_content={
                        "reason": "generated_or_dependency_directory"
                    },
                )
            )

        for block_type, values in occurrences.items():
            seen: set[tuple[str, int, str]] = set()
            for relative, line, value in values:
                identity = (relative, line, value)
                if identity in seen:
                    continue
                seen.add(identity)
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type=block_type,
                        locator=f"{relative}::line[{line}]",
                        order=order,
                        text_content=value,
                    )
                )

        detected = {
            "included_files": len(included),
            "ignored_files": len(ignored),
            "routes": len(
                {
                    value
                    for value in occurrences["route"]
                }
            ),
            "components": len(
                {
                    value
                    for value in occurrences["component"]
                }
            ),
            "forms": len(
                {
                    value
                    for value in occurrences["form"]
                }
            ),
            "api_calls": len(
                {
                    value
                    for value in occurrences["api_call"]
                }
            ),
        }
        type_by_inventory = {
            "included_files": "source_file",
            "ignored_files": "ignored_file",
            "routes": "route",
            "components": "component",
            "forms": "form",
            "api_calls": "api_call",
        }
        parsed = {
            key: sum(block.block_type == block_type for block in blocks)
            for key, block_type in type_by_inventory.items()
        }
        return finalize_artifact(
            artifact=artifact,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            blocks=blocks,
            detected_inventory=detected,
            parsed_inventory=parsed,
            unsupported_features=[
                finding(
                    "input.static_source_semantics",
                    "静态盘点不执行源码，不能证明运行时路由、条件渲染和动态接口绑定。",
                )
            ],
        )
