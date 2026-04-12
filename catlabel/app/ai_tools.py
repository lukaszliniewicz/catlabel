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


def _append_text(
    items,
    *,
    text,
    x,
    y,
    width,
    height=None,
    size=None,
    align="left",
    weight=700,
    fit_to_width=False,
    invert=False,
    pageIndex=0,
    **extra,
):
    item = {
        "id": str(uuid.uuid4()),
        "type": "text",
        "text": text,
        "x": _as_int(x, 0),
        "y": _as_int(y, 0),
        "width": max(1, _as_int(width, 1)),
        "align": align,
        "weight": _as_int(weight, 700),
        "pageIndex": _as_int(pageIndex, 0),
    }
    if height is not None:
        item["height"] = max(1, _as_int(height, 1))
    if size is not None:
        item["size"] = max(1, _as_int(size, 1))
    if fit_to_width:
        item["fit_to_width"] = True
    if invert:
        item["invert"] = True
    item.update(extra)
    items.append(item)
    return item


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
            "name": "layout_centered_text",
            "description": "MACRO: Replaces the specified page with a single, perfectly centered text block that automatically scales to fill the label. Supports {{ variables }}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "invert": {"type": "boolean", "description": "White text on black background.", "default": False},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "layout_stacked_text",
            "description": "MACRO: Replaces the page with two text elements (Top and Bottom) that automatically share the space and scale to fit. Great for Title/Subtitle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "top_text": {"type": "string"},
                    "bottom_text": {"type": "string"},
                    "primary_is_top": {"type": "boolean", "default": True},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["top_text", "bottom_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "layout_list_text",
            "description": "MACRO: Replaces the page with perfectly spaced, auto-scaling text rows. Perfect for lists, specs, ingredients, or multi-line details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of strings. Use {{ var }} for dynamic data. E.g. ['Item: {{name}}', 'SKU: {{sku}}']"
                    },
                    "align": {"type": "string", "enum": ["left", "center", "right"], "default": "left"},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["lines"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "layout_columns",
            "description": "MACRO: Replaces the page with two side-by-side columns of text sharing the same horizontal line. Perfect for Price Tags (e.g., Name on left, Price on right).",
            "parameters": {
                "type": "object",
                "properties": {
                    "left_text": {"type": "string"},
                    "right_text": {"type": "string"},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["left_text", "right_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "layout_barcode_with_text",
            "description": "MACRO: Replaces the page with a perfectly centered barcode/qrcode and auto-scaling text. Ideal for Asset Tags and Inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code_type": {"type": "string", "enum": ["barcode", "qrcode"], "default": "barcode"},
                    "code_data": {"type": "string", "description": "Data for the barcode. Can be a {{ variable }}."},
                    "top_text": {"type": "string", "description": "Optional title above the barcode."},
                    "bottom_text": {"type": "string", "description": "Text displayed below the barcode."},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["code_type", "code_data", "bottom_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "layout_shipping_address",
            "description": "MACRO: Replaces the page with a standardized Shipping/Mailing label layout. Auto-rotates to landscape.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sender_text": {"type": "string", "description": "Return address (multiline supported)."},
                    "recipient_text": {"type": "string", "description": "Main destination address (multiline supported)."},
                    "footer_text": {"type": "string", "description": "Optional bottom note (e.g. 'Fragile', 'Order #123')."},
                    "pageIndex": {"type": "integer", "default": 0}
                },
                "required": ["sender_text", "recipient_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_text_element",
            "description": "GRANULAR (AVOID IF POSSIBLE): Add a text element at specific X/Y coordinates. WARNING: You lack spatial reasoning. Using this often results in overlapping text at y:0. Use MACROS instead unless strictly required.",
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
            "name": "add_html_element",
            "description": "GRANULAR: Add an HTML/SVG element for highly complex graphics or icons. (e.g. <svg>...</svg>).",
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
            "description": "Deletes all elements from all pages.",
            "parameters": {"type": "object", "properties": {}}
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


def execute_tool(name: str, args: dict, canvas_state: dict) -> str:
    cw, ch = _canvas_size(canvas_state)

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
        w = max(1, _as_int(args["width"], 384))
        h = max(1, _as_int(args["height"], 384))
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

    elif name == "layout_centered_text":
        page_idx = _page_index(args)
        _clear_page(canvas_state, page_idx)
        items = canvas_state.setdefault("items", [])

        _append_text(
            items,
            text=args["text"],
            x=0,
            y=0,
            width=cw,
            height=ch,
            align="center",
            weight=700,
            fit_to_width=True,
            invert=bool(args.get("invert", False)),
            pageIndex=page_idx,
        )
        return f"Page {page_idx} replaced with centered text."

    elif name == "layout_stacked_text":
        page_idx = _page_index(args)
        _clear_page(canvas_state, page_idx)
        items = canvas_state.setdefault("items", [])

        primary_top = args.get("primary_is_top", True)
        top_h = int(ch * 0.6) if primary_top else int(ch * 0.4)
        top_h = max(1, top_h)
        bot_h = max(1, ch - top_h)

        _append_text(
            items,
            text=args["top_text"],
            x=0,
            y=0,
            width=cw,
            height=top_h,
            align="center",
            weight=900 if primary_top else 400,
            fit_to_width=True,
            pageIndex=page_idx,
        )
        _append_text(
            items,
            text=args["bottom_text"],
            x=0,
            y=top_h,
            width=cw,
            height=bot_h,
            align="center",
            weight=400 if primary_top else 900,
            fit_to_width=True,
            pageIndex=page_idx,
        )
        return f"Page {page_idx} replaced with stacked text."

    elif name == "layout_list_text":
        page_idx = _page_index(args)
        lines = [str(line) for line in (args.get("lines") or []) if line is not None]
        if not lines:
            return "Error: No lines provided."

        _clear_page(canvas_state, page_idx)
        items = canvas_state.setdefault("items", [])
        align = args.get("align", "left")
        row_h = max(1, ch // len(lines))

        for idx, line_text in enumerate(lines):
            row_y = idx * row_h
            current_h = row_h if idx < len(lines) - 1 else max(1, ch - row_y)
            _append_text(
                items,
                text=line_text,
                x=0,
                y=row_y,
                width=cw,
                height=current_h,
                align=align,
                weight=900 if idx == 0 else 700,
                fit_to_width=True,
                pageIndex=page_idx,
            )
        return f"Page {page_idx} replaced with {len(lines)} list rows."

    elif name == "layout_columns":
        page_idx = _page_index(args)
        _clear_page(canvas_state, page_idx)
        items = canvas_state.setdefault("items", [])

        outer_pad = max(8, cw // 48)
        gutter = max(12, cw // 32)
        col_w = max(1, (cw - (outer_pad * 2) - gutter) // 2)

        _append_text(
            items,
            text=args["left_text"],
            x=outer_pad,
            y=0,
            width=col_w,
            height=ch,
            align="left",
            weight=700,
            fit_to_width=True,
            pageIndex=page_idx,
        )
        _append_text(
            items,
            text=args["right_text"],
            x=outer_pad + col_w + gutter,
            y=0,
            width=col_w,
            height=ch,
            align="right",
            weight=900,
            fit_to_width=True,
            pageIndex=page_idx,
        )
        return f"Page {page_idx} replaced with 2-column layout."

    elif name == "layout_barcode_with_text":
        page_idx = _page_index(args)
        _clear_page(canvas_state, page_idx)
        items = canvas_state.setdefault("items", [])

        code_type = args.get("code_type", "barcode")
        top_txt = args.get("top_text", "") or ""
        bottom_txt = args.get("bottom_text", "") or ""

        top_h = int(ch * 0.22) if top_txt else 0
        bottom_h = int(ch * 0.18) if bottom_txt else 0
        code_h = max(1, ch - top_h - bottom_h)
        code_margin = max(4, min(cw, ch) // 40)

        current_y = 0
        if top_txt:
            _append_text(
                items,
                text=top_txt,
                x=0,
                y=0,
                width=cw,
                height=top_h,
                align="center",
                weight=900,
                fit_to_width=True,
                pageIndex=page_idx,
            )
            current_y += top_h

        if code_type == "qrcode":
            code_size = max(1, min(cw - (code_margin * 2), code_h - (code_margin * 2)))
            code_w = code_size
            code_h_render = code_size
            code_x = (cw - code_w) // 2
            code_y = current_y + max(0, (code_h - code_h_render) // 2)
        else:
            code_w = max(1, int(cw * 0.9))
            code_h_render = max(1, code_h - (code_margin * 2))
            code_x = (cw - code_w) // 2
            code_y = current_y + code_margin

        items.append({
            "id": str(uuid.uuid4()),
            "type": code_type,
            "data": args["code_data"],
            "x": code_x,
            "y": code_y,
            "width": code_w,
            "height": code_h_render,
            "pageIndex": page_idx,
        })

        current_y += code_h
        if bottom_txt:
            _append_text(
                items,
                text=bottom_txt,
                x=0,
                y=current_y,
                width=cw,
                height=max(1, ch - current_y),
                align="center",
                weight=700,
                fit_to_width=True,
                pageIndex=page_idx,
            )

        return f"Page {page_idx} replaced with barcode layout."

    elif name == "layout_shipping_address":
        page_idx = _page_index(args)
        _clear_page(canvas_state, page_idx)

        if cw < ch:
            cw, ch = ch, cw
            canvas_state["width"] = cw
            canvas_state["height"] = ch
            canvas_state["isRotated"] = True

        items = canvas_state.setdefault("items", [])
        sender = args.get("sender_text", "Sender")
        recipient = args.get("recipient_text", "Recipient")
        footer = args.get("footer_text", "") or ""

        outer_pad = max(16, min(cw, ch) // 18)
        sender_w = max(120, int(cw * 0.45))
        sender_h = max(48, int(ch * 0.22))
        divider_y = outer_pad + sender_h + (outer_pad // 2)
        badge_h = max(28, int(ch * 0.09))
        badge_w = max(110, int(cw * 0.24))
        badge_y = divider_y + max(8, outer_pad // 2)
        footer_h = max(36, int(ch * 0.12)) if footer else 0
        recipient_y = badge_y + badge_h + max(10, outer_pad // 2)
        recipient_h = max(40, ch - recipient_y - outer_pad - footer_h)

        _append_text(
            items,
            text=f"FROM:\n{sender}",
            x=outer_pad,
            y=outer_pad,
            width=sender_w,
            height=sender_h,
            align="left",
            weight=700,
            fit_to_width=True,
            pageIndex=page_idx,
        )
        _append_text(
            items,
            text="",
            x=0,
            y=divider_y,
            width=cw,
            size=2,
            border_style="top",
            border_thickness=4,
            pageIndex=page_idx,
        )
        _append_text(
            items,
            text="SHIP TO:",
            x=outer_pad,
            y=badge_y,
            width=badge_w,
            height=badge_h,
            align="center",
            weight=900,
            fit_to_width=True,
            invert=True,
            border_style="box",
            pageIndex=page_idx,
        )
        _append_text(
            items,
            text=recipient,
            x=outer_pad,
            y=recipient_y,
            width=cw - (outer_pad * 2),
            height=recipient_h,
            align="left",
            weight=900,
            fit_to_width=True,
            pageIndex=page_idx,
        )

        if footer:
            footer_y = ch - outer_pad - footer_h
            _append_text(
                items,
                text="",
                x=0,
                y=max(0, footer_y - max(6, outer_pad // 2)),
                width=cw,
                size=2,
                border_style="top",
                border_thickness=4,
                pageIndex=page_idx,
            )
            _append_text(
                items,
                text=footer,
                x=outer_pad,
                y=footer_y,
                width=cw - (outer_pad * 2),
                height=footer_h,
                align="center",
                weight=700,
                fit_to_width=True,
                pageIndex=page_idx,
            )

        return f"Page {page_idx} replaced with shipping address layout."

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
        seq = args.get("variables_sequence", {}) or {}

        if seq:
            v_name = seq["variable_name"]
            start = int(seq["start"])
            end = int(seq["end"])
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
            if parent_id is not None and not session.get(Category, parent_id):
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
            if cat_id is not None and not session.get(Category, cat_id):
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

    elif name == "trigger_ui_action":
        canvas_state.setdefault("__actions__", []).append({
            "action": args.get("action"),
            "project_name": args.get("project_name")
        })
        return f"Instructed UI to {args.get('action')}."

    return f"Error: Unknown tool {name}"
