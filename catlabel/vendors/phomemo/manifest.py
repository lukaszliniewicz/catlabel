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
            {**base, "name": "P12 / P12 Pro", "model_id": "P12", "width_px": 96, "width_mm": 12, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_p12"},
            {**base, "name": "A30", "model_id": "A30", "width_px": 120, "width_mm": 15, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_p12"},
            {**base, "name": "M02 / M02S / M02X", "model_id": "M02", "width_px": 384, "width_mm": 48, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_m02"},
            {**base, "name": "M02 Pro", "model_id": "M02_PRO", "width_px": 624, "width_mm": 53, "dpi": 300, "media_type": "continuous", "protocol_family": "phomemo_m02"},
            {**base, "name": "M03", "model_id": "M03", "width_px": 432, "width_mm": 53, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_m"},
            {**base, "name": "M04S / M04AS", "model_id": "M04S", "width_px": 1232, "width_mm": 110, "dpi": 300, "media_type": "continuous", "protocol_family": "phomemo_m04"},
            {**base, "name": "M110 / M120", "model_id": "M110", "width_px": 384, "width_mm": 48, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_m110"},
            {**base, "name": "M200 / M250", "model_id": "M200", "width_px": 608, "width_mm": 75, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_m"},
            {**base, "name": "M220 / M221 / M260", "model_id": "M220", "width_px": 576, "width_mm": 72, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_m"},
            {**base, "name": "T02", "model_id": "T02", "width_px": 384, "width_mm": 48, "dpi": 203, "media_type": "continuous", "protocol_family": "phomemo_m"},
            {**base, "name": "D30 / D35 / D50", "model_id": "D30", "width_px": 120, "width_mm": 15, "dpi": 203, "media_type": "pre-cut", "protocol_family": "phomemo_d"},
            {**base, "name": "Q30 / Q30S", "model_id": "Q30", "width_px": 120, "width_mm": 15, "dpi": 203, "media_type": "pre-cut", "protocol_family": "phomemo_d"},
            {**base, "name": "PM-241-BT (Shipping)", "model_id": "PM241", "width_px": 816, "width_mm": 102, "dpi": 203, "media_type": "continuous", "protocol_family": "tspl"},
        ]

    def get_presets(self) -> List[Dict]:
        return [
            {"name": "Phomemo D-Series (12x40mm)", "media_type": "pre-cut", "description": "Standard D30/D35 label.", "width_mm": 12, "height_mm": 40, "is_rotated": True, "split_mode": False, "border": "none"},
            {"name": "Phomemo D-Series (15x30mm)", "media_type": "pre-cut", "description": "Wider D30 label.", "width_mm": 15, "height_mm": 30, "is_rotated": True, "split_mode": False, "border": "none"},
            {"name": "Phomemo M-Series (40x30mm)", "media_type": "continuous", "description": "Standard M110/M200 continuous roll.", "width_mm": 40, "height_mm": 30, "is_rotated": True, "split_mode": False, "border": "none"},
            {"name": "Phomemo M-Series (50x30mm)", "media_type": "continuous", "description": "Wider M-series label.", "width_mm": 50, "height_mm": 30, "is_rotated": True, "split_mode": False, "border": "none"},
            {"name": "Phomemo M-Series (50x80mm)", "media_type": "continuous", "description": "Large M-series label.", "width_mm": 50, "height_mm": 80, "is_rotated": False, "split_mode": False, "border": "none"},
            {"name": "Phomemo Round (30mm)", "media_type": "continuous", "description": "30mm circle.", "width_mm": 30, "height_mm": 30, "is_rotated": False, "split_mode": False, "border": "none"},
            {"name": "Phomemo Round (50mm)", "media_type": "continuous", "description": "50mm circle.", "width_mm": 50, "height_mm": 50, "is_rotated": False, "split_mode": False, "border": "none"},
            {"name": "Phomemo T02 (50x50mm)", "media_type": "continuous", "description": "Standard Phomemo T02 square.", "width_mm": 50, "height_mm": 50, "is_rotated": False, "split_mode": False, "border": "none"},
            {"name": "Shipping 4x6 (102x152mm)", "media_type": "continuous", "description": "Standard shipping label for PM-241.", "width_mm": 102, "height_mm": 152, "is_rotated": False, "split_mode": False, "border": "none"},
        ]

    def _model_prefixes(self, model_id: str) -> tuple[str, ...]:
        mapping = {
            "P12": ("P12", "P12PRO", "P12 PRO"),
            "A30": ("A30",),
            "M02": ("M02", "M02S", "M02X"),
            "M02_PRO": ("M02 PRO", "M02PRO"),
            "M03": ("M03",),
            "M04S": ("M04", "M04S", "M04AS"),
            "M110": ("M110", "M120"),
            "M200": ("M200", "M250"),
            "M220": ("M220", "M221", "M260"),
            "D30": ("D30", "D35", "D50", "D"),
            "Q30": ("Q30", "Q30S"),
            "T02": ("T02", "T02E", "Q02E", "C02E"),
            "PM241": ("PM-241", "PM241", "PM 241"),
        }
        if model_id == "M200":
            return mapping.get(model_id, (model_id,)) + ("PHOMEMO", "MR.IN")
        return mapping.get(model_id, (model_id,))

    def identify_device(self, name: str, device=None, mac: Optional[str] = None) -> Optional[Dict]:
        normalized = (name or "").strip().upper()
        if not normalized:
            return None

        candidate_names = [normalized]
        for vendor_prefix in ("PHOMEMO ", "PHOMEMO-", "MR.IN ", "MR.IN-", "MR.IN"):
            if normalized.startswith(vendor_prefix):
                stripped = normalized[len(vendor_prefix) :].strip()
                if stripped:
                    candidate_names.append(stripped)

        for model in self.get_supported_models():
            prefixes = self._model_prefixes(model["model_id"])
            if any(
                candidate.startswith(prefix)
                for candidate in dict.fromkeys(candidate_names)
                for prefix in prefixes
            ):
                return model
        return None

    def get_client(self, device, hardware_info: dict, profile, settings):
        return PhomemoClient(device, hardware_info, profile, settings)
