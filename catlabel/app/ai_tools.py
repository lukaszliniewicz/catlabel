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
            "description": "Set custom canvas dimensions ONLY if a preset does not apply. Width is the long feed axis for landscape labels (isRotated=true).",
            "parameters": {
                "type": "object",
                "properties": {
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "isRotated": {"type": "boolean"}
                },
                "required": ["width", "height"]
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
            "description": "CRITICAL FOR BATCH/SERIES: Configures multiple labels for batch printing using a single template. Design the template FIRST using {{ var }} syntax, then call this. You MUST provide EITHER variables_list OR variables_matrix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variables_list": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Use this for a flat list of unrelated records. E.g. [{'name': 'Alice', 'role': 'Manager'}, {'name': 'Bob', 'role': 'IT'}]."
                    },
                    "variables_matrix": {
                        "type": "object",
                        "description": "Use this for combinatorial permutations (Cartesian product). E.g. {'size': ['M2','M3'], 'length': ['5mm','10mm']}."
                    }
                }
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
            "description": "Executes physical actions on behalf of the user, such as printing the design or saving it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["print", "save_project"]},
                    "project_name": {"type": "string"}
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
        from .server import STANDARD_PRESETS
        preset = next((p for p in STANDARD_PRESETS if p["name"].casefold() == preset_name.casefold()), None)
        if not preset:
            return "Error: Preset not found."
        
        canvas_state["width"] = int(preset["width_mm"] * 8)
        canvas_state["height"] = int(preset["height_mm"] * 8)
        canvas_state["isRotated"] = preset["is_rotated"]
        canvas_state["splitMode"] = preset.get("split_mode", False)
        canvas_state["canvasBorder"] = preset.get("border", "none")
        return f"Applied preset: {preset['name']}"

    elif name == "set_canvas_dimensions":
        canvas_state["width"] = args["width"]
        canvas_state["height"] = args["height"]
        canvas_state["isRotated"] = args.get("isRotated", False)
        return "Dimensions updated."

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
