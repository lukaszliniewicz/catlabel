import uuid

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "add_text_element",
            "description": "Add a new text element to the canvas. Use this for standard layout or dates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text content."},
                    "x": {"type": "integer", "description": "X position in pixels (1mm = 8px)."},
                    "y": {"type": "integer", "description": "Y position in pixels."},
                    "size": {"type": "integer", "description": "Font size.", "default": 24},
                    "width": {"type": "integer", "description": "Bounding box width in pixels."},
                    "align": {"type": "string", "enum": ["left", "center", "right"], "default": "left"},
                    "weight": {"type": "integer", "description": "Font weight (100-900).", "default": 700},
                    "fit_to_width": {"type": "boolean", "default": False}
                },
                "required": ["text", "x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_barcode_or_qrcode",
            "description": "Add a barcode or QR code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["barcode", "qrcode"]},
                    "data": {"type": "string", "description": "The encoded data."},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "width": {"type": "integer", "description": "Width in pixels."},
                    "height": {"type": "integer", "description": "Height in pixels."}
                },
                "required": ["type", "data", "x", "y", "width"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_html_element",
            "description": "Add an HTML/CSS/SVG element to the canvas. You MUST use inline styles or embedded <style>. Use width:100% and height:100% with box-sizing:border-box on the root. Do not load external assets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "html": {"type": "string", "description": "The full HTML/SVG content including <style> tags."},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"}
                },
                "required": ["html", "x", "y", "width", "height"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "align_group",
            "description": "Aligns or centers a group of items relative to the canvas collectively.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {"type": "array", "items": {"type": "string"}, "description": "List of element IDs to move together."},
                    "horizontal": {"type": "string", "enum": ["left", "center", "right", "none"], "default": "center"},
                    "vertical": {"type": "string", "enum": ["top", "center", "bottom", "none"], "default": "center"}
                },
                "required": ["item_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_canvas_dimensions",
            "description": "Change the global canvas size or orientation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "width": {"type": "integer", "description": "Canvas width in pixels (1mm = 8px)."},
                    "height": {"type": "integer", "description": "Canvas height in pixels."},
                    "isRotated": {"type": "boolean"},
                    "splitMode": {"type": "boolean"}
                },
                "required": ["width", "height"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_canvas",
            "description": "Deletes all elements from the canvas.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_shipping_label",
            "description": "Macro to instantly create a perfectly formatted shipping label.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sender_lines": {"type": "array", "items": {"type": "string"}},
                    "recipient_name": {"type": "string"},
                    "recipient_address": {"type": "array", "items": {"type": "string"}},
                    "bottom_text": {"type": "string"}
                },
                "required": ["recipient_name", "recipient_address"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_batch_records",
            "description": "Configures multiple labels for batch printing. The UI will generate separate label canvases for each record. Use this instead of duplicating elements manually when the user wants multiple variations of a label.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variables_list": {"type": "array", "items": {"type": "object"}, "description": "List of flat dictionaries mapping variable names to values."},
                    "variables_matrix": {"type": "object", "description": "Cartesian matrix mapping keys to lists of values. E.g. {'size': ['S','M'], 'color': ['Red','Blue']}. The engine will automatically generate all permutations."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_ui_action",
            "description": "Executes physical actions on behalf of the user, such as sending the design directly to the printer or saving it to the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["print", "save_project"]},
                    "project_name": {"type": "string", "description": "Required if action is save_project."}
                },
                "required": ["action"]
            }
        }
    }
]

def execute_tool(name: str, args: dict, canvas_state: dict) -> str:
    """Executes the requested tool and mutates the canvas_state in-place."""
    if name == "add_text_element":
        item = {
            "id": str(uuid.uuid4()),
            "type": "text",
            "text": args["text"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "size": args.get("size", 24),
            "width": args.get("width", canvas_state.get("width", 384)),
            "align": args.get("align", "left"),
            "weight": args.get("weight", 700),
            "fit_to_width": args.get("fit_to_width", False),
        }
        canvas_state.setdefault("items", []).append(item)
        return f"Text element added with ID {item['id']}."

    elif name == "add_barcode_or_qrcode":
        item = {
            "id": str(uuid.uuid4()),
            "type": args["type"],
            "data": args["data"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "width": args["width"],
            "height": args.get("height", args["width"] if args["type"] == "qrcode" else 80)
        }
        canvas_state.setdefault("items", []).append(item)
        return f"{args['type']} added with ID {item['id']}."

    elif name == "add_html_element":
        item = {
            "id": str(uuid.uuid4()),
            "type": "html",
            "html": args["html"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "width": args.get("width", canvas_state.get("width", 384)),
            "height": args.get("height", 200)
        }
        canvas_state.setdefault("items", []).append(item)
        return f"HTML/SVG element added with ID {item['id']}."

    elif name == "align_group":
        item_ids = args.get("item_ids", [])
        h_align = args.get("horizontal", "center")
        v_align = args.get("vertical", "center")

        target_items = [i for i in canvas_state.get("items", []) if i.get("id") in item_ids]
        if not target_items:
            return "No items found matching the provided IDs."

        min_x = min(i.get("x", 0) for i in target_items)
        min_y = min(i.get("y", 0) for i in target_items)
        max_x = max(i.get("x", 0) + i.get("width", 384) for i in target_items)
        
        def get_h(item):
            if "height" in item: return item["height"]
            if item["type"] == "text": return item.get("size", 24) * 1.2
            return 50
            
        max_y = max(i.get("y", 0) + get_h(i) for i in target_items)

        group_w = max_x - min_x
        group_h = max_y - min_y
        cw = canvas_state.get("width", 384)
        ch = canvas_state.get("height", 384)

        delta_x = 0
        if h_align == "center": delta_x = (cw - group_w) / 2 - min_x
        elif h_align == "left": delta_x = -min_x
        elif h_align == "right": delta_x = cw - group_w - min_x

        delta_y = 0
        if v_align == "center": delta_y = (ch - group_h) / 2 - min_y
        elif v_align == "top": delta_y = -min_y
        elif v_align == "bottom": delta_y = ch - group_h - min_y

        for i in target_items:
            i["x"] = int(i.get("x", 0) + delta_x)
            i["y"] = int(i.get("y", 0) + delta_y)

        return f"Group of {len(target_items)} items successfully aligned {h_align}/{v_align}."

    elif name == "set_canvas_dimensions":
        canvas_state["width"] = args["width"]
        canvas_state["height"] = args["height"]
        if "isRotated" in args:
            canvas_state["isRotated"] = args["isRotated"]
        if "splitMode" in args:
            canvas_state["splitMode"] = args["splitMode"]
        return f"Canvas updated to {args['width']}x{args['height']} px."

    elif name == "clear_canvas":
        canvas_state["items"] = []
        return "Canvas cleared."

    elif name == "create_shipping_label":
        sender = args.get("sender_lines", [])
        recipient_name = args.get("recipient_name", "Recipient")
        recipient_addr = args.get("recipient_address", [])
        custom_text = args.get("bottom_text", "")

        target_w, target_h = 576, 384
        canvas_state.update({"width": target_w, "height": target_h, "isRotated": True, "splitMode": False, "items": []})

        ts = uuid.uuid4().hex[:6]
        items = canvas_state["items"]
        
        items.append({"id": f"s-f-{ts}", "type": "text", "text": "FROM:\n" + "\n".join(sender), "x": 16, "y": 16, "size": 16, "weight": 700, "width": int(target_w * 0.45), "align": "left", "no_wrap": False})
        items.append({"id": f"s-l1-{ts}", "type": "text", "text": "", "x": 0, "y": 110, "width": target_w, "size": 2, "border_style": "top", "border_thickness": 4})
        items.append({"id": f"s-st-{ts}", "type": "text", "text": "SHIP TO:", "x": 16, "y": 130, "size": 20, "weight": 700, "width": 100, "align": "center", "no_wrap": True, "invert": True, "border_style": "box"})
        items.append({"id": f"s-rn-{ts}", "type": "text", "text": recipient_name, "x": 16, "y": 170, "size": 60, "weight": 700, "width": target_w - 32, "align": "left", "no_wrap": True, "fit_to_width": True})
        items.append({"id": f"s-ra-{ts}", "type": "text", "text": "\n".join(recipient_addr), "x": 16, "y": 240, "size": 32, "weight": 700, "width": target_w - 32, "align": "left", "no_wrap": False})

        if custom_text:
            items.append({"id": f"s-l2-{ts}", "type": "text", "text": "", "x": 0, "y": target_h - 40, "width": target_w, "size": 2, "border_style": "top", "border_thickness": 4})
            items.append({"id": f"s-ct-{ts}", "type": "text", "text": custom_text, "x": 16, "y": target_h - 32, "size": 20, "weight": 700, "width": target_w - 32, "align": "center", "no_wrap": True, "fit_to_width": True})
            
        return "Shipping label created."

    elif name == "set_batch_records":
        records = list(args.get("variables_list", []) or [])
        matrix = args.get("variables_matrix", {}) or {}
        if matrix:
            import itertools
            keys = list(matrix.keys())
            value_sets = []
            for value in matrix.values():
                if isinstance(value, (list, tuple)):
                    value_sets.append(list(value))
                else:
                    value_sets.append([value])

            records.extend(
                dict(zip(keys, combo))
                for combo in itertools.product(*value_sets)
            )

        if not records:
            records = [{}]

        canvas_state["batchRecords"] = records
        return f"Configured {len(records)} batch records. The UI now previews these as separate label canvases."

    elif name == "trigger_ui_action":
        action = args.get("action")
        # Add side-channel array to state for the frontend to intercept
        canvas_state.setdefault("__actions__", []).append({
            "action": action, "project_name": args.get("project_name")
        })
        return f"Instructed the frontend interface to execute {action}."

    return f"Error: Unknown tool {name}"
