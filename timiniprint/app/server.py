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

from .models import PrinterProfile, Font, Template
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

@app.post("/api/print/template/{template_id}")
async def print_template(template_id: int, request: PrintRequest):
    with Session(engine) as session:
        template = session.get(Template, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        template_data = json.loads(template.canvas_state_json)
        
    # 1. Render the image using our new engine
    img = render_template(template_data, request.variables)
    
    # 2. Find the printer
    registry = PrinterModelRegistry.load()
    resolver = DeviceResolver(registry)
    devices, _ = await resolver.scan_printer_devices_with_failures(
        include_classic=True,
        include_ble=True,
    )
    
    target_device = next((d for d in devices if d.address == request.mac_address), None)
    if not target_device:
        raise HTTPException(status_code=404, detail=f"Printer {request.mac_address} not found in scan")
        
    # 3. Print
    from ..rendering.renderer import image_to_raster
    from ..protocol.job import build_job_from_raster
    
    # The model defines the image pipeline (e.g. dithering, width)
    pipeline_config = target_device.model.image_pipeline
    
    # Convert PIL Image to RasterBuffer
    raster = image_to_raster(img, pipeline_config)
    
    # Build the protocol job
    job = build_job_from_raster(raster, target_device.model.protocol_family)
    
    # Send it over Bluetooth
    backend = SppBackend()
    async with backend.connect(target_device) as transport_session:
        await transport_session.send(job)
    
    return {
        "status": "success", 
        "message": f"Template printed successfully to {request.mac_address}",
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
        results.append({
            "name": device.name,
            "address": device.address,
            "display_address": device.display_address,
            "transport": device.transport.value,
            "paired": device.paired,
        })
    return {"devices": results, "failures": [str(f.error) for f in failures]}
