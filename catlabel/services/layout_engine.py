"""Template metadata shared with the existing React markup generator."""

import json
from pathlib import Path
from typing import Any, cast

TEMPLATE_METADATA = cast(
    list[dict[str, Any]],
    json.loads(
        (Path(__file__).resolve().parents[1] / "data/templates.json").read_text(
            encoding="utf-8"
        )
    ),
)
