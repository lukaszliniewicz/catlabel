"""Shared agent context without importing the API composition root."""

from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from ..core.models import Category, Font, LabelPreset, Project, Settings
from .layout_engine import TEMPLATE_METADATA


def build_agent_context(engine: Engine) -> dict[str, Any]:
    with Session(engine) as session:
        settings = session.get(Settings, 1)
        if not settings:
            settings = Settings(default_font="RobotoCondensed.ttf")
        elif not settings.default_font:
            settings.default_font = "RobotoCondensed.ttf"

        fonts = session.exec(select(Font)).all()
        font_names = [f.name.rsplit(".", 1)[0] for f in fonts]

        root_projects = session.exec(
            select(Project).where(col(Project.category_id).is_(None))
        ).all()
        root_categories = session.exec(
            select(Category).where(col(Category.parent_id).is_(None))
        ).all()
        presets = session.exec(select(LabelPreset).order_by(LabelPreset.name)).all()

        project_summaries = [{"id": p.id, "name": p.name} for p in root_projects]
        category_summaries = [{"id": c.id, "name": c.name} for c in root_categories]
        presets_data = [
            {
                "name": p.name,
                "media_type": p.media_type,
                "description": p.description,
                "width_mm": p.width_mm,
                "height_mm": p.height_mm,
            }
            for p in presets
        ]

    return {
        "intended_media_type": settings.intended_media_type,
        "engine_rules": {
            "coordinate_system": "Dimensions are in PIXELS. 1 mm = (DPI / 25.4) pixels. The active DPI will be provided in your printer_info block. If no printer is connected, assume 203 DPI (1mm ≈ 8px).",
            "hardware_width_mm": settings.print_width_mm,
            "hardware_width_px": int(
                settings.print_width_mm * (settings.default_dpi / 25.4)
            ),
            "behavior_padding": "If you define a canvas narrower than the hardware width, the engine will automatically center and pad it with white space. Do NOT stretch elements to fit the hardware if the user wants a small label.",
            "behavior_oversize": "If the dimension across the print head exceeds hardware width and splitMode=false, the engine scales it down.",
            "orientation_and_rotation": "CRITICAL ORIENTATION RULES:\n1. PRE-CUT LABELS (Niimbot): Usually fed sideways. ALWAYS use `apply_preset`. It automatically sets the correct rotation. Design normally left-to-right.\n2. CONTINUOUS ROLLS: Tape feeds infinitely. Use `set_canvas_dimensions`:\n  - Portrait ('across_tape'): width <= hardware_width, height = custom length. Good for standard lists/tags.\n  - Banner ('along_tape_banner'): height <= hardware_width, width = custom length. Use this when the user asks for a 'long' label, '20cm box label', or wide layout. Text reads along the tape.",
        },
        "standard_presets": presets_data,
        "available_fonts": font_names,
        "root_projects": project_summaries,
        "root_categories": category_summaries,
        "global_default_font": settings.default_font,
        "available_templates": TEMPLATE_METADATA,
    }
