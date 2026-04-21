# CatLabel API Reference

This document is optimized for LLM Agents, programmatic generation, and external API integrations. It explains how to construct payloads, handle spatial reasoning, utilize the built-in layout/template engine, and execute complex batch workflows with minimal token overhead.

## Core Concepts & Agent Guidelines

*   **Coordinate System**: Canvas dimensions and coordinates are in **pixels**.
    *   **203 DPI**: 1 mm ≈ 8 pixels. (Standard hardware width: 384px = 48mm)
    *   **300 DPI**: 1 mm ≈ 11.8 pixels.
    *   *Tip*: Always check `/api/agent/context` or the hardware profile for the exact width/DPI.
*   **Media Types (CRITICAL)**: 
    *   **`continuous` (Rolls)**: Can be cut to any length. Set `canvas_state.isRotated = true` to print infinitely long landscape banners.
    *   **`pre-cut` (Niimbot D11, B21, etc.)**: Fixed boundaries. You *must* strictly adhere to the defined canvas size. **Do not use `splitMode` on pre-cut media.**
*   **Banners vs. Oversize Split (CRITICAL)**:
    *   **Long Banners**: To print a long banner on a *single* strip of continuous tape, set `"isRotated": true`, make the `width` as long as you need (e.g., 1000px), and keep `height: 384` (hardware max). **Do NOT use `splitMode`**.
    *   **Oversize Multi-Strip Decals**: Only set `"splitMode": true` if the user wants a giant graphic stitched together from *multiple parallel strips of tape*.
*   **Design Modes**: The canvas operates in two distinct modes:
    1.  **`canvas`**: WYSIWYG mode using absolute-positioned elements (Text, QR, Barcode, Shape, Icon).
    2.  **`html`**: Renders pure HTML/CSS. Great for flexbox, CSS Grid, or highly stylized layouts.
*   **Built-in Dynamic Tags**:
    *   `{{ $date }}` -> Inserts today's date (YYYY-MM-DD).
    *   `{{ $date+7 }}` / `{{ $date-30 }}` -> Inserts offset dates.
    *   `{{ $time }}` -> Inserts HH:MM time.

---

## Dynamic Context (CRITICAL FOR AGENTS)
Before generating new payloads or guessing standard sizes, always query `GET /api/agent/context`.
This provides you with:
1. Printer/Media constraints (`intended_media_type`, `hardware_width_px`).
2. Available `.ttf` fonts (`global_default_font`).
3. Standard presets (e.g., Gridfinity 30x12mm).
4. **Available Templates**: The list of built-in `template_id` options for rapid layout generation (e.g., `price_tag`, `inventory_tag`, `shipping_address`).

---

## 1. REST Endpoints

### `POST /api/print/direct`
Prints a single label immediately using a fully headless Chromium renderer.
```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "dither": true,
  "canvas_state": { /* Canvas State Object */ },
  "variables": { "product_name": "Screws" }
}
```

### `POST /api/print/batch`
Prints a queue of labels. Highly optimized for programmatic and LLM usage. You can provide explicit lists OR a `variables_matrix` to let the backend automatically generate Cartesian permutations.
```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "copies": 1,
  "dither": true,
  "canvas_state": { /* Canvas State Object */ },
  
  // OPTION A: Explicit list of records
  "variables_list": [
    {"name": "Alice"}, {"name": "Bob"}
  ],

  // OPTION B: Cartesian Matrix
  "variables_matrix": {
    "size": ["M2", "M3", "M4"],
    "length": ["10mm", "20mm"],
    "type": ["Flat", "Concave"]
  }
}
```

### `POST /api/print/images`
Prints directly from an array of base64 PNG images. Useful if you render your own graphics entirely externally.
```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "images": ["data:image/png;base64,iVBORw0..."],
  "split_mode": false,
  "is_rotated": false,
  "dither": true
}
```

### `POST /api/templates/generate`
Generates a pre-configured layout based on standard templates. Ideal for LLMs so you don't have to guess coordinates.
```json
{
  "template_id": "shipping_address",
  "width": 576,
  "height": 384,
  "params": {
    "sender": "John Doe\n123 Street",
    "recipient": "Jane Smith\n456 Ave",
    "service": "PRIORITY"
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
  "splitMode": false,
  "canvasBorder": "none",           // "none", "box", "top", "bottom", "cut_line"
  "canvasBorderThickness": 4,       // Integer pixel thickness
  "designMode": "canvas",           // "canvas" OR "html"
  "htmlContent": "",                // HTML string (used only if designMode is "html")
  "items": [ /* Element Objects */ ],
  "batchRecords": [ {} ],           // Used by the UI state to track permutations/batches
  "printCopies": 1
}
```

*Note: Elements may optionally include `"pageIndex": 0`. Elements on different pages render as separate label jobs.*

### Element Object Schemas

**1. Text (Auto-scaling & Wrapping)**
```json
{
  "id": "txt_1",
  "type": "text",
  "text": "ID: {{ asset_id }}",
  "x": 0, "y": 10,
  "width": 384, "height": 50,
  "size": 36,               // Ignored if fit_to_width is true
  "weight": 700,            // Font weight (400 = Regular, 700 = Bold, 900 = Black)
  "align": "center",        // "left", "center", "right"
  "verticalAlign": "middle",// "top", "middle", "bottom"
  "font": "Roboto.ttf",
  "fit_to_width": true,     // Shrinks/expands text to exactly fill the bounding box
  "batch_scale_mode": "uniform", // "uniform" (syncs all batch labels) or "individual"
  "no_wrap": false,         // Set true to force a single line
  "invert": false,          // White text on black box
  "padding": 0,             // Internal padding inside the box
  "border_style": "none",   // "none", "box", "top", "bottom", "cut_line"
  "border_thickness": 4
}
```

**2. Icon + Text (Specialized Hybrid Element)**
Ensures perfect alignment between a leading icon and trailing text.
```json
{
  "id": "it_1",
  "type": "icon_text",
  "icon_src": "data:image/svg+xml;base64,...",
  "text": "Caution: Hot",
  "size": 32, "weight": 700,
  "icon_size": 48,
  "icon_x": 0, "icon_y": 0, "text_x": 60, "text_y": 8,
  "width": 384, "height": 100,
  "fit_to_width": true
}
```

**3. Barcode & QR Code**
```json
{
  "id": "bc_1",
  "type": "barcode",         // OR "qrcode"
  "barcode_type": "code128", // "code128", "code39", "ean13"
  "data": "{{ sku }}",
  "x": 42, "y": 100,
  "width": 300, "height": 80 // QR codes will use `width` as scale for both dimensions
}
```

**4. Shapes**
```json
{
  "id": "shp_1",
  "type": "shape",
  "shapeType": "rect",       // "rect", "circle", "ellipse", "line"
  "x": 10, "y": 10, "width": 364, "height": 4,
  "fill": "black",           // "black", "white", "transparent"
  "stroke": "transparent",
  "strokeWidth": 0
}
```

**5. HTML Mode / `.auto-text` Helper**
If `designMode` is `"html"`, elements inside `items` are ignored. Instead, the renderer evaluates `htmlContent`.
To automatically scale text to fit an HTML container, wrap it in `<div class="auto-text">`.
```json
{
  "designMode": "html",
  "htmlContent": "<div style='display:flex; width:100%; height:100%;'><div style='flex:1; min-width:0; min-height:0; overflow:hidden;'><div class='auto-text'><h1>{{ title }}</h1><p>{{ subtitle }}</p></div></div></div>"
}
```
*Agent Rule: You MUST set strict boundaries (e.g. `overflow: hidden; min-width: 0; min-height: 0;` inside flexbox/grid cells) on the parent of `.auto-text` for the auto-sizing logic to measure properly. NEVER apply `font-size` directly to `.auto-text`.*

---

## 3. Simulated Agentic Workflows

### Scenario A: Complex Batch Using Templates
**User Request:** *"I need 5 price tags. Products are Apple, Banana, Orange, Peach, Grape. Price is $1.99 each."*
**Agent Thought Process:** Instead of manually calculating X/Y coordinates for text and lines, I will use the built-in layout engine tool (`apply_template`) for a `price_tag`, then instantly set the batch variables.
**Tool Calls:**
1. `apply_template({ "template_id": "price_tag", "params": { "currency_symbol": "$", "price_main": "1", "price_cents": "99", "product_name": "{{ product }}" } })`
2. `set_batch_records({ "variables_list": [{"product": "Apple"}, {"product": "Banana"}, {"product": "Orange"}, {"product": "Peach"}, {"product": "Grape"}] })`
*Execution:* The UI instantly updates, showing the professionally laid out `price_tag` template mapped out 5 times.

### Scenario B: Generating a Serialized Asset Sequence
**User Request:** *"Print asset tags from AST-001 to AST-150."*
**Agent Thought Process:** Instead of generating 150 items in a JSON array, I will use the `variables_sequence` tool.
**Tool Calls:**
1. `add_text_element({ "text": "Property of IT: {{ asset_id }}", "fit_to_width": true, "width": "100%", "height": "100%" })`
2. `set_batch_records({ "variables_sequence": { "variable_name": "asset_id", "start": 1, "end": 150, "prefix": "AST-", "padding": 3 } })`
*Execution:* The engine builds 150 permutations safely in the UI.

### Scenario C: The Infinite Continuous Banner
**User Request:** *"Print a long banner warning saying 'FRAGILE - DO NOT DROP'. Make it white text on a black background."*
**Agent Thought Process:** Banners require continuous media. The hardware height limit is 384px. To make a banner, I set `isRotated` to true and stretch the `width` arbitrarily.
**Tool Calls:**
1. `set_canvas_dimensions({ "width": 1200, "height": 384, "print_direction": "along_tape_banner" })`
2. `add_text_element({ "text": "FRAGILE - DO NOT DROP", "x": 0, "y": 0, "width": 1200, "height": 384, "fit_to_width": true, "invert": true, "bgColor": "black" })`
*Execution:* The renderer rotates the resulting 1200x384 image 90 degrees and streams it infinitely through the printer feed mechanism.
