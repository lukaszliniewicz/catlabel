<div align="center">
  <img src="logo.webp" width="140" alt="CatLabel logo">
  <h1>CatLabel Studio</h1>
  <p>Design labels in your browser. Print them over Bluetooth. Or let your AI harness do the whole workflow.</p>
</div>

CatLabel is a local label designer for portable thermal printers, including
Niimbot, Phomemo and many generic “cat printers”. It combines a visual canvas,
HTML/CSS layouts, reusable templates and batch printing with MCP
and browser site tools for OpenCode, ChatGPT Work and other harnesses. Your projects and printer connection
stay on your computer; ordinary design and printing need no account or AI service.

A fork of [TiMini-Print](https://github.com/Dejniel/TiMini-Print), with a
FastAPI/React interface, dedicated Niimbot support and shared services for the
editor, REST API and MCP.

[Installation](#installation) · [MCP / OpenCode](#use-with-opencode-and-other-harnesses) ·
[Features](#what-you-can-make) · [Printers](#printer-support) · [Documentation](#documentation)

<img width="1000" alt="CatLabel editor and printed labels" src="https://github.com/user-attachments/assets/20a525d0-b6b4-4e8e-a743-ebb3ff5333ea">

## Installation

**Download v0.3:**

[![Linux AppImage](https://img.shields.io/badge/Download-Linux_AppImage-2563eb?style=for-the-badge&logo=linux&logoColor=white)](https://github.com/lukaszliniewicz/catlabel/releases/download/0.3/CatLabel-0.3.0-x86_64.AppImage)
[![Windows launcher](https://img.shields.io/badge/Download-Windows_launcher-2563eb?style=for-the-badge)](https://github.com/lukaszliniewicz/catlabel/releases/download/0.3/CatLabel-Launcher.exe)
[![Portable application ZIP](https://img.shields.io/badge/Download-Portable_ZIP-475569?style=for-the-badge)](https://github.com/lukaszliniewicz/catlabel/releases/download/0.3/CatLabel-0.3.0.zip)

On **Linux x86_64**, make the AppImage executable and open it. On **Windows
x86_64**, put the launcher in a writable folder and double-click it. Fresh
packaged installs include MCP and preview support by default. These are small
bootstrap downloads: first setup still needs internet access to install the
runtime and Chromium. [Checksums and release notes](https://github.com/lukaszliniewicz/catlabel/releases/tag/0.3).

For **macOS or Linux ARM64**, or a browser-only installation, extract the portable
ZIP to a writable folder and use the scripts below. Developers can
[download the source](https://github.com/lukaszliniewicz/catlabel/archive/refs/heads/main.zip)
or clone the repository.

| System | Start CatLabel |
| --- | --- |
| Linux / macOS | Open a terminal in the extracted folder and run `bash ./run.sh`. |
| Windows | Double-click `run.bat`, or run it from a terminal. |

The launcher installs an isolated, locked Python environment and opens
[localhost:8000](http://localhost:8000) when the app is ready. **You do not need
system Python or Node.js.** The compiled frontend is included. First setup needs
internet access; subsequent verified launches reuse the installed environment.

Linux has been verified with printer hardware. Windows launcher packaging and
fresh setup are checked on a native CI runner. macOS installation and
Windows/macOS Bluetooth printing remain best effort. The runtime targets Linux x86_64/ARM64, Windows x86_64 and macOS
Intel/Apple Silicon. See [installation and recovery](docs/installation.md) for
platform requirements, diagnostics, data paths, updates and rollback.

### Linux AppImage

Download the x86_64 AppImage above, make it executable and run it. First
launch installs the locked runtime, MCP and preview support; projects live under `~/.local/share/catlabel`
by default. Use `--appimage-extract-and-run` if FUSE is unavailable. See the
[AppImage instructions](docs/installation.md#linux-appimage) for setup and updates.

### Optional add-ons

Fresh packaged desktop installations enable MCP and preview support by default.
Source-folder installations keep the smaller browser-only default. Existing
installations retain their choices. Use these flags with the launcher, `run.bat`
or `bash ./run.sh`; enabled add-ons are remembered:

| Flag | Adds |
| --- | --- |
| `--install-mcp` | Harness tools and headless Chromium for previews and printing. |
| `--install-headless` | Backend HTML rendering for direct REST clients. |
| `--install-ai` | Provider SDKs for the built-in chat assistant. |
| `--setup-only` | Setup without starting the app. |
| `--diagnose` / `--repair` | Installation diagnostics / runtime repair. |

Normal browser design and printing need none of these add-ons. MCP uses the
harness's model, so it **does not require the AI add-on or provider keys in CatLabel**.
The matching `--skip-mcp`, `--skip-headless` and `--skip-ai` flags disable an add-on
without deleting projects or retained installation files.

## Use with OpenCode and other harnesses

CatLabel exposes **22 shared tools** to create and edit saved designs, import
images/PDFs, inspect PNG previews, export portable designs, discover printers,
adjust profiles and start or inspect print jobs. The editor and harness use the
same documents, renderer and printer backend. **No provider keys are needed in
CatLabel** when you use your existing harness.

### ChatGPT Work / Codex desktop: open the app and ask

1. Start CatLabel and choose **Connect AI harness** in the sidebar.
2. Copy the app address and open it in your harness's built-in browser.
3. Ask for a label. Compatible browsers discover the page's tools automatically;
   there is no JSON configuration or token to paste for this route.

Site tools require a compatible desktop browser, an eligible model and enabled
browser/workspace permissions. Their availability follows the host's rollout.
See [OpenAI's site-tools guide](https://learn.chatgpt.com/docs/webmcp). Tools work
with saved projects; save your current canvas first or ask for a new named design.
Keep CatLabel running. Cloud-only chats cannot reach your local printer through a
localhost URL.

### OpenCode: use the prepared connection file

When MCP is enabled, CatLabel automatically prepares a private OpenCode v2 file
for its current port. **Connect AI harness** shows its path. For a new OpenCode
session, copy the launch command from the sidebar and paste it into your terminal.
It sets `OPENCODE_CONFIG` and starts `opencode --standalone`, using a private
server. Check `/mcps` and wait for CatLabel to connect. For an existing shared
service, merge its `mcp.servers.catlabel` entry into your project config, preserve
other entries, then run `opencode reload` and reconnect with `/mcps`.

The fragment uses a private token-file reference. It does not print or embed the
credential. Keep both files on the same computer and outside Git/shared folders.

New packaged desktop installs enable MCP by default. To enable it in an existing
or source-folder installation, close CatLabel and run:

```sh
bash ./run.sh --install-mcp
```

Use `run.bat --install-mcp` on Windows, or the AppImage with `--install-mcp`.
The local endpoint is `http://127.0.0.1:8000/mcp/` unless you choose another port.
Other MCP clients use Streamable HTTP and CatLabel's private bearer credential.
For platform commands, manual configuration, connection checks and troubleshooting,
see [the MCP guide](docs/mcp.md).

Try a request such as:

> Create a 48 × 25 mm label with “Spare parts” and a QR code. Save it as “Parts
> shelf”, show me the preview, then prepare a print plan for the printer I choose.
> Ask before starting the physical print.

A print plan freezes the preview, printer and settings. Starting it requires its
hash and an idempotency key: retrying the same request returns the same job,
including after a restart. Interrupted delivery is marked uncertain and never
replayed automatically. Saved edits require a revision, and the editor notices
external changes while preserving your current canvas and undo history.

The server supports the **July 2026 MCP protocol (`2026-07-28`)** with the
`2025-11-25` compatibility path over local Streamable HTTP. OpenCode design and
preview workflows are verified. Stdio, legacy SSE and the Tasks extension are
not currently implemented.

## What you can make

- **Visual labels:** text, QR codes, barcodes, icons, images and shapes; drag,
  resize, align, group and reorder elements. Millimetre controls help keep the
  design matched to the paper. Upload your own fonts and import PDF pages.
- **Reusable layouts:** shipping/address labels, price tags, inventory/IT asset
  labels and date tools, with saved projects, folders and JSON export/import.
- **Batch labels:** put `{{ product_name }}` or `{{ sku }}` in text, codes or
  HTML, then populate the Batch Data tab from CSV, a table, number sequences or
  a matrix of combinations.
- **HTML/CSS designs:** compose sanitized layouts alongside canvas elements.
  Auto-fitting text and dynamic code elements make dense labels easier to build.
- **Printer profiles:** save per-printer density/energy, feed and supported speed
  or paper-mode controls. Availability and ranges depend on the model; a speed
  control is not supported by every printer.
- **Long or oversized layouts:** rotate a continuous-roll design for a banner,
  or use split mode to print a wider design in strips. Keep pre-cut labels within
  their physical dimensions.
- **Optional AI assistance:** use MCP from your existing harness, or install the
  built-in chat add-on. External prompt/JSON copy-and-paste is also available.

For example, a batch design can use `{{ sku }}` in its barcode and
`{{ product_name }}` in its heading. Import a CSV with those columns, check the
preview, and print each row without editing the layout repeatedly.

## Printer support

CatLabel talks directly to printers over Bluetooth Classic or BLE, depending on
the device. Printer recognition is conservative: an unknown or ambiguous device
name is not assigned a protocol just because it resembles another model.

| Backend | Examples and scope |
| --- | --- |
| Niimbot | D11, D110, D101; B1, B21, B3S, B24, B18. D11S has an experimental 203 DPI profile. |
| Phomemo | M02/M02S/M02X/T02, plus local M03/M04/M200, D30, P12 and PM-241 recipes. |
| Generic | PD01 and catalogued Tiny, Luck, V5G/V5X/V5C, Eleph/ToPrint, Instaprint, Funny LX, Orgstra and selected PrintMaster families. |

Catalog support and protocol tests are not a guarantee for every firmware or
Bluetooth adapter. Exact M110/M120 names use experimental PrintMaster recipes;
M220 and unconfirmed M221/M260 aliases remain unavailable. Check the app's model
list and [protocol compatibility notes](docs/upstream-parity.md) for the supported
scope and known limitations.

### Bluetooth and printing tips

Turn the printer on, load the appropriate paper and scan from the sidebar.
Some Classic/SPP devices need pairing in the operating system first; BLE devices
such as Niimbot generally connect directly. If discovery or connection fails,
check the OS Bluetooth service, restart the printer and retry the scan.

Density changes darkness; speed controls the motor on models that expose it.
Transport pacing and the negotiated Bluetooth transfer size can also affect
throughput. A successful submission means the data was sent; check the physical
output before retrying an uncertain job. See [print-job behavior](docs/print-jobs.md).

## Documentation

| Guide | Contents |
| --- | --- |
| [Installation and recovery](docs/installation.md) | Add-ons, prerequisites, data locations, diagnostics, update and rollback. |
| [MCP and site tools](docs/mcp.md) | Desktop browser setup, OpenCode, credentials, previews and durable jobs. |
| [REST API](API_REFERENCE.md) | Payloads, templates, batch generation and direct integrations. |
| [Local operation](docs/local-operation.md) | Ports, access tokens, optional LAN operation and API headers. |
| [Project persistence](docs/project-persistence.md) / [resource limits](docs/resource-limits.md) | Revision guards, imports and processing limits. |
| [Backend](docs/architecture.md) / [frontend architecture](docs/frontend-architecture.md) | Shared services, documents, rendering and printer layers. |
| [Development checks](docs/development-checks.md) | Ruff, basedpyright, React lint, Knip, cycles, tests and audits. |
| [Release packaging](docs/releases.md) | Immutable ZIPs and launcher/AppImage builds. |
| [Upstream synchronization](docs/upstream-sync.md) | Pinned catalog provenance and contributor workflow. |

## License and attribution

CatLabel is distributed under the [Apache License 2.0](LICENSE). It builds on
[TiMini-Print](https://github.com/Dejniel/TiMini-Print) by Dejniel, including the
reverse-engineered printer protocols and encoding logic. See [NOTICE](NOTICE)
for attribution.
