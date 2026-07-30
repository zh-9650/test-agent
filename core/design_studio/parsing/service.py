"""输入解析公共入口。"""

from __future__ import annotations

from pathlib import Path

from core.design_studio.contracts import ParsedArtifact, SourceInput
from core.design_studio.ingestion.artifact_store import FilesystemArtifactStore
from core.design_studio.ingestion.inspection import inspect_source, unavailable_source

from .base import finalize_artifact, finding
from .docx_parser import DocxParser
from .html_parser import HtmlPrototypeParser
from .image_parser import ImageParser
from .markdown_parser import MarkdownParser
from .registry import ParserRegistry
from .source_tree_parser import SourceTreeParser
from .structured_parser import StructuredDocumentParser


class InputParsingService:
    """把一份原始资料转换为结构化块和保真报告。"""

    def __init__(
        self,
        registry: ParserRegistry,
        *,
        artifact_store: FilesystemArtifactStore | None = None,
    ) -> None:
        self._registry = registry
        self._artifact_store = artifact_store

    @classmethod
    def default(
        cls,
        *,
        artifact_root: Path | None = None,
    ) -> "InputParsingService":
        return cls(
            ParserRegistry(
                [
                    DocxParser(),
                    MarkdownParser(),
                    StructuredDocumentParser(),
                    HtmlPrototypeParser(),
                    SourceTreeParser(),
                    ImageParser(),
                ]
            ),
            artifact_store=(
                FilesystemArtifactStore(artifact_root)
                if artifact_root is not None
                else None
            ),
        )

    def parse(self, source: SourceInput) -> ParsedArtifact:
        try:
            parse_source = (
                self._artifact_store.capture(source)
                if self._artifact_store is not None
                else source
            )
            artifact = inspect_source(parse_source)
        except (OSError, ValueError) as exc:
            artifact = unavailable_source(source)
            return finalize_artifact(
                artifact=artifact,
                parser_name="source_inspector",
                parser_version="1.0.0",
                blocks=[],
                detected_inventory={},
                parsed_inventory={},
                errors=[
                    finding(
                        "input.source_unreadable",
                        f"{type(exc).__name__}: {exc}",
                        str(source.path),
                    )
                ],
            )
        return self._registry.parse(parse_source, artifact)
