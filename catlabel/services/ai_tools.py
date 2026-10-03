import json
import uuid
from collections.abc import Mapping

from fastapi import HTTPException
from pydantic import ValidationError

_AI_DELETION_REVIEW_MESSAGE = (
    "Confirmation required: Open Projects, find {kind} '{name}' (ID {target_id}), "
    "and choose Actions > Delete to review and confirm deletion. "
    "The assistant has not deleted any saved content."
)
_AI_DELETION_INVALID_PROJECT = "Error: The project ID is invalid."
_AI_DELETION_INVALID_CATEGORY = "Error: The folder ID is invalid."
_AI_DELETION_MISSING_PROJECT = "Error: Project ID not found."
_AI_DELETION_MISSING_CATEGORY = "Error: Folder ID not found."


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_index(args):
    return max(0, _as_int(args.get("pageIndex", 0), 0))


def _canvas_size(canvas_state):
    return (
        max(1, _as_int(canvas_state.get("width", 384), 384)),
        max(1, _as_int(canvas_state.get("height", 384), 384)),
    )


def _clear_page(canvas_state, page_idx):
    canvas_state["items"] = [
        item
        for item in canvas_state.get("items", [])
        if _as_int(item.get("pageIndex", 0), 0) != page_idx
    ]


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "apply_template",
            "description": "MACRO: Replaces the canvas with a full HTML/CSS responsive layout. Call apply_preset FIRST to set the canvas size.",
            "parameters": {
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "string",
                        "description": "ID of the template (e.g., price_tag, inventory_tag, shipping_address)",
                    },
                    "page_index": {
                        "type": "integer",
                        "description": "0 for the first label, 1 for the second. Allows mixed templates per page.",
                    },
                    "params": {
                        "type": "object",
                        "description": "Key-value pairs for the template fields. Use {{ var }} for batch data.",
                    },
                },
                "required": ["template_id", "params"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_preset",
            "description": "Instantly configures the canvas dimensions, rotation, and borders for a known standard label type. Call this FIRST. **Do NOT use if using set_canvas_dimensions.**",
            "parameters": {
                "type": "object",
                "properties": {
                    "preset_name": {
                        "type": "string",
                        "description": "The exact name of the preset.",
                    }
                },
                "required": ["preset_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_canvas_dimensions",
            "description": "Sets custom canvas dimensions in pixels (1mm = 8px) for CONTINUOUS rolls. Call this FIRST if making a custom size. **Do NOT use if using apply_preset.**",
            "parameters": {
                "type": "object",
                "properties": {
                    "width": {"type": "integer", "description": "Width in pixels."},
                    "height": {"type": "integer", "description": "Height in pixels."},
                    "print_direction": {
                        "type": "string",
                        "enum": ["across_tape", "along_tape_banner"],
                        "description": "CRITICAL: 'across_tape' caps width at hardware max (e.g. 384px) and allows infinite height. 'along_tape_banner' caps height at hardware max and allows infinite width.",
                    },
                },
                "required": ["width", "height", "print_direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_canvas_orientation",
            "description": "Toggles the entire canvas between portrait and landscape. Rotates the dimensions 90 degrees.",
            "parameters": {
                "type": "object",
                "properties": {
                    "isRotated": {
                        "type": "boolean",
                        "description": "True for landscape (sideways), false for portrait.",
                    }
                },
                "required": ["isRotated"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_text_element",
            "description": "GRANULAR (AVOID IF POSSIBLE): Add a text element at specific X/Y coordinates using a strict bounding box.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "width": {
                        "type": ["integer", "string"],
                        "description": "Strict bounding box width. Use '100%' to fill the canvas.",
                    },
                    "height": {
                        "type": ["integer", "string"],
                        "description": "Strict bounding box height. Use '100%' to fill the canvas.",
                    },
                    "size": {
                        "type": "number",
                        "default": 24,
                        "description": "Target font size. Can be fractional (e.g., 24.5). Ignored if fit_to_width is true.",
                    },
                    "align": {
                        "type": "string",
                        "enum": ["left", "center", "right"],
                        "default": "left",
                    },
                    "weight": {"type": "integer", "default": 700},
                    "italic": {"type": "boolean", "default": False},
                    "underline": {"type": "boolean", "default": False},
                    "color": {
                        "type": "string",
                        "enum": ["black", "white"],
                        "default": "black",
                    },
                    "bgColor": {
                        "type": "string",
                        "enum": ["transparent", "black", "white"],
                        "default": "transparent",
                    },
                    "rotation": {
                        "type": "integer",
                        "default": 0,
                        "description": "Rotation in degrees (0-360)",
                    },
                    "fit_to_width": {
                        "type": "boolean",
                        "default": True,
                        "description": "CRITICAL: Auto-scales font to fit inside width/height bounding box",
                    },
                    "batch_scale_mode": {
                        "type": "string",
                        "enum": ["uniform", "individual"],
                        "default": "uniform",
                        "description": "If fit_to_width is true, 'uniform' matches the longest string in the batch. 'individual' scales each label independently.",
                    },
                    "pageIndex": {"type": "integer", "default": 0},
                },
                "required": ["text", "x", "y", "width", "height"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_barcode_or_qrcode",
            "description": "GRANULAR (AVOID IF POSSIBLE): Add a barcode or QR code at specific X/Y coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["barcode", "qrcode"]},
                    "data": {"type": "string"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "pageIndex": {"type": "integer", "default": 0},
                },
                "required": ["type", "data", "x", "y", "width"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_page_layout",
            "description": "Sets the base HTML/CSS background layout for a specific page index. Can be combined with Konva items layered on top. CRITICAL: ONLY auto-scaling text and dynamic barcodes MUST be wrapped in `<div class='bound-box'>`. Decorative CSS/divs can exist outside bound-boxes. `.bound-box` locks layout to prevent flexbox collapse. Example text: `<div class='bound-box' style='flex: 1;'><div class='auto-text' style='white-space: nowrap;'>{{ var }}</div></div>`. For backgrounds, place a position:absolute div behind a position:relative flex container to prevent breaking flex properties. Keep padding 0-4px. Never set font-size manually.",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_index": {
                        "type": "integer",
                        "description": "0 for the first page, 1 for the second, etc. Used to create distinct labels in a series.",
                    },
                    "html": {"type": "string"},
                },
                "required": ["page_index", "html"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_visual_preview",
            "description": "Renders the current canvas and returns it as an image to you. Use this ONLY if you need to visually verify a complex layout, check for overlapping text, or ensure design quality.",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_element_bounds",
            "description": "Returns the exact rendered coordinates and bounds of all elements on the active canvas page. Useful for calculating precise alignment and identifying overlapping elements before proceeding with changes.",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_batch_records",
            "description": "CRITICAL FOR BATCH/SERIES: Configures multiple labels for batch printing. Use this immediately in the same response after laying out your {{ var }} template. Use variables_list for explicit rows, variables_matrix for Cartesian-product combinations, or variables_sequence for fast serial numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variables_list": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Use this for a flat list of unrelated records. E.g. [{'name': 'Alice'}, {'name': 'Bob'}].",
                    },
                    "variables_matrix": {
                        "type": "object",
                        "description": "Use this for combinatorial permutations (Cartesian product). E.g. {'size': ['M2','M3'], 'length': ['5mm','10mm']}.",
                    },
                    "variables_sequence": {
                        "type": "object",
                        "description": "Generate sequential data (e.g. barcodes, asset tags) instantly.",
                        "properties": {
                            "variable_name": {"type": "string"},
                            "start": {"type": "integer"},
                            "end": {"type": "integer"},
                            "prefix": {"type": "string", "default": ""},
                            "suffix": {"type": "string", "default": ""},
                            "padding": {"type": "integer", "default": 0},
                        },
                        "required": ["variable_name", "start", "end"],
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Lists the sub-folders and projects inside a specific folder ID. Pass null to list the root directory.",
            "parameters": {
                "type": "object",
                "properties": {"category_id": {"type": ["integer", "null"]}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_category",
            "description": "Creates a new folder. Returns the new category ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "parent_id": {"type": ["integer", "null"]},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_project",
            "description": "Loads a specific project ID from the database, completely overwriting your current canvas state with its design.",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "integer"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_project",
            "description": "Saves your CURRENT canvas state into the database as a project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category_id": {
                        "type": ["integer", "null"],
                        "description": "The folder ID to save into. Null for Root.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_project",
            "description": "Updates an existing project only after you have loaded that target project into the current canvas. If a revision conflict occurs, reload the project and review its latest contents before updating again.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "name": {
                        "type": ["string", "null"],
                        "description": "Optional new name. Leave null to keep existing name.",
                    },
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_project",
            "description": "Requests deletion review for a saved project. No content is deleted by this tool. The user must open Projects > Actions > Delete and confirm deletion there.",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "integer"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_category",
            "description": "Requests deletion review for a folder and its contents. No content is deleted by this tool. The user must open Projects > Actions > Delete and confirm recursive deletion there.",
            "parameters": {
                "type": "object",
                "properties": {"category_id": {"type": "integer"}},
                "required": ["category_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_canvas",
            "description": "Deletes all elements from all pages.",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_ui_action",
            "description": "Requests print review. No job is sent by this tool. The user must review labels, copies and printer, then use Print in the app.",
            "parameters": {
                "type": "object",
                "properties": {"action": {"type": "string", "enum": ["print"]}},
                "required": ["action"],
            },
        },
    },
]


class ToolRegistry:
    _tools = {}

    @classmethod
    def register(cls, name):
        def decorator(func):
            cls._tools[name] = func
            return func

        return decorator

    @classmethod
    def execute(
        cls, name: str, args: dict, canvas_state: dict, cw: int, ch: int
    ) -> str:
        if name not in cls._tools:
            return f"Error: Unknown tool {name}"
        return cls._tools[name](args, canvas_state, cw, ch)


@ToolRegistry.register("apply_template")
def tool_apply_template(args, canvas_state, cw, ch):
    from .layout_engine import TEMPLATE_METADATA

    template_id = str(args.get("template_id") or "").strip()
    params = args.get("params") or {}
    page_idx = _as_int(args.get("page_index", 0), 0)
    valid_template_ids = {template["id"] for template in TEMPLATE_METADATA}

    if not template_id:
        return "Error: template_id is required."
    if not isinstance(params, dict):
        return "Error: params must be an object."
    if template_id not in valid_template_ids:
        return f"Error: Unknown template_id '{template_id}'."

    layouts = canvas_state.get("pageLayouts", [])
    while len(layouts) <= page_idx:
        layouts.append(
            {"pageIndex": len(layouts), "htmlContent": "", "activeTemplate": None}
        )

    layouts[page_idx] = {
        "pageIndex": page_idx,
        "activeTemplate": {"id": template_id, "params": params},
        "htmlContent": "",
    }
    canvas_state["pageLayouts"] = layouts
    canvas_state["currentPage"] = page_idx

    return f"Page {page_idx} template applied: '{template_id}'."


@ToolRegistry.register("apply_preset")
def tool_apply_preset(args, canvas_state, cw, ch):
    preset_name = (args.get("preset_name") or "").strip()
    from sqlmodel import Session, select

    from ..core.database import engine
    from ..core.models import LabelPreset

    with Session(engine) as session:
        presets = session.exec(select(LabelPreset)).all()
        preset = next(
            (p for p in presets if p.name.casefold() == preset_name.casefold()), None
        )

        if not preset:
            preset = next(
                (p for p in presets if preset_name.casefold() in p.name.casefold()),
                None,
            )

        if not preset:
            return "Error: Preset not found. Check available presets in your system prompt."

        current_dpi = canvas_state.get("__dpi__", 203) or 203
        dots_per_mm = current_dpi / 25.4

        canvas_state["width"] = max(1, int(round(preset.width_mm * dots_per_mm)))
        canvas_state["height"] = max(1, int(round(preset.height_mm * dots_per_mm)))
        canvas_state["isRotated"] = preset.is_rotated
        canvas_state["splitMode"] = preset.split_mode
        canvas_state["canvasBorder"] = preset.border
        return f"Applied preset: {preset.name}"


@ToolRegistry.register("set_canvas_orientation")
def tool_set_canvas_orientation(args, canvas_state, cw, ch):
    current_rot = canvas_state.get("isRotated", False)
    new_rot = args.get("isRotated", False)
    if current_rot != new_rot:
        canvas_state["isRotated"] = new_rot
        cw, ch = canvas_state.get("width", 384), canvas_state.get("height", 384)
        canvas_state["width"], canvas_state["height"] = ch, cw
    return (
        f"Canvas orientation set to {'Landscape (Rotated)' if new_rot else 'Portrait'}."
    )


@ToolRegistry.register("set_canvas_dimensions")
def tool_set_canvas_dimensions(args, canvas_state, cw, ch):
    w = max(1, _as_int(args.get("width", 384), 384))
    h = max(1, _as_int(args.get("height", 384), 384))
    direction = args.get("print_direction", "across_tape")

    if direction == "along_tape_banner":
        if h > w:
            w, h = h, w
        canvas_state["isRotated"] = True
    else:
        if w > h:
            w, h = h, w
        canvas_state["isRotated"] = False

    canvas_state["width"] = w
    canvas_state["height"] = h
    return f"Dimensions updated to {w}x{h}, direction: {direction}."


@ToolRegistry.register("add_text_element")
def tool_add_text_element(args, canvas_state, cw, ch):
    canvas_state.setdefault("items", []).append(
        {
            "id": str(uuid.uuid4()),
            "type": "text",
            "text": args.get("text", ""),
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "width": args.get("width", cw),
            "height": args.get("height", 50),
            "size": args.get("size", 24),
            "align": args.get("align", "left"),
            "weight": args.get("weight", 700),
            "italic": args.get("italic", False),
            "underline": args.get("underline", False),
            "color": args.get("color", "black"),
            "bgColor": args.get("bgColor", "transparent"),
            "rotation": args.get("rotation", 0),
            "fit_to_width": args.get("fit_to_width", True),
            "batch_scale_mode": args.get("batch_scale_mode", "uniform"),
            "pageIndex": args.get("pageIndex", 0),
        }
    )
    return "Text element added."


@ToolRegistry.register("add_barcode_or_qrcode")
def tool_add_barcode_or_qrcode(args, canvas_state, cw, ch):
    canvas_state.setdefault("items", []).append(
        {
            "id": str(uuid.uuid4()),
            "type": args.get("type", "qrcode"),
            "data": args.get("data", ""),
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "width": args.get("width", 100),
            "height": args.get("height", args.get("width", 100)),
            "pageIndex": args.get("pageIndex", 0),
        }
    )
    return f"{args.get('type')} added."


@ToolRegistry.register("set_page_layout")
def tool_set_page_layout(args, canvas_state, cw, ch):
    page_idx = _as_int(args.get("page_index", 0), 0)
    html = args.get("html", "")

    layouts = canvas_state.get("pageLayouts", [])
    while len(layouts) <= page_idx:
        layouts.append(
            {"pageIndex": len(layouts), "htmlContent": "", "activeTemplate": None}
        )

    layouts[page_idx] = {
        "pageIndex": page_idx,
        "htmlContent": html,
        "activeTemplate": None,
    }
    canvas_state["pageLayouts"] = layouts
    canvas_state["currentPage"] = page_idx
    return f"HTML Layout applied to page {page_idx}."


@ToolRegistry.register("request_visual_preview")
def tool_request_visual_preview(args, canvas_state, cw, ch):
    return "Visual preview requested. The system will pause and the UI will provide the image in the next turn."


@ToolRegistry.register("get_element_bounds")
def tool_get_element_bounds(args, canvas_state, cw, ch):
    canvas_state.setdefault("__actions__", []).append({"action": "get_element_bounds"})
    return "Requested frontend to provide bounding box coordinates in the next turn."


@ToolRegistry.register("set_batch_records")
def tool_set_batch_records(args, canvas_state, cw, ch):
    from ..core.resource_limits import (
        MAX_BATCH_RECORDS,
        MAX_DIMENSION,
        ResourceLimitError,
        batch_record_count,
    )

    raw_records = args.get("variables_list", [])
    if raw_records is None:
        raw_records = []
    if not isinstance(raw_records, list):
        return "Error: variables_list must be a list of mappings."
    if len(raw_records) > MAX_BATCH_RECORDS:
        return f"Error: variables_list exceeds {MAX_BATCH_RECORDS} records."
    if any(not isinstance(record, Mapping) for record in raw_records):
        return "Error: Each variables_list entry must be a mapping."

    raw_matrix = args.get("variables_matrix", {})
    if raw_matrix is None:
        raw_matrix = {}
    if not isinstance(raw_matrix, Mapping):
        return "Error: variables_matrix must be a mapping."

    sequence = args.get("variables_sequence", {})
    if sequence is None:
        sequence = {}
    if not isinstance(sequence, Mapping):
        return "Error: variables_sequence must be a mapping."

    sequence_count = 0
    start = 0
    end = 0
    padding = 0
    variable_name = None
    prefix = ""
    suffix = ""
    if sequence:
        try:
            start = int(sequence.get("start", 0))
            end = int(sequence.get("end", 0))
        except (TypeError, ValueError, OverflowError):
            return "Error: variables_sequence start and end must be integers."
        sequence_count = abs(end - start) + 1
        if sequence_count > MAX_BATCH_RECORDS:
            return f"Error: variables_sequence exceeds {MAX_BATCH_RECORDS} records."

        try:
            padding = int(sequence.get("padding", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return "Error: variables_sequence padding must be a nonnegative integer."
        if padding < 0 or padding > MAX_DIMENSION:
            return (
                "Error: variables_sequence padding must be between 0 and "
                f"{MAX_DIMENSION}."
            )
        variable_name = sequence.get("variable_name")
        prefix = sequence.get("prefix", "")
        suffix = sequence.get("suffix", "")

    matrix_axes = {}
    for key, axis in raw_matrix.items():
        matrix_axes[key] = axis if isinstance(axis, (list, tuple)) else (axis,)

    try:
        matrix_count = batch_record_count([], matrix_axes) if matrix_axes else 0
    except ResourceLimitError as exc:
        return f"Error: {exc}"

    total_count = len(raw_records) + sequence_count + matrix_count
    if total_count > MAX_BATCH_RECORDS:
        return f"Error: Combined batch exceeds {MAX_BATCH_RECORDS} records."

    records = list(raw_records)
    if sequence_count:
        step = 1 if start <= end else -1
        records.extend(
            {variable_name: f"{prefix}{str(value).zfill(padding)}{suffix}"}
            for value in range(start, end + step, step)
        )

    if matrix_axes:
        import itertools

        keys = list(matrix_axes)
        records.extend(
            dict(zip(keys, combination, strict=True))
            for combination in itertools.product(*matrix_axes.values())
        )

    if not records:
        records = [{}]

    canvas_state["batchRecords"] = records
    return f"Configured {len(records)} batch records."


@ToolRegistry.register("list_directory")
def tool_list_directory(args, canvas_state, cw, ch):
    from ..core import database
    from . import projects as project_service

    cat_id = args.get("category_id")
    return json.dumps(project_service.list_directory(cat_id, db_engine=database.engine))


@ToolRegistry.register("create_category")
def tool_create_category(args, canvas_state, cw, ch):
    from ..core import database
    from . import projects as project_service

    try:
        category = project_service.create_category(
            project_service.CategoryCreate(
                name=args.get("name", "New Folder"),
                parent_id=args.get("parent_id"),
            ),
            db_engine=database.engine,
        )
    except (HTTPException, project_service.ProjectServiceError) as exc:
        return _safe_api_error(exc, operation="create the folder")
    except ValidationError:
        return "Error: The folder request is invalid."

    canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
    return f"Folder '{category.name}' created with ID: {category.id}"


@ToolRegistry.register("load_project")
def tool_load_project(args, canvas_state, cw, ch):
    from ..core import database
    from . import projects as project_service

    try:
        proj = project_service.get_project(
            args.get("project_id"), db_engine=database.engine
        )
    except project_service.ProjectServiceError as exc:
        if exc.status_code == 404:
            return "Error: Project ID not found."
        return _safe_api_error(exc, operation="load the project")

    loaded_state = json.loads(proj.canvas_state_json)
    canvas_state.clear()
    canvas_state.update(loaded_state)
    assert proj.id is not None
    canvas_state["__project_id__"] = proj.id
    canvas_state["__project_revision__"] = proj.revision
    canvas_state.setdefault("__actions__", []).append(
        {
            "action": "loaded_project_id",
            "project_id": proj.id,
            "revision": proj.revision,
        }
    )
    return f"Successfully loaded '{proj.name}'. The canvas state is now populated with this design."


@ToolRegistry.register("save_project")
def tool_save_project(args, canvas_state, cw, ch):
    from ..core import database
    from . import projects as project_service

    cat_id = args.get("category_id")
    state_to_save = {
        key: value
        for key, value in canvas_state.items()
        if key not in {"__actions__", "__project_id__", "__project_revision__"}
    }
    try:
        proj = project_service.create_project(
            project_service.ProjectCreate(
                name=args.get("name", "New Project"),
                category_id=cat_id,
                canvas_state=state_to_save,
            ),
            db_engine=database.engine,
        )
    except (HTTPException, project_service.ProjectServiceError) as exc:
        return _safe_api_error(exc, operation="save the project")
    except ValidationError:
        return "Error: The project request is invalid."

    assert proj.id is not None
    canvas_state["__project_id__"] = proj.id
    canvas_state["__project_revision__"] = proj.revision
    canvas_state.setdefault("__actions__", []).append(
        {
            "action": "loaded_project_id",
            "project_id": proj.id,
            "revision": proj.revision,
        }
    )
    canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
    return f"Project '{proj.name}' successfully saved with ID: {proj.id}."


@ToolRegistry.register("update_project")
def tool_update_project(args, canvas_state, cw, ch):
    from ..core import database
    from . import projects as project_service

    project_id = args.get("project_id")
    loaded_project_id = canvas_state.get("__project_id__")
    revision = canvas_state.get("__project_revision__")
    if (
        type(project_id) is not int
        or project_id <= 0
        or project_id != loaded_project_id
        or type(loaded_project_id) is not int
        or loaded_project_id <= 0
        or type(revision) is not int
        or revision <= 0
    ):
        return "Error: Load the target saved project before updating it."

    state_to_save = {
        key: value
        for key, value in canvas_state.items()
        if key not in {"__actions__", "__project_id__", "__project_revision__"}
    }
    payload: dict[str, object] = {
        "expected_revision": revision,
        "canvas_state": state_to_save,
    }
    name = args.get("name")
    if name is not None:
        payload["name"] = name

    try:
        update_request = project_service.ProjectUpdate.model_validate(payload)
        proj = project_service.update_project(
            project_id, update_request, db_engine=database.engine
        )
    except (HTTPException, project_service.ProjectServiceError) as exc:
        return _safe_api_error(
            exc, operation="update the project", revision_conflict=True
        )
    except ValidationError:
        return "Error: The project update is invalid."

    assert proj.id is not None
    canvas_state["__project_revision__"] = proj.revision
    canvas_state.setdefault("__actions__", []).append(
        {
            "action": "loaded_project_id",
            "project_id": proj.id,
            "revision": proj.revision,
        }
    )
    canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
    return f"Successfully updated project ID {proj.id} ('{proj.name}')."


def _safe_api_error(
    exc: HTTPException | Exception,
    *,
    operation: str,
    revision_conflict: bool = False,
) -> str:
    status_code = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None)
    if revision_conflict and status_code in (409, 428):
        return (
            "Error: The project changed or its revision could not be verified. "
            "Reload it and review the latest contents before updating."
        )
    if isinstance(detail, str):
        return f"Error: {detail}"
    return f"Error: Could not {operation} because the request was invalid."


def _defer_saved_delete(args, canvas_state, *, kind):
    from ..core import database
    from . import projects as project_service

    if kind == "project":
        target_id = args.get("project_id")
        target_kind = "project"
        invalid_message = _AI_DELETION_INVALID_PROJECT
        missing_message = _AI_DELETION_MISSING_PROJECT
    else:
        target_id = args.get("category_id")
        target_kind = "folder"
        invalid_message = _AI_DELETION_INVALID_CATEGORY
        missing_message = _AI_DELETION_MISSING_CATEGORY

    if type(target_id) is not int or target_id <= 0:
        return invalid_message

    try:
        if kind == "project":
            record = project_service.get_project(target_id, db_engine=database.engine)
        else:
            record = project_service.get_category(target_id, db_engine=database.engine)
    except project_service.ProjectServiceError as exc:
        if exc.status_code == 404:
            return missing_message
        return _safe_api_error(exc, operation="find the saved content")
    name = record.name

    action = {
        "action": "deletion_review_required",
        "target_kind": target_kind,
        "target_id": target_id,
        "name": name,
    }
    actions = canvas_state.setdefault("__actions__", [])
    if not any(
        isinstance(existing, dict)
        and existing.get("action") == action["action"]
        and existing.get("target_kind") == target_kind
        and type(existing.get("target_id")) is int
        and existing["target_id"] == target_id
        for existing in actions
    ):
        actions.append(action)

    return _AI_DELETION_REVIEW_MESSAGE.format(kind=kind, name=name, target_id=target_id)


@ToolRegistry.register("delete_project")
def tool_delete_project(args, canvas_state, cw, ch):
    return _defer_saved_delete(args, canvas_state, kind="project")


@ToolRegistry.register("delete_category")
def tool_delete_category(args, canvas_state, cw, ch):
    return _defer_saved_delete(args, canvas_state, kind="folder")


@ToolRegistry.register("clear_canvas")
def tool_clear_canvas(args, canvas_state, cw, ch):
    canvas_state["items"] = []
    canvas_state["currentPage"] = 0
    canvas_state["pageLayouts"] = [
        {"pageIndex": 0, "htmlContent": "", "activeTemplate": None}
    ]
    canvas_state.pop("__project_id__", None)
    canvas_state.pop("__project_revision__", None)
    return "Canvas cleared and reset to WYSIWYG mode."


@ToolRegistry.register("trigger_ui_action")
def tool_trigger_ui_action(args, canvas_state, cw, ch):
    if args.get("action") != "print":
        return "Error: Unsupported UI action."
    canvas_state.setdefault("__actions__", []).append(
        {"action": "print_review_required"}
    )
    return "Confirmation required: Review the labels, copies and printer, then use Print in the app. The assistant has not sent a print job."


def execute_tool(name: str, args: dict, canvas_state: dict) -> str:
    cw, ch = _canvas_size(canvas_state)
    return ToolRegistry.execute(name, args, canvas_state, cw, ch)
