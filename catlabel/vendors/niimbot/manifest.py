from typing import Dict, List, Optional

from ...devices import PrinterModelRegistry
from ..manifest import VendorManifest
from ..utils import _registry_models, extract_raw_hardware_info, find_model_in_registry
from .client import NiimbotClient


class NiimbotManifest(VendorManifest):
    @property
    def vendor_id(self) -> str:
        return "niimbot"

    @property
    def display_name(self) -> str:
        return "Niimbot (Pre-cut Labels)"

    def _build_capabilities(self, raw_info: dict) -> dict:
        return {
            "speed": {"available": False},
            "energy": {"available": False},
            "density": {
                "available": True,
                "min": 1,
                "max": raw_info.get("max_density") or 5,
                "default": raw_info.get("default_energy") or 3,
            },
            "feed": {"available": False},
        }

    def get_supported_models(self) -> List[Dict]:
        registry = PrinterModelRegistry.load()
        results: List[Dict] = []
        seen = set()

        for model in _registry_models(registry):
            raw = extract_raw_hardware_info(model)
            if raw["vendor"] != "niimbot":
                continue

            if raw["model_id"] in seen:
                continue
            seen.add(raw["model_id"])

            raw["vendor_display"] = self.display_name
            raw["capabilities"] = self._build_capabilities(raw)
            results.append(raw)

        return results

    def get_presets(self) -> List[Dict]:
        return [
            {
                "name": "Pre-cut: Niimbot 30x15mm",
                "media_type": "pre-cut",
                "description": "Standard small Niimbot D-series label.",
                "width_mm": 30,
                "height_mm": 15,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Pre-cut: Niimbot 40x12mm",
                "media_type": "pre-cut",
                "description": "Standard medium Niimbot D-series label.",
                "width_mm": 40,
                "height_mm": 12,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Pre-cut: Niimbot 50x14mm",
                "media_type": "pre-cut",
                "description": "Standard large Niimbot D-series label.",
                "width_mm": 50,
                "height_mm": 14,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Pre-cut: Niimbot Cable 109x12.5mm",
                "media_type": "pre-cut",
                "description": "Niimbot D-series cable wrap label.",
                "width_mm": 109,
                "height_mm": 12.5,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Pre-cut: Niimbot B-Series 40x14mm",
                "media_type": "pre-cut",
                "description": "Small B-series label.",
                "width_mm": 40,
                "height_mm": 14,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Pre-cut: Niimbot B1/B21 50x30mm",
                "media_type": "pre-cut",
                "description": "Large B-series label.",
                "width_mm": 50,
                "height_mm": 30,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
        ]

    def identify_device(self, name: str, device=None, mac: Optional[str] = None) -> Optional[Dict]:
        registry = PrinterModelRegistry.load()
        model = None

        if device and hasattr(device, "model") and device.model:
            model = device.model
        else:
            model = find_model_in_registry(registry, name)

        if model:
            raw = extract_raw_hardware_info(model)
            if raw["vendor"] == "niimbot":
                raw["vendor_display"] = self.display_name
                raw["capabilities"] = self._build_capabilities(raw)
                return raw

        return None

    def get_client(self, device, hardware_info: dict, profile, settings):
        return NiimbotClient(device, hardware_info, profile, settings)
