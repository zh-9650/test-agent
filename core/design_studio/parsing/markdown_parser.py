"""Markdown / TXT 结构解析器。"""

from __future__ import annotations

import re

from core.design_studio.contracts import ParsedArtifact, SourceArtifact, SourceInput

from .base import finalize_artifact, finding, make_block


_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})([^`]*)$")
_TABLE_DIVIDER = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*$"
)
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")


def _table_regions(lines: list[str]) -> list[tuple[int, int, list[int]]]:
    """返回 (header index, last index, row indexes)，不含分隔线。"""

    regions: list[tuple[int, int, list[int]]] = []
    occupied: set[int] = set()
    for divider_index, line in enumerate(lines):
        if divider_index == 0 or divider_index in occupied:
            continue
        if not _TABLE_DIVIDER.match(line) or "|" not in lines[divider_index - 1]:
            continue
        rows = [divider_index - 1]
        cursor = divider_index + 1
        while cursor < len(lines):
            value = lines[cursor]
            if not value.strip() or "|" not in value:
                break
            if _HEADING.match(value) or _FENCE.match(value):
                break
            rows.append(cursor)
            cursor += 1
        last = rows[-1] if rows else divider_index
        regions.append((divider_index - 1, last, rows))
        occupied.update(range(divider_index - 1, last + 1))
    return regions


def _inventory(lines: list[str]) -> tuple[dict[str, int], bool]:
    regions = _table_regions(lines)
    table_lines = {
        index
        for start, end, _ in regions
        for index in range(start, end + 1)
    }
    headings = 0
    paragraphs = 0
    code_blocks = 0
    links = 0
    in_fence = False
    fence_marker = ""
    paragraph_open = False

    for index, line in enumerate(lines):
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                if paragraph_open:
                    paragraphs += 1
                    paragraph_open = False
                in_fence = True
                fence_marker = marker[0]
                code_blocks += 1
            elif marker[0] == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        if index in table_lines or _TABLE_DIVIDER.match(line):
            if paragraph_open:
                paragraphs += 1
                paragraph_open = False
            if index in table_lines:
                links += len(_LINK.findall(line))
            continue
        heading = _HEADING.match(line)
        if heading:
            if paragraph_open:
                paragraphs += 1
                paragraph_open = False
            headings += 1
            links += len(_LINK.findall(line))
            continue
        if not line.strip():
            if paragraph_open:
                paragraphs += 1
                paragraph_open = False
            continue
        paragraph_open = True
        links += len(_LINK.findall(line))
    if paragraph_open:
        paragraphs += 1
    return (
        {
            "headings": headings,
            "paragraphs": paragraphs,
            "tables": len(regions),
            "table_rows": sum(len(rows) for _, _, rows in regions),
            "code_blocks": code_blocks,
            "links": links,
        },
        in_fence,
    )


class MarkdownParser:
    parser_name = "markdown_structured"
    parser_version = "1.0.0"

    def supports(self, source: SourceInput, artifact: SourceArtifact) -> bool:
        del artifact
        return source.path.suffix.casefold() in {".md", ".markdown", ".txt"}

    def parse(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> ParsedArtifact:
        try:
            text = source.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return finalize_artifact(
                artifact=artifact,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                blocks=[],
                detected_inventory={},
                parsed_inventory={},
                errors=[
                    finding(
                        "input.text_unreadable",
                        f"{type(exc).__name__}: {exc}",
                        artifact.original_name,
                    )
                ],
            )

        lines = text.splitlines()
        detected, unclosed_fence = _inventory(lines)
        regions = _table_regions(lines)
        region_by_start = {start: (end, rows) for start, end, rows in regions}
        blocks = []
        order = 0
        paragraph_buffer: list[tuple[int, str]] = []
        heading_path: list[str] = []

        def add_links(value: str, locator: str) -> None:
            nonlocal order
            for link_index, match in enumerate(_LINK.finditer(value), start=1):
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="link",
                        locator=f"{locator}::link[{link_index}]",
                        order=order,
                        text_content=match.group(1),
                        structured_content={"target": match.group(2)},
                    )
                )

        def flush_paragraph() -> None:
            nonlocal order
            if not paragraph_buffer:
                return
            first = paragraph_buffer[0][0]
            last = paragraph_buffer[-1][0]
            value = "\n".join(item[1] for item in paragraph_buffer).strip()
            locator = f"line[{first}:{last}]"
            if value:
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="paragraph",
                        locator=locator,
                        order=order,
                        text_content=value,
                        structured_content={"heading_path": list(heading_path)},
                    )
                )
                add_links(value, locator)
            paragraph_buffer.clear()

        index = 0
        while index < len(lines):
            line = lines[index]
            line_number = index + 1

            if index in region_by_start:
                flush_paragraph()
                end, row_indexes = region_by_start[index]
                order += 1
                table_locator = f"line[{line_number}:{end + 1}]"
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="table",
                        locator=table_locator,
                        order=order,
                        structured_content={
                            "heading_path": list(heading_path),
                            "row_count": len(row_indexes),
                        },
                    )
                )
                for row_number, row_index in enumerate(row_indexes, start=1):
                    value = lines[row_index]
                    row_locator = f"line[{row_index + 1}]"
                    cells = [
                        cell.strip()
                        for cell in value.strip().strip("|").split("|")
                    ]
                    order += 1
                    blocks.append(
                        make_block(
                            artifact,
                            parser_name=self.parser_name,
                            parser_version=self.parser_version,
                            block_type="table_row",
                            locator=row_locator,
                            order=order,
                            text_content=value,
                            structured_content={
                                "row_number": row_number,
                                "cells": cells,
                            },
                        )
                    )
                    add_links(value, row_locator)
                index = end + 1
                continue

            fence = _FENCE.match(line)
            if fence:
                flush_paragraph()
                marker = fence.group(1)
                language = fence.group(2).strip()
                content: list[str] = []
                cursor = index + 1
                closed = False
                while cursor < len(lines):
                    closing = _FENCE.match(lines[cursor])
                    if closing and closing.group(1)[0] == marker[0]:
                        closed = True
                        break
                    content.append(lines[cursor])
                    cursor += 1
                last_line = cursor + 1 if closed else len(lines)
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="code_block",
                        locator=f"line[{line_number}:{last_line}]",
                        order=order,
                        text_content="\n".join(content),
                        structured_content={
                            "language": language,
                            "closed": closed,
                            "heading_path": list(heading_path),
                        },
                    )
                )
                index = cursor + 1 if closed else len(lines)
                continue

            heading = _HEADING.match(line)
            if heading:
                flush_paragraph()
                level = len(heading.group(1))
                title = heading.group(2).strip()
                heading_path[level - 1 :] = [title]
                order += 1
                locator = f"line[{line_number}]"
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="heading",
                        locator=locator,
                        order=order,
                        text_content=title,
                        structured_content={
                            "level": level,
                            "heading_path": list(heading_path),
                        },
                    )
                )
                add_links(title, locator)
            elif line.strip() and not _TABLE_DIVIDER.match(line):
                paragraph_buffer.append((line_number, line))
            else:
                flush_paragraph()
            index += 1

        flush_paragraph()
        parsed = {
            key: sum(
                block.block_type
                == {
                    "headings": "heading",
                    "paragraphs": "paragraph",
                    "tables": "table",
                    "table_rows": "table_row",
                    "code_blocks": "code_block",
                    "links": "link",
                }[key]
                for block in blocks
            )
            for key in detected
        }
        unsupported = (
            [
                finding(
                    "input.unclosed_code_fence",
                    "Markdown 存在未闭合代码围栏。",
                    artifact.original_name,
                )
            ]
            if unclosed_fence
            else []
        )
        return finalize_artifact(
            artifact=artifact,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            blocks=blocks,
            detected_inventory=detected,
            parsed_inventory=parsed,
            unsupported_features=unsupported,
        )
