"""Turn an OpenAPI document into a governed connector and its operation tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core import ConnectorSpec, DataClass, HttpMethod, RiskLevel
from .catalog import ToolEntry

MAX_OPERATIONS = 200

_METHODS = frozenset({"get", "put", "post", "delete", "patch", "head"})
_DATA_CLASSES = frozenset({"public", "internal", "confidential", "restricted"})
_RISK_LEVELS = frozenset({"L1", "L2", "L3", "L4"})


class OpenApiImportError(Exception):
    """The document cannot become a connector. ``code`` is stable."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class OpenApiImport:
    connector: ConnectorSpec
    tools: list[ToolEntry]
    skipped: list[str]


def _server_url(document: dict[str, Any], override: str | None) -> str:
    if override:
        return override
    servers = document.get("servers")
    if not isinstance(servers, list) or not servers:
        raise OpenApiImportError("missing_server", "document has no servers[0].url")
    first = servers[0]
    url = first.get("url") if isinstance(first, dict) else None
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise OpenApiImportError("missing_server", "servers[0].url must be absolute")
    return url


def _lookup(
    operation: dict[str, Any], path_item: dict[str, Any], document: dict[str, Any], key: str
) -> Any:
    """The first non-null value from the operation, its path item, or the document."""
    for source in (operation, path_item, document):
        value = source.get(key)
        if value is not None:
            return value
    return None


def _operation_data_classes(
    operation: dict[str, Any], path_item: dict[str, Any], document: dict[str, Any]
) -> list[DataClass]:
    raw = _lookup(operation, path_item, document, "x-data-classes")
    if raw is None:
        return ["internal"]
    if not isinstance(raw, list) or not raw:
        raise OpenApiImportError("invalid_data_class", "x-data-classes must be a non-empty list")
    for value in raw:
        if not isinstance(value, str) or value not in _DATA_CLASSES:
            raise OpenApiImportError("invalid_data_class", repr(value))
    return sorted(set(raw))  # type: ignore[return-value]


def _risk_level(
    operation: dict[str, Any], path_item: dict[str, Any], document: dict[str, Any]
) -> RiskLevel:
    raw = _lookup(operation, path_item, document, "x-risk-level")
    if raw is None:
        return "L2"
    if not isinstance(raw, str) or raw not in _RISK_LEVELS:
        raise OpenApiImportError("invalid_risk_level", f"x-risk-level {raw!r}")
    return raw  # type: ignore[return-value]


def _prefix_for(path: str) -> str:
    """The static part of an operation path; callers cannot choose the path."""
    head = path.split("{", 1)[0]
    if not head:
        return "/"
    return head


def import_openapi(
    document: Any,
    connector_id: str,
    *,
    tenant: str | None = None,
    base_url: str | None = None,
) -> OpenApiImport:
    """Build the connector plus one tool per ``operationId``."""
    if not isinstance(document, dict):
        raise OpenApiImportError("spec_invalid", "document must be a JSON object")
    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise OpenApiImportError("spec_invalid", "document has no paths")
    url = _server_url(document, base_url)

    operations: list[dict[str, Any]] = []
    descriptions: dict[str, str] = {}
    skipped: list[str] = []
    methods: set[HttpMethod] = set()
    prefixes: set[str] = set()
    for raw_path, item in paths.items():
        if not isinstance(item, dict):
            raise OpenApiImportError("spec_invalid", f"path item {raw_path} is not an object")
        if not isinstance(raw_path, str) or not raw_path.startswith("/"):
            raise OpenApiImportError("spec_invalid", "paths must start with /")
        for key, operation in item.items():
            if key.lower() not in _METHODS:
                continue
            if not isinstance(operation, dict):
                raise OpenApiImportError("spec_invalid", f"operation {raw_path} is not an object")
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id.strip():
                skipped.append(f"{key.upper()} {raw_path}")
                continue
            if len(operations) >= MAX_OPERATIONS:
                raise OpenApiImportError("too_many_operations", f"more than {MAX_OPERATIONS}")
            method = key.upper()
            tool_id = f"{connector_id}.{operation_id.strip()}"
            risk = _risk_level(operation, item, document)
            data_classes = _operation_data_classes(operation, item, document)
            if any(operation_entry["tool_id"] == tool_id for operation_entry in operations):
                raise OpenApiImportError("duplicate_operation_id", tool_id)
            operations.append(
                {
                    "tool_id": tool_id,
                    "path": raw_path,
                    "method": method,
                    "risk_level": risk,
                    "data_classes": list(data_classes),
                    "write": method not in ("GET", "HEAD"),
                }
            )
            descriptions[tool_id] = str(operation.get("summary") or operation_id.strip())
            methods.add(method)  # type: ignore[arg-type]
            prefixes.add(_prefix_for(raw_path))

    if not operations:
        raise OpenApiImportError("no_operations", "no operation has an operationId")

    try:
        connector = ConnectorSpec(
            connector_id=connector_id,
            tenant=tenant,
            kind="openapi",
            base_url=url,
            methods=sorted(methods),
            path_prefixes=sorted(prefixes),
            data_classes=["internal"],
            risk_level="L2",
            operations=operations,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        raise OpenApiImportError("spec_invalid", "connector rejected: " + str(exc)) from None
    tools = [
        ToolEntry(
            tool_id=operation.tool_id,
            description=descriptions[operation.tool_id],
            source="openapi",
            data_classes=list(governance[1]),
            requires_approval=governance[0] in ("L3", "L4"),
            risk_level=governance[0],
            tenant=tenant,
            write=operation.write,
        )
        for operation in connector.operations
        for governance in (connector.operation_governance(operation),)
    ]
    return OpenApiImport(connector=connector, tools=tools, skipped=skipped)


__all__ = ["MAX_OPERATIONS", "OpenApiImport", "OpenApiImportError", "import_openapi"]
