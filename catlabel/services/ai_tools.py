import json
import uuid


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
            "description": "MACRO: Replaces (or appends to) the canvas with a standard layout. Call apply_preset FIRST to set the canvas size.",
            "parameters": {
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "string",
                        "description": "ID of the template (e.g., price_tag, inventory_tag, shipping_address)"
                    },
                    "params": {
                        "type": "object",
                        "description": "Key-value pairs for the template fields. Use {{ var }} for batch data."
                    },
                    "append": {
                        "type": "boolean",
                        "default": False,
                        "description": "Set to true if you are adding this template to existing elements on the canvas instead of clearing it."
                    }
                },
                "required": ["template_id", "params"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_preset",
            "description": "Instantly configures the canvas dimensions, rotation, and borders for a known standard label type (e.g., 'Niimbot D11', 'Cable Flag'). Call this FIRST.",
            "parameters": {
                "type": "object",
                "properties": {
                    "preset_name": {"type": "string", "description": "The exact name of the preset."}
                },
                "required": ["preset_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_canvas_dimensions",
            "description": "Sets custom canvas dimensions in pixels (1mm = 8px) for CONTINUOUS rolls.",
            "parameters": {
                "type": "object",
                "properties": {
                    "width": {"type": "integer", "description": "Width in pixels."},
                    "height": {"type": "integer", "description": "Height in pixels."},
                    "print_direction": {
                        "type": "string",
                        "enum": ["across_tape", "along_tape_banner"],
                        "description": "CRITICAL: 'across_tape' caps width at hardware max (e.g. 384px) and allows infinite height. 'along_tape_banner' caps height at hardware max and allows infinite width."
                    }
                },
                "required": ["width", "height", "print_direction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_canvas_orientation",
            "description": "Toggles the entire canvas between portrait and landscape. Rotates the dimensions 90 degrees.",
            "parameters": {
                "type": "object",
                "properties": {
                    "isRotated": {"type": "boolean", "description": "True for landscape (sideways), false for portrait."}
                },
                "required": ["isRotated"]
            }
        }
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
                    "width": {"type": ["integer", "string"], "description": "Strict bounding box width. Use '100%' to fill the canvas."},
                    "height": {"type": ["integer", "string"], "description": "Strict bounding box height. Use '100%' to fill the canvas."},
                    "size": {"type": "number", "default": 24, "description": "Target font size. Can be fractional (e.g., 24.5). Ignored if fit_to_width is true."},
                    "align": {"type": "string", "enum": ["left", "center", "right"], "default": "left"},
                    "weight": {"type": "integer", "default": 700},
                    "italic": {"type": "boolean", "default": False},
                    "underline": {"type": "boolean", "default": False},
                    "color": {"type": "string", "enum": ["black", "white"], "default": "black"},
                    "bgColor": {"type": "string", "enum": ["transparent", "black", "white"], "default": "transparent"},
                    "rotation": {"type": "integer", "default": 0, "description": "Rotation in degrees (0-360)"},
                    "fit_to_width": {"type": "boolean", "default": True, "description": "CRITICAL: Auto-scales font to fit inside width/height bounding box"},
                    "batch_scale_mode": {"type": "string", "enum": ["uniform", "individual"], "default": "uniform", "description": "If fit_to_width is true, 'uniform' matches the longest string in the batch. 'individual' scales each label independently."},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["text", "x", "y", "width", "height"]
            }
        }
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
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["type", "data", "x", "y", "width"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_html_design",
            "description": "Switches to HTML Mode and designs the label using raw HTML/CSS. CRITICAL AUTO-SCALING: To make text dynamically scale to fit, wrap it exactly as <div class='auto-text'><h1>{{ var }}</h1></div>. The parent container MUST have strict CSS boundaries (use min-width: 0; min-height: 0; overflow: hidden; in grids/flexbox). Do NOT apply font-size to .auto-text or its children!",
            "parameters": {
                "type": "object",
                "properties": {
                    "html": {"type": "string"}
                },
                "required": ["html"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_visual_preview",
            "description": "Renders the current canvas and returns it as an image to you. Use this ONLY if you need to visually verify a complex layout, check for overlapping text, or ensure design quality."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_element_bounds",
            "description": "Returns the exact rendered coordinates and bounds of all elements on the active canvas page. Useful for calculating precise alignment and identifying overlapping elements before proceeding with changes."
        }
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
                        "description": "Use this for a flat list of unrelated records. E.g. [{'name': 'Alice'}, {'name': 'Bob'}]."
                    },
                    "variables_matrix": {
                        "type": "object",
                        "description": "Use this for combinatorial permutations (Cartesian product). E.g. {'size': ['M2','M3'], 'length': ['5mm','10mm']}."
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
                            "padding": {"type": "integer", "default": 0}
                        },
                        "required": ["variable_name", "start", "end"]
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Lists the sub-folders and projects inside a specific folder ID. Pass null to list the root directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category_id": {"type": ["integer", "null"]}
                }
            }
        }
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
                    "parent_id": {"type": ["integer", "null"]}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_project",
            "description": "Loads a specific project ID from the database, completely overwriting your current canvas state with its design.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"}
                },
                "required": ["project_id"]
            }
        }
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
                    "category_id": {"type": ["integer", "null"], "description": "The folder ID to save into. Null for Root."}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_project",
            "description": "Updates/overwrites an existing project ID in the database with your CURRENT canvas state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "name": {"type": ["string", "null"], "description": "Optional new name. Leave null to keep existing name."}
                },
                "required": ["project_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_project",
            "description": "Deletes a project from the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"}
                },
                "required": ["project_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_category",
            "description": "Deletes a folder AND all its contents recursively. Use with extreme caution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category_id": {"type": "integer"}
                },
                "required": ["category_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_canvas",
            "description": "Deletes all elements from all pages."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_ui_action",
            "description": "Executes physical actions on behalf of the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["print"]}
                },
                "required": ["action"]
            }
        }
    }
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
    def execute(cls, name: str, args: dict, canvas_state: dict, cw: int, ch: int) -> str:
        if name not in cls._tools:
            return f"Error: Unknown tool {name}"
        return cls._tools[name](args, canvas_state, cw, ch)

@ToolRegistry.register("apply_template")
def tool_apply_template(args, canvas_state, cw, ch):
    from .layout_engine import generate_template_items

    page_idx = max(
        0,
        _as_int(args.get("pageIndex", canvas_state.get("currentPage", 0)), _as_int(canvas_state.get("currentPage", 0), 0)),
    )
    template_id = str(args.get("template_id") or "").strip()
    params = args.get("params") or {}
    should_append = args.get("append", False)

    if not template_id:
        return "Error: template_id is required."
    if not isinstance(params, dict):
        return "Error: params must be an object."

    items = generate_template_items(template_id, cw, ch, params)
    if items is None:
        return f"Error: Unknown template_id '{template_id}'."

    if not should_append:
        _clear_page(canvas_state, page_idx)

    canvas_items = canvas_state.setdefault("items", [])
    for item in items:
        item["pageIndex"] = page_idx
        canvas_items.append(item)

    return f"Page {page_idx} {'appended with' if should_append else 'replaced with'} template '{template_id}'."

@ToolRegistry.register("apply_preset")
def tool_apply_preset(args, canvas_state, cw, ch):
    preset_name = (args.get("preset_name") or "").strip()
    from ..core.database import engine
    from sqlmodel import Session, select
    from ..core.models import LabelPreset

    with Session(engine) as session:
        presets = session.exec(select(LabelPreset)).all()
        preset = next((p for p in presets if p.name.casefold() == preset_name.casefold()), None)

        if not preset:
            preset = next((p for p in presets if preset_name.casefold() in p.name.casefold()), None)

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
    return f"Canvas orientation set to {'Landscape (Rotated)' if new_rot else 'Portrait'}."

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
    canvas_state.setdefault("items", []).append({
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
    })
    return "Text element added."

@ToolRegistry.register("add_barcode_or_qrcode")
def tool_add_barcode_or_qrcode(args, canvas_state, cw, ch):
    canvas_state.setdefault("items", []).append({
        "id": str(uuid.uuid4()),
        "type": args.get("type", "qrcode"),
        "data": args.get("data", ""),
        "x": args.get("x", 0),
        "y": args.get("y", 0),
        "width": args.get("width", 100),
        "height": args.get("height", args.get("width", 100)),
        "pageIndex": args.get("pageIndex", 0)
    })
    return f"{args.get('type')} added."

@ToolRegistry.register("set_html_design")
def tool_set_html_design(args, canvas_state, cw, ch):
    canvas_state["designMode"] = "html"
    canvas_state["htmlContent"] = args.get("html", "")
    canvas_state["items"] = []
    canvas_state["currentPage"] = 0
    return "Switched to HTML design mode and applied layout."

@ToolRegistry.register("request_visual_preview")
def tool_request_visual_preview(args, canvas_state, cw, ch):
    return "Visual preview generated and will be provided in the next message."

@ToolRegistry.register("get_element_bounds")
def tool_get_element_bounds(args, canvas_state, cw, ch):
    canvas_state.setdefault("__actions__", []).append({"action": "get_element_bounds"})
    return "Requested frontend to provide bounding box coordinates in the next turn."

@ToolRegistry.register("set_batch_records")
def tool_set_batch_records(args, canvas_state, cw, ch):
    records = list(args.get("variables_list", []) or [])
    matrix = args.get("variables_matrix", {}) or {}
    seq = args.get("variables_sequence", {}) or {}

    if seq:
        v_name = seq.get("variable_name")
        start = int(seq.get("start", 0))
        end = int(seq.get("end", 0))
        prefix = seq.get("prefix", "")
        suffix = seq.get("suffix", "")
        pad = max(0, int(seq.get("padding", 0) or 0))
        step = 1 if start <= end else -1

        seq_records = []
        for i in range(start, end + step, step):
            val = f"{prefix}{str(i).zfill(pad)}{suffix}"
            seq_records.append({v_name: val})
        records.extend(seq_records)

    if matrix:
        import itertools
        keys = list(matrix.keys())
        value_sets = [[v] if not isinstance(v, (list, tuple)) else list(v) for v in matrix.values()]
        records.extend(dict(zip(keys, combo)) for combo in itertools.product(*value_sets))

    if not records:
        records = [{}]

    canvas_state["batchRecords"] = records
    return f"Configured {len(records)} batch records."

@ToolRegistry.register("list_directory")
def tool_list_directory(args, canvas_state, cw, ch):
    from ..core.database import engine
    from sqlmodel import Session, select
    from ..core.models import Category, Project

    cat_id = args.get("category_id")
    with Session(engine) as session:
        cats = session.exec(select(Category).where(Category.parent_id == cat_id)).all()
        projs = session.exec(select(Project).where(Project.category_id == cat_id)).all()
        return json.dumps({
            "sub_folders": [{"id": c.id, "name": c.name} for c in cats],
            "projects": [{"id": p.id, "name": p.name} for p in projs]
        })

@ToolRegistry.register("create_category")
def tool_create_category(args, canvas_state, cw, ch):
    from ..core.database import engine
    from sqlmodel import Session
    from ..core.models import Category

    with Session(engine) as session:
        parent_id = args.get("parent_id")
        if parent_id is not None and not session.get(Category, parent_id):
            return f"Error: The parent folder ID {parent_id} does not exist."

        cat = Category(name=args.get("name", "New Folder"), parent_id=parent_id)
        session.add(cat)
        session.commit()
        session.refresh(cat)
        canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
        return f"Folder '{cat.name}' created with ID: {cat.id}"

@ToolRegistry.register("load_project")
def tool_load_project(args, canvas_state, cw, ch):
    from ..core.database import engine
    from sqlmodel import Session
    from ..core.models import Project

    with Session(engine) as session:
        proj = session.get(Project, args.get("project_id"))
        if not proj:
            return "Error: Project ID not found."

        loaded_state = json.loads(proj.canvas_state_json)
        canvas_state.clear()
        canvas_state.update(loaded_state)
        canvas_state.setdefault("__actions__", []).append({
            "action": "loaded_project_id",
            "project_id": proj.id
        })
        return f"Successfully loaded '{proj.name}'. The canvas state is now populated with this design."

@ToolRegistry.register("save_project")
def tool_save_project(args, canvas_state, cw, ch):
    from ..core.database import engine
    from sqlmodel import Session
    from ..core.models import Project, Category

    with Session(engine) as session:
        cat_id = args.get("category_id")
        if cat_id is not None and not session.get(Category, cat_id):
            return f"Error: The destination folder ID {cat_id} does not exist."

        state_to_save = {k: v for k, v in canvas_state.items() if k != "__actions__"}
        proj = Project(
            name=args.get("name", "New Project"),
            category_id=cat_id,
            canvas_state_json=json.dumps(state_to_save)
        )
        session.add(proj)
        session.commit()
        session.refresh(proj)

        canvas_state.setdefault("__actions__", []).append({"action": "loaded_project_id", "project_id": proj.id})
        canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
        return f"Project '{proj.name}' successfully saved with ID: {proj.id}."

@ToolRegistry.register("update_project")
def tool_update_project(args, canvas_state, cw, ch):
    from ..core.database import engine
    from sqlmodel import Session
    from ..core.models import Project

    with Session(engine) as session:
        proj = session.get(Project, args.get("project_id"))
        if not proj:
            return "Error: Project ID not found."

        if args.get("name"):
            proj.name = args.get("name")

        state_to_save = {k: v for k, v in canvas_state.items() if k != "__actions__"}
        proj.canvas_state_json = json.dumps(state_to_save)

        session.add(proj)
        session.commit()
        canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
        return f"Successfully updated project ID {proj.id} ('{proj.name}')."

@ToolRegistry.register("delete_project")
def tool_delete_project(args, canvas_state, cw, ch):
    from ..core.database import engine
    from sqlmodel import Session
    from ..core.models import Project

    with Session(engine) as session:
        proj = session.get(Project, args.get("project_id"))
        if not proj:
            return "Error: Project ID not found."

        session.delete(proj)
        session.commit()
        canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
        return f"Project ID {args.get('project_id')} deleted."

@ToolRegistry.register("delete_category")
def tool_delete_category(args, canvas_state, cw, ch):
    from ..core.database import engine
    from ..api.routes_project import _delete_category_recursive
    from sqlmodel import Session
    from ..core.models import Category

    with Session(engine) as session:
        cat = session.get(Category, args.get("category_id"))
        if not cat:
            return "Error: Folder ID not found."

        _delete_category_recursive(args.get("category_id"), session)
        session.commit()
        canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
        return f"Folder ID {args.get('category_id')} and all contents recursively deleted."

@ToolRegistry.register("clear_canvas")
def tool_clear_canvas(args, canvas_state, cw, ch):
    canvas_state["items"] = []
    canvas_state["currentPage"] = 0
    canvas_state["designMode"] = "canvas"
    canvas_state["htmlContent"] = ""
    return "Canvas cleared and reset to WYSIWYG mode."

@ToolRegistry.register("trigger_ui_action")
def tool_trigger_ui_action(args, canvas_state, cw, ch):
    canvas_state.setdefault("__actions__", []).append({
        "action": args.get("action"),
        "project_name": args.get("project_name")
    })
    return f"Instructed UI to {args.get('action')}."

def execute_tool(name: str, args: dict, canvas_state: dict) -> str:
    cw, ch = _canvas_size(canvas_state)
    return ToolRegistry.execute(name, args, canvas_state, cw, ch)
