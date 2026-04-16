from typing import Dict, List, Optional

from ..manifest import VendorManifest
from .client import PhomemoClient


class PhomemoManifest(VendorManifest):
    @property
    def vendor_id(self) -> str:
        return "phomemo"

    @property
    def display_name(self) -> str:
        return "Phomemo"

    def _build_capabilities(self) -> dict:
        return {
            "speed": {"available": False},
            "energy": {"available": False},
            "density": {"available": True, "min": 1, "max": 8, "default": 6},
            "feed": {"available": True, "default": 32},
        }

    def get_supported_models(self) -> List[Dict]:
        base = {
            "vendor": "phomemo",
            "vendor_display": self.display_name,
            "capabilities": self._build_capabilities(),
            "default_energy": 6,
            "max_density": 8,
        }
        return [
            {**base, "name": "P12", "model_id": "P12", "width_px": 96, "width_mm": 12, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_p12"},
            {**base, "name": "M110", "model_id": "M110", "width_px": 384, "width_mm": 48, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_m110"},
            {**base, "name": "D30", "model_id": "D30", "width_px": 120, "width_mm": 15, "dpi": 203, "media_type": "pre-cut", "protocol_family": "phomemo_d"},
            {**base, "name": "T02", "model_id": "T02", "width_px": 384, "width_mm": 48, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_m02"},
        ]

    def get_presets(self) -> List[Dict]:
        return [
            {"name": "Phomemo D30 (12x40mm)", "media_type": "pre-cut", "description": "Standard Phomemo D30 label.", "width_mm": 12, "height_mm": 40, "is_rotated": True, "split_mode": False, "border": "none"},
            {"name": "Phomemo M110 (40x30mm)", "media_type": "continuous", "description": "Standard Phomemo M110 continuous roll.", "width_mm": 40, "height_mm": 30, "is_rotated": True, "split_mode": False, "border": "none"},
            {"name": "Phomemo T02 (50x50mm)", "media_type": "continuous", "description": "Standard Phomemo T02 square.", "width_mm": 50, "height_mm": 50, "is_rotated": False, "split_mode": False, "border": "none"},
        ]

    def _model_prefixes(self, model_id: str) -> tuple[str, ...]:
        if model_id == "T02":
            return ("T02", "T02E", "Q02E", "C02E")
        return (model_id,)

    def identify_device(self, name: str, device=None, mac: Optional[str] = None) -> Optional[Dict]:
        normalized = (name or "").strip().upper()
        for model in self.get_supported_models():
            if any(normalized.startswith(prefix) for prefix in self._model_prefixes(model["model_id"])):
                return model
        return None

    def get_client(self, device, hardware_info: dict, profile, settings):
        return PhomemoClient(device, hardware_info, profile, settings)
