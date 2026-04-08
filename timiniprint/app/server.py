import asyncio
import json
from typing import Dict, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
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
    
    # 2. Save to disk for debugging (we will wire up Bluetooth next)
    debug_filename = f"debug_render_{template_id}.png"
    img.save(debug_filename)
    
    return {
        "status": "success", 
        "message": f"Template rendered and saved to {debug_filename}",
        "mac_address": request.mac_address
    }

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
