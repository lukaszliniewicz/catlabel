import asyncio
import logging
import os
import shutil
import urllib.request
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from functools import lru_cache
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select
from starlette.responses import Response

from ..core.database import create_db_and_tables, engine
from ..core.models import Address, Font, LabelPreset, Project, Settings
from ..core.paths import (
    APPLICATION_ROOT,
    DATA_DIRECTORY,
    FONTS_DIRECTORY,
    FRONTEND_DIRECTORY,
    LEGACY_FONTS_DIRECTORY,
)
from ..core.release_artifacts import load_release_manifest, verify_artifact_directory
from ..core.runtime_lease import RuntimeLease
from ..core.server_security import ServerSecurity
from ..rendering.template import close_browser_renderer
from ..services.agent_context import build_agent_context
from ..services.artifacts import ArtifactError, ArtifactStore
from ..services.harness import HarnessServices
from ..services.layout_engine import TEMPLATE_METADATA
from ..services.prepared_prints import PreparedPrintStore
from ..services.uploads import convert_uploaded_pdf, store_uploaded_font
from . import routes_print
from .request_limits import RequestLimitsMiddleware
from .routes_ai import migrate_legacy_provider
from .routes_ai import router as ai_router
from .routes_prepared_print import router as prepared_print_router
from .routes_print import router as print_router
from .routes_project import router as project_router
from .security import LocalSecurityMiddleware

logger = logging.getLogger(__name__)


def seed_default_presets():
    from ..vendors import VendorRegistry

    with Session(engine) as session:
        existing_names = {
            preset.name for preset in session.exec(select(LabelPreset)).all()
        }

        added = False
        for preset in VendorRegistry.get_all_presets():
            if preset["name"] in existing_names:
                continue
            session.add(LabelPreset(**preset))
            added = True

        if added:
            session.commit()


def download_default_fonts():
    fonts = {
        "Roboto.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth%2Cwght%5D.ttf",
        "RobotoCondensed.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/robotocondensed/RobotoCondensed%5Bwght%5D.ttf",
        "FiraCode.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/firacode/FiraCode%5Bwght%5D.ttf",
        "Oswald.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/Oswald%5Bwght%5D.ttf",
        "BebasNeue.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
        "PlayfairDisplay.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    }
    FONTS_DIRECTORY.mkdir(parents=True, exist_ok=True)

    if LEGACY_FONTS_DIRECTORY.is_dir():
        for source in LEGACY_FONTS_DIRECTORY.iterdir():
            if source.is_file() and source.suffix.lower() in (".ttf", ".otf"):
                target = FONTS_DIRECTORY / source.name
                if not target.exists():
                    shutil.copy2(source, target)

    for filename, url in fonts.items():
        target = FONTS_DIRECTORY / filename
        if not os.path.exists(target):
            print(f"Downloading Variable Font: {filename}...")
            temporary_target = target.with_name(f"{target.name}.download")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with (
                    urllib.request.urlopen(req, timeout=30) as response,
                    temporary_target.open("wb") as f,
                ):
                    shutil.copyfileobj(response, f)
                os.replace(temporary_target, target)
            except Exception as e:
                if temporary_target.exists():
                    temporary_target.unlink()
                print(f"Failed to download {filename}: {e}")


@lru_cache(maxsize=1)
def release_identity() -> dict[str, str | int] | None:
    manifest_path = APPLICATION_ROOT / "release-manifest.json"
    if not manifest_path.exists():
        return None
    manifest = load_release_manifest(manifest_path)
    verify_artifact_directory(APPLICATION_ROOT, manifest)
    return {
        "release_id": manifest.release_id,
        "source_commit": manifest.source_commit,
        "frontend_sha256": manifest.frontend_sha256,
        "database_epoch": manifest.database_epoch,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    with RuntimeLease(DATA_DIRECTORY):
        prepared_print_store = PreparedPrintStore()
        app.state.prepared_print_store = prepared_print_store
        reaper_task = asyncio.create_task(
            _reap_prepared_print_sessions(prepared_print_store),
            name="catlabel-prepared-print-reaper",
        )
        try:
            release_identity()
            create_db_and_tables()
            migrate_legacy_provider(engine)
            seed_default_presets()
            if os.environ.get("CATLABEL_ACCEPTANCE_PROBE") != "1":
                download_default_fonts()
            artifacts = ArtifactStore(engine, DATA_DIRECTORY / "artifacts")
            services = HarnessServices(engine, artifacts, principal="local-editor")
            app.state.harness_services = services
            routes_print.configure_harness(services)
            try:
                async with AsyncExitStack() as stack:
                    if os.environ.get("CATLABEL_MCP_ENABLED") == "1":
                        from ..mcp.auth import credential_path, load_credential
                        from ..mcp.integration import build_mcp

                        credential = load_credential(
                            credential_path(DATA_DIRECTORY), create=True
                        )
                        services.principal = credential.principal
                        registry, asgi = build_mcp(
                            services, credential, security_settings.port
                        )
                        await stack.enter_async_context(
                            registry.server.session_manager.run()
                        )
                        app.state.mcp_asgi = asgi
                    yield
            finally:
                routes_print.configure_harness(None)
                app.state.mcp_asgi = None
                await services.jobs.close()
                artifacts.close()
                app.state.harness_services = None
        finally:
            try:
                reaper_task.cancel()
                with suppress(asyncio.CancelledError):
                    await reaper_task
            finally:
                prepared_print_store.close()
                if (
                    getattr(app.state, "prepared_print_store", None)
                    is prepared_print_store
                ):
                    app.state.prepared_print_store = None
                try:
                    await close_browser_renderer()
                except Exception:
                    logger.exception("Browser renderer cleanup failed during shutdown")


async def _reap_prepared_print_sessions(store: PreparedPrintStore) -> None:
    while True:
        await asyncio.sleep(30)
        try:
            store.reap()
            services = getattr(app.state, "harness_services", None)
            if services is not None:
                services.jobs.reap()
                services.artifacts.reap()
        except Exception:
            logger.exception("Failed to reap expired prepared print sessions")


security_settings = ServerSecurity.from_environment()
app = FastAPI(title="CatLabel Server", lifespan=lifespan)

FONTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
app.mount("/fonts", StaticFiles(directory=str(FONTS_DIRECTORY)), name="fonts")

app.add_middleware(RequestLimitsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(security_settings.allowed_origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CatLabel-Client", "Authorization"],
    allow_credentials=True,
)
app.add_middleware(LocalSecurityMiddleware, settings=security_settings)

if os.environ.get("CATLABEL_MCP_ENABLED") == "1":
    if security_settings.host not in {"127.0.0.1", "::1"}:
        raise RuntimeError("The local MCP requires CATLABEL_HOST=127.0.0.1 or ::1.")
    from ..mcp.integration import MCPMount

    app.mount("/mcp", MCPMount(app), name="mcp")

app.include_router(print_router)
app.include_router(prepared_print_router)
app.include_router(project_router)
app.include_router(ai_router)


@app.get("/api/projects/{project_id}/revision")
def get_project_revision(project_id: int):
    with Session(engine) as session:
        revision = session.exec(
            select(Project.revision).where(Project.id == project_id)
        ).first()
        if revision is None:
            raise HTTPException(404, "Project not found.")
        return {"id": project_id, "revision": revision}


@app.get("/api/assets/{artifact_id}")
def get_managed_asset(artifact_id: str):
    services = getattr(app.state, "harness_services", None)
    if services is None:
        raise HTTPException(503, "Asset service is not ready.")
    try:
        metadata = services.artifacts.get(artifact_id)
        data = services.artifacts.read_bytes(artifact_id)
    except ArtifactError as exc:
        raise HTTPException(404, "Image asset not found.") from exc
    if metadata["mime_type"] != "image/png":
        raise HTTPException(404, "Image asset not found.")
    return Response(
        data,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/api/health", tags=["Diagnostics"])
def health_check():
    """Lightweight same-origin probe used to distinguish API errors from a stopped server."""
    identity = release_identity()
    if identity is None:
        return {"status": "ok"}
    return {"status": "ok", "release": identity}


class PresetCreate(BaseModel):
    name: str
    description: str | None = None
    media_type: str = "any"
    width_mm: float
    height_mm: float
    is_rotated: bool = False
    split_mode: bool = False
    border: str = "none"


@app.get("/api/presets")
def list_presets():
    with Session(engine) as session:
        return session.exec(select(LabelPreset).order_by(LabelPreset.name)).all()


@app.post("/api/presets")
def create_preset(preset: PresetCreate):
    with Session(engine) as session:
        payload = (
            preset.model_dump() if hasattr(preset, "model_dump") else preset.dict()
        )
        db_preset = LabelPreset(**payload)
        session.add(db_preset)
        session.commit()
        session.refresh(db_preset)
        return db_preset


@app.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: int):
    with Session(engine) as session:
        db_preset = session.get(LabelPreset, preset_id)
        if db_preset:
            session.delete(db_preset)
            session.commit()
        return {"status": "ok"}


@app.get("/api/agent/context")
def get_agent_context():
    return build_agent_context(engine)


@app.get("/api/settings")
def get_settings():
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        if not settings:
            settings = Settings(default_font="RobotoCondensed.ttf")
            session.add(settings)
            session.commit()
            session.refresh(settings)
        elif not settings.default_font:
            settings.default_font = "RobotoCondensed.ttf"
            session.add(settings)
            session.commit()
            session.refresh(settings)
        return settings


@app.post("/api/settings")
def update_settings(new_settings: Settings):
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        if not settings:
            settings = Settings()
        settings.paper_width_mm = new_settings.paper_width_mm
        settings.print_width_mm = new_settings.print_width_mm
        settings.default_dpi = new_settings.default_dpi
        settings.speed = new_settings.speed
        settings.energy = new_settings.energy
        settings.feed_lines = new_settings.feed_lines
        settings.default_font = new_settings.default_font
        settings.intended_media_type = new_settings.intended_media_type
        session.add(settings)
        session.commit()
        return settings


@app.post("/api/fonts")
async def upload_font(file: Annotated[UploadFile, File()]):
    return await store_uploaded_font(file, engine)


@app.get("/api/fonts")
def list_fonts():
    FONTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with Session(engine) as session:
        db_fonts = {f.name: f for f in session.exec(select(Font)).all()}
        disk_fonts = [
            font_path.name
            for font_path in FONTS_DIRECTORY.iterdir()
            if font_path.is_file() and font_path.suffix.lower() in (".ttf", ".otf")
        ]

        new_fonts = []
        for f in disk_fonts:
            if f not in db_fonts:
                new_font = Font(name=f, file_path=f"fonts/{f}")
                session.add(new_font)
                new_fonts.append(new_font)

        if new_fonts:
            session.commit()

        return session.exec(select(Font)).all()


@app.get("/api/addresses")
def get_addresses():
    with Session(engine) as session:
        return session.exec(select(Address)).all()


@app.post("/api/addresses")
def create_address(address: Address):
    with Session(engine) as session:
        session.add(address)
        session.commit()
        session.refresh(address)
        return address


@app.delete("/api/addresses/{address_id}")
def delete_address(address_id: int):
    with Session(engine) as session:
        db_address = session.get(Address, address_id)
        if db_address:
            session.delete(db_address)
            session.commit()
        return {"status": "deleted"}


class TemplateGenerateRequest(BaseModel):
    template_id: str
    width: int
    height: int
    params: dict[str, str] = {}


@app.get("/api/templates")
def get_templates():
    return {"templates": TEMPLATE_METADATA}


@app.post("/api/templates/generate")
def generate_template(req: TemplateGenerateRequest):
    valid = any(template["id"] == req.template_id for template in TEMPLATE_METADATA)

    if not valid:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400, detail=f"Unknown template_id: '{req.template_id}'"
        )

    return {"items": []}


@app.post("/api/pdf/convert")
async def convert_pdf(file: Annotated[UploadFile, File()]):
    return {"images": await convert_uploaded_pdf(file)}


if FRONTEND_DIRECTORY.exists():
    app.mount(
        "/", StaticFiles(directory=str(FRONTEND_DIRECTORY), html=True), name="frontend"
    )
