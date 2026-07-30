"""保留 OOXML 结构和定位的 DOCX 解析器。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from core.design_studio.contracts import ParsedArtifact, SourceArtifact, SourceInput

from .base import finalize_artifact, finding, make_block


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {
    "w": _WORD_NS,
    "r": _REL_NS,
    "a": _DRAWING_NS,
    "pr": _PACKAGE_REL_NS,
}


def _text(node: ET.Element) -> str:
    return "".join(item.text or "" for item in node.findall(".//w:t", _NS)).strip()


def _relationship_path(part_name: str) -> str:
    part = Path(part_name)
    return (part.parent / "_rels" / f"{part.name}.rels").as_posix()


class DocxParser:
    parser_name = "docx_ooxml"
    parser_version = "1.0.0"

    def supports(self, source: SourceInput, artifact: SourceArtifact) -> bool:
        return (
            source.path.suffix.casefold() == ".docx"
            or artifact.media_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    def parse(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> ParsedArtifact:
        try:
            return self._parse(source, artifact)
        except (BadZipFile, ET.ParseError, KeyError, OSError, ValueError) as exc:
            return finalize_artifact(
                artifact=artifact,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                blocks=[],
                detected_inventory={},
                parsed_inventory={},
                errors=[
                    finding(
                        "input.docx_corrupt",
                        f"{type(exc).__name__}: {exc}",
                        artifact.original_name,
                    )
                ],
            )

    def _parse(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> ParsedArtifact:
        del source
        with ZipFile(artifact.local_path) as package:
            names = set(package.namelist())
            if "word/document.xml" not in names:
                raise ValueError("DOCX 缺少 word/document.xml")

            part_names = ["word/document.xml"]
            headers = sorted(
                name
                for name in names
                if name.startswith("word/header") and name.endswith(".xml")
            )
            footers = sorted(
                name
                for name in names
                if name.startswith("word/footer") and name.endswith(".xml")
            )
            part_names.extend(headers)
            part_names.extend(footers)
            parts = {
                name: ET.fromstring(package.read(name))
                for name in part_names
            }

            style_names: dict[str, str] = {}
            if "word/styles.xml" in names:
                styles = ET.fromstring(package.read("word/styles.xml"))
                for style in styles.findall(".//w:style", _NS):
                    style_id = style.attrib.get(f"{{{_WORD_NS}}}styleId", "")
                    name = style.find("./w:name", _NS)
                    style_names[style_id] = (
                        name.attrib.get(f"{{{_WORD_NS}}}val", "")
                        if name is not None
                        else ""
                    )

            relationships: dict[str, dict[str, str]] = {}
            for part_name in part_names:
                rel_name = _relationship_path(part_name)
                rels: dict[str, str] = {}
                if rel_name in names:
                    root = ET.fromstring(package.read(rel_name))
                    for relationship in root:
                        rels[relationship.attrib.get("Id", "")] = (
                            relationship.attrib.get("Target", "")
                        )
                relationships[part_name] = rels

            media = sorted(
                name
                for name in names
                if name.startswith("word/media/") and not name.endswith("/")
            )
            detected = {
                "paragraphs": sum(
                    len(root.findall(".//w:p", _NS)) for root in parts.values()
                ),
                "tables": sum(
                    len(root.findall(".//w:tbl", _NS)) for root in parts.values()
                ),
                "rows": sum(
                    len(root.findall(".//w:tr", _NS)) for root in parts.values()
                ),
                "cells": sum(
                    len(root.findall(".//w:tc", _NS)) for root in parts.values()
                ),
                "drawings": sum(
                    len(root.findall(".//w:drawing", _NS)) for root in parts.values()
                ),
                "media": len(media),
                "hyperlinks": sum(
                    len(root.findall(".//w:hyperlink", _NS)) for root in parts.values()
                ),
                "headers": len(headers),
                "footers": len(footers),
            }

            blocks = []
            order = 0
            unsupported = []
            warnings = []
            for part_name, root in parts.items():
                part_type = (
                    "header"
                    if part_name in headers
                    else "footer"
                    if part_name in footers
                    else "document"
                )
                if part_type in {"header", "footer"}:
                    order += 1
                    blocks.append(
                        make_block(
                            artifact,
                            parser_name=self.parser_name,
                            parser_version=self.parser_version,
                            block_type=f"{part_type}_part",
                            locator=part_name,
                            order=order,
                        )
                    )

                for index, paragraph in enumerate(
                    root.findall(".//w:p", _NS), start=1
                ):
                    style = paragraph.find("./w:pPr/w:pStyle", _NS)
                    style_id = (
                        style.attrib.get(f"{{{_WORD_NS}}}val", "")
                        if style is not None
                        else ""
                    )
                    order += 1
                    blocks.append(
                        make_block(
                            artifact,
                            parser_name=self.parser_name,
                            parser_version=self.parser_version,
                            block_type="paragraph",
                            locator=f"{part_name}::paragraph[{index}]",
                            order=order,
                            text_content=_text(paragraph),
                            structured_content={
                                "part_type": part_type,
                                "style_id": style_id,
                                "style_name": style_names.get(style_id, ""),
                            },
                        )
                    )

                for index, table in enumerate(root.findall(".//w:tbl", _NS), start=1):
                    order += 1
                    blocks.append(
                        make_block(
                            artifact,
                            parser_name=self.parser_name,
                            parser_version=self.parser_version,
                            block_type="table",
                            locator=f"{part_name}::table[{index}]",
                            order=order,
                            structured_content={
                                "row_count": len(table.findall("./w:tr", _NS))
                            },
                        )
                    )
                for index, row in enumerate(root.findall(".//w:tr", _NS), start=1):
                    order += 1
                    blocks.append(
                        make_block(
                            artifact,
                            parser_name=self.parser_name,
                            parser_version=self.parser_version,
                            block_type="table_row",
                            locator=f"{part_name}::row[{index}]",
                            order=order,
                            structured_content={
                                "cell_count": len(row.findall("./w:tc", _NS))
                            },
                        )
                    )
                for index, cell in enumerate(root.findall(".//w:tc", _NS), start=1):
                    grid_span = cell.find("./w:tcPr/w:gridSpan", _NS)
                    vertical_merge = cell.find("./w:tcPr/w:vMerge", _NS)
                    order += 1
                    blocks.append(
                        make_block(
                            artifact,
                            parser_name=self.parser_name,
                            parser_version=self.parser_version,
                            block_type="table_cell",
                            locator=f"{part_name}::cell[{index}]",
                            order=order,
                            text_content=_text(cell),
                            structured_content={
                                "grid_span": (
                                    grid_span.attrib.get(f"{{{_WORD_NS}}}val", "1")
                                    if grid_span is not None
                                    else "1"
                                ),
                                "vertical_merge": (
                                    vertical_merge.attrib.get(
                                        f"{{{_WORD_NS}}}val", "continue"
                                    )
                                    if vertical_merge is not None
                                    else None
                                ),
                            },
                        )
                    )

                for index, drawing in enumerate(
                    root.findall(".//w:drawing", _NS), start=1
                ):
                    relation_ids = [
                        blip.attrib.get(f"{{{_REL_NS}}}embed", "")
                        for blip in drawing.findall(".//a:blip", _NS)
                    ]
                    relation_ids = [item for item in relation_ids if item]
                    targets = [
                        relationships[part_name].get(rel_id, "")
                        for rel_id in relation_ids
                    ]
                    order += 1
                    blocks.append(
                        make_block(
                            artifact,
                            parser_name=self.parser_name,
                            parser_version=self.parser_version,
                            block_type="drawing",
                            locator=f"{part_name}::drawing[{index}]",
                            order=order,
                            structured_content={
                                "relationship_ids": relation_ids,
                                "targets": targets,
                            },
                            asset_refs=[target for target in targets if target],
                        )
                    )
                    if not relation_ids:
                        unsupported.append(
                            finding(
                                "input.unsupported_structure",
                                "drawing 没有嵌入图片关系，可能是尚未保真解析的图表或绘图对象。",
                                f"{part_name}::drawing[{index}]",
                            )
                        )

                for index, hyperlink in enumerate(
                    root.findall(".//w:hyperlink", _NS), start=1
                ):
                    relation_id = hyperlink.attrib.get(f"{{{_REL_NS}}}id", "")
                    order += 1
                    blocks.append(
                        make_block(
                            artifact,
                            parser_name=self.parser_name,
                            parser_version=self.parser_version,
                            block_type="hyperlink",
                            locator=f"{part_name}::hyperlink[{index}]",
                            order=order,
                            text_content=_text(hyperlink),
                            structured_content={
                                "relationship_id": relation_id,
                                "target": relationships[part_name].get(
                                    relation_id, ""
                                ),
                                "anchor": hyperlink.attrib.get(
                                    f"{{{_WORD_NS}}}anchor", ""
                                ),
                            },
                        )
                    )

                feature_queries = {
                    "textboxes": ".//w:txbxContent",
                    "embedded_objects": ".//w:object",
                    "alt_chunks": ".//w:altChunk",
                    "tracked_insertions": ".//w:ins",
                    "tracked_deletions": ".//w:del",
                    "smart_art": (
                        ".//{http://schemas.openxmlformats.org/"
                        "drawingml/2006/diagram}relIds"
                    ),
                }
                for feature, query in feature_queries.items():
                    count = len(root.findall(query, _NS))
                    if count:
                        unsupported.append(
                            finding(
                                "input.unsupported_structure",
                                f"DOCX 包含当前未保真解析的 {feature}: {count}",
                                part_name,
                            )
                        )

            for index, media_name in enumerate(media, start=1):
                data = package.read(media_name)
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="media",
                        locator=media_name,
                        order=order,
                        structured_content={
                            "byte_size": len(data),
                            "sha256": sha256(data).hexdigest().upper(),
                        },
                        asset_refs=[media_name],
                    )
                )

            if "word/comments.xml" in names:
                comments = ET.fromstring(package.read("word/comments.xml"))
                comment_count = len(comments.findall(".//w:comment", _NS))
                if comment_count:
                    unsupported.append(
                        finding(
                            "input.unsupported_structure",
                            f"DOCX 批注尚未解析: {comment_count}",
                            "word/comments.xml",
                        )
                    )

            parsed = {
                "paragraphs": sum(item.block_type == "paragraph" for item in blocks),
                "tables": sum(item.block_type == "table" for item in blocks),
                "rows": sum(item.block_type == "table_row" for item in blocks),
                "cells": sum(item.block_type == "table_cell" for item in blocks),
                "drawings": sum(item.block_type == "drawing" for item in blocks),
                "media": sum(item.block_type == "media" for item in blocks),
                "hyperlinks": sum(item.block_type == "hyperlink" for item in blocks),
                "headers": sum(item.block_type == "header_part" for item in blocks),
                "footers": sum(item.block_type == "footer_part" for item in blocks),
            }
            return finalize_artifact(
                artifact=artifact,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                blocks=blocks,
                detected_inventory=detected,
                parsed_inventory=parsed,
                unsupported_features=unsupported,
                warnings=warnings,
            )
