import json
import uuid

TOOLS_SCHEMA = [
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
                        "description": "CRITICAL: 'across_tape' (Portrait) caps width at hardware max (e.g. 384px) and allows infinite height. 'along_tape_banner' (Landscape) caps height at hardware max and allows infinite width (great for long text/boxes)."
                    }
                },
                "required": ["width", "height", "print_direction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "layout_centered_text",
            "description": "MACRO: Replaces the specified page with a single, perfectly centered text block that automatically scales to fill the label. Supports {{ variables }}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "invert": {"type": "boolean", "description": "White text on black background.", "default": False},
                    "pageIndex": {"type": "integer", "description": "The page to apply this to (default 0).", "default": 0}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "layout_stacked_text",
            "description": "MACRO: Replaces the specified page with two text elements (Top and Bottom) that automatically share the space and scale to fit. Great for primary/secondary info. Supports {{ variables }}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "top_text": {"type": "string"},
                    "bottom_text": {"type": "string"},
                    "primary_is_top": {"type": "boolean", "description": "True if the top text should be larger/bolder.", "default": True},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["top_text", "bottom_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_text_element",
            "description": "GRANULAR: Add a text element at specific X/Y coordinates. Use this for specific layouts like Cable Flags where macros don't work.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "size": {"type": "integer", "default": 24},
                    "width": {"type": "integer"},
                    "align": {"type": "string", "enum": ["left", "center", "right"], "default": "left"},
                    "weight": {"type": "integer", "default": 700},
                    "fit_to_width": {"type": "boolean", "default": False},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["text", "x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_barcode_or_qrcode",
            "description": "GRANULAR: Add a barcode or QR code at specific X/Y coordinates.",
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
            "name": "add_html_element",
            "description": "GRANULAR: Add an HTML/CSS/SVG element for highly complex graphics or specific SVG icons. Must use inline styles. Do not load external assets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "html": {"type": "string"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["html", "x", "y", "width", "height"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_batch_records",
            "description": "CRITICAL FOR BATCH/SERIES: Configures multiple labels for batch printing. Use this immediately in the same response after laying out your {{ var }} template. Use variables_list for explicit rows or variables_matrix for Cartesian-product combinations from multiple variable lists.",
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
                        "description": "Use this for combinatorial permutations (Cartesian product), such as comma-separated user lists for size, length, head type, or material. E.g. {'size': ['M2','M3'], 'length': ['5mm','10mm']}."
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
            "description": "Deletes all elements from all pages.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_ui_action",
            "description": "Executes physical actions on behalf of the user, such as printing the design.",
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

def execute_tool(name: str, args: dict, canvas_state: dict) -> str:
    cw = canvas_state.get("width", 384)
    ch = canvas_state.get("height", 384)

    if name == "apply_preset":
        preset_name = (args.get("preset_name") or "").strip()
        from .server import engine
        from sqlmodel import Session, select
        from .models import LabelPreset

        with Session(engine) as session:
            presets = session.exec(select(LabelPreset)).all()
            preset = next((p for p in presets if p.name.casefold() == preset_name.casefold()), None)

            if not preset:
                return "Error: Preset not found."

            current_dpi = canvas_state.get("__dpi__", 203) or 203
            dots_per_mm = current_dpi / 25.4

            canvas_state["width"] = max(1, int(round(preset.width_mm * dots_per_mm)))
            canvas_state["height"] = max(1, int(round(preset.height_mm * dots_per_mm)))
            canvas_state["isRotated"] = preset.is_rotated
            canvas_state["splitMode"] = preset.split_mode
            canvas_state["canvasBorder"] = preset.border
            return f"Applied preset: {preset.name}"

    elif name == "set_canvas_dimensions":
        w = args["width"]
        h = args["height"]
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

    elif name == "list_directory":
        from .server import engine
        from sqlmodel import Session, select
        from .models import Category, Project

        cat_id = args.get("category_id")
        with Session(engine) as session:
            cats = session.exec(select(Category).where(Category.parent_id == cat_id)).all()
            projs = session.exec(select(Project).where(Project.category_id == cat_id)).all()
            return json.dumps({
                "sub_folders": [{"id": c.id, "name": c.name} for c in cats],
                "projects": [{"id": p.id, "name": p.name} for p in projs]
            })

    elif name == "create_category":
        from .server import engine
        from sqlmodel import Session
        from .models import Category

        with Session(engine) as session:
            parent_id = args.get("parent_id")
            if parent_id is not None:
                if not session.get(Category, parent_id):
                    return f"Error: The parent folder ID {parent_id} does not exist."

            cat = Category(name=args["name"], parent_id=parent_id)
            session.add(cat)
            session.commit()
            session.refresh(cat)
            canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
            return f"Folder '{cat.name}' created with ID: {cat.id}"

    elif name == "load_project":
        from .server import engine
        from sqlmodel import Session
        from .models import Project

        with Session(engine) as session:
            proj = session.get(Project, args["project_id"])
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

    elif name == "save_project":
        from .server import engine
        from sqlmodel import Session
        from .models import Project, Category

        with Session(engine) as session:
            cat_id = args.get("category_id")
            if cat_id is not None:
                if not session.get(Category, cat_id):
                    return f"Error: The destination folder ID {cat_id} does not exist."

            state_to_save = {k: v for k, v in canvas_state.items() if k != "__actions__"}
            proj = Project(
                name=args["name"],
                category_id=cat_id,
                canvas_state_json=json.dumps(state_to_save)
            )
            session.add(proj)
            session.commit()
            session.refresh(proj)

            canvas_state.setdefault("__actions__", []).append({"action": "loaded_project_id", "project_id": proj.id})
            canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
            return f"Project '{proj.name}' successfully saved with ID: {proj.id}."

    elif name == "update_project":
        from .server import engine
        from sqlmodel import Session
        from .models import Project

        with Session(engine) as session:
            proj = session.get(Project, args["project_id"])
            if not proj:
                return "Error: Project ID not found."

            if args.get("name"):
                proj.name = args["name"]

            state_to_save = {k: v for k, v in canvas_state.items() if k != "__actions__"}
            proj.canvas_state_json = json.dumps(state_to_save)

            session.add(proj)
            session.commit()
            canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
            return f"Successfully updated project ID {proj.id} ('{proj.name}')."

    elif name == "delete_project":
        from .server import engine
        from sqlmodel import Session
        from .models import Project

        with Session(engine) as session:
            proj = session.get(Project, args["project_id"])
            if not proj:
                return "Error: Project ID not found."
            session.delete(proj)
            session.commit()
            canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
            return f"Project ID {args['project_id']} deleted."

    elif name == "delete_category":
        from .server import engine, _delete_category_recursive
        from sqlmodel import Session
        from .models import Category

        with Session(engine) as session:
            cat = session.get(Category, args["category_id"])
            if not cat:
                return "Error: Folder ID not found."
            _delete_category_recursive(args["category_id"], session)
            session.commit()
            canvas_state.setdefault("__actions__", []).append({"action": "refresh_projects"})
            return f"Folder ID {args['category_id']} and all contents recursively deleted."

    elif name == "clear_canvas":
        canvas_state["items"] = []
        canvas_state["currentPage"] = 0
        return "Canvas cleared."

    elif name == "layout_centered_text":
        page_idx = args.get("pageIndex", 0)
        canvas_state["items"] = [i for i in canvas_state.get("items", []) if i.get("pageIndex", 0) != page_idx]
        
        canvas_state["items"].append({
            "id": str(uuid.uuid4()),
            "type": "text",
            "text": args["text"],
            "x": 0,
            "y": 0,
            "width": cw,
            "height": ch,
            "align": "center",
            "weight": 700,
            "fit_to_width": True,
            "invert": args.get("invert", False),
            "pageIndex": page_idx
        })
        return f"Page {page_idx} replaced with perfectly centered auto-fit text."

    elif name == "layout_stacked_text":
        page_idx = args.get("pageIndex", 0)
        canvas_state["items"] = [i for i in canvas_state.get("items", []) if i.get("pageIndex", 0) != page_idx]
        
        primary_top = args.get("primary_is_top", True)
        top_h = int(ch * 0.6) if primary_top else int(ch * 0.4)
        bot_h = ch - top_h
        
        canvas_state["items"].extend([
            {
                "id": str(uuid.uuid4()),
                "type": "text",
                "text": args["top_text"],
                "x": 0,
                "y": 0,
                "width": cw,
                "height": top_h,
                "align": "center",
                "fit_to_width": True,
                "weight": 900 if primary_top else 400,
                "pageIndex": page_idx
            },
            {
                "id": str(uuid.uuid4()),
                "type": "text",
                "text": args["bottom_text"],
                "x": 0,
                "y": top_h,
                "width": cw,
                "height": bot_h,
                "align": "center",
                "fit_to_width": True,
                "weight": 400 if primary_top else 900,
                "pageIndex": page_idx
            }
        ])
        return f"Page {page_idx} replaced with stacked, auto-scaling text layout."

    elif name == "add_text_element":
        canvas_state.setdefault("items", []).append({
            "id": str(uuid.uuid4()),
            "type": "text",
            "text": args["text"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "size": args.get("size", 24),
            "width": args.get("width", cw),
            "align": args.get("align", "left"),
            "weight": args.get("weight", 700),
            "fit_to_width": args.get("fit_to_width", False),
            "pageIndex": args.get("pageIndex", 0),
        })
        return "Text element added."

    elif name == "add_barcode_or_qrcode":
        canvas_state.setdefault("items", []).append({
            "id": str(uuid.uuid4()),
            "type": args["type"],
            "data": args["data"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "width": args["width"],
            "height": args.get("height", args["width"]),
            "pageIndex": args.get("pageIndex", 0)
        })
        return f"{args['type']} added."

    elif name == "add_html_element":
        canvas_state.setdefault("items", []).append({
            "id": str(uuid.uuid4()),
            "type": "html",
            "html": args["html"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "width": args.get("width", cw),
            "height": args.get("height", ch),
            "pageIndex": args.get("pageIndex", 0)
        })
        return "HTML element added."

    elif name == "set_batch_records":
        records = list(args.get("variables_list", []) or [])
        matrix = args.get("variables_matrix", {}) or {}
        
        if matrix:
            import itertools
            keys = list(matrix.keys())
            value_sets = [[v] if not isinstance(v, (list, tuple)) else list(v) for v in matrix.values()]
            records.extend(dict(zip(keys, combo)) for combo in itertools.product(*value_sets))

        if not records:
            records = [{}]

        canvas_state["batchRecords"] = records
        return f"Configured {len(records)} batch records. The UI will render permutations using {{ var }} tags in the design."

    elif name == "trigger_ui_action":
        canvas_state.setdefault("__actions__", []).append({
            "action": args.get("action"), "project_name": args.get("project_name")
        })
        return f"Instructed UI to {args.get('action')}."

    return f"Error: Unknown tool {name}"
