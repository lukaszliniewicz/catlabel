import asyncio
import json
import os
import base64
import urllib.request
import zipfile
import io
from io import BytesIO
import shutil
import subprocess
import tempfile
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pypdfium2 as pdfium
from sqlmodel import SQLModel, create_engine, Session, select

from .models import PrinterProfile, Font, Category, Project, Settings, Address, LabelPreset
from ..rendering.template import render_template
from ..devices import DeviceResolver, PrinterModelRegistry
from ..transport.bluetooth import SppBackend
from .ai_agent import router as ai_router
from .. import reporting

NIIMBOT_MODELS = {
    # D-Series (15mm print head = 240px max) - Max Density: 3
    "D110": {"vendor": "niimbot", "width_px": 240, "width_mm": 15.0, "dpi": 203, "model": "d110", "max_density": 3},
    "D11":  {"vendor": "niimbot", "width_px": 240, "width_mm": 15.0, "dpi": 203, "model": "d11", "max_density": 3},
    "D101": {"vendor": "niimbot", "width_px": 240, "width_mm": 15.0, "dpi": 203, "model": "d101", "max_density": 3},
    # B-Series (48mm print head = 384px max)
    "B18":  {"vendor": "niimbot", "width_px": 384, "width_mm": 48.0, "dpi": 203, "model": "b18", "max_density": 3},
    "B1":   {"vendor": "niimbot", "width_px": 384, "width_mm": 48.0, "dpi": 203, "model": "b1", "max_density": 5},
    "B21":  {"vendor": "niimbot", "width_px": 384, "width_mm": 48.0, "dpi": 203, "model": "b21", "max_density": 5},
}

def _manual_generic_model(model: str, width_mm: float, dpi: int = 203):
    return {
        "vendor": "generic",
        "width_px": max(1, int(round(width_mm * (dpi / 25.4)))),
        "width_mm": width_mm,
        "dpi": dpi,
        "model": model,
        "model_id": model,
        "media_type": "continuous",
        "default_speed": 0,
        "default_energy": 5000,
        "max_density": None,
    }

GENERIC_MODEL_ALIASES = {
    "GT01": _manual_generic_model("gt01", 48.0),
    "PD01": _manual_generic_model("gt01", 48.0),
    "MX05": _manual_generic_model("gt01", 48.0),
    "GENERIC": _manual_generic_model("generic", 48.0),
    "M08F": _manual_generic_model("m08f", 210.0),
}

def identify_printer_hardware(name: str, device=None):
    name_upper = (name or "").upper().strip()

    # Sort keys by length descending to ensure D110 is checked before D11
    for prefix in sorted(NIIMBOT_MODELS.keys(), key=len, reverse=True):
        if name_upper.startswith(prefix):
            return {
                **NIIMBOT_MODELS[prefix],
                "media_type": "pre-cut",
                "default_speed": 1,
                "default_energy": 3,
                "model_id": NIIMBOT_MODELS[prefix]["model"],
            }

    manual_alias = GENERIC_MODEL_ALIASES.get(name_upper)
    if manual_alias:
        return dict(manual_alias)

    hw_info = {
        "vendor": "generic",
        "width_px": 384,
        "width_mm": 48.0,
        "dpi": 203,
        "model": "generic",
        "model_id": "generic",
        "default_speed": 0,
        "default_energy": 5000,
        "max_density": None,
    }

    if device and hasattr(device, "model") and device.model:
        hw_info["width_px"] = device.model.width
        hw_info["dpi"] = device.model.dev_dpi
        hw_info["width_mm"] = round(device.model.width / device.model.dev_dpi * 25.4, 1)
        hw_info["model"] = device.model.model_no
        hw_info["model_id"] = device.model.model_no
        hw_info["default_speed"] = device.model.img_print_speed
        hw_info["default_energy"] = device.model.moderation_energy or 5000

    hw_info["media_type"] = "pre-cut" if hw_info["vendor"] == "niimbot" else "continuous"
    return hw_info

os.makedirs("data", exist_ok=True)
sqlite_file_name = "data/catlabel.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)

_scanned_devices_cache: List[Any] = []

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

DEFAULT_LABEL_PRESETS = [
    # Continuous Media
    {"name": "Roll: Standard Square (48x48mm)", "media_type": "continuous", "description": "Default full-width square for continuous rolls.", "width_mm": 48, "height_mm": 48, "is_rotated": False, "split_mode": False, "border": "none"},
    {"name": "Roll: Narrow Tag (48x12mm)", "media_type": "continuous", "description": "Generic roll preset with full width and 12mm height.", "width_mm": 48, "height_mm": 12, "is_rotated": False, "split_mode": False, "border": "none"},
    {"name": "Roll: Narrow Tag (48x15mm)", "media_type": "continuous", "description": "Short horizontal tag for lists/names. Prints fast, saves tape. Includes a cut-line for scissors.", "width_mm": 48, "height_mm": 15, "is_rotated": False, "split_mode": False, "border": "cut_line"},
    {"name": "Roll: Small Item / Gridfinity (30x12mm)", "media_type": "continuous", "description": "Small centered label. The printer pads the sides. Includes a bounding box to cut out.", "width_mm": 30, "height_mm": 12, "is_rotated": False, "split_mode": False, "border": "box"},
    {"name": "Roll: Long Banner (48x100mm)", "media_type": "continuous", "description": "Landscape banner for continuous rolls. Use for shipping or long text.", "width_mm": 100, "height_mm": 48, "is_rotated": True, "split_mode": False, "border": "none"},
    {"name": "Roll: Cable Flag (30x48mm)", "media_type": "continuous", "description": "Fold-over cable flag. Prints vertically.", "width_mm": 30, "height_mm": 48, "is_rotated": False, "split_mode": False, "border": "cut_line"},

    # Pre-cut Media (Niimbot)
    {"name": "Pre-cut: Niimbot 30x15mm", "media_type": "pre-cut", "description": "Standard small Niimbot D-series label.", "width_mm": 30, "height_mm": 15, "is_rotated": True, "split_mode": False, "border": "none"},
    {"name": "Pre-cut: Niimbot 40x12mm", "media_type": "pre-cut", "description": "Standard medium Niimbot D-series label.", "width_mm": 40, "height_mm": 12, "is_rotated": True, "split_mode": False, "border": "none"},
    {"name": "Pre-cut: Niimbot 50x14mm", "media_type": "pre-cut", "description": "Standard large Niimbot D-series label.", "width_mm": 50, "height_mm": 14, "is_rotated": True, "split_mode": False, "border": "none"},
    {"name": "Pre-cut: Niimbot Cable 109x12.5mm", "media_type": "pre-cut", "description": "Niimbot D-series cable wrap label.", "width_mm": 109, "height_mm": 12.5, "is_rotated": True, "split_mode": False, "border": "none"},
    {"name": "Pre-cut: Niimbot B-Series 40x14mm", "media_type": "pre-cut", "description": "Small B-series label.", "width_mm": 40, "height_mm": 14, "is_rotated": True, "split_mode": False, "border": "none"},
    {"name": "Pre-cut: Niimbot B1/B21 50x30mm", "media_type": "pre-cut", "description": "Large B-series label.", "width_mm": 50, "height_mm": 30, "is_rotated": True, "split_mode": False, "border": "none"},

    # Any/Split
    {"name": "A6 Shipping (105x148mm)", "media_type": "continuous", "description": "Giant multi-strip decal for A6 shipping labels.", "width_mm": 105, "height_mm": 148, "is_rotated": False, "split_mode": True, "border": "none"},
]

def seed_default_presets():
    with Session(engine) as session:
        existing_names = {
            preset.name
            for preset in session.exec(select(LabelPreset)).all()
        }

        added = False
        for preset in DEFAULT_LABEL_PRESETS:
            if preset["name"] in existing_names:
                continue
            session.add(LabelPreset(**preset))
            added = True

        if added:
            session.commit()

def download_default_fonts():
    """Silently downloads Variable Fonts from Google Fonts raw CDN."""
    fonts = {
        "Roboto.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth%2Cwght%5D.ttf",
        "RobotoCondensed.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/robotocondensed/RobotoCondensed%5Bwght%5D.ttf",
        "FiraCode.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/firacode/FiraCode%5Bwght%5D.ttf",
        "Oswald.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/Oswald%5Bwght%5D.ttf"
    }
    os.makedirs("data/fonts", exist_ok=True)
    for filename, url in fonts.items():
        target = os.path.join("data/fonts", filename)
        if not os.path.exists(target):
            print(f"Downloading Variable Font: {filename}...")
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response, open(target, 'wb') as f:
                    f.write(response.read())
            except Exception as e:
                print(f"Failed to download {filename}: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    seed_default_presets()
    download_default_fonts()
    yield

app = FastAPI(title="CatLabel Server", lifespan=lifespan)

os.makedirs("data/fonts", exist_ok=True)
app.mount("/fonts", StaticFiles(directory="data/fonts"), name="fonts")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router)

class PresetCreate(BaseModel):
    name: str
    description: Optional[str] = None
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
        payload = preset.model_dump() if hasattr(preset, "model_dump") else preset.dict()
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

@app.get("/api/printers/model/{name}")
def get_printer_model_info(name: str):
    """Returns hardware characteristics based on the model name alias."""
    return identify_printer_hardware(name)

@app.get("/api/agent/context")
def get_agent_context():
    """
    Highly optimized endpoint specifically for LLM System Prompt injection.
    Gives the agent total situational awareness of the physical layout rules and database state.
    """
    with Session(engine) as session:
        settings = session.get(Settings, 1) or Settings()

        fonts = session.exec(select(Font)).all()
        font_names = [f.name for f in fonts]

        root_projects = session.exec(select(Project).where(Project.category_id == None)).all()
        root_categories = session.exec(select(Category).where(Category.parent_id == None)).all()
        presets = session.exec(select(LabelPreset).order_by(LabelPreset.name)).all()

        project_summaries = [{"id": p.id, "name": p.name} for p in root_projects]
        category_summaries = [{"id": c.id, "name": c.name} for c in root_categories]
        presets_data = [
            {
                "name": p.name,
                "media_type": p.media_type,
                "description": p.description,
                "width_mm": p.width_mm,
                "height_mm": p.height_mm
            } for p in presets
        ]

    return {
        "intended_media_type": settings.intended_media_type,
        "engine_rules": {
            "coordinate_system": "Dimensions are in PIXELS. 1 mm = (DPI / 25.4) pixels. The active DPI will be provided in your printer_info block. If no printer is connected, assume 203 DPI (1mm ≈ 8px).",
            "hardware_width_mm": settings.print_width_mm,
            "hardware_width_px": int(settings.print_width_mm * (settings.default_dpi / 25.4)),
            "behavior_padding": "If you define a canvas narrower than the hardware width, the engine will automatically center and pad it with white space. Do NOT stretch elements to fit the hardware if the user wants a small label.",
            "behavior_oversize": "If the dimension across the print head exceeds hardware width and splitMode=false, the engine scales it down.",
            "orientation_and_rotation": "CRITICAL ORIENTATION RULES:\n1. PRE-CUT LABELS (Niimbot): Usually fed sideways. ALWAYS use `apply_preset`. It automatically sets the correct rotation. Design normally left-to-right.\n2. CONTINUOUS ROLLS: Tape feeds infinitely. Use `set_canvas_dimensions`:\n  - Portrait ('across_tape'): width <= hardware_width, height = custom length. Good for standard lists/tags.\n  - Banner ('along_tape_banner'): height <= hardware_width, width = custom length. Use this when the user asks for a 'long' label, '20cm box label', or wide layout. Text reads along the tape."
        },
        "standard_presets": presets_data,
        "available_fonts": font_names,
        "root_projects": project_summaries,
        "root_categories": category_summaries,
        "global_default_font": settings.default_font
    }

class ProjectCreate(BaseModel):
    name: str
    canvas_state: Dict[str, Any]
    category_id: Optional[int] = None

class PrintRequest(BaseModel):
    mac_address: str
    variables: Dict[str, str] = {}

class DirectPrintRequest(BaseModel):
    mac_address: str
    canvas_state: Dict[str, Any]
    variables: Dict[str, str] = {}

class BatchPrintRequest(BaseModel):
    mac_address: str
    canvas_state: Dict[str, Any]
    copies: int = 1
    variables_list: List[Dict[str, str]] = []
    variables_matrix: Optional[Dict[str, List[str]]] = None

class PrinterProfileUpdate(BaseModel):
    speed: Optional[int] = None
    energy: Optional[int] = None
    feed_lines: Optional[int] = None

@app.get("/api/printers/{mac_address}/profile")
def get_printer_profile(mac_address: str):
    with Session(engine) as session:
        profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()
        if not profile:
            profile = PrinterProfile(mac_address=mac_address)
            session.add(profile)
            session.commit()
            session.refresh(profile)
        return profile

@app.put("/api/printers/{mac_address}/profile")
def update_printer_profile(mac_address: str, update: PrinterProfileUpdate):
    with Session(engine) as session:
        profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()
        if not profile:
            profile = PrinterProfile(mac_address=mac_address)

        if update.speed is not None:
            profile.speed = update.speed
        if update.energy is not None:
            profile.energy = update.energy
        if update.feed_lines is not None:
            profile.feed_lines = update.feed_lines

        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile

async def execute_print_jobs(mac_address: str, images: List[Any], split_mode: bool = False):
    """Handles scanning, continuous connection, and streaming multiple jobs efficiently."""
    global _scanned_devices_cache
    
    with Session(engine) as session:
        settings = session.get(Settings, 1) or Settings()
        printer_profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()

    registry = PrinterModelRegistry.load()
    resolver = DeviceResolver(registry)
    
    # 1. Try to fetch from recent scans first
    target_device = next((d for d in _scanned_devices_cache if d.address == mac_address), None)
    
    # 2. If not found, scan the environment (e.g., first print after backend restart)
    if not target_device:
        devices, _ = await resolver.scan_printer_devices_with_failures(
            include_classic=True, include_ble=True
        )
        _scanned_devices_cache = devices
        target_device = next((d for d in _scanned_devices_cache if d.address == mac_address), None)
        
    if not target_device:
        raise HTTPException(status_code=404, detail=f"Printer {mac_address} not found. Is it turned on?")
        
    # 2. Check Vendor
    hardware_info = identify_printer_hardware(target_device.name, target_device)
    print_width_px = hardware_info["width_px"]
    
    from PIL import Image
    
    final_images = []
    for img in images:
        if split_mode and img.width > print_width_px:
            # Slice image horizontally into printer-sized vertical strips
            for x in range(0, img.width, print_width_px):
                strip = img.crop((x, 0, min(x + print_width_px, img.width), img.height))
                if strip.width < print_width_px:
                    padded = Image.new("RGB", (print_width_px, strip.height), "white")
                    padded.paste(strip, (0, 0))
                    strip = padded
                final_images.append(strip)
        else:
            if hardware_info["vendor"] == "niimbot":
                # CRITICAL FIX: Do NOT pad Niimbot labels. Let the Niimbot engine set actual dimensions.
                if img.width > print_width_px:
                    ratio = print_width_px / float(img.width)
                    new_height = max(1, int(img.height * ratio))
                    img = img.resize((print_width_px, new_height), Image.Resampling.LANCZOS)
                final_images.append(img)
            else:
                # Generic Chinese Printers MUST pad narrower canvases to physical head width
                if img.width != print_width_px:
                    if img.width < print_width_px:
                        padded = Image.new("RGB", (print_width_px, img.height), "white")
                        offset_x = (print_width_px - img.width) // 2
                        padded.paste(img, (offset_x, 0))
                        img = padded
                    else:
                        ratio = print_width_px / float(img.width)
                        new_height = max(1, int(img.height * ratio))
                        img = img.resize((print_width_px, new_height), Image.Resampling.LANCZOS)
                final_images.append(img)

    # ==========================================
    # BRANCH: ROUTE TO SPECIFIC VENDOR ENGINE
    # ==========================================
    
    if hardware_info["vendor"] == "niimbot":
        # Route to Niimbot Engine
        from .vendors.niimbot.printer import PrinterClient

        # NiimPrintX expects a 'device' object with an address attribute
        class FakeBleakDevice:
            def __init__(self, address):
                self.address = address
                self.name = target_device.name

        # Ensure we connect to the BLE endpoint (UUID on macOS, BLE MAC on Win/Lin)
        ble_address = mac_address
        if hasattr(target_device, "ble_endpoint") and target_device.ble_endpoint:
            ble_address = target_device.ble_endpoint.address

        device = FakeBleakDevice(ble_address)
        printer = PrinterClient(device)

        if not await printer.connect():
            raise HTTPException(status_code=500, detail="Failed to connect to Niimbot")

        try:
            default_density = int(hardware_info.get("default_energy", 3) or 3)
            max_allowed = max(1, int(hardware_info.get("max_density", 5) or 5))
            raw_density = (
                printer_profile.energy
                if printer_profile and printer_profile.energy not in (None, 0)
                else default_density
            )
            density = max(1, min(int(raw_density), max_allowed))

            for img in final_images:
                await printer.print_image(img, density=density, quantity=1)
                await asyncio.sleep(1.0)
        finally:
            await printer.disconnect()

    else:
        # Route to Generic Chinese Engine (CatLabel default)
        from ..rendering.renderer import image_to_raster
        from ..protocol.job import build_job_from_raster
        from ..transport.bluetooth import SppBackend
        
        pipeline_config = target_device.model.image_pipeline

        hardware_default_speed = hardware_info.get("default_speed", getattr(target_device.model, "img_print_speed", 0))
        hardware_default_energy = hardware_info.get("default_energy", getattr(target_device.model, "moderation_energy", 5000) or 5000)

        use_speed = (
            printer_profile.speed
            if printer_profile and printer_profile.speed not in (None, 0)
            else (settings.speed if settings.speed > 0 else hardware_default_speed)
        )
        use_energy = (
            printer_profile.energy
            if printer_profile and printer_profile.energy not in (None, 0)
            else (settings.energy if settings.energy > 0 else hardware_default_energy)
        )
        use_feed = (
            printer_profile.feed_lines
            if printer_profile and printer_profile.feed_lines is not None
            else settings.feed_lines
        )

        jobs = []
        total_images = len(final_images)
        for i, img in enumerate(final_images):
            is_last = (i == total_images - 1)
            current_feed = use_feed if is_last else 0

            raster = image_to_raster(img, pipeline_config.default_format, dither=True)
            job = build_job_from_raster(
                raster=raster,
                is_text=False,
                speed=use_speed,
                energy=use_energy,
                blackening=3,
                lsb_first=not target_device.model.a4xii,
                protocol_family=target_device.model.protocol_family,
                feed_padding=current_feed,
                dev_dpi=target_device.model.dev_dpi,
                can_print_label=target_device.model.can_print_label,
                image_pipeline=pipeline_config,
            )
            jobs.append(job)
        
        backend = SppBackend()
        attempts = resolver.build_connection_attempts(target_device)
        if not attempts:
            raise HTTPException(status_code=500, detail="No valid connection endpoints found.")
            
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                await backend.connect_attempts(attempts)
                try:
                    # Stream all jobs continuously over the single open connection
                    interval = getattr(target_device.model, "interval_ms", 0)
                    for i, job in enumerate(jobs):
                        await backend.write(job, chunk_size=128, interval_ms=interval)
                        
                        # Thermal cooling pauses for long print batches
                        if i < len(jobs) - 1:
                            if (i + 1) % 3 == 0:
                                await asyncio.sleep(2.0)  # Let thermal head cool down
                            else:
                                await asyncio.sleep(0.3)  # Small gap between jobs
                finally:
                    await backend.disconnect()
                return
            except Exception as e:
                last_error = e
                await asyncio.sleep(1.5)
                
        raise HTTPException(status_code=500, detail=f"Failed to connect: {str(last_error)}")

async def execute_print_job(mac_address: str, img: Any, split_mode: bool = False):
    await execute_print_jobs(mac_address, [img], split_mode)

@app.get("/api/settings")
def get_settings():
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        if not settings:
            settings = Settings()
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

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    canvas_state: Optional[Dict[str, Any]] = None
    category_id: Optional[int] = None

class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None

def _provided_model_fields(model):
    if hasattr(model, "model_fields_set"):
        return set(model.model_fields_set)
    return set(getattr(model, "__fields_set__", set()))

@app.post("/api/projects")
def create_project(project: ProjectCreate):
    with Session(engine) as session:
        db_project = Project(
            name=project.name,
            category_id=project.category_id,
            canvas_state_json=json.dumps(project.canvas_state)
        )
        session.add(db_project)
        session.commit()
        session.refresh(db_project)
        return db_project

@app.get("/api/projects")
def list_projects():
    with Session(engine) as session:
        projects = session.exec(select(Project)).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "category_id": p.category_id,
                "canvas_state": json.loads(p.canvas_state_json)
            }
            for p in projects
        ]

@app.put("/api/projects/{project_id}")
def update_project(project_id: int, project_update: ProjectUpdate):
    with Session(engine) as session:
        db_project = session.get(Project, project_id)
        if not db_project:
            raise HTTPException(status_code=404, detail="Project not found")

        provided_fields = _provided_model_fields(project_update)

        if "name" in provided_fields and project_update.name is not None:
            db_project.name = project_update.name
        if "category_id" in provided_fields:
            db_project.category_id = project_update.category_id
        if "canvas_state" in provided_fields and project_update.canvas_state is not None:
            db_project.canvas_state_json = json.dumps(project_update.canvas_state)

        session.add(db_project)
        session.commit()
        session.refresh(db_project)
        return db_project

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    with Session(engine) as session:
        db_project = session.get(Project, project_id)
        if not db_project:
            raise HTTPException(status_code=404, detail="Project not found")
        session.delete(db_project)
        session.commit()
        return {"status": "deleted"}

@app.get("/api/categories")
def list_categories():
    with Session(engine) as session:
        return session.exec(select(Category)).all()

@app.post("/api/categories")
def create_category(cat: CategoryCreate):
    with Session(engine) as session:
        db_cat = Category(name=cat.name, parent_id=cat.parent_id)
        session.add(db_cat)
        session.commit()
        session.refresh(db_cat)
        return db_cat

@app.put("/api/categories/{cat_id}")
def update_category(cat_id: int, cat_update: CategoryUpdate):
    with Session(engine) as session:
        db_cat = session.get(Category, cat_id)
        if not db_cat:
            raise HTTPException(status_code=404, detail="Category not found")

        provided_fields = _provided_model_fields(cat_update)

        if "name" in provided_fields and cat_update.name is not None:
            db_cat.name = cat_update.name
        if "parent_id" in provided_fields:
            new_parent_id = cat_update.parent_id
            if new_parent_id == cat_id:
                raise HTTPException(status_code=400, detail="Category cannot be its own parent")

            current_check_id = new_parent_id
            while current_check_id is not None:
                if current_check_id == cat_id:
                    raise HTTPException(status_code=400, detail="Circular reference detected. Cannot move a folder into its own subfolder.")
                check_cat = session.get(Category, current_check_id)
                current_check_id = check_cat.parent_id if check_cat else None

            db_cat.parent_id = new_parent_id

        session.add(db_cat)
        session.commit()
        session.refresh(db_cat)
        return db_cat

def _delete_category_recursive(cat_id: int, session: Session):
    children = session.exec(select(Category).where(Category.parent_id == cat_id)).all()
    for child in children:
        _delete_category_recursive(child.id, session)

    projects = session.exec(select(Project).where(Project.category_id == cat_id)).all()
    for proj in projects:
        session.delete(proj)

    cat = session.get(Category, cat_id)
    if cat:
        session.delete(cat)

@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int):
    with Session(engine) as session:
        _delete_category_recursive(cat_id, session)
        session.commit()
        return {"status": "deleted"}

def _export_tree(category_id: Optional[int], session: Session, visited: set = None) -> dict:
    if visited is None:
        visited = set()

    if category_id is not None:
        if category_id in visited:
            return {}
        visited.add(category_id)

    cat_node = {"type": "category", "name": "Root", "children": []}
    if category_id:
        cat = session.get(Category, category_id)
        if not cat:
            return {}
        cat_node["name"] = cat.name

    children_cats = session.exec(select(Category).where(Category.parent_id == category_id)).all()
    for c in children_cats:
        child_export = _export_tree(c.id, session, visited)
        if child_export:
            cat_node["children"].append(child_export)

    projects = session.exec(select(Project).where(Project.category_id == category_id)).all()
    for p in projects:
        cat_node["children"].append({
            "type": "project",
            "name": p.name,
            "canvas_state": json.loads(p.canvas_state_json)
        })

    return cat_node

@app.get("/api/export")
def export_filesystem(category_id: Optional[int] = None):
    with Session(engine) as session:
        data = _export_tree(category_id, session)
        return {"catlabel_export_version": "1.0", "data": data}

def _import_tree(node: dict, parent_id: Optional[int], session: Session):
    if node.get("type") == "category":
        new_parent_id = parent_id
        if node.get("name") != "Root" or parent_id is not None:
            new_cat = Category(name=node["name"], parent_id=parent_id)
            session.add(new_cat)
            session.commit()
            session.refresh(new_cat)
            new_parent_id = new_cat.id

        for child in node.get("children", []):
            _import_tree(child, new_parent_id, session)

    elif node.get("type") == "project":
        new_proj = Project(
            name=node["name"],
            category_id=parent_id,
            canvas_state_json=json.dumps(node["canvas_state"])
        )
        session.add(new_proj)
        session.commit()

@app.post("/api/import")
async def import_filesystem(file: UploadFile = File(...), target_category_id: Optional[int] = None):
    try:
        content = await file.read()
        payload = json.loads(content)
        if payload.get("catlabel_export_version") != "1.0":
            raise ValueError("Invalid export file format.")

        with Session(engine) as session:
            _import_tree(payload["data"], target_category_id, session)

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def _extract_pages_from_canvas(canvas_state: Dict[str, Any], variables: Dict[str, str], default_font: str) -> List[Any]:
    items = list(canvas_state.get("items", []) or [])
    pages: Dict[int, List[Dict[str, Any]]] = {}

    if not items:
        pages[0] = []
    else:
        for item in items:
            page_index = int(item.get("pageIndex", 0) or 0)
            pages.setdefault(page_index, []).append(item)

    images = []
    for page_index in sorted(pages.keys()):
        page_state = dict(canvas_state)
        page_state["items"] = pages[page_index]
        images.append(render_template(page_state, variables, default_font=default_font))
    return images

@app.post("/api/print/direct")
async def print_direct(request: DirectPrintRequest):
    """Endpoint for the frontend to test print without saving a template."""
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        default_font = settings.default_font if settings else "Roboto.ttf"

    split_mode = request.canvas_state.get("splitMode", False)
    images = _extract_pages_from_canvas(request.canvas_state, request.variables, default_font)
    await execute_print_jobs(request.mac_address, images, split_mode)
    
    return {
        "status": "success", 
        "message": f"Direct print successful to {request.mac_address}",
        "mac_address": request.mac_address
    }

@app.post("/api/print/batch")
async def print_batch(request: BatchPrintRequest):
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        default_font = settings.default_font if settings else "Roboto.ttf"

    split_mode = request.canvas_state.get("splitMode", False)
    images = []
    
    variables_collection = []
    if request.variables_list:
        variables_collection.extend(request.variables_list)
        
    if request.variables_matrix:
        import itertools
        keys = list(request.variables_matrix.keys())
        values = list(request.variables_matrix.values())
        for combination in itertools.product(*values):
            variables_collection.append(dict(zip(keys, combination)))
            
    if not variables_collection:
        variables_collection = [{}]

    for variables in variables_collection:
        for _ in range(request.copies):
            images.extend(_extract_pages_from_canvas(request.canvas_state, variables, default_font))
            
    await execute_print_jobs(request.mac_address, images, split_mode)
    return {"status": "success", "printed": len(images)}

@app.post("/api/pdf/convert")
async def convert_pdf(file: UploadFile = File(...)):
    """Takes a PDF, renders it via PyPDFium2 to an image stream for Canvas extraction."""
    try:
        pdf_bytes = await file.read()
        doc = pdfium.PdfDocument(pdf_bytes)
        images = []
        scale = 203 / 72.0  # Equivalent conversion scale targeting 203 DPI standard
        for i in range(len(doc)):
            page = doc[i]
            pil_img = page.render(scale=scale).to_pil()
            
            buf = BytesIO()
            pil_img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            images.append(f"data:image/png;base64,{b64}")
            
        return {"images": images}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/fonts")
async def upload_font(file: UploadFile = File(...)):
    os.makedirs("data/fonts", exist_ok=True)
    file_path = f"data/fonts/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    with Session(engine) as session:
        db_font = Font(name=file.filename, file_path=f"fonts/{file.filename}")
        session.add(db_font)
        session.commit()
        session.refresh(db_font)
        return db_font

@app.get("/api/fonts")
def list_fonts():
    os.makedirs("data/fonts", exist_ok=True)
    with Session(engine) as session:
        # 1. Get existing fonts from the database
        db_fonts = {f.name: f for f in session.exec(select(Font)).all()}
        
        # 2. Scan the 'fonts' folder on disk
        disk_fonts = [f for f in os.listdir("data/fonts") if f.lower().endswith((".ttf", ".otf"))]
        
        # 3. Add any missing fonts from disk to the database
        new_fonts = []
        for f in disk_fonts:
            if f not in db_fonts:
                new_font = Font(name=f, file_path=f"fonts/{f}")
                session.add(new_font)
                new_fonts.append(new_font)
        
        # 4. Commit if we found new files
        if new_fonts:
            session.commit()
            
        # 5. Return the fully synced list
        return session.exec(select(Font)).all()

@app.get("/api/printers/scan")
async def scan_printers():
    global _scanned_devices_cache
    registry = PrinterModelRegistry.load()
    resolver = DeviceResolver(registry)
    devices, failures = await resolver.scan_printer_devices_with_failures(
        include_classic=True,
        include_ble=True,
    )
    _scanned_devices_cache = devices
    
    results = []
    for device in devices:
        # Safely get the name, falling back to the model name if available
        name = getattr(device, "name", None)
        if not name and hasattr(device, "model") and device.model:
            name = getattr(device.model, "head_name", "").strip('-')
        
        name = name or "Unknown Printer"
        hardware_info = identify_printer_hardware(name, device)
            
        results.append({
            "name": name,
            "address": device.address,
            "display_address": getattr(device, "display_address", device.address),
            "paired": device.paired,
            "vendor": hardware_info["vendor"],
            "width_px": hardware_info["width_px"],
            "width_mm": hardware_info["width_mm"],
            "dpi": hardware_info["dpi"],
            "model_id": hardware_info["model"],
            "media_type": hardware_info["media_type"],
            "default_speed": hardware_info.get("default_speed", 0),
            "default_energy": hardware_info.get("default_energy", 0),
            "max_density": hardware_info.get("max_density"),
        })
    return {"devices": results, "failures": [str(f.error) for f in failures]}

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

if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
