# TiMini Print Server API Reference

This document is optimized for LLM Agents and programmatic generation. It explains how to construct payloads, handle spatial reasoning, and execute complex batch workflows with minimal token overhead.

## Core Concepts & Agent Guidelines

*   **Coordinate System**: Canvas coordinates are in pixels. **1 mm ≈ 8 pixels**. Standard 2-inch tape printable width is **384 pixels** (48mm).
*   **Spatial Math Bypass**: Avoid calculating exact `x` offsets to center text. Instead, set `x: 0`, `width: 384`, and `align: "center"`.
*   **Dynamic Height**: Omit the `height` property for text elements unless you want to force a strict bounding box. The engine will dynamically calculate vertical height based on text size and line breaks.
*   **Banners vs. Oversize (CRITICAL)**: 
    *   **Long Banners**: Thermal printers can print infinitely along the feed axis. To print a long banner on a *single* strip of tape, set `"isRotated": true`, make the `width` as long as you need (e.g., 1000), and keep `height: 384`. **Do NOT use splitMode**.
    *   **Giant Multi-Strip Decals**: Only set `"splitMode": true` if the user explicitly wants a giant graphic (like a huge QR code) stitched together from *multiple parallel strips of tape*. If the user's intent is ambiguous, ask them to clarify.
*   **Default Font**: If `font` is omitted, the engine automatically falls back to the user's globally configured Default Font.

---

## Dynamic Context (CRITICAL FOR AGENTS)
Before generating new payloads or guessing standard sizes, you should query `GET /api/agent/context`.
This will provide you with:
1. `1mm = 8px` conversion rules and padding logic.
2. Standard presets (e.g., Gridfinity is 42x12mm -> 336x96px).
3. The exact list of `.ttf` fonts installed on the user's system.
4. The IDs and Names of the user's saved Projects.

## Sizing & Padding Rules
*   **Narrow Labels**: If the user asks for a "12mm label", set the canvas width to `96` (12 * 8). The backend will automatically center and pad the 12mm design onto the 48mm hardware tape. **Do not** manually calculate offsets to center a small design on a 384px canvas. Let the engine handle the padding.
*   **Coordinates**: All `x`, `y`, `width`, `height`, and `size` properties in your JSON payload must be provided in **pixels**, not millimeters. Multiply requested mm by 8.

---

## 1. Endpoints

### `POST /api/print/direct`
Prints a single label immediately based on the provided canvas state.

```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "canvas_state": { ... },
  "variables": { "var_name": "Value" }
}
```

### `POST /api/print/batch`
Prints a queue of labels. This endpoint is highly optimized for LLMs. You can provide explicit lists OR a `variables_matrix` to let the backend generate the Cartesian product automatically.

```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "copies": 1,
  "canvas_state": { ... },
  
  // OPTION A: Explicit list of records
  "variables_list": [
    {"name": "Alice"}, {"name": "Bob"}
  ],

  // OPTION B: Cartesian Matrix (Agent Recommended)
  // Generates combinations for all permutations (e.g., M2-Flat, M2-Concave...)
  "variables_matrix": {
    "size": ["M2", "M3", "M4", "M5", "M6"],
    "length": ["2mm", "4mm", "10mm", "20mm"],
    "type": ["Flat", "Concave"]
  }
}
```

---

## 2. Canvas State Schema

```json
{
  "width": 384,
  "height": 384,
  "isRotated": false, 
  "splitMode": false, // Set to true for continuous banners that exceed 384px height
  "canvasBorder": "none", // options: "none", "box", "top", "bottom", "cut_line"
  "items": [ /* Element Objects */ ]
}
```

### Element Object Schemas

**1. Text (Auto-scaling & Wrapping)**
Use Jinja-like `{{ var }}` syntax for dynamic replacement.
```json
{
  "id": "text_1",
  "type": "text",
  "text": "ID: {{ asset_id }}\n{{ description }}",
  "x": 0, "y": 10,
  "width": 384,           // Constrain to canvas width
  "size": 36,             // Font size
  "weight": 700,          // NEW: OpenType Variable Font Weight (100 = Thin, 400 = Regular, 700 = Bold, 900 = Black)
  "font": "Roboto.ttf",
  "fit_to_width": true,   // *AGENT TIP: Auto-shrinks text to fit horizontally
  "no_wrap": false,       // Set true to force a single line
  "align": "center",      // "left", "center", "right"
  "invert": false,        // White text on black box
  "border_style": "none"  // "none", "box", "top", "bottom", "cut_line"
}
```
*Tip: To draw a solid line, pass empty text `""` with `size: 2` and `border_style: "top"`.*

**2. Custom HTML / CSS**
```json
{
  "id": "html_1",
  "type": "html",
  "x": 0, "y": 0, "width": 384, "height": 200,
  "html": "<div style='border:2px solid black;'><h2>{{ title }}</h2></div>"
}
```

**3. Barcode & QR Code**
```json
{
  "id": "bc_1",
  "type": "barcode", // OR "qrcode"
  "barcode_type": "code128", // "code128", "code39", "ean13"
  "data": "{{ var_code }}",
  "x": 42, "y": 100,
  "width": 300, "height": 80
}
```

---

## 3. Simulated Agentic Workflows

### Scenario A: The Combinatorial Matrix (Inventory Tagging)
**Request:** *"Print a set of screw labels from M2 to M6, each with lengths of 2,4,10,20mm, and each with two types: flat head and concave."*
**Agent Thought Process:** Instead of generating 40 records manually and wasting tokens, I will use the `variables_matrix` payload on the `/batch` endpoint. I'll use `fit_to_width` for the title to ensure safe boundaries.
**Payload:**
```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "canvas_state": {
    "width": 384, "height": 180, "isRotated": false,
    "items": [
      {
        "id": "t1", "type": "text", "text": "Size: {{ size }}\nLen: {{ length }}\nType: {{ type }}",
        "x": 0, "y": 20, "width": 384, "size": 32, "align": "center", "fit_to_width": true
      }
    ]
  },
  "variables_matrix": {
    "size": ["M2", "M3", "M4", "M5", "M6"],
    "length": ["2mm", "4mm", "10mm", "20mm"],
    "type": ["Flat Head", "Concave"]
  }
}
```

### Scenario B: The Horizontal Banner (Single Tape Width)
**Request:** *"Print a continuous banner saying 'FRAGILE - DO NOT DROP'."*
**Agent Thought Process:** A standard label is 384px wide. The user just wants a long text banner. Thermal printers feed infinitely, so I don't need `splitMode`. I will set `isRotated: true`, make the canvas width long enough to fit the text (e.g., 1000px), and keep the height at exactly 384px so it fits perfectly on one strip of tape.
**Payload:**
```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "canvas_state": {
    "width": 1000, "height": 384, "isRotated": true, "splitMode": false,
    "items": [
      {
        "id": "banner_text", "type": "text", "text": "FRAGILE - DO NOT DROP",
        "x": 0, "y": 80, "width": 1000, "size": 150, "align": "center", "fit_to_width": true, "no_wrap": true
      }
    ]
  }
}
```

### Scenario C: The Oversize Multi-Strip Decal
**Request:** *"Print a giant 100x100mm QR code for my warehouse wall."*
**Agent Thought Process:** 100mm is ~800 pixels. The printer head is only 384 pixels wide. Because both the width and height exceed a single strip of tape, I *must* use `splitMode: true`. The backend will automatically slice the 800x800 image into 3 parallel strips that the user can stick together.
**Payload:**
```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "canvas_state": {
    "width": 800, "height": 800, "isRotated": false, "splitMode": true,
    "items": [
      {
        "id": "qr_1", "type": "qrcode", "data": "WH-A1-BIN-99",
        "x": 0, "y": 0, "width": 800, "height": 800
      }
    ]
  }
}
```
