"""Canonical canvas documents and atomic, harness-independent editing."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.resource_limits import (
    MAX_CANVAS_ENTRIES,
    MAX_DIMENSION,
    MAX_PRINT_COPIES,
    validate_render_budget,
)
from .layout_engine import TEMPLATE_METADATA

JsonObject = dict[str, Any]
Percent = Annotated[str, Field(pattern=r"^-?\d+(?:\.\d+)?%$")]
Border = Literal["none", "box", "top", "bottom", "cut_line"]
ElementKind = Literal[
    "text",
    "icon_text",
    "image",
    "html",
    "barcode",
    "qrcode",
    "shape",
    "cut_line_indicator",
    "group",
    "label_template",
]


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class CanvasElement(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    id: str = Field(min_length=1, max_length=128)
    type: ElementKind
    pageIndex: int = Field(default=0, ge=0, lt=500)
    x: float | Percent = 0.0
    y: float | Percent = 0.0
    width: float | Percent | None = None
    height: float | Percent | None = None
    rotation: float = 0.0
    text: str | None = None
    data: str | None = None
    src: str | None = None
    html: str | None = None
    font: str | None = None
    icon: str | None = None
    size: float | None = Field(default=None, gt=0)
    barcodeType: str | None = None
    shapeType: Literal["rect", "circle", "ellipse", "line"] | None = None
    children: list[CanvasElement] | None = None

    @field_validator("x", "y", "width", "height")
    @classmethod
    def geometry(cls, value: float | str | None) -> float | str | None:
        if isinstance(value, str) and not re.fullmatch(r"-?\d+(?:\.\d+)?%", value):
            raise ValueError("Geometry strings must be percentages.")
        return value

    @model_validator(mode="after")
    def group_children(self) -> CanvasElement:
        if self.type == "group" and self.children is None:
            raise ValueError("Groups require children.")
        return self


class PageLayout(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    pageIndex: int = Field(ge=0, lt=500)
    htmlContent: str = ""
    activeTemplate: JsonObject | None = None


class CanvasDocument(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    document_version: Literal[1] = 1
    dpi: float = Field(default=203, gt=0, le=2400)
    width: float = Field(default=384, gt=0, le=MAX_DIMENSION)
    height: float = Field(default=384, gt=0, le=MAX_DIMENSION)
    canvasBorder: Border = "none"
    canvasBorderThickness: float = Field(default=4, gt=0, le=MAX_DIMENSION)
    isRotated: bool = False
    splitMode: bool = False
    pageLayouts: list[PageLayout] = Field(
        default_factory=lambda: [PageLayout(pageIndex=0)], min_length=1, max_length=500
    )
    items: list[CanvasElement] = Field(
        default_factory=list, max_length=MAX_CANVAS_ENTRIES
    )
    currentPage: int = Field(default=0, ge=0, lt=500)
    batchRecords: list[JsonObject] = Field(
        default_factory=lambda: [{}], min_length=1, max_length=1000
    )
    printCopies: int = Field(default=1, ge=1, le=MAX_PRINT_COPIES)


def normalize_document(value: JsonObject) -> JsonObject:
    """Migrate known legacy shapes once, preserve extras, validate all geometry."""
    document = copy.deepcopy(value)
    if "dpi" not in document:
        document["dpi"] = document.pop("__dpi__", 203)
    layouts = document.get("pageLayouts")
    if not layouts:
        document["pageLayouts"] = [
            {
                "pageIndex": 0,
                "htmlContent": document.pop("htmlContent", ""),
                "activeTemplate": document.pop("activeTemplate", None),
            }
        ]
    pending: list[tuple[object, int]] = [(document.get("items", []), 0)]
    ids: set[str] = set()
    count = 0
    while pending:
        elements, depth = pending.pop()
        if not isinstance(elements, list) or depth > 32:
            raise ValueError("Invalid elements or group depth exceeds 32.")
        for raw_element in cast(list[object], elements):
            count += 1
            if count > MAX_CANVAS_ENTRIES or not isinstance(raw_element, dict):
                raise ValueError("Element limit exceeded or invalid element.")
            element = cast(JsonObject, raw_element)
            if "id" not in element:
                element["id"] = f"legacy-{count}"
            element["id"] = str(element["id"])
            if element["id"] in ids:
                raise ValueError("Element IDs must be unique throughout the document.")
            ids.add(element["id"])
            if "children" in element:
                pending.append((element["children"], depth + 1))
    normalized = CanvasDocument.model_validate(document).model_dump(exclude_none=True)
    pages = {page["pageIndex"] for page in normalized["pageLayouts"]}
    if len(pages) != len(normalized["pageLayouts"]):
        raise ValueError("Page indices must be unique.")
    if normalized["currentPage"] not in pages:
        raise ValueError("Current page must exist.")
    for item in normalized["items"]:
        if item["pageIndex"] not in pages:
            raise ValueError("Element page must exist.")
    validate_render_budget(
        normalized,
        records=len(normalized["batchRecords"]),
        copies=normalized["printCopies"],
    )
    canonical_bytes(normalized)  # Reject NaN/Infinity, including preserved fields.
    return normalized


def create_document(width_mm: float, height_mm: float, dpi: float = 203) -> JsonObject:
    return normalize_document(
        {
            "dpi": dpi,
            "width": round(width_mm * dpi / 25.4),
            "height": round(height_mm * dpi / 25.4),
        }
    )


def apply_operations(value: JsonObject, operations: list[JsonObject]) -> JsonObject:
    """All edits commit together after complete validation; no mutations on error."""
    if not 1 <= len(operations) <= 100:
        raise ValueError("Supply 1 to 100 operations.")
    document = normalize_document(value)
    for operation in operations:
        op = operation.get("op")
        if op == "add_element":
            item = copy.deepcopy(operation["element"])
            item.setdefault("id", uuid.uuid4().hex)
            document["items"].append(item)
        elif op in {"update_element", "remove_element"}:

            def edit(
                elements: list[JsonObject],
                operation: JsonObject = operation,
                op: str = op,
            ) -> bool:
                for index, element in enumerate(elements):
                    if element["id"] == operation["id"]:
                        if op == "remove_element":
                            elements.pop(index)
                        else:
                            patch = operation["patch"]
                            if "id" in patch and patch["id"] != element["id"]:
                                raise ValueError("Element identity cannot change.")
                            element.update(copy.deepcopy(patch))
                        return True
                    if isinstance(element.get("children"), list) and edit(
                        element["children"]
                    ):
                        return True
                return False

            if not edit(document["items"]):
                raise ValueError("Element not found.")
        elif op == "set_geometry":
            dpi = operation.get("dpi", document["dpi"])
            document.update(
                dpi=dpi,
                width=round(operation["width_mm"] * dpi / 25.4),
                height=round(operation["height_mm"] * dpi / 25.4),
            )
        elif op == "set_border":
            document["canvasBorder"] = operation["border"]
            document["canvasBorderThickness"] = operation.get(
                "thickness", document["canvasBorderThickness"]
            )
        elif op == "set_batch":
            document["batchRecords"] = copy.deepcopy(operation["records"])
            document["printCopies"] = operation.get("copies", document["printCopies"])
        elif op in {"add_page", "duplicate_page"}:
            index = max(p["pageIndex"] for p in document["pageLayouts"]) + 1
            page = {"pageIndex": index, "htmlContent": "", "activeTemplate": None}
            if op == "duplicate_page":
                source = operation["page_index"]
                page = copy.deepcopy(
                    next(p for p in document["pageLayouts"] if p["pageIndex"] == source)
                )
                page["pageIndex"] = index
                for item in list(document["items"]):
                    if item["pageIndex"] == source:
                        cloned = copy.deepcopy(item)
                        stack = [cloned]
                        while stack:
                            node = stack.pop()
                            node.update(id=uuid.uuid4().hex, pageIndex=index)
                            stack.extend(node.get("children", []))
                        document["items"].append(cloned)
            document["pageLayouts"].append(page)
        elif op == "remove_page":
            index = operation["page_index"]
            if not any(p["pageIndex"] == index for p in document["pageLayouts"]):
                raise ValueError("Page not found.")
            if len(document["pageLayouts"]) == 1:
                raise ValueError("A document must retain at least one page.")
            document["pageLayouts"] = [
                p for p in document["pageLayouts"] if p["pageIndex"] != index
            ]
            document["items"] = [
                i for i in document["items"] if i["pageIndex"] != index
            ]
            mapping = {
                old: new
                for new, old in enumerate(
                    sorted(p["pageIndex"] for p in document["pageLayouts"])
                )
            }
            for page in document["pageLayouts"]:
                page["pageIndex"] = mapping[page["pageIndex"]]
            stack = list(document["items"])
            while stack:
                item = stack.pop()
                item["pageIndex"] = mapping[item["pageIndex"]]
                stack.extend(item.get("children", []))
            document["currentPage"] = 0
        elif op == "apply_template":
            template_id = operation["template_id"]
            if not any(t["id"] == template_id for t in TEMPLATE_METADATA):
                raise ValueError("Unknown template.")
            page = next(
                p
                for p in document["pageLayouts"]
                if p["pageIndex"] == operation.get("page_index", 0)
            )
            page["activeTemplate"] = {
                "id": template_id,
                "params": copy.deepcopy(operation.get("params", {})),
            }
            page["htmlContent"] = (
                ""  # React generates canonical markup from this metadata.
            )
        else:
            raise ValueError(f"Unsupported edit operation: {op}")
    return normalize_document(document)


class EditOperation(BaseModel):
    """A supported atomic edit. Geometry is in document pixels except set_geometry's millimetres."""

    model_config = ConfigDict(extra="forbid", strict=True)
    op: Literal[
        "add_element",
        "update_element",
        "remove_element",
        "add_page",
        "duplicate_page",
        "remove_page",
        "set_geometry",
        "set_border",
        "apply_template",
        "set_batch",
    ]
    element: JsonObject | None = Field(
        default=None,
        description="Required for add_element; type, geometry and content; id generated when omitted.",
    )
    id: str | None = Field(
        default=None, description="Existing element ID for update/remove."
    )
    patch: JsonObject | None = Field(
        default=None, description="Changed element fields for update_element."
    )
    width_mm: float | None = Field(default=None, gt=0)
    height_mm: float | None = Field(default=None, gt=0)
    dpi: float | None = Field(default=None, gt=0, le=2400)
    border: Border | None = None
    thickness: float | None = Field(default=None, gt=0)
    records: list[JsonObject] | None = Field(
        default=None, min_length=1, max_length=1000
    )
    copies: int | None = Field(default=None, ge=1, le=MAX_PRINT_COPIES)
    page_index: int | None = Field(default=None, ge=0, lt=500)
    template_id: str | None = None
    params: JsonObject | None = None

    @model_validator(mode="after")
    def required_arguments(self) -> EditOperation:
        required = {
            "add_element": ["element"],
            "update_element": ["id", "patch"],
            "remove_element": ["id"],
            "duplicate_page": ["page_index"],
            "remove_page": ["page_index"],
            "set_geometry": ["width_mm", "height_mm"],
            "set_border": ["border"],
            "apply_template": ["template_id"],
            "set_batch": ["records"],
        }
        for name in required.get(self.op, []):
            if getattr(self, name) is None:
                raise ValueError(f"{name} is required for {self.op}.")
        return self
