"""Official SDK tools/resources over shared CatLabel application services."""

from __future__ import annotations

import base64
import inspect
import json
from collections.abc import Callable
from typing import Annotated, Any, Literal, cast

from mcp.server import MCPServer
from mcp.types import (
    CallToolResult,
    ImageContent,
    ResourceLink,
    TextContent,
    ToolAnnotations,
)
from pydantic import BaseModel

from ..services import printers, projects
from ..services.documents import (
    EditOperation,
    apply_operations,
    create_document,
    normalize_document,
)
from ..services.harness import HarnessServices


class ToolOutcome(BaseModel):
    ok: bool
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


MCPResult = Annotated[CallToolResult, ToolOutcome]


class Registry:
    def __init__(self, services: HarnessServices) -> None:
        self.services = services
        self.server = MCPServer(
            "CatLabel",
            version="0.1.0",
            instructions="Create or load a saved design, edit with expected_revision, inspect a PNG preview, prepare a frozen printer plan, then start with a unique idempotency key. Print start has physical effects; use the harness approval policy. Submitted means physical completion is unverified. Never silently retry an uncertain delivery.",
        )
        self._register()

    async def invoke(
        self, call: Callable[[], object], *, preview: bool = False, image_index: int = 0
    ) -> MCPResult:
        try:
            result = call()
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, BaseModel):
                result = result.model_dump()
            if not isinstance(result, dict):
                result = {"items": result}
            data = cast(dict[str, Any], result)
            blocks: list[Any] = []
            if preview:
                data = {k: v for k, v in data.items() if k != "document"}
                artifacts = data.get("artifacts", [])
                if artifacts:
                    if not 0 <= image_index < len(artifacts):
                        raise ValueError("Preview image index is out of range.")
                    artifact = artifacts[image_index]
                    if (
                        artifact["mime_type"] == "image/png"
                        and artifact["size_bytes"] <= 1024 * 1024
                    ):
                        blocks.append(
                            ImageContent(
                                data=base64.b64encode(
                                    self.services.artifacts.read_bytes(artifact["id"])
                                ).decode("ascii"),
                                mime_type="image/png",
                            )
                        )
                    blocks.append(
                        ResourceLink(
                            name="Full artifact",
                            uri="catlabel://artifacts/" + artifact["id"],
                            mime_type=artifact["mime_type"],
                            size=artifact["size_bytes"],
                        )
                    )
            structured = ToolOutcome(ok=True, data=data).model_dump(exclude_none=True)
            blocks.insert(
                0,
                TextContent(
                    text=json.dumps(structured, ensure_ascii=False, allow_nan=False)
                ),
            )
            return CallToolResult(content=blocks, structured_content=structured)
        except Exception as exc:
            detail = getattr(exc, "detail", getattr(exc, "details", None))
            status = getattr(exc, "status_code", None)
            code = getattr(
                exc,
                "code",
                "revision_conflict"
                if status == 409 and isinstance(exc, projects.ProjectServiceError)
                else "invalid_request"
                if isinstance(exc, (ValueError, KeyError, StopIteration))
                else "operation_failed",
            )
            error = {
                "code": code,
                "message": str(exc),
                "retryable": bool(getattr(exc, "retryable", False)),
            }
            if detail is not None:
                error["details"] = detail
            structured = ToolOutcome(ok=False, error=error).model_dump(
                exclude_none=True
            )
            return CallToolResult(
                content=[
                    TextContent(
                        text=json.dumps(structured, ensure_ascii=False, default=str)
                    )
                ],
                structured_content=structured,
                is_error=True,
            )

    def _register(self) -> None:
        server, service = self.server, self.services
        read = ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        )
        write = ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
        physical = ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=True,
        )

        @server.tool(annotations=read)
        async def catlabel_server_info() -> MCPResult:
            """Inspect transport, limits and available workflow capabilities."""
            return await self.invoke(
                lambda: {
                    "name": "CatLabel",
                    "protocols": ["2026-07-28", "2025-11-25"],
                    "tasks": False,
                    "transport": "streamable_http",
                    "retry_window_days": 90,
                    "physical_completion": "unverified",
                    "capabilities": [
                        "design",
                        "preview",
                        "export",
                        "printer",
                        "print_jobs",
                    ],
                }
            )

        @server.tool(annotations=read)
        async def catlabel_catalog_get(
            kind: Literal["schema", "fonts", "templates", "presets", "models"],
        ) -> MCPResult:
            """Inspect canonical schema, fonts, templates, presets or supported models."""
            return await self.invoke(lambda: service.catalog(kind))

        @server.tool(annotations=read)
        async def catlabel_design_list(
            limit: int = 100, after_id: int = 0
        ) -> MCPResult:
            """List compact saved design summaries using a stable cursor."""
            return await self.invoke(
                lambda: projects.list_project_summaries(
                    limit, after_id, db_engine=service.engine
                )
            )

        @server.tool(annotations=read)
        async def catlabel_design_get(design_id: int) -> MCPResult:
            """Read a saved design and its optimistic revision."""
            return await self.invoke(lambda: service.get_design(design_id))

        @server.tool(annotations=write)
        async def catlabel_design_create(
            name: str,
            width_mm: float = 48,
            height_mm: float = 25,
            dpi: float = 203,
            category_id: int | None = None,
            document: dict[str, Any] | None = None,
        ) -> MCPResult:
            """Create a saved design with physical dimensions or a validated document."""

            def create() -> dict[str, Any]:
                value = (
                    create_document(width_mm, height_mm, dpi)
                    if document is None
                    else normalize_document(document)
                )
                saved = projects.create_project(
                    projects.ProjectCreate(
                        name=name, canvas_state=value, category_id=category_id
                    ),
                    db_engine=service.engine,
                )
                assert saved.id is not None
                return service.get_design(saved.id)

            return await self.invoke(create)

        @server.tool(annotations=write)
        async def catlabel_design_apply(
            design_id: int, expected_revision: int, operations: list[EditOperation]
        ) -> MCPResult:
            """Atomically apply supported element/page/geometry/template/batch edits; reject stale revisions."""

            def apply() -> dict[str, Any]:
                existing = service.get_design(design_id)
                document = apply_operations(
                    existing["canvas_state"],
                    [op.model_dump(exclude_none=True) for op in operations],
                )
                projects.update_project(
                    design_id,
                    projects.ProjectUpdate(
                        canvas_state=document, expected_revision=expected_revision
                    ),
                    db_engine=service.engine,
                )
                return service.get_design(design_id)

            return await self.invoke(apply)

        @server.tool(annotations=write)
        async def catlabel_design_copy(design_id: int, name: str) -> MCPResult:
            """Create a named working copy without altering the original."""

            def copy_design() -> dict[str, Any]:
                source = service.get_design(design_id)
                saved = projects.create_project(
                    projects.ProjectCreate(
                        name=name,
                        canvas_state=normalize_document(source["canvas_state"]),
                        category_id=source["category_id"],
                    ),
                    db_engine=service.engine,
                )
                assert saved.id is not None
                return service.get_design(saved.id)

            return await self.invoke(copy_design)

        @server.tool(annotations=read)
        async def catlabel_design_export(design_id: int) -> MCPResult:
            """Export the saved document as portable CatLabel JSON."""

            return await self.invoke(lambda: service.export_design(design_id))

        @server.tool(annotations=read)
        async def catlabel_categories_list() -> MCPResult:
            """List saved organization categories."""
            return await self.invoke(
                lambda: {
                    "categories": [
                        c.model_dump()
                        for c in projects.list_categories(db_engine=service.engine)
                    ]
                }
            )

        @server.tool(annotations=write)
        async def catlabel_category_upsert(
            name: str, category_id: int | None = None, parent_id: int | None = None
        ) -> MCPResult:
            """Create or update a category with cycle validation."""
            return await self.invoke(
                lambda: (
                    projects.create_category(
                        projects.CategoryCreate(name=name, parent_id=parent_id),
                        db_engine=service.engine,
                    )
                    if category_id is None
                    else projects.update_category(
                        category_id,
                        projects.CategoryUpdate(name=name, parent_id=parent_id),
                        db_engine=service.engine,
                    )
                )
            )

        @server.tool(annotations=write)
        async def catlabel_asset_import(
            base64_data: str,
            mime_type: Literal[
                "image/png", "image/jpeg", "image/webp", "application/pdf"
            ],
        ) -> MCPResult:
            """Import bounded image/PDF bytes into managed assets; no server paths or URL fetches."""
            return await self.invoke(
                lambda: service.import_asset(base64_data, mime_type)
            )

        @server.tool(annotations=write)
        async def catlabel_preview_create(
            design_id: int, expected_revision: int, pages: list[int] | None = None
        ) -> MCPResult:
            """Render selected saved pages through the existing React renderer; return PNG and immutable identity."""
            return await self.invoke(
                lambda: service.preview(design_id, expected_revision, pages),
                preview=True,
            )

        @server.tool(annotations=read)
        async def catlabel_preview_get(
            preview_id: str, image_index: int = 0
        ) -> MCPResult:
            """Retrieve an existing immutable preview, its PNG and full artifact link."""
            return await self.invoke(
                lambda: service.get_preview(preview_id),
                preview=True,
                image_index=image_index,
            )

        @server.tool(annotations=read)
        async def catlabel_artifact_get(artifact_id: str) -> MCPResult:
            """Inspect an artifact and retrieve a bounded PNG without resource browsing."""
            return await self.invoke(
                lambda: {"artifacts": [service.artifacts.get(artifact_id)]},
                preview=True,
            )

        @server.tool(
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=True,
            )
        )
        async def catlabel_printers_scan() -> MCPResult:
            """Discover supported BLE/classic printers; printer must be powered on."""
            return await self.invoke(printers.scan_printers)

        @server.tool(annotations=read)
        async def catlabel_printer_get(printer_address: str) -> MCPResult:
            """Inspect saved/default printer settings without creating database rows."""
            return await self.invoke(
                lambda: printers.get_printer_profile(
                    printer_address, db_engine=service.engine
                )
            )

        @server.tool(annotations=write)
        async def catlabel_printer_profile_update(
            printer_address: str, settings: printers.PrinterProfileUpdate
        ) -> MCPResult:
            """Persist printer defaults; prepared plans retain their frozen settings."""
            return await self.invoke(
                lambda: printers.update_printer_profile(
                    printer_address,
                    settings,
                    db_engine=service.engine,
                )
            )

        @server.tool(annotations=write)
        async def catlabel_print_prepare(
            preview_id: str,
            expected_preview_hash: str,
            printer_address: str,
            copies: int | None = None,
        ) -> MCPResult:
            """Freeze reviewed source PNGs, settings and explicit printer identity into a short-lived plan. No print data is sent."""
            return await self.invoke(
                lambda: service.prepare(
                    preview_id, expected_preview_hash, printer_address, copies
                )
            )

        @server.tool(annotations=physical)
        async def catlabel_print_start(
            plan_id: str, expected_plan_hash: str, idempotency_key: str
        ) -> MCPResult:
            """Start a physical print once per key. Apply harness approval policy; inspect uncertain jobs before deliberate retry."""
            return await self.invoke(
                lambda: service.jobs.start(
                    plan_id, expected_plan_hash, idempotency_key, service.principal
                )
            )

        @server.tool(annotations=read)
        async def catlabel_job_get(job_id: str) -> MCPResult:
            """Read durable submission state; submitted does not prove physical completion."""
            return await self.invoke(
                lambda: service.jobs.job_get(job_id, service.principal)
            )

        @server.tool(annotations=read)
        async def catlabel_jobs_list(
            limit: int = 100, after_id: str | None = None
        ) -> MCPResult:
            """List compact durable job receipts for this credential."""
            return await self.invoke(
                lambda: service.jobs.jobs_list(
                    service.principal, limit=limit, after_id=after_id
                )
            )

        @server.tool(annotations=write)
        async def catlabel_job_cancel(job_id: str) -> MCPResult:
            """Cancel only before delivery begins; sending cannot be generically retracted."""
            return await self.invoke(
                lambda: service.jobs.cancel(job_id, service.principal)
            )

        @server.resource("catlabel://schema/document", mime_type="application/json")
        def document_schema() -> str:
            return json.dumps(service.catalog("schema")["document"])

        @server.resource("catlabel://catalog/{kind}", mime_type="application/json")
        def catalog_resource(kind: str) -> str:
            return json.dumps(service.catalog(kind))

        @server.resource(
            "catlabel://artifacts/{artifact_id}", mime_type="application/octet-stream"
        )
        def artifact_resource(artifact_id: str) -> bytes:
            return service.artifacts.read_bytes(artifact_id)
