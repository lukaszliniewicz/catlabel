from ...protocol.families.v5g import V5G_DENSITY_MAX, V5G_DENSITY_MIN
from ..manifest import VendorManifest
from ..utils import _registry_models, extract_raw_hardware_info
from .client import GenericClient
from .models import PrinterModelRegistry


class GenericManifest(VendorManifest):
    @property
    def vendor_id(self) -> str:
        return "generic"

    @property
    def display_name(self) -> str:
        return "Generic / Cat Printers"

    def _build_capabilities(self, raw_info: dict) -> dict:
        protocol_family = str(raw_info.get("protocol_family") or "").lower()
        if protocol_family == "yk_astra_p1":
            return {
                "speed": {
                    "available": True,
                    "min": 0,
                    "max": min(255, int(raw_info.get("max_speed", 25))),
                    "default": raw_info.get("default_speed", 25),
                },
                "energy": {"available": False},
                "density": {
                    "available": True,
                    "min": raw_info.get("min_density", 5),
                    "max": raw_info.get("max_density", 13),
                    "default": raw_info.get("default_density", 9),
                    "allow_auto": False,
                    "scale": "level",
                },
                "feed": {"available": False},
            }
        if protocol_family in {
            "luck_normal",
            "luck_normal_a4",
            "v5g",
            "v5x",
            "v5c",
        }:
            if protocol_family == "v5g":
                density_capability = {
                    "available": True,
                    "min": V5G_DENSITY_MIN,
                    "max": V5G_DENSITY_MAX,
                    "default": raw_info.get("default_density"),
                    "recommended_min": raw_info.get("min_density"),
                    "recommended_max": raw_info.get("max_density"),
                    "allow_auto": True,
                    "scale": "raw",
                }
            else:
                density_capability = {
                    "available": True,
                    "min": 1,
                    "max": 5,
                    "default": 3,
                    "allow_auto": False,
                    "scale": "level",
                }
            return {
                "speed": {"available": False},
                "energy": {"available": False},
                "density": density_capability,
                "feed": {"available": True, "default": 0},
            }
        return {
            "speed": {
                "available": True,
                "min": 0,
                "max": raw_info.get("max_speed", 100),
                "default": raw_info.get("default_speed", 0),
            },
            "energy": {
                "available": True,
                "min": raw_info.get("min_energy", 1000),
                "max": raw_info.get("max_energy", 65535),
                "step": 500,
                "default": raw_info.get("default_energy", 5000),
            },
            "density": {"available": False},
            "feed": {"available": True, "default": 50},
        }

    def get_supported_models(self) -> list[dict]:
        registry = PrinterModelRegistry.load()
        results: list[dict] = []
        seen = set()

        for model in _registry_models(registry):
            raw = extract_raw_hardware_info(model)
            if raw["vendor"] in ("niimbot", "phomemo"):
                continue

            if raw["model_id"] in seen:
                continue
            seen.add(raw["model_id"])

            raw["vendor_display"] = self.display_name
            raw["capabilities"] = self._build_capabilities(raw)
            results.append(raw)

        return results

    def get_presets(self) -> list[dict]:
        return [
            {
                "name": "Roll: Standard Square (48x48mm)",
                "media_type": "continuous",
                "description": "Default full-width square for continuous rolls.",
                "width_mm": 48,
                "height_mm": 48,
                "is_rotated": False,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Roll: Narrow Tag (48x12mm)",
                "media_type": "continuous",
                "description": "Generic roll preset with full width and 12mm height.",
                "width_mm": 48,
                "height_mm": 12,
                "is_rotated": False,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Roll: Narrow Tag (48x15mm)",
                "media_type": "continuous",
                "description": "Short horizontal tag for lists/names. Prints fast, saves tape.",
                "width_mm": 48,
                "height_mm": 15,
                "is_rotated": False,
                "split_mode": False,
                "border": "cut_line",
            },
            {
                "name": "Roll: Small Item / Gridfinity (30x12mm)",
                "media_type": "continuous",
                "description": "Small centered label.",
                "width_mm": 30,
                "height_mm": 12,
                "is_rotated": False,
                "split_mode": False,
                "border": "box",
            },
            {
                "name": "Roll: Long Banner (48x100mm)",
                "media_type": "continuous",
                "description": "Landscape banner for continuous rolls.",
                "width_mm": 100,
                "height_mm": 48,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Roll: Cable Flag (30x48mm)",
                "media_type": "continuous",
                "description": "Fold-over cable flag.",
                "width_mm": 30,
                "height_mm": 48,
                "is_rotated": False,
                "split_mode": False,
                "border": "cut_line",
            },
            {
                "name": "A6 Shipping (105x148mm)",
                "media_type": "continuous",
                "description": "Giant multi-strip decal for A6 shipping labels.",
                "width_mm": 105,
                "height_mm": 148,
                "is_rotated": False,
                "split_mode": True,
                "border": "none",
            },
        ]

    def identify_device(
        self, name: str, device=None, mac: str | None = None
    ) -> dict | None:
        registry = PrinterModelRegistry.load()
        model = None

        match = None
        if device and hasattr(device, "model") and device.model:
            model = device.model
        else:
            match = registry.detect_with_origin(name, mac)
            model = match.model if match else None

        if model:
            raw = extract_raw_hardware_info(model)
            if match is not None:
                raw["protocol_family"] = match.protocol_family.value
                raw["protocol_variant"] = match.protocol_variant
            if raw["vendor"] not in ("niimbot", "phomemo"):
                raw["vendor_display"] = self.display_name
                raw["capabilities"] = self._build_capabilities(raw)
                return raw

        return None

    def get_fallback_info(self) -> dict:
        raw = {
            "name": "Generic Printer",
            "vendor": "generic",
            "width_px": 384,
            "width_mm": 48.0,
            "dpi": 203,
            "model": "generic",
            "model_no": "generic",
            "model_id": "generic",
            "default_speed": 0,
            "default_energy": 5000,
            "min_energy": 1,
            "max_energy": 65535,
            "max_speed": 100,
            "max_density": None,
            "media_type": "continuous",
            "protocol_family": "legacy",
        }
        raw["vendor_display"] = self.display_name
        raw["capabilities"] = self._build_capabilities(raw)
        return raw

    def get_client(self, device, hardware_info: dict, profile, settings):
        return GenericClient(device, hardware_info, profile, settings)
