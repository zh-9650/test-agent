"""JSON/YAML 与 OpenAPI 结构解析器。"""

from __future__ import annotations

import json
from typing import Any, Iterator

import yaml

from core.design_studio.contracts import ParsedArtifact, SourceArtifact, SourceInput

from .base import finalize_artifact, finding, make_block


_HTTP_METHODS = {
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
}


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _pointer(parent: str, value: str | int) -> str:
    return f"{parent}/{_escape_pointer(str(value))}"


def _walk(value: Any, pointer: str = "#") -> Iterator[tuple[str, Any]]:
    yield pointer, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, _pointer(pointer, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, _pointer(pointer, index))


def _resolve_local_ref(root: Any, reference: str) -> bool:
    if reference == "#":
        return True
    if not reference.startswith("#/"):
        return False
    current = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
            continue
        return False
    return True


def _load(path: SourceInput) -> Any:
    text = path.path.read_text(encoding="utf-8")
    if path.path.suffix.casefold() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


class StructuredDocumentParser:
    parser_name = "structured_document"
    parser_version = "1.0.0"

    def supports(self, source: SourceInput, artifact: SourceArtifact) -> bool:
        del artifact
        return source.path.suffix.casefold() in {".json", ".yaml", ".yml"}

    def parse(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> ParsedArtifact:
        try:
            document = _load(source)
        except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
            return finalize_artifact(
                artifact=artifact,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                blocks=[],
                detected_inventory={},
                parsed_inventory={},
                errors=[
                    finding(
                        "input.structured_parse_failed",
                        f"{type(exc).__name__}: {exc}",
                        artifact.original_name,
                    )
                ],
            )
        if isinstance(document, dict) and (
            "openapi" in document or "swagger" in document
        ):
            return self._parse_openapi(artifact, document)
        return self._parse_generic(artifact, document)

    def _parse_generic(
        self,
        artifact: SourceArtifact,
        document: Any,
    ) -> ParsedArtifact:
        nodes = list(_walk(document))
        blocks = []
        for order, (pointer, value) in enumerate(nodes, start=1):
            if isinstance(value, dict):
                kind = "object"
                content: Any = {"keys": list(value)}
                text = ""
            elif isinstance(value, list):
                kind = "array"
                content = {"length": len(value)}
                text = ""
            else:
                kind = "value"
                content = {"value": value}
                text = "" if value is None else str(value)
            blocks.append(
                make_block(
                    artifact,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    block_type="structured_node",
                    locator=pointer,
                    order=order,
                    text_content=text,
                    structured_content={"kind": kind, **content},
                )
            )
        inventory = {"nodes": len(nodes)}
        return finalize_artifact(
            artifact=artifact,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            blocks=blocks,
            detected_inventory=inventory,
            parsed_inventory={"nodes": len(blocks)},
        )

    def _parse_openapi(
        self,
        artifact: SourceArtifact,
        document: dict[str, Any],
    ) -> ParsedArtifact:
        paths = document.get("paths")
        paths = paths if isinstance(paths, dict) else {}
        schemas = (
            document.get("components", {}).get("schemas", {})
            if isinstance(document.get("components"), dict)
            else {}
        )
        if not schemas and isinstance(document.get("definitions"), dict):
            schemas = document["definitions"]
        schemas = schemas if isinstance(schemas, dict) else {}

        operations: list[tuple[str, str, dict[str, Any], str]] = []
        parameters: list[tuple[str, Any]] = []
        request_bodies: list[tuple[str, Any]] = []
        responses: list[tuple[str, Any]] = []
        for path_name, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            path_pointer = _pointer("#/paths", path_name)
            path_parameters = path_item.get("parameters")
            if isinstance(path_parameters, list):
                parameters.extend(
                    (_pointer(f"{path_pointer}/parameters", index), parameter)
                    for index, parameter in enumerate(path_parameters)
                )
            for method, operation in path_item.items():
                method_value = str(method).casefold()
                if method_value not in _HTTP_METHODS or not isinstance(operation, dict):
                    continue
                operation_pointer = f"{path_pointer}/{method_value}"
                operations.append(
                    (str(path_name), method_value, operation, operation_pointer)
                )
                operation_parameters = operation.get("parameters")
                if isinstance(operation_parameters, list):
                    parameters.extend(
                        (
                            _pointer(f"{operation_pointer}/parameters", index),
                            parameter,
                        )
                        for index, parameter in enumerate(operation_parameters)
                    )
                if "requestBody" in operation:
                    request_bodies.append(
                        (f"{operation_pointer}/requestBody", operation["requestBody"])
                    )
                operation_responses = operation.get("responses")
                if isinstance(operation_responses, dict):
                    responses.extend(
                        (
                            _pointer(f"{operation_pointer}/responses", status),
                            response,
                        )
                        for status, response in operation_responses.items()
                    )

        enum_nodes = [
            (pointer, value["enum"])
            for pointer, value in _walk(document)
            if isinstance(value, dict) and isinstance(value.get("enum"), list)
        ]
        ref_nodes = [
            (pointer, value["$ref"])
            for pointer, value in _walk(document)
            if isinstance(value, dict) and isinstance(value.get("$ref"), str)
        ]
        detected = {
            "operations": len(operations),
            "parameters": len(parameters),
            "request_bodies": len(request_bodies),
            "responses": len(responses),
            "schemas": len(schemas),
            "enums": len(enum_nodes),
            "refs": len(ref_nodes),
        }

        blocks = []
        order = 0

        def append(
            block_type: str,
            locator: str,
            *,
            text_content: str = "",
            structured_content: dict[str, Any] | None = None,
        ) -> None:
            nonlocal order
            order += 1
            blocks.append(
                make_block(
                    artifact,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    block_type=block_type,
                    locator=locator,
                    order=order,
                    text_content=text_content,
                    structured_content=structured_content,
                )
            )

        for path_name, method, operation, locator in operations:
            append(
                "api_operation",
                locator,
                text_content=operation.get("summary", "")
                if isinstance(operation.get("summary"), str)
                else "",
                structured_content={
                    "path": path_name,
                    "method": method,
                    "operation_id": operation.get("operationId", ""),
                    "tags": operation.get("tags", []),
                },
            )
        for locator, parameter in parameters:
            append(
                "api_parameter",
                locator,
                structured_content={
                    "parameter": parameter
                    if isinstance(parameter, dict)
                    else {"value": parameter}
                },
            )
        for locator, request_body in request_bodies:
            append(
                "api_request_body",
                locator,
                structured_content={
                    "request_body": request_body
                    if isinstance(request_body, dict)
                    else {"value": request_body}
                },
            )
        for locator, response in responses:
            append(
                "api_response",
                locator,
                structured_content={
                    "response": response
                    if isinstance(response, dict)
                    else {"value": response}
                },
            )
        schema_root = (
            "#/components/schemas"
            if isinstance(document.get("components"), dict)
            else "#/definitions"
        )
        for schema_name, schema in schemas.items():
            append(
                "schema",
                _pointer(schema_root, schema_name),
                structured_content={
                    "name": schema_name,
                    "schema": schema
                    if isinstance(schema, dict)
                    else {"value": schema},
                },
            )
        for locator, values in enum_nodes:
            append("enum", f"{locator}/enum", structured_content={"values": values})
        for locator, reference in ref_nodes:
            append(
                "reference",
                f"{locator}/$ref",
                structured_content={"target": reference},
            )

        errors = []
        unsupported = []
        for locator, reference in ref_nodes:
            if reference.startswith("#"):
                if not _resolve_local_ref(document, reference):
                    errors.append(
                        finding(
                            "input.unresolved_ref",
                            f"无法解析 OpenAPI 本地引用: {reference}",
                            f"{locator}/$ref",
                        )
                    )
            else:
                unsupported.append(
                    finding(
                        "input.external_ref",
                        f"外部 OpenAPI 引用尚未获取: {reference}",
                        f"{locator}/$ref",
                    )
                )

        block_type_by_inventory = {
            "operations": "api_operation",
            "parameters": "api_parameter",
            "request_bodies": "api_request_body",
            "responses": "api_response",
            "schemas": "schema",
            "enums": "enum",
            "refs": "reference",
        }
        parsed = {
            key: sum(
                block.block_type == block_type
                for block in blocks
            )
            for key, block_type in block_type_by_inventory.items()
        }
        return finalize_artifact(
            artifact=artifact,
            parser_name="openapi_structured",
            parser_version=self.parser_version,
            blocks=blocks,
            detected_inventory=detected,
            parsed_inventory=parsed,
            unsupported_features=unsupported,
            errors=errors,
        )
