"""HTML 原型目录或 ZIP 的静态保真解析器。

本解析器只证明文件、静态文字、原生/声明式控件和本地资源引用；它不会执行源码，
也不会把 JS 驱动可见性或自定义控件行为声明为已理解。
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import mimetypes
from pathlib import PurePosixPath
import posixpath
import re
from typing import Iterable
from urllib.parse import unquote, urlparse
from zipfile import BadZipFile, ZipFile

from core.design_studio.contracts import (
    ParsedArtifact,
    SourceArtifact,
    SourceInput,
)
from core.design_studio.ingestion.zip_safety import validate_zip_safety

from .base import finalize_artifact, finding, make_block


_CSS_REF = re.compile(
    r"(?:url\(\s*|@import\s+)[\"']?([^\"')\s;]+)",
    re.IGNORECASE,
)
_JS_IMPORT = re.compile(
    r"(?:from\s+|import\s*\(\s*|import\s+)[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_NATIVE_CONTROL_TAGS = {"input", "select", "textarea", "button", "a"}
_INTERACTIVE_ROLES = {
    "button",
    "checkbox",
    "combobox",
    "link",
    "menuitem",
    "option",
    "radio",
    "slider",
    "switch",
    "tab",
    "textbox",
}


class _StaticHTMLInventory(HTMLParser):
    _HIDDEN_TAGS = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str, str]] = []
        self.visible_texts: list[tuple[str, int, int]] = []
        self.native_controls: list[dict[str, str]] = []
        self.custom_controls: list[dict[str, str]] = []
        self.script_count = 0
        self.inline_svg_count = 0
        self._hidden_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.casefold()
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag in self._HIDDEN_TAGS:
            self._hidden_depth += 1
        if tag == "script":
            self.script_count += 1
        if tag == "svg":
            self.inline_svg_count += 1

        for attribute in ("src", "href", "poster"):
            value = values.get(attribute)
            if value:
                self.references.append((tag, attribute, value))
        if values.get("srcset"):
            for item in values["srcset"].split(","):
                candidate = item.strip().split(" ", 1)[0]
                if candidate:
                    self.references.append((tag, "srcset", candidate))

        retained = {
            key: value
            for key, value in values.items()
            if key
            in {
                "id",
                "name",
                "type",
                "role",
                "aria-label",
                "placeholder",
                "href",
                "value",
                "onclick",
            }
        }
        source_line, source_column = self.getpos()
        retained["source_line"] = str(source_line)
        retained["source_column"] = str(source_column)
        if tag in _NATIVE_CONTROL_TAGS:
            self.native_controls.append({"tag": tag, **retained})
        elif (
            values.get("role", "").casefold() in _INTERACTIVE_ROLES
            or "onclick" in values
            or values.get("tabindex") == "0"
        ):
            self.custom_controls.append({"tag": tag, **retained})

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._HIDDEN_TAGS and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        value = " ".join(data.split())
        if value:
            source_line, source_column = self.getpos()
            self.visible_texts.append((value, source_line, source_column))


class _Bundle:
    def __init__(self, source: SourceInput) -> None:
        self.source = source
        self.path = source.path.resolve()
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
            validate_zip_safety(self._zip, label="HTML ZIP")
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
            self.root = self.path.parent
            self.names = {
                item.relative_to(self.root).as_posix()
                for item in self.root.rglob("*")
                if item.is_file()
            }

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def read(self, relative: str) -> bytes:
        if self._zip is not None:
            return self._zip.read(relative)
        assert self.root is not None
        return (self.root / PurePosixPath(relative)).read_bytes()

    def local_path(self, relative: str) -> str:
        if self._zip is not None:
            return f"{self.path}!/{relative}"
        assert self.root is not None
        return str((self.root / PurePosixPath(relative)).resolve())

    def default_entries(self) -> list[str]:
        if self.path.is_file() and self.path.suffix.casefold() in {".html", ".htm"}:
            return [self.path.name]
        return sorted(
            (
                name
                for name in self.names
                if PurePosixPath(name).suffix.casefold() in {".html", ".htm"}
            ),
            key=str.casefold,
        )


def _decode(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeError("无法以 UTF-8 或 GB18030 解码")


def _normalize_reference(
    current: str,
    raw: str,
    *,
    tag: str,
    attribute: str,
    available: set[str],
) -> tuple[str | None, str | None]:
    parsed = urlparse(unquote(raw.strip()))
    if (
        not raw.strip()
        or parsed.scheme
        or parsed.netloc
        or raw.startswith(("#", "data:", "mailto:", "tel:", "javascript:"))
    ):
        return None, None
    raw_path = parsed.path.replace("\\", "/")
    if not raw_path:
        return None, None
    if raw_path.startswith("/"):
        candidate = posixpath.normpath(raw_path.lstrip("/"))
    else:
        candidate = posixpath.normpath(
            posixpath.join(posixpath.dirname(current), raw_path)
        )
    if candidate == ".." or candidate.startswith("../"):
        return None, "outside"

    if candidate in available:
        return candidate, None
    if tag == "a" and attribute == "href":
        suffix = PurePosixPath(candidate).suffix.casefold()
        if not suffix or suffix not in {".html", ".htm"}:
            return None, None
    return candidate, "missing"


def _source_for_resource(
    parent: SourceArtifact,
    relative: str,
    data: bytes,
    local_path: str,
) -> SourceArtifact:
    digest = sha256(data).hexdigest().upper()
    identity = sha256(
        f"{parent.source_id}|{relative}".encode("utf-8")
    ).hexdigest()[:12].upper()
    return SourceArtifact(
        source_id=f"{parent.source_id}:resource:{identity}",
        source_kind="prototype_resource",
        authority=parent.authority,
        required=False,
        media_type=mimetypes.guess_type(relative)[0] or "application/octet-stream",
        original_name=PurePosixPath(relative).name,
        origin_uri=f"bundle://{parent.source_id}/{relative}",
        local_path=local_path,
        sha256=digest,
        byte_size=len(data),
        source_version=digest,
        captured_at=datetime.now(timezone.utc),
        secret_refs=[],
    )


class HtmlPrototypeParser:
    parser_name = "html_prototype_static"
    parser_version = "1.0.0"

    def supports(self, source: SourceInput, artifact: SourceArtifact) -> bool:
        del artifact
        return (
            source.source_kind.casefold()
            in {"prototype", "html_prototype", "prototype_bundle"}
            and (
                source.path.is_dir()
                or source.path.suffix.casefold() in {".html", ".htm", ".zip"}
            )
        )

    def parse(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> ParsedArtifact:
        bundle: _Bundle | None = None
        try:
            bundle = _Bundle(source)
            return self._parse_bundle(source, artifact, bundle)
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
                        "input.html_bundle_unreadable",
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
        source: SourceInput,
        artifact: SourceArtifact,
        bundle: _Bundle,
    ) -> ParsedArtifact:
        entry_pages = source.entry_points or bundle.default_entries()
        entry_pages = [PurePosixPath(item).as_posix().lstrip("./") for item in entry_pages]
        missing_entries = [item for item in entry_pages if item not in bundle.names]
        if missing_entries:
            return finalize_artifact(
                artifact=artifact,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                blocks=[],
                detected_inventory={"entry_pages": len(entry_pages)},
                parsed_inventory={"entry_pages": 0},
                errors=[
                    finding(
                        "input.missing_entry_point",
                        f"HTML 入口不存在: {item}",
                        item,
                    )
                    for item in missing_entries
                ],
            )

        page_inventories: dict[str, _StaticHTMLInventory] = {}
        encodings: dict[str, str] = {}
        queue = list(entry_pages)
        closure: set[str] = set()
        direct_closure: set[str] = set(entry_pages)
        missing: set[tuple[str, str]] = set()
        outside: set[tuple[str, str]] = set()

        while queue:
            current = queue.pop(0)
            if current in closure:
                continue
            closure.add(current)
            data = bundle.read(current)
            suffix = PurePosixPath(current).suffix.casefold()
            references: Iterable[tuple[str, str, str]] = []
            if suffix in {".html", ".htm"}:
                value, encoding = _decode(data)
                encodings[current] = encoding
                parser = _StaticHTMLInventory()
                parser.feed(value)
                page_inventories[current] = parser
                references = parser.references
            elif suffix == ".css":
                value, _ = _decode(data)
                references = [
                    ("style", "url", match.group(1))
                    for match in _CSS_REF.finditer(value)
                ]
            elif suffix in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
                value, _ = _decode(data)
                references = [
                    ("script", "import", match.group(1))
                    for match in _JS_IMPORT.finditer(value)
                    if match.group(1).startswith((".", "/"))
                ]

            for tag, attribute, raw in references:
                target, problem = _normalize_reference(
                    current,
                    raw,
                    tag=tag,
                    attribute=attribute,
                    available=bundle.names,
                )
                if problem == "outside":
                    outside.add((current, raw))
                elif problem == "missing" and target is not None:
                    missing.add((current, raw))
                elif target is not None and target not in closure:
                    if current in entry_pages:
                        direct_closure.add(target)
                    queue.append(target)

        blocks = []
        order = 0
        page_order = list(entry_pages) + sorted(
            set(page_inventories) - set(entry_pages),
            key=str.casefold,
        )
        for page in page_order:
            inventory = page_inventories[page]
            order += 1
            blocks.append(
                make_block(
                    artifact,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    block_type="html_page",
                    locator=page,
                    order=order,
                    structured_content={
                        "encoding": encodings.get(page, ""),
                        "entry_point": page in entry_pages,
                    },
                )
            )
            for index, (value, line, column) in enumerate(
                inventory.visible_texts,
                start=1,
            ):
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="visible_text",
                        locator=(
                            f"{page}::line[{line}]:column[{column}]::text[{index}]"
                        ),
                        order=order,
                        text_content=value,
                    )
                )
            for index, control in enumerate(inventory.native_controls, start=1):
                line = control.get("source_line", "0")
                column = control.get("source_column", "0")
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="html_control",
                        locator=(
                            f"{page}::line[{line}]:column[{column}]::control[{index}]"
                        ),
                        order=order,
                        structured_content=control,
                    )
                )
            for index, control in enumerate(inventory.custom_controls, start=1):
                line = control.get("source_line", "0")
                column = control.get("source_column", "0")
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="custom_control",
                        locator=(
                            f"{page}::line[{line}]:column[{column}]"
                            f"::custom-control[{index}]"
                        ),
                        order=order,
                        structured_content=control,
                    )
                )
            for index in range(1, inventory.script_count + 1):
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="script",
                        locator=f"{page}::script[{index}]",
                        order=order,
                    )
                )
            for index in range(1, inventory.inline_svg_count + 1):
                order += 1
                blocks.append(
                    make_block(
                        artifact,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        block_type="inline_svg",
                        locator=f"{page}::svg[{index}]",
                        order=order,
                    )
                )

        related_sources = []
        resource_entries = []
        for relative in sorted(closure, key=str.casefold):
            data = bundle.read(relative)
            related = _source_for_resource(
                artifact,
                relative,
                data,
                bundle.local_path(relative),
            )
            related_sources.append(related)
            resource_entries.append(
                {
                    "relative_path": relative,
                    "byte_size": related.byte_size,
                    "sha256": related.sha256,
                    "direct": relative in direct_closure,
                }
            )
            order += 1
            blocks.append(
                make_block(
                    artifact,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    block_type="resource",
                    locator=relative,
                    order=order,
                    structured_content={
                        "media_type": related.media_type,
                        "byte_size": related.byte_size,
                        "sha256": related.sha256,
                        "direct": relative in direct_closure,
                    },
                    asset_refs=[related.source_id],
                )
            )

        def manifest_hash(entries: list[dict[str, object]]) -> str:
            value = "\n".join(
                f"{item['relative_path']}\t{item['byte_size']}\t{item['sha256']}"
                for item in entries
            )
            return sha256(value.encode("utf-8")).hexdigest().upper()

        direct_entries = [
            item for item in resource_entries if bool(item["direct"])
        ]
        order += 1
        blocks.append(
            make_block(
                artifact,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                block_type="resource_manifest",
                locator="manifest::resources",
                order=order,
                structured_content={
                    "direct_file_count": len(direct_entries),
                    "direct_sha256": manifest_hash(direct_entries),
                    "transitive_file_count": len(resource_entries),
                    "transitive_sha256": manifest_hash(resource_entries),
                    "entries": resource_entries,
                },
            )
        )

        for current, raw in sorted(missing):
            order += 1
            blocks.append(
                make_block(
                    artifact,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    block_type="missing_reference",
                    locator=f"{current}::{raw}",
                    order=order,
                )
            )

        visible_count = sum(
            len(item.visible_texts) for item in page_inventories.values()
        )
        native_count = sum(
            len(item.native_controls) for item in page_inventories.values()
        )
        custom_count = sum(
            len(item.custom_controls) for item in page_inventories.values()
        )
        script_count = sum(
            item.script_count for item in page_inventories.values()
        )
        svg_count = sum(
            item.inline_svg_count for item in page_inventories.values()
        )
        detected = {
            "entry_pages": len(entry_pages),
            "discovered_pages": len(page_inventories),
            "direct_referenced_files": len(direct_closure),
            "referenced_files": len(closure),
            "missing_references": len(missing),
            "visible_text_blocks": visible_count,
            "native_controls": native_count,
            "custom_controls": custom_count,
            "scripts": script_count,
            "inline_svg": svg_count,
        }
        type_by_inventory = {
            "missing_references": "missing_reference",
            "visible_text_blocks": "visible_text",
            "native_controls": "html_control",
            "custom_controls": "custom_control",
            "scripts": "script",
            "inline_svg": "inline_svg",
        }
        parsed = {
            key: sum(block.block_type == block_type for block in blocks)
            for key, block_type in type_by_inventory.items()
        }
        parsed["entry_pages"] = sum(
            block.block_type == "html_page"
            and bool(block.structured_content.get("entry_point"))
            for block in blocks
        )
        parsed["discovered_pages"] = sum(
            block.block_type == "html_page" for block in blocks
        )
        parsed["direct_referenced_files"] = sum(
            block.block_type == "resource"
            and bool(block.structured_content.get("direct"))
            for block in blocks
        )
        parsed["referenced_files"] = sum(
            block.block_type == "resource" for block in blocks
        )
        errors = [
            finding(
                "input.missing_reference",
                f"{current} 引用了不存在的本地资源: {raw}",
                current,
            )
            for current, raw in sorted(missing)
        ]
        errors.extend(
            finding(
                "input.reference_outside_bundle",
                f"{current} 的引用越过资料根目录: {raw}",
                current,
            )
            for current, raw in sorted(outside)
        )
        dynamic_semantics = bool(script_count or custom_count or svg_count)
        unsupported = (
            [
                finding(
                    "input.rendered_interaction_semantics",
                    "静态解析不能证明 JS 驱动状态、自定义控件行为或渲染后可见性。",
                )
            ]
            if dynamic_semantics
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
            errors=errors,
            related_sources=related_sources,
        )
