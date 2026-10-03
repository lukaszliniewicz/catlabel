"""Shared design/preview/print-plan workflows, independent of MCP and REST."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import io
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

from PIL import Image
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from ..core.models import LabelPreset, Settings
from ..core.paths import FONTS_DIRECTORY, FRONTEND_DIRECTORY
from ..core.resource_limits import (
    MAX_IMAGE_BYTES,
    MAX_REQUEST_BYTES,
    MAX_UPLOAD_BYTES,
    validate_render_budget,
)
from ..rendering.image_payload import decode_image_payloads
from ..rendering.template import render_via_browser_async
from . import printers, projects
from .artifacts import ArtifactStore
from .documents import canonical_bytes, content_hash, normalize_document
from .print_executor import execute_owned_print_jobs
from .print_jobs import PrintJobCoordinator
from .uploads import convert_uploaded_pdf

JsonObject = dict[str, Any]


class HarnessServices:
    def __init__(
        self, db_engine: Engine, artifacts: ArtifactStore, *, principal: str
    ) -> None:
        self.engine = db_engine
        self.artifacts = artifacts
        self.principal = principal
        self.jobs = PrintJobCoordinator(db_engine, artifacts, self._execute)

    def get_design(self, design_id: int) -> JsonObject:
        return projects.get_project_document(design_id, db_engine=self.engine)

    def export_design(self, design_id: int) -> JsonObject:
        design = self.get_design(design_id)
        document = copy.deepcopy(design["canvas_state"])
        stack = list(document.get("items", []))
        embedded_bytes = 0
        while stack:
            element = stack.pop()
            src = element.get("src")
            if isinstance(src, str) and src.startswith("catlabel://artifacts/"):
                metadata = self.artifacts.get(src.rsplit("/", 1)[-1])
                embedded_bytes += (metadata["size_bytes"] + 2) // 3 * 4
                if embedded_bytes > MAX_REQUEST_BYTES:
                    raise ValueError("Portable export exceeds the document byte limit.")
                raw = self.artifacts.read_bytes(metadata["id"])
                element["src"] = "data:image/png;base64," + base64.b64encode(
                    raw
                ).decode("ascii")
            stack.extend(element.get("children", []))
        exported = {
            "catlabel_export_version": "1.0",
            "data": {
                "type": "project",
                "name": design["name"],
                "canvas_state": document,
            },
        }
        if len(canonical_bytes(exported)) > MAX_REQUEST_BYTES:
            raise ValueError("Portable export exceeds the document byte limit.")
        return exported

    def catalog(self, kind: str) -> JsonObject:
        from .documents import CanvasDocument, EditOperation
        from .layout_engine import TEMPLATE_METADATA

        if kind == "schema":
            return {
                "document": CanvasDocument.model_json_schema(),
                "edit_operation": EditOperation.model_json_schema(),
            }
        if kind == "templates":
            return {"templates": TEMPLATE_METADATA}
        if kind == "fonts":
            return {
                "fonts": sorted(
                    p.name
                    for p in FONTS_DIRECTORY.glob("*")
                    if p.suffix.lower() in {".ttf", ".otf"}
                )
            }
        if kind == "models":
            return printers.get_supported_models()
        if kind == "presets":
            with Session(self.engine) as session:
                return {
                    "presets": [
                        p.model_dump() for p in session.exec(select(LabelPreset)).all()
                    ]
                }
        raise ValueError("Unknown catalog kind.")

    async def import_asset(self, encoded: str, mime_type: str) -> JsonObject:
        from fastapi import UploadFile

        if len(encoded) > ((MAX_UPLOAD_BYTES + 2) // 3) * 4:
            raise ValueError("Asset exceeds upload limit.")
        data = base64.b64decode(encoded, validate=True)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("Asset exceeds upload limit.")
        if mime_type == "application/pdf":
            file = UploadFile(io.BytesIO(data), filename="input.pdf")
            pages = await convert_uploaded_pdf(file)
            result: list[JsonObject] = []
            for page in pages:
                payload = base64.b64decode(page.split(",", 1)[-1], validate=True)
                result.append(
                    self.artifacts.put_bytes(
                        payload, mime_type="image/png", kind="asset"
                    )
                )
            return {"assets": result}
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds image limit.")
        images = decode_image_payloads([encoded])
        try:
            output = io.BytesIO()
            images[0].save(output, format="PNG")
            return {
                "assets": [
                    self.artifacts.put_bytes(
                        output.getvalue(), mime_type="image/png", kind="asset"
                    )
                ]
            }
        finally:
            for image in images:
                image.close()

    async def submit_legacy(
        self,
        address: str,
        prepare: Callable[[], Awaitable[list[Image.Image]]],
        split_mode: bool,
        dither: bool,
    ) -> JsonObject:
        images = await prepare()
        sources: list[JsonObject] = []
        try:
            for image in images:
                output = io.BytesIO()
                image.save(output, format="PNG")
                sources.append(
                    self.artifacts.put_bytes(
                        output.getvalue(), mime_type="image/png", kind="print_source"
                    )
                )
        finally:
            for image in images:
                image.close()
        if not sources:
            raise ValueError("No labels supplied.")
        scan = await printers.scan_printers()
        from ..printing.admission import canonical_device_address

        target = next(
            (
                d
                for d in scan["devices"]
                if canonical_device_address(d["address"])
                == canonical_device_address(address)
            ),
            None,
        )
        if target is None:
            raise printers.ServiceError(
                404,
                {
                    "message": "Printer not found.",
                    "stage": "scan",
                    "delivery_uncertain": False,
                },
            )
        with Session(self.engine) as session:
            settings = session.get(Settings, 1) or Settings()
        profile = printers.get_printer_profile(address, db_engine=self.engine)
        assert profile is not None
        manifest = {
            "printer_address": address,
            "settings": settings.model_dump(),
            "profile": profile.model_dump(),
            "hardware": {
                "vendor": target["vendor"],
                "model_id": target["model_id"],
                "catalog_sha256": printers.hardware_catalog_hash(),
            },
            "copies": 1,
            "pages_per_record": len(sources),
            "split_mode": split_mode,
            "dither": dither,
            "is_rotated": False,
        }
        plan = self.jobs.create_plan(manifest, [a["id"] for a in sources])
        job = await self.jobs.start(
            plan["id"], plan["plan_hash"], uuid.uuid4().hex, "local-editor"
        )
        while job["state"] in {"accepted", "sending"}:
            await asyncio.sleep(0.1)
            job = self.jobs.job_get(job["id"], "local-editor")
        if job["state"] == "submitted":
            return {**job["receipt"], "job_id": job["id"]}
        error = cast(JsonObject, job.get("error") or {})
        details = cast(JsonObject, error.get("details") or {})
        raise printers.ServiceError(
            int(
                details.get(
                    "status_code", 409 if error.get("code") == "printer_busy" else 500
                )
            ),
            {
                **details,
                "message": error.get("message", "Print job stopped."),
                "stage": error.get("stage", "print"),
                "job_id": job["id"],
                "error_id": job["id"],
                "delivery_uncertain": job["state"] == "delivery_uncertain",
            },
        )

    def renderer_identity(self) -> JsonObject:
        from importlib.metadata import version

        bundle = hashlib.sha256()
        for path in sorted(FRONTEND_DIRECTORY.rglob("*")):
            if path.is_file():
                bundle.update(str(path.relative_to(FRONTEND_DIRECTORY)).encode())
                bundle.update(path.read_bytes())
        return {
            "frontend_sha256": bundle.hexdigest(),
            "playwright": version("playwright"),
            "template_sha256": content_hash(self.catalog("templates")),
            "render_contract": 1,
        }

    async def preview(
        self, design_id: int, expected_revision: int, pages: list[int] | None = None
    ) -> JsonObject:
        project = self.get_design(design_id)
        if project["revision"] != expected_revision:
            raise projects.ProjectServiceError(
                409,
                {
                    "message": "Project changed.",
                    "current_revision": project["revision"],
                },
            )
        document = normalize_document(project["canvas_state"])
        available = [p["pageIndex"] for p in document["pageLayouts"]]
        selected = available if pages is None else pages
        if (
            not selected
            or len(set(selected)) != len(selected)
            or any(p not in available for p in selected)
        ):
            raise ValueError("Select existing unique pages.")
        render_document = copy.deepcopy(document)
        render_document["__secure_network__"] = True
        render_document["pageLayouts"] = [
            p for p in document["pageLayouts"] if p["pageIndex"] in selected
        ]
        render_document["items"] = [
            i for i in document["items"] if i["pageIndex"] in selected
        ]
        render_document["currentPage"] = selected[0]
        # Existing renderer orders pages numerically. Preserve/report that order.
        selected = sorted(selected)
        page_mapping = {original: index for index, original in enumerate(selected)}
        for layout in render_document["pageLayouts"]:
            layout["pageIndex"] = page_mapping[layout["pageIndex"]]
        for item in render_document["items"]:
            item["pageIndex"] = page_mapping[item["pageIndex"]]
        render_document["currentPage"] = 0
        stack = list(render_document["items"])
        while stack:
            item = stack.pop()
            src = item.get("src")
            if isinstance(src, str) and src.startswith("catlabel://artifacts/"):
                raw = self.artifacts.read_bytes(src.rsplit("/", 1)[-1])
                item["src"] = "data:image/png;base64," + base64.b64encode(raw).decode(
                    "ascii"
                )
            elif isinstance(src, str) and not src.startswith("data:"):
                raise ValueError(
                    "Import image bytes as a managed asset before rendering."
                )
            stack.extend(item.get("children", []))
        validate_render_budget(
            render_document, records=len(document["batchRecords"]), copies=1
        )
        images = await render_via_browser_async(
            render_document, document["batchRecords"], 1
        )
        artifacts: list[JsonObject] = []
        try:
            for image in images:
                output = io.BytesIO()
                image.save(output, format="PNG")
                artifacts.append(
                    self.artifacts.put_bytes(
                        output.getvalue(), mime_type="image/png", kind="preview_page"
                    )
                )
        finally:
            for image in images:
                image.close()
        manifest = {
            "design_id": design_id,
            "revision": expected_revision,
            "document_hash": content_hash(document),
            "document": document,
            "pages": selected,
            "artifacts": artifacts,
            "dpi": document["dpi"],
            "width_mm": document["width"] * 25.4 / document["dpi"],
            "height_mm": document["height"] * 25.4 / document["dpi"],
            "renderer": self.renderer_identity(),
            "warnings": [],
        }
        metadata = self.artifacts.put_bytes(
            canonical_bytes(manifest), mime_type="application/json", kind="preview"
        )
        self.artifacts.pin(
            "preview:" + metadata["id"],
            [metadata["id"], *[a["id"] for a in artifacts]],
            expires_at=time.time() + 86400,
        )
        return {
            "preview_id": metadata["id"],
            "preview_hash": metadata["sha256"],
            **manifest,
        }

    def get_preview(self, preview_id: str) -> JsonObject:
        metadata = self.artifacts.get(preview_id)
        if metadata["kind"] != "preview" or metadata["expires_at"] < time.time():
            raise ValueError("Preview missing or expired.")
        return {
            "preview_id": preview_id,
            "preview_hash": metadata["sha256"],
            **json.loads(self.artifacts.read_bytes(preview_id)),
        }

    async def prepare(
        self,
        preview_id: str,
        expected_preview_hash: str,
        printer_address: str,
        copies: int | None = None,
    ) -> JsonObject:
        preview = self.get_preview(preview_id)
        if preview["preview_hash"] != expected_preview_hash:
            raise ValueError("Preview hash does not match.")
        scan = await printers.scan_printers()
        from ..printing.admission import canonical_device_address

        target = next(
            (
                d
                for d in scan["devices"]
                if canonical_device_address(d["address"])
                == canonical_device_address(printer_address)
            ),
            None,
        )
        if target is None:
            raise ValueError("Printer not found. Power it on and scan again.")
        if not target.get("model_id") or target["model_id"] == "generic":
            raise ValueError("Printer model is not supported unambiguously.")
        document = preview["document"]
        count = document["printCopies"] if copies is None else copies
        validate_render_budget(
            document, records=len(document["batchRecords"]), copies=count
        )
        with Session(self.engine) as session:
            settings = session.get(Settings, 1) or Settings()
        profile = printers.get_printer_profile(printer_address, db_engine=self.engine)
        assert profile is not None
        manifest = {
            "preview_id": preview_id,
            "preview_hash": expected_preview_hash,
            "printer_address": printer_address,
            "hardware": {
                "vendor": target["vendor"],
                "model_id": target["model_id"],
                "catalog_sha256": printers.hardware_catalog_hash(),
            },
            "settings": settings.model_dump(),
            "profile": profile.model_dump(),
            "copies": count,
            "split_mode": document["splitMode"],
            "dither": True,
            "is_rotated": document["isRotated"],
            "label_count": len(preview["artifacts"]) * count,
            "pages_per_record": len(preview["pages"]),
            "printer_transformations_resolved": False,
            "warnings": [
                "The source PNGs are frozen. Vendor resizing, dithering, splitting and firmware may affect physical output."
            ],
        }
        return self.jobs.create_plan(manifest, [a["id"] for a in preview["artifacts"]])

    async def _execute(
        self, manifest: JsonObject, on_delivery_start: Callable[[], Awaitable[None]]
    ) -> JsonObject:
        async def prepare_images() -> list[Image.Image]:
            images: list[Image.Image] = []
            try:
                sources = manifest["source_artifacts"]
                pages_per_record = manifest["pages_per_record"]
                for start in range(0, len(sources), pages_per_record):
                    for _ in range(manifest["copies"]):
                        for source in sources[start : start + pages_per_record]:
                            image = Image.open(
                                io.BytesIO(self.artifacts.read_bytes(source["id"]))
                            )
                            try:
                                image.load()
                                prepared = image.convert("RGB")
                            finally:
                                image.close()
                            if manifest["is_rotated"]:
                                rotated = prepared.rotate(90, expand=True)
                                prepared.close()
                                prepared = rotated
                            images.append(prepared)
                return images
            except BaseException:
                for image in images:
                    image.close()
                raise

        return await execute_owned_print_jobs(
            manifest["printer_address"],
            prepare_images,
            manifest["split_mode"],
            manifest["dither"],
            db_engine=self.engine,
            frozen_settings=manifest["settings"],
            frozen_profile=manifest["profile"],
            expected_hardware=manifest["hardware"],
            on_delivery_start=on_delivery_start,
        )
