from ..manifest import VendorManifest
from .client import NiimbotClient


class NiimbotManifest(VendorManifest):
    @property
    def vendor_id(self) -> str:
        return "niimbot"

    @property
    def display_name(self) -> str:
        return "Niimbot"

    def _build_capabilities(self) -> dict:
        return {
            "speed": {"available": False},
            "energy": {"available": False},
            "density": {"available": True, "min": 1, "max": 5, "default": 3},
            "feed": {"available": False},
        }

    def get_supported_models(self) -> list[dict]:
        base = {
            "vendor": "niimbot",
            "vendor_display": self.display_name,
            "capabilities": self._build_capabilities(),
            "media_type": "pre-cut",
            "protocol_family": "niimbot",
            "default_energy": 3,
            "max_density": 5,
        }
        return [
            {
                **base,
                "name": "D11/D110 (15mm)",
                "model_id": "D110",
                "protocol_variant": "d110",
                "width_px": 120,
                "width_mm": 15,
                "dpi": 203,
            },
            {
                **base,
                "name": "D11S (experimental, 203 DPI)",
                "model_id": "D11S",
                "protocol_variant": "d11_v1",
                "width_px": 96,
                "width_mm": 12,
                "dpi": 203,
            },
            {
                **base,
                "name": "D101 (25mm)",
                "model_id": "D101",
                "width_px": 200,
                "width_mm": 25,
                "dpi": 203,
            },
            {
                **base,
                "name": "B18",
                "model_id": "B18",
                "width_px": 112,
                "width_mm": 14,
                "dpi": 203,
            },
            {
                **base,
                "name": "B1/B21",
                "model_id": "B1",
                "width_px": 384,
                "width_mm": 48,
                "dpi": 203,
            },
            {
                **base,
                "name": "B3S/B24",
                "model_id": "B3S",
                "width_px": 576,
                "width_mm": 72,
                "dpi": 203,
            },
        ]

    def get_presets(self) -> list[dict]:
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
                "name": "Pre-cut: Niimbot 75x12mm",
                "media_type": "pre-cut",
                "description": "Long Niimbot D-series label.",
                "width_mm": 75,
                "height_mm": 12,
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
                "name": "Pre-cut: Niimbot B18 120x14mm",
                "media_type": "pre-cut",
                "description": "Niimbot B18 long label.",
                "width_mm": 120,
                "height_mm": 14,
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
                "description": "Medium B-series label.",
                "width_mm": 50,
                "height_mm": 30,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Pre-cut: Niimbot B1/B21 50x50mm",
                "media_type": "pre-cut",
                "description": "Square B-series label.",
                "width_mm": 50,
                "height_mm": 50,
                "is_rotated": False,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Pre-cut: Niimbot B3S 70x40mm",
                "media_type": "pre-cut",
                "description": "Standard B3S/B24 label.",
                "width_mm": 70,
                "height_mm": 40,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
        ]

    def _model_prefixes(self, model_id: str) -> tuple[str, ...]:
        if model_id == "D110":
            return ("D11", "D110")
        if model_id == "D101":
            return ("D101",)
        if model_id == "B18":
            return ("B18",)
        if model_id == "B1":
            return ("B1", "B21")
        if model_id == "B3S":
            return ("B3S", "B24")
        return (model_id,)

    def identify_device(
        self,
        name: str,
        device=None,
        mac: str | None = None,
    ) -> dict | None:
        normalized = (name or "").strip().upper()
        vendor_prefix = "NIIMBOT"
        if normalized.startswith(vendor_prefix):
            vendor_separator_start = normalized[
                len(vendor_prefix) : len(vendor_prefix) + 1
            ]
            if vendor_separator_start and (
                vendor_separator_start.isspace() or vendor_separator_start in "-_"
            ):
                normalized = normalized[len(vendor_prefix) :]
                while normalized and (normalized[0].isspace() or normalized[0] in "-_"):
                    normalized = normalized[1:]

        matches = []
        for model in self.get_supported_models():
            model_id = model["model_id"]
            for alias in self._model_prefixes(model_id):
                normalized_alias = alias.upper()
                if not normalized_alias:
                    continue
                if normalized == normalized_alias:
                    matches.append(
                        (len(normalized_alias), model_id, model, normalized_alias)
                    )
                elif normalized.startswith(normalized_alias):
                    boundary = normalized[len(normalized_alias)]
                    if boundary.isspace() or boundary in "-_":
                        matches.append(
                            (len(normalized_alias), model_id, model, normalized_alias)
                        )

        if not matches:
            return None

        longest_alias_length = max(match[0] for match in matches)
        best_matches = [match for match in matches if match[0] == longest_alias_length]
        if len({match[1] for match in best_matches}) != 1:
            return None
        selected = best_matches[0]
        model = selected[2]
        if selected[1] == "D110" and selected[3] == "D11":
            # Keep CatLabel's existing geometry while probing the protocol.
            # The retail D11 name alone does not establish head width or DPI.
            return {**model, "protocol_variant": "d11_auto"}
        return model

    def get_client(self, device, hardware_info: dict, profile, settings):
        return NiimbotClient(device, hardware_info, profile, settings)
