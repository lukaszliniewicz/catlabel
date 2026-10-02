"""Application and data paths shared by the backend."""

from __future__ import annotations

import os
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[2]

_configured_data_directory = os.environ.get("CATLABEL_DATA_DIR")
DATA_DIRECTORY = (
    Path.cwd() / "data"
    if _configured_data_directory is None
    else Path(_configured_data_directory).expanduser()
)
if not DATA_DIRECTORY.is_absolute():
    raise ValueError("CATLABEL_DATA_DIR must be an absolute path")

FONTS_DIRECTORY = DATA_DIRECTORY / "fonts"
FRONTEND_DIRECTORY = APPLICATION_ROOT / "frontend" / "dist"
LEGACY_FONTS_DIRECTORY = APPLICATION_ROOT / "fonts"
