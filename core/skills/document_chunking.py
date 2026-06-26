"""Utilities for splitting long requirement inputs without losing headings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from core.focus_scope import expand_focus_terms
from core.input_normalization import normalize_text_input


@dataclass(frozen=True)
class DocumentChunk:
    source_type: str
    source_reference: str
    content: str


_HEADING_RE = re.compile(r"(?m)^(#{1,6}\s+.+)$")


def _split_oversized_section(section: str, max_chars: int) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", section)
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_size = 0
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start:start + max_chars])
            continue

        added_size = len(paragraph) + (2 if current else 0)
        if current and current_size + added_size > max_chars:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_size = len(paragraph)
        else:
            current.append(paragraph)
            current_size += added_size

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def split_markdown(
    content: Any,
    *,
    source_type: str,
    source_reference: str,
    max_chars: int | None = None,
) -> list[DocumentChunk]:
    """Split text near Markdown headings and paragraph boundaries."""
    text = normalize_text_input(content).strip()
    if not text:
        return []

    limit = max_chars or int(os.getenv("L1_CHUNK_MAX_CHARS", "12000"))
    if limit < 1000:
        raise ValueError("L1_CHUNK_MAX_CHARS must be at least 1000")

    matches = list(_HEADING_RE.finditer(text))
    sections: list[tuple[str, str]] = []
    if not matches:
        sections = [(source_reference, text)]
    else:
        if matches[0].start() > 0:
            preamble = text[:matches[0].start()].strip()
            if preamble:
                sections.append((source_reference, preamble))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            heading = match.group(1).lstrip("#").strip()
            sections.append((f"{source_reference} > {heading}", text[match.start():end].strip()))

    chunks: list[DocumentChunk] = []
    pending_parts: list[str] = []
    pending_refs: list[str] = []
    pending_size = 0

    def flush() -> None:
        nonlocal pending_parts, pending_refs, pending_size
        if not pending_parts:
            return
        chunks.append(DocumentChunk(
            source_type=source_type,
            source_reference=" | ".join(dict.fromkeys(pending_refs)),
            content="\n\n".join(pending_parts),
        ))
        pending_parts = []
        pending_refs = []
        pending_size = 0

    for reference, section in sections:
        if len(section) > limit:
            flush()
            pieces = _split_oversized_section(section, limit)
            for piece_index, piece in enumerate(pieces, start=1):
                chunks.append(DocumentChunk(
                    source_type=source_type,
                    source_reference=f"{reference} [片段 {piece_index}/{len(pieces)}]",
                    content=piece,
                ))
            continue

        added_size = len(section) + (2 if pending_parts else 0)
        if pending_parts and pending_size + added_size > limit:
            flush()
        pending_parts.append(section)
        pending_refs.append(reference)
        pending_size += added_size

    flush()
    return chunks


def _filter_chunks_by_focus(
    chunks: list[DocumentChunk],
    *,
    focus_areas: str | list[str] | None = None,
    target_url: str = "",
) -> list[DocumentChunk]:
    terms = expand_focus_terms(focus_areas, target_url)
    if not terms:
        return chunks

    reference_matched = [
        chunk
        for chunk in chunks
        if any(
            term in chunk.source_reference.casefold()
            for term in terms
        )
    ]
    matched = reference_matched or [
        chunk
        for chunk in chunks
        if any(
            term in f"{chunk.source_reference}\n{chunk.content}".casefold()
            for term in terms
        )
    ]
    if matched:
        print(
            "[DocumentChunking] Focus scope filtered chunks: "
            f"{len(matched)}/{len(chunks)} for terms={sorted(terms)}."
        )
        return matched
    return chunks


def build_requirement_chunks(
    *,
    prd_content: Any = "",
    api_doc_content: Any = "",
    changelog_content: Any = "",
    prototype_notes: Any = "",
    architecture_notes: Any = "",
    rules: Any = "",
    focus_areas: str | list[str] | None = None,
    target_url: str = "",
) -> list[DocumentChunk]:
    sources = [
        ("prd", "PRD", prd_content),
        ("swagger", "Swagger/API", api_doc_content),
        ("changelog", "Changelog", changelog_content),
        ("prototype", "Prototype", prototype_notes),
        ("architecture", "Architecture", architecture_notes),
        ("rule", "Rules", rules),
    ]
    chunks: list[DocumentChunk] = []
    for source_type, reference, content in sources:
        chunks.extend(split_markdown(
            content,
            source_type=source_type,
            source_reference=reference,
        ))
    return _filter_chunks_by_focus(
        chunks,
        focus_areas=focus_areas,
        target_url=target_url,
    )
