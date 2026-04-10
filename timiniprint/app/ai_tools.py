import uuid

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "add_text_element",
            "description": "Add a new text element to the canvas.",
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

    return f"Error: Unknown tool {name}"
