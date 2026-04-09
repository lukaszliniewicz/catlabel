import asyncio
import json
import os
import base64
from io import BytesIO
import shutil
from typing import Dict, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pypdfium2 as pdfium
from sqlmodel import SQLModel, create_engine, Session, select

from .models import PrinterProfile, Font, Template, Settings, Address
from ..rendering.template import render_template
from ..devices import DeviceResolver, PrinterModelRegistry
from ..transport.bluetooth import SppBackend
from .. import reporting

sqlite_file_name = "timiniprint.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="TiMini Print Server", lifespan=lifespan)

os.makedirs("fonts", exist_ok=True)
app.mount("/fonts", StaticFiles(directory="fonts"), name="fonts")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TemplateCreate(BaseModel):
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
            # Protect protocol buffer wrapping: scale non-split items to exact hardware width if they over/underflow
            if img.width != print_width_px:
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
                for job in jobs:
                    await backend.write(job, chunk_size=128, interval_ms=0)
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

@app.post("/api/templates")
def create_template(template: TemplateCreate):
    with Session(engine) as session:
        db_template = Template(
            name=template.name, 
            canvas_state_json=json.dumps(template.canvas_state)
        )
        session.add(db_template)
        session.commit()
        session.refresh(db_template)
        return db_template

@app.get("/api/templates")
def list_templates():
    with Session(engine) as session:
        templates = session.exec(select(Template)).all()
        # Parse JSON back to dict for the API response
        return [
            {
                "id": t.id, 
                "name": t.name, 
                "canvas_state": json.loads(t.canvas_state_json)
            } 
            for t in templates
        ]

class TemplateUpdate(BaseModel):
    canvas_state: Dict[str, Any]

@app.put("/api/templates/{template_id}")
def update_template(template_id: int, template_update: TemplateUpdate):
    with Session(engine) as session:
        db_template = session.get(Template, template_id)
        if not db_template:
            raise HTTPException(status_code=404, detail="Template not found")
        db_template.canvas_state_json = json.dumps(template_update.canvas_state)
        session.add(db_template)
        session.commit()
        session.refresh(db_template)
        return db_template

@app.delete("/api/templates/{template_id}")
def delete_template(template_id: int):
    with Session(engine) as session:
        db_template = session.get(Template, template_id)
        if not db_template:
            raise HTTPException(status_code=404, detail="Template not found")
        session.delete(db_template)
        session.commit()
        return {"status": "deleted"}

@app.post("/api/print/template/{template_id}")
async def print_template(template_id: int, request: PrintRequest):
    with Session(engine) as session:
        template = session.get(Template, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        template_data = json.loads(template.canvas_state_json)
        split_mode = template_data.get("splitMode", False)
        
    # Render the image using our engine
    img = render_template(template_data, request.variables)
    
    # Execute the print job with retries
    await execute_print_job(request.mac_address, img, split_mode)
    
    return {
        "status": "success", 
        "message": f"Template printed successfully to {request.mac_address}",
        "mac_address": request.mac_address
    }

@app.post("/api/print/direct")
async def print_direct(request: DirectPrintRequest):
    """Endpoint for the frontend to test print without saving a template."""
    split_mode = request.canvas_state.get("splitMode", False)
    img = render_template(request.canvas_state, request.variables)
    await execute_print_job(request.mac_address, img, split_mode)
    
    return {
        "status": "success", 
        "message": f"Direct print successful to {request.mac_address}",
        "mac_address": request.mac_address
    }

@app.post("/api/print/batch")
async def print_batch(request: BatchPrintRequest):
    split_mode = request.canvas_state.get("splitMode", False)
    images = []
    if request.variables_list:
        for variables in request.variables_list:
            for _ in range(request.copies):
                img = render_template(request.canvas_state, variables)
                images.append(img)
    else:
        img = render_template(request.canvas_state, {})
        for _ in range(request.copies):
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
    os.makedirs("fonts", exist_ok=True)
    file_path = f"fonts/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    with Session(engine) as session:
        db_font = Font(name=file.filename, file_path=file_path)
        session.add(db_font)
        session.commit()
        session.refresh(db_font)
        return db_font

@app.get("/api/fonts")
def list_fonts():
    os.makedirs("fonts", exist_ok=True)
    with Session(engine) as session:
        # 1. Get existing fonts from the database
        db_fonts = {f.name: f for f in session.exec(select(Font)).all()}
        
        # 2. Scan the 'fonts' folder on disk
        disk_fonts = [f for f in os.listdir("fonts") if f.lower().endswith((".ttf", ".otf"))]
        
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
