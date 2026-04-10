import asyncio
import json
import os
import base64
from io import BytesIO
import shutil
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pypdfium2 as pdfium
from sqlmodel import SQLModel, create_engine, Session, select

from .models import PrinterProfile, Font, Project, Settings, Address
from ..rendering.template import render_template
from ..devices import DeviceResolver, PrinterModelRegistry
from ..transport.bluetooth import SppBackend
from .. import reporting

os.makedirs("data", exist_ok=True)
sqlite_file_name = "data/timiniprint.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="TiMini Print Server", lifespan=lifespan)

os.makedirs("data/fonts", exist_ok=True)
app.mount("/fonts", StaticFiles(directory="data/fonts"), name="fonts")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STANDARD_PRESETS = [
    {"name": "Standard Tape (Full Width)", "width_mm": 48, "height_mm": 48, "is_rotated": False, "border": "none"},
    {"name": "Gridfinity Bin Label (42x12mm)", "width_mm": 42, "height_mm": 12, "is_rotated": False, "border": "box"},
    {"name": "Cable Flag / Wire Wrap (30x48mm)", "width_mm": 30, "height_mm": 48, "is_rotated": False, "border": "cut_line"},
    {"name": "Folder Tab (50x15mm)", "width_mm": 50, "height_mm": 15, "is_rotated": False, "border": "box"},
    {"name": "A6 Shipping (105x148mm - Oversize)", "width_mm": 105, "height_mm": 148, "is_rotated": False, "split_mode": True, "border": "box"},
]

@app.get("/api/presets")
def list_presets():
    """Provides standard layout dimensions to the UI and LLM."""
    return STANDARD_PRESETS

@app.get("/api/agent/context")
def get_agent_context():
    """
    Highly optimized endpoint specifically for LLM System Prompt injection.
    Gives the agent total situational awareness of the physical layout rules and database state.
    """
    with Session(engine) as session:
        # Get active settings & hardware limits
        settings = session.get(Settings, 1) or Settings()
        
        # Get available fonts to prevent LLM hallucination
        fonts = session.exec(select(Font)).all()
        font_names = [f.name for f in fonts]
        
        # Get user's saved projects so the LLM can reference or print them by ID
        projects = session.exec(select(Project)).all()
        project_summaries = [{"id": p.id, "name": p.name} for p in projects]

    return {
        "engine_rules": {
            "coordinate_system": "1 mm = 8 pixels. ALWAYS use pixels for canvas width/height and element x/y/width/height.",
            "hardware_width_mm": settings.print_width_mm,
            "hardware_width_px": int(settings.print_width_mm * 8),
            "behavior_padding": "If you define a canvas narrower than the hardware width, the engine will automatically center and pad it with white space. Do NOT stretch elements to fit the hardware if the user wants a small label.",
            "behavior_oversize": "If canvas width exceeds hardware width and splitMode=false, the engine scales it down. If splitMode=true, it slices it into parallel printable strips.",
            "feed_axis": "Thermal tape is infinitely long. Leave splitMode=false and set canvas height to whatever you need for long banners."
        },
        "standard_presets": STANDARD_PRESETS,
        "available_fonts": font_names,
        "saved_projects": project_summaries,
        "global_default_font": settings.default_font
    }

class ProjectCreate(BaseModel):
    name: str
    canvas_state: Dict[str, Any]

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

async def execute_print_jobs(mac_address: str, images: List[Any], split_mode: bool = False):
    """Handles scanning, continuous connection, and streaming multiple jobs efficiently."""
    with Session(engine) as session:
        settings = session.get(Settings, 1) or Settings()

    registry = PrinterModelRegistry.load()
    resolver = DeviceResolver(registry)
    
    devices, _ = await resolver.scan_printer_devices_with_failures(
        include_classic=True, include_ble=True
    )
    
    target_device = next((d for d in devices if d.address == mac_address), None)
    if not target_device:
        raise HTTPException(status_code=404, detail=f"Printer {mac_address} not found. Is it turned on?")
        
    from ..rendering.renderer import image_to_raster
    from ..protocol.job import build_job_from_raster
    from ..transport.bluetooth import SppBackend
    
    from PIL import Image
    pipeline_config = target_device.model.image_pipeline
    print_width_px = target_device.model.width
    
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
            # CRITICAL FIX: Pad narrower canvases, only downscale if strictly oversize
            if img.width != print_width_px:
                if img.width < print_width_px:
                    # User designed a narrow label (e.g. 12mm). Center it on the 48mm tape.
                    padded = Image.new("RGB", (print_width_px, img.height), "white")
                    offset_x = (print_width_px - img.width) // 2
                    padded.paste(img, (offset_x, 0))
                    img = padded
                else:
                    # Image is larger than tape but not in split mode; scale it down
                    ratio = print_width_px / float(img.width)
                    new_height = max(1, int(img.height * ratio))
                    img = img.resize((print_width_px, new_height), Image.Resampling.LANCZOS)
            final_images.append(img)

    # Pre-render all raw protocol jobs
    jobs = []
    total_images = len(final_images)
    for i, img in enumerate(final_images):
        # 1. Apply feed padding only to the very last segment in a batch sequence
        is_last = (i == total_images - 1)
        current_feed = settings.feed_lines if is_last else 0
        
        raster = image_to_raster(img, pipeline_config.default_format, dither=True)
        job = build_job_from_raster(
            raster=raster,
            is_text=False,
            speed=settings.speed if settings.speed > 0 else target_device.model.img_print_speed,
            energy=settings.energy if settings.energy > 0 else (target_device.model.moderation_energy or 5000),
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
                for i, job in enumerate(jobs):
                    await backend.write(job, chunk_size=128, interval_ms=0)
                    
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
        session.add(settings)
        session.commit()
        return settings

class ProjectUpdate(BaseModel):
    canvas_state: Dict[str, Any]

@app.post("/api/projects")
def create_project(project: ProjectCreate):
    with Session(engine) as session:
        db_project = Project(
            name=project.name, 
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
        # Parse JSON back to dict for the API response
        return [
            {
                "id": p.id, 
                "name": p.name, 
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

@app.post("/api/print/direct")
async def print_direct(request: DirectPrintRequest):
    """Endpoint for the frontend to test print without saving a template."""
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        default_font = settings.default_font if settings else "arial.ttf"

    split_mode = request.canvas_state.get("splitMode", False)
    img = render_template(request.canvas_state, request.variables, default_font=default_font)
    await execute_print_job(request.mac_address, img, split_mode)
    
    return {
        "status": "success", 
        "message": f"Direct print successful to {request.mac_address}",
        "mac_address": request.mac_address
    }

@app.post("/api/print/batch")
async def print_batch(request: BatchPrintRequest):
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        default_font = settings.default_font if settings else "arial.ttf"

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
            img = render_template(request.canvas_state, variables, default_font=default_font)
            images.append(img)
            
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
    registry = PrinterModelRegistry.load()
    resolver = DeviceResolver(registry)
    devices, failures = await resolver.scan_printer_devices_with_failures(
        include_classic=True,
        include_ble=True,
    )
    
    results = []
    for device in devices:
        # Safely get the name, falling back to the model name if available
        name = getattr(device, "name", None)
        if not name and device.model:
            name = device.model.name
            
        results.append({
            "name": name or "Unknown Printer",
            "address": device.address,
            "display_address": getattr(device, "display_address", device.address),
            "paired": device.paired,
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
