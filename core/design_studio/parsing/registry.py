"""按格式路由解析器，不允许静默回退为空文本。"""

from __future__ import annotations

from core.design_studio.contracts import (
    ParseFidelityStatus,
    ParsedArtifact,
    SourceArtifact,
    SourceInput,
)

from .base import SourceParser, finalize_artifact, finding


class ParserRegistry:
    def __init__(self, parsers: list[SourceParser]) -> None:
        self._parsers = list(parsers)

    def select(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> SourceParser | None:
        return next(
            (
                parser
                for parser in self._parsers
                if parser.supports(source, artifact)
            ),
            None,
        )

    def parse(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> ParsedArtifact:
        parser = self.select(source, artifact)
        if parser is not None:
            return parser.parse(source, artifact)
        return finalize_artifact(
            artifact=artifact,
            parser_name="parser_registry",
            parser_version="1.0.0",
            blocks=[],
            detected_inventory={},
            parsed_inventory={},
            unsupported_features=[
                finding(
                    "input.unsupported_format",
                    f"未注册解析器: {artifact.media_type} ({artifact.original_name})",
                    artifact.original_name,
                )
            ],
            forced_status=ParseFidelityStatus.UNSUPPORTED,
        )
