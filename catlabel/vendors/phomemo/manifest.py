from typing import Dict, List, Optional

from ...devices import PrinterModelRegistry
from ..manifest import VendorManifest
from ..utils import _registry_models, extract_raw_hardware_info, find_model_in_registry
from .client import PhomemoClient


class PhomemoManifest(VendorManifest):
    @property
    def vendor_id(self) -> str:
        return "phomemo"

    @property
    def display_name(self) -> str:
        return "Phomemo"

    def _build_capabilities(self, raw_info: dict) -> dict:
        return {
            "speed": {"available": False},
            "energy": {"available": False},
            "density": {
                "available": True,
                "min": 1,
                "max": raw_info.get("max_density") or 8,
                "default": raw_info.get("default_energy") or 6,
            },
            "feed": {"available": True, "default": 32},
        }

    def get_supported_models(self) -> List[Dict]:
        registry = PrinterModelRegistry.load()
        results: List[Dict] = []
        seen = set()

        for model in _registry_models(registry):
            raw = extract_raw_hardware_info(model)
            if raw["vendor"] != "phomemo":
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
                "name": "Phomemo D30 (12x40mm)",
                "media_type": "pre-cut",
                "description": "Standard Phomemo D30 label.",
                "width_mm": 12,
                "height_mm": 40,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Phomemo M110 (40x30mm)",
                "media_type": "continuous",
                "description": "Standard Phomemo M110 continuous/gap roll.",
                "width_mm": 40,
                "height_mm": 30,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Phomemo T02 (50x50mm)",
                "media_type": "continuous",
                "description": "Standard Phomemo T02 square.",
                "width_mm": 50,
                "height_mm": 50,
                "is_rotated": False,
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
            if raw["vendor"] == "phomemo":
                raw["vendor_display"] = self.display_name
                raw["capabilities"] = self._build_capabilities(raw)
                return raw

        return None

    def get_client(self, device, hardware_info: dict, profile, settings):
        return PhomemoClient(device, hardware_info, profile, settings)
