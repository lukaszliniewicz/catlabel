# CatLabel REST API

Use the REST API for direct integrations. For saved designs, revision-checked
edits, PNG previews and durable print plans, start with the [MCP guide](docs/mcp.md).
The running application's `/openapi.json` describes the complete REST request
schemas; this guide covers the main design and printing routes.

Every `/api` request requires `X-CatLabel-Client: 1`. If an access token is
configured, also send `Authorization: Bearer <token>`. See
[local operation](docs/local-operation.md) for authentication and LAN access.

## Discover the available context

```sh
curl --fail -H 'X-CatLabel-Client: 1' http://127.0.0.1:8000/api/agent/context
```

The response includes media policy, engine rules, presets, available fonts,
the default font, templates, and root projects/categories. Use the selected
printer's profile for its actual printable width, DPI and supported settings.
Do not infer these from a similar-looking model name.

Canvas dimensions and element geometry use document pixels. At 203 DPI, one
millimetre is approximately eight pixels; at 300 DPI it is approximately 11.8.
MCP design creation also accepts physical dimensions in millimetres.

## Canvas documents

The saved-design contract is defined in
[document.schema.json](catlabel/data/document.schema.json). Its
[edit-operation schema](catlabel/data/edit-operation.schema.json) describes the
operations accepted by MCP design editing. The runtime MCP schema catalog is
available through `catlabel_catalog_get` with `kind: "schema"`.

```json
{
  "document_version": 1,
  "dpi": 203,
  "width": 384,
  "height": 200,
  "isRotated": false,
  "splitMode": false,
  "canvasBorder": "none",
  "canvasBorderThickness": 4,
  "currentPage": 0,
  "pageLayouts": [
    { "pageIndex": 0, "htmlContent": "", "activeTemplate": null }
  ],
  "items": [
    {
      "id": "title",
      "type": "text",
      "pageIndex": 0,
      "text": "Parts: {{ sku }}",
      "x": 8,
      "y": 8,
      "width": 368,
      "height": 48,
      "size": 28,
      "fit_to_width": true
    },
    {
      "id": "code",
      "type": "qrcode",
      "pageIndex": 0,
      "data": "{{ sku }}",
      "x": 8,
      "y": 64,
      "width": 96,
      "height": 96
    }
  ],
  "batchRecords": [{}],
  "printCopies": 1
}
```

Each element has an `id`, a `type` and a page assignment. Existing elements without
`pageIndex` belong to page 0. Pages use their own items and exact `pageLayouts`
entry; they do not inherit another page's HTML or template.

| Element | Common fields |
| --- | --- |
| Text | `text`, `font`, `size`, `weight`, `align`, `fit_to_width`, `no_wrap`, `invert` |
| Barcode / QR | `data`, `width`, `height`; barcodes also use `barcode_type`, such as `code128` |
| Shape | `shapeType`: `rect`, `circle`, `ellipse` or `line`; `fill`, `stroke`, `strokeWidth` |
| Image | `src` and geometry; use managed assets or an embedded image for portability |
| Group | `children`, containing its nested elements |

The renderer uses `data` for barcode/QR contents, with `text` as a compatibility
fallback. Placeholders such as `{{ sku }}` are substituted per record. Built-in
date/time variables include `{{ $date }}`, `{{ $date+7 }}` and `{{ $time }}`.

The direct-print routes accept a canvas object rather than requiring the full
saved-document schema. Use the document structure above for new integrations;
render and resource validation still apply to direct requests.

### HTML and canvas layers

Put HTML in the appropriate `pageLayouts[].htmlContent`. Sanitized HTML and
canvas elements can render together on the same page. `designMode` is not a
canonical document field and does not disable the canvas layer.

For auto-sized text or generated codes, use `.bound-box` around `.auto-text` or
`.catlabel-code`. Give the wrapper its layout dimensions, and let `.auto-text`
calculate its font size. For a single line, add `white-space: nowrap`.

This example is one entry inside `pageLayouts`:

```json
{
  "pageIndex": 0,
  "htmlContent": "<div style='display:flex;gap:4px;height:100%'><div class='bound-box' style='flex:2'><div class='auto-text' style='white-space:nowrap'>{{ title }}</div></div><div class='bound-box' style='flex:1'><div class='catlabel-code' data-type='qrcode' data-value='{{ sku }}'></div></div></div>"
}
```

Dynamic HTML barcodes use `data-type="barcode"`, `data-format="code128"` and
`data-value`. The saved-design normalizer migrates older top-level `htmlContent`
only when `pageLayouts` is absent or empty. New payloads should use page layouts.

## Printing routes

Direct and batch canvas rendering require the headless add-on, installed with
`--install-headless` or `--install-mcp`. These POST requests can start physical
printing. A successful receipt reports `status`, a `submitted` count,
`physical_completion: "unverified"`, a `job_id` and a message. Submission does not
prove that every label emerged. Check the output before retrying an uncertain
delivery; see [print-job behavior](docs/print-jobs.md).

### `POST /api/print/direct`

Required: `mac_address` and `canvas_state`. Optional: `variables` (a string-valued
record, default `{}`) and `dither` (default `true`). It renders one record and one
copy; the receipt also includes the requested `mac_address`.

```json
{
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "dither": true,
  "canvas_state": {
    "width": 384,
    "height": 200,
    "pageLayouts": [{ "pageIndex": 0 }],
    "items": [
      { "id": "label", "type": "text", "text": "{{ product }}", "width": 384, "height": 80, "size": 32 }
    ]
  },
  "variables": { "product": "Screws" }
}
```

Replace the example address with the discovered printer address. Rotation and
split behavior come from `canvas_state.isRotated` and `canvas_state.splitMode`.

### `POST /api/print/batch`

Required: `mac_address` and `canvas_state`. Optional fields are `copies`
(integer 1–100, default 1), `variables_list` (default `[]`), `variables_matrix`
(default `null`) and `dither` (default `true`). Record values must be strings.

```json
{
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "copies": 1,
  "canvas_state": {
    "width": 384,
    "height": 200,
    "pageLayouts": [{ "pageIndex": 0 }],
    "items": [
      { "id": "label", "type": "text", "text": "{{ size }} / {{ length }}", "width": 384, "height": 80, "size": 32 }
    ]
  },
  "variables_matrix": {
    "size": ["M2", "M3"],
    "length": ["10 mm", "20 mm"]
  }
}
```

This matrix produces four records. If both a list and a matrix are supplied,
list rows are followed by matrix-product rows. An empty record collection uses
one empty record. Total jobs are records × copies × distinct pages and must fit
the [resource limits](docs/resource-limits.md).

`variables_sequence` belongs to the separate manual AI `set_batch_records` tool;
it is not a field of this REST request. Generate the sequence in your client and
send `variables_list`, or use the saved-design workflow through MCP.

### `POST /api/print/images`

Required: `mac_address` and `images`, an array of complete base64 PNG images or
PNG data URLs. Optional: `split_mode`, `is_rotated` (both default `false`) and
`dither` (default `true`). At most 500 images are accepted. This route can print
externally rendered images without the Chromium add-on.

An empty image array returns `status: "empty"` and `submitted: 0`. Nonempty
requests return the normal submission receipt.

### Banners and pre-cut labels

Use `isRotated: true` for a design that runs along a continuous roll; keep the
cross-roll dimension within the printer's printable width. `splitMode` divides
an oversized design into separate strips. Do not use it for fixed pre-cut labels.

Continuous paper does not imply unlimited rendering. Each dimension is capped at
20,000 pixels, total render pixels at 50 million, and each job at 500 labels.
Firmware, physical paper and processing deadlines can impose smaller limits.

## Templates

`GET /api/templates` returns template metadata. The same catalog appears in
`GET /api/agent/context`. Use the editor or MCP saved-design operations to apply
a template to a design.

`POST /api/templates/generate` is a compatibility endpoint. It accepts
`template_id`, integer `width`/`height` and optional string-valued `params`, but
currently returns `{"items": []}` for a known template ID; unknown IDs return
HTTP 400. It does not produce a complete layout.

## Manual prompt and JSON tools

These routes support the built-in manual prompt/JSON workflow. Their tool names
are separate from the `catlabel_*` MCP tools.

- `POST /api/ai/manual/prompt-builder` accepts `intent` and `canvas_state`, plus
  optional `printer_info` and `mac_address`. It returns `{"prompt": "..."}` with
  the current manual tool schema. Printer constraints are resolved from
  `printer_info`.
- `POST /api/ai/manual/execute` accepts `canvas_state` and a `tool_calls` array of
  objects such as `{"tool": "add_text_element", "arguments": {"text": "Parts"}}`.
  It returns `canvas_state` and `execution_results`. Each result records the
  call's index, tool, status and result; inspect individual errors even when the
  HTTP request succeeds.

## Browser harness adapter

`GET /api/harness/connection` reports the local connection/configuration-file
location and whether harness support is enabled. `GET /api/harness/tools` returns
the MCP tool definitions for browser registration.

`POST /api/harness/tools/{name}` accepts `{"arguments": {...}}` and returns the
SDK tool result, including `content`, `structuredContent` and `isError`. These
routes use editor authentication and `X-CatLabel-Client: 1`; they do not return
the MCP bearer credential. Saved edits use the same
[revision guards](docs/project-persistence.md) as the editor.
