# TiMini Print Server API Reference

Here is a comprehensive API overview designed specifically for LLM agents to understand how to construct payloads, followed by simulated workflows, and finally the code changes needed to support setting a **Default Font** globally via the UI and API.

---

### Part 1: API Overview for Agentic Use

To allow an LLM agent to programmatically generate labels, it needs to understand the payload structure for the **TiMini Print Server**.

#### Key Endpoints
1. **`POST /api/print/direct`**: Prints a single label immediately.
2. **`POST /api/print/batch`**: Prints multiple copies or iterates over an array of variable dictionaries (CSV style).
3. **`GET /api/printers/scan`**: Returns a list of available BLE/Serial printers and their MAC addresses.

#### The `canvas_state` Payload
The core of the printing engine is the `canvas_state`. Agents should construct this JSON object to define the label. 
*Note: $1 \text{ mm} \approx 8 \text{ pixels}$. Standard 2-inch thermal tape is usually 384 pixels wide.*

```json
{
  "width": 384,
  "height": 384,
  "isRotated": false, 
  "canvasBorder": "none", // options: "none", "box", "top", "bottom", "cut_line"
  "items": [
    // Array of element objects (see below)
  ]
}
```

#### Element Object Schemas for Agents

**1. Auto-scaling Text** (Highly recommended for dynamic data)
```json
{
  "id": "text_1",
  "type": "text",
  "text": "Hello Printer\n{{ variable_name }}", // Supports Jinja-like {{ }}
  "x": 0, "y": 10,
  "width": 384,           // Constrain to width
  "size": 36,             // Starting font size
  "fit_to_width": true,   // *AGENT TIP: Set this to true to auto-shrink text to fit width
  "no_wrap": true,        // Force single line
  "align": "center",      // "left", "center", "right"
  "font": "arial.ttf",    // Or any uploaded font name
  "invert": false,        // White text on black box
  "border_style": "none"  // "none", "box", "bottom", "cut_line"
}
```

**2. Custom HTML / CSS** (Best for highly complex layouts)
```json
{
  "id": "html_1",
  "type": "html",
  "x": 0, "y": 0,
  "width": 384, 
  "height": 200,
  "html": "<div style='border:2px solid black; padding:10px; font-family:sans-serif;'><h2>Item: {{ item_name }}</h2></div>"
}
```

**3. Icon + Text Group** (Good for headers/warnings)
```json
{
  "id": "icon_1",
  "type": "icon_text",
  "icon_src": "data:image/png;base64,...", // Base64 image
  "icon_size": 40,
  "icon_x": 0, "icon_y": 0,
  "text": "WARNING: Fragile",
  "text_x": 50, "text_y": 10,
  "size": 24,
  "x": 10, "y": 10
}
```

**4. Barcode / QR Code**
```json
{
  "id": "bc_1",
  "type": "barcode", // OR "qrcode"
  "barcode_type": "code128", // "code128", "code39", "ean13"
  "data": "123456789",
  "x": 42, "y": 100,
  "width": 300, "height": 80
}
```

---

### Part 2: Simulated Agentic Workflows

#### Scenario 1: The Inventory Tag (Auto-stretching text)
**Agent Thought Process:** "The user wants a bold label for 'BOX-A1' taking up the whole 58mm width. I will use a text element with `fit_to_width: true` and `width: 384`, anchored at `x:0`."
**Payload:**
```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "canvas_state": {
    "width": 384, "height": 150, "isRotated": false,
    "items": [{
      "id": "t1", "type": "text", "text": "BOX-A1",
      "x": 0, "y": 20, "width": 384, "size": 100,
      "fit_to_width": true, "no_wrap": true, "align": "center", "invert": true
    }]
  }
}
```

#### Scenario 2: Batch Shipping Labels (HTML Template + Variables)
**Agent Thought Process:** "The user wants 3 shipping labels. I will build an HTML template string using variable placeholders `{{ name }}`, and use the `/api/print/batch` endpoint."
**Payload sent to `/api/print/batch`:**
```json
{
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "copies": 1,
  "canvas_state": {
    "width": 384, "height": 400, "isRotated": false,
    "items": [{
      "id": "h1", "type": "html", "x": 0, "y": 0, "width": 384, "height": 400,
      "html": "<h1 style='margin:0'>Ship To:</h1><h2>{{ name }}</h2><p>{{ address }}</p>"
    }]
  },
  "variables_list": [
    {"name": "Alice", "address": "123 Main St"},
    {"name": "Bob", "address": "456 Oak Rd"},
    {"name": "Charlie", "address": "789 Pine Ave"}
  ]
}
```
