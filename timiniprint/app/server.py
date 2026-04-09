import asyncio
import json
import os
import shutil
from typing import Dict, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, create_engine, Session, select

from .models import PrinterProfile, Font, Template, Settings
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

async def execute_print_job(mac_address: str, img: Any):
    """Helper function to handle scanning, connecting with retries, and printing."""
    registry = PrinterModelRegistry.load()
    resolver = DeviceResolver(registry)
    
    # Scan to find the device and its capabilities
    devices, _ = await resolver.scan_printer_devices_with_failures(
        include_classic=True,
        include_ble=True,
    )
    
    target_device = next((d for d in devices if d.address == mac_address), None)
    if not target_device:
        raise HTTPException(status_code=404, detail=f"Printer {mac_address} not found in scan. Is it turned on?")
        
    from ..rendering.renderer import image_to_raster
    from ..protocol.job import build_job_from_raster
    from ..transport.bluetooth import SppBackend
    
    pipeline_config = target_device.model.image_pipeline
    raster = image_to_raster(img, pipeline_config.default_format, dither=True)
    
    job = build_job_from_raster(
        raster=raster,
        is_text=False,
        speed=target_device.model.img_print_speed,
        energy=target_device.model.moderation_energy or 5000,
        blackening=3,
        lsb_first=not target_device.model.a4xii,
        protocol_family=target_device.model.protocol_family,
        feed_padding=12,
        dev_dpi=target_device.model.dev_dpi,
        can_print_label=target_device.model.can_print_label,
        image_pipeline=pipeline_config,
    )
    
    backend = SppBackend()
    
    # Get the connection attempts (BLE vs Classic)
    attempts = resolver.build_connection_attempts(target_device)
    if not attempts:
        raise HTTPException(status_code=500, detail="No valid connection endpoints found for this printer.")
        
    # Robust retry loop for waking up sleeping printers
    max_retries = 3
    last_error = None
    
    for attempt in range(max_retries):
        try:
            await backend.connect_attempts(attempts)
            try:
                # Send the job in chunks
                await backend.write(job, chunk_size=128, interval_ms=0)
            finally:
                await backend.disconnect()
            return # Success!
        except Exception as e:
            last_error = e
            await asyncio.sleep(1.5) # Wait before retrying
            
    raise HTTPException(status_code=500, detail=f"Failed to connect after {max_retries} attempts. Error: {str(last_error)}")

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

@app.post("/api/print/template/{template_id}")
async def print_template(template_id: int, request: PrintRequest):
    with Session(engine) as session:
        template = session.get(Template, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        template_data = json.loads(template.canvas_state_json)
        
    # Render the image using our engine
    img = render_template(template_data, request.variables)
    
    # Execute the print job with retries
    await execute_print_job(request.mac_address, img)
    
    return {
        "status": "success", 
        "message": f"Template printed successfully to {request.mac_address}",
        "mac_address": request.mac_address
    }

@app.post("/api/print/direct")
async def print_direct(request: DirectPrintRequest):
    """Endpoint for the frontend to test print without saving a template."""
    img = render_template(request.canvas_state, request.variables)
    await execute_print_job(request.mac_address, img)
    
    return {
        "status": "success", 
        "message": f"Direct print successful to {request.mac_address}",
        "mac_address": request.mac_address
    }

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
    with Session(engine) as session:
        fonts = session.exec(select(Font)).all()
        return fonts

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
