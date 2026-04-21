# CatLabel

CatLabel is a web-based design and printing application for thermal label printers. It is a fork of [TiMini Print](https://github.com/Dejniel/TiMini-Print), moving the original CLI and Tkinter-based logic into a web interface built with **FastAPI** and **React**.

The project uses the protocol implementations and rendering logic from the original TiMini Print, while adding native support for Niimbot printers and other modern features, to communicate with various thermal printers over Bluetooth.

---

## Features

### Core Design Tools
*   **Visual Canvas:** A WYSIWYG editor for placing text, barcodes, QR codes, and images on a label.
*   **Precision Controls:** Adjust element coordinates and dimensions using millimeter-based "scrubber" inputs for exact alignment.
*   **Icon Library:** Integrated searchable access to the Lucide icon library, with automatic rasterization for thermal print heads.
*   **Custom HTML/CSS:** An advanced mode to design labels using raw HTML and CSS for complex or pixel-perfect layouts.
*   **Undo/Redo:** Full history tracking for canvas modifications.
*   **Grouping & Arranging:** Group elements for collective movement and manage the Z-order (stacking) of layers.

### Automation & Wizards
*   **Onboarding Wizard:** Guided setup for printer detection (Bluetooth scan) or manual brand selection (Niimbot, Phomemo, Generic).
*   **AI-Assisted Layouts:** Generate designs from natural language prompts using an LLM-powered agent (requires an API key).
*   **Shipping Label Wizard:** A dedicated tool for creating shipping labels with a built-in address book and automated layout generation.
*   **Template Wizards:** Specialized forms for generating layouts for price tags, inventory labels, and cable flags.
*   **Date Tool:** Insert today's date, or calculate offset dates (e.g., for food expiry) in multiple formats.
*   **Batch Printing:** Import CSV data or use built-in tools for Cartesian product permutations and serialized number sequences.

### Advanced Rendering & Control
*   **Image Processing:** Automatic gamma adjustment, equalization, and sharpening kernels to ensure clarity on 1-bit thermal heads.
*   **Print Tuning:** Real-time density adjustments based on printer temperature, coverage ratio (black bit density), and specific print head types (e.g., Gaoya/Diya).
*   **Hardware Control:** Granular settings for motor speed, energy levels (blackening), and precise paper feeding/retraction.
*   **Project Management:** Hierarchical folder system for organizing designs, with support for recursive deletion and full project tree import/export.
*   **Diagnostics:** Startup health checks that verify environment dependencies and Bluetooth stack status.

---

## Dynamic Data & Variables

CatLabel supports a flexible variable system using the `{{ variable_name }}` syntax. This allows you to create a single design and populate it with multiple records via the Batch Printing tool.

### Variable Usage:
*   **Standard Text:** Type `{{ price }}` or `{{ name }}` into any text element.
*   **HTML/CSS Mode:** Use variables directly in your markup, for example:
    ```html
    <div class="auto-text">
      <h1>{{ product_name }}</h1>
      <p>SKU: {{ sku_code }}</p>
    </div>
    ```
*   **Variable Combinations:** Use multiple variables in a single string, like `Model: {{ model }} / S/N: {{ serial }}`.

### Data Management:
*   **Manual Entry:** Edit batch records directly in a spreadsheet-like table within the UI.
*   **CSV Import:** Upload datasets and map columns to your canvas variables.
*   **Permutations (Matrix):** Generate Cartesian product combinations from comma-separated lists.
*   **Sequences:** Create serialized labels with custom prefixes, suffixes, and padding.

---

## Supported Printers

CatLabel works with many portable Bluetooth thermal printers that do not use standard ESC/POS commands. 

*   **Niimbot:** D11, D110, B21, and other V5 protocol models.
*   **Phomemo:** T02, M02, and similar "cat printers."
*   **Generic Labels:** Printers using apps like "Tiny Print" or "iBleem."
*   **Protocol Families:** Native support for V5X, V5G, V5C, DCK, and Legacy protocol families.

For a detailed list of supported model numbers and Bluetooth name prefixes, see [API_REFERENCE.md](API_REFERENCE.md).

---

## Installation

### 1. Launcher (Windows)
The `launcher.py` script is the intended way to run the app on Windows. It manages the repository and environment automatically.

1.  Download the repository.
2.  Run `launcher.py` (or the compiled `CatLabel-Launcher.exe` if available).
3.  The launcher will clone the code (if needed), update it, and start the backend.

### 2. Manual Setup (Windows/Linux/macOS)
The repository includes bootstrapper scripts (`run.bat` for Windows, `run.sh` for Linux/macOS) that use **Micromamba** to create an isolated environment.

**Commands:**
*   **Windows:** `run.bat`
*   **Linux/macOS:** `chmod +x run.sh && ./run.sh`

**Technical Process:**
1.  The script downloads a local copy of Micromamba.
2.  It creates a virtual environment in the `env/` folder.
3.  It installs Python dependencies and Node.js.
4.  It compiles the React frontend.
5.  It starts the FastAPI server on [http://localhost:8000](http://localhost:8000).

---

## Architecture

CatLabel is a local web application:

*   **Backend:** A FastAPI server that manages the SQLite database, handles image processing (rasterization), and executes printer protocols.
*   **Frontend:** A React application for the user interface.
*   **Communication:** Uses the `bleak` library for Bluetooth and `pyserial` for serial connections.
*   **Rendering:** Designs are converted to 1-bit PNGs/bitmaps before being sent to the printer.

---

## Development

To contribute or run in development mode:

1.  **Environment:** Ensure Python 3.11+ and Node.js 18+ are available.
2.  **Backend:** Run `python -m catlabel`.
3.  **Frontend:** Navigate to `frontend/` and run `npm run dev`.

---

## Attribution & License

This project is a fork of [TiMini Print](https://github.com/Dejniel/TiMini-Print) by Dejniel. We acknowledge the original author's work in reverse-engineering the printer protocols and building the core rendering engine.

CatLabel is distributed under the **Apache License 2.0**.
