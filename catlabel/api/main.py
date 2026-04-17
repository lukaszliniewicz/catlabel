import os
import urllib.request
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
import shutil

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select
import pypdfium2 as pdfium

from ..core.database import create_db_and_tables, engine
from ..core.models import Font, Settings, Address, LabelPreset, Project, Category
from ..services.layout_engine import TEMPLATE_METADATA, generate_template_items

from .routes_print import router as print_router
from .routes_project import router as project_router
from .routes_ai import router as ai_router

def seed_default_presets():
    from ..vendors import VendorRegistry

    with Session(engine) as session:
        existing_names = {
            preset.name
            for preset in session.exec(select(LabelPreset)).all()
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
        "PlayfairDisplay.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay%5Bital%2Cwght%5D.ttf"
    }
    os.makedirs("data/fonts", exist_ok=True)
    
    if os.path.exists("fonts"):
        for filename in os.listdir("fonts"):
            if filename.lower().endswith((".ttf", ".otf")):
                src = os.path.join("fonts", filename)
                dst = os.path.join("data/fonts", filename)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)

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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(print_router)
app.include_router(project_router)
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

@app.get("/api/agent/context")
def get_agent_context():
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        if not settings:
            settings = Settings(default_font="RobotoCondensed.ttf")
        elif not settings.default_font:
            settings.default_font = "RobotoCondensed.ttf"

        fonts = session.exec(select(Font)).all()
        font_names = [f.name.rsplit(".", 1)[0] for f in fonts]

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
        "global_default_font": settings.default_font,
        "available_templates": TEMPLATE_METADATA
    }

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
def upload_font(file: UploadFile = File(...)):
    os.makedirs("data/fonts", exist_ok=True)
    safe_filename = os.path.basename(file.filename)
    file_path = f"data/fonts/{safe_filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    with Session(engine) as session:
        db_font = Font(name=safe_filename, file_path=f"fonts/{safe_filename}")
        session.add(db_font)
        session.commit()
        session.refresh(db_font)
        return db_font

@app.get("/api/fonts")
def list_fonts():
    os.makedirs("data/fonts", exist_ok=True)
    with Session(engine) as session:
        db_fonts = {f.name: f for f in session.exec(select(Font)).all()}
        disk_fonts = [f for f in os.listdir("data/fonts") if f.lower().endswith((".ttf", ".otf"))]
        
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
    params: Dict[str, str] = {}

@app.get("/api/templates")
def get_templates():
    return {"templates": TEMPLATE_METADATA}

@app.post("/api/templates/generate")
def generate_template(req: TemplateGenerateRequest):
    items = generate_template_items(req.template_id, req.width, req.height, req.params)

    if items is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown template_id: '{req.template_id}'")

    return {"items": items}

@app.post("/api/pdf/convert")
async def convert_pdf(file: UploadFile = File(...)):
    import base64
    import asyncio
    from io import BytesIO
    from fastapi import HTTPException
    try:
        pdf_bytes = await file.read()
        
        def _process_pdf(data_bytes):
            doc = pdfium.PdfDocument(data_bytes)
            images = []
            scale = 203 / 72.0
            for i in range(len(doc)):
                page = doc[i]
                pil_img = page.render(scale=scale).to_pil()
                
                buf = BytesIO()
                pil_img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                images.append(f"data:image/png;base64,{b64}")
            return images
            
        images = await asyncio.to_thread(_process_pdf, pdf_bytes)
            
        return {"images": images}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
