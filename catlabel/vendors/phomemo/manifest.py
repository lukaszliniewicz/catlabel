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

    def get_supported_models(self) -> list[dict]:
        base = {
            "vendor": "phomemo",
            "vendor_display": self.display_name,
            "capabilities": self._build_capabilities(),
            "default_energy": 6,
            "max_density": 8,
        }
        return [
            {
                **base,
                "name": "P12 / P12 Pro",
                "model_id": "P12",
                "width_px": 96,
                "width_mm": 12,
                "dpi": 203,
                "media_type": "continuous",
                "protocol_family": "phomemo_p12",
            },
            {
                **base,
                "name": "A30",
                "model_id": "A30",
                "width_px": 120,
                "width_mm": 15,
                "dpi": 203,
                "media_type": "continuous",
                "protocol_family": "phomemo_p12",
            },
            {
                **base,
                "name": "M02 / M02S / M02X",
                "model_id": "M02",
                "width_px": 384,
                "width_mm": 48,
                "dpi": 203,
                "media_type": "continuous",
                "protocol_family": "phomemo_m02",
            },
            {
                **base,
                "name": "M02 Pro",
                "model_id": "M02_PRO",
                "width_px": 624,
                "width_mm": 53,
                "dpi": 300,
                "media_type": "continuous",
                "protocol_family": "phomemo_m02",
            },
            {
                **base,
                "name": "M03",
                "model_id": "M03",
                "width_px": 432,
                "width_mm": 53,
                "dpi": 203,
                "media_type": "continuous",
                "protocol_family": "phomemo_m",
            },
            {
                **base,
                "name": "M04S / M04AS",
                "model_id": "M04S",
                "width_px": 1232,
                "width_mm": 110,
                "dpi": 300,
                "media_type": "continuous",
                "protocol_family": "phomemo_m04",
            },
            {
                **base,
                "name": "M110 / M120",
                "model_id": "M110",
                "width_px": 384,
                "width_mm": 48,
                "dpi": 203,
                "media_type": "continuous",
                "protocol_family": "phomemo_m110",
            },
            {
                **base,
                "name": "M200 / M250",
                "model_id": "M200",
                "width_px": 608,
                "width_mm": 75,
                "dpi": 203,
                "media_type": "continuous",
                "protocol_family": "phomemo_m",
            },
            {
                **base,
                "name": "M220 / M221 / M260",
                "model_id": "M220",
                "width_px": 576,
                "width_mm": 72,
                "dpi": 203,
                "media_type": "continuous",
                "protocol_family": "phomemo_m",
            },
            {
                **base,
                "name": "T02",
                "model_id": "T02",
                "width_px": 384,
                "width_mm": 48,
                "dpi": 203,
                "media_type": "continuous",
                "protocol_family": "phomemo_m",
            },
            {
                **base,
                "name": "D30 / D35 / D50",
                "model_id": "D30",
                "width_px": 120,
                "width_mm": 15,
                "dpi": 203,
                "media_type": "pre-cut",
                "protocol_family": "phomemo_d",
            },
            {
                **base,
                "name": "Q30 / Q30S",
                "model_id": "Q30",
                "width_px": 120,
                "width_mm": 15,
                "dpi": 203,
                "media_type": "pre-cut",
                "protocol_family": "phomemo_d",
            },
            {
                **base,
                "name": "PM-241-BT (Shipping)",
                "model_id": "PM241",
                "width_px": 816,
                "width_mm": 102,
                "dpi": 203,
                "media_type": "continuous",
                "protocol_family": "tspl",
            },
        ]

    def get_presets(self) -> list[dict]:
        return [
            {
                "name": "Phomemo D-Series (12x40mm)",
                "media_type": "pre-cut",
                "description": "Standard D30/D35 label.",
                "width_mm": 12,
                "height_mm": 40,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Phomemo D-Series (15x30mm)",
                "media_type": "pre-cut",
                "description": "Wider D30 label.",
                "width_mm": 15,
                "height_mm": 30,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Phomemo M-Series (40x30mm)",
                "media_type": "continuous",
                "description": "Standard M110/M200 continuous roll.",
                "width_mm": 40,
                "height_mm": 30,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Phomemo M-Series (50x30mm)",
                "media_type": "continuous",
                "description": "Wider M-series label.",
                "width_mm": 50,
                "height_mm": 30,
                "is_rotated": True,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Phomemo M-Series (50x80mm)",
                "media_type": "continuous",
                "description": "Large M-series label.",
                "width_mm": 50,
                "height_mm": 80,
                "is_rotated": False,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Phomemo Round (30mm)",
                "media_type": "continuous",
                "description": "30mm circle.",
                "width_mm": 30,
                "height_mm": 30,
                "is_rotated": False,
                "split_mode": False,
                "border": "none",
            },
            {
                "name": "Phomemo Round (50mm)",
                "media_type": "continuous",
                "description": "50mm circle.",
                "width_mm": 50,
                "height_mm": 50,
                "is_rotated": False,
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
            {
                "name": "Shipping 4x6 (102x152mm)",
                "media_type": "continuous",
                "description": "Standard shipping label for PM-241.",
                "width_mm": 102,
                "height_mm": 152,
                "is_rotated": False,
                "split_mode": False,
                "border": "none",
            },
        ]

    def _model_aliases(self, model_id: str) -> tuple[str, ...]:
        mapping = {
            "P12": ("P12", "P12PRO", "P12 PRO"),
            "A30": ("A30",),
            "M02": ("M02", "M02S", "M02X"),
            "M02_PRO": ("M02 PRO", "M02PRO", "M02_PRO"),
            "M03": ("M03",),
            "M04S": ("M04", "M04S", "M04AS"),
            "M110": ("M110", "M120"),
            "M200": ("M200", "M250"),
            "M220": ("M220", "M221", "M260"),
            "D30": ("D30", "D35", "D50"),
            "Q30": ("Q30", "Q30S"),
            "T02": ("T02", "T02E", "Q02E", "C02E"),
            "PM241": ("PM-241", "PM241", "PM 241", "PM241BT", "PM-241-BT"),
        }
        return mapping.get(model_id, (model_id,))

    def _candidate_names(self, normalized: str) -> tuple[str, ...]:
        candidates = [normalized]
        for vendor_prefix in ("PHOMEMO ", "PHOMEMO-", "MR.IN ", "MR.IN-", "MR.IN"):
            if normalized.startswith(vendor_prefix):
                stripped = normalized[len(vendor_prefix) :].strip()
                if stripped:
                    candidates.append(stripped)
                break
        return tuple(dict.fromkeys(candidates))

    @staticmethod
    def _matches_alias(candidate: str, alias: str) -> bool:
        if candidate == alias:
            return True
        if not candidate.startswith(alias):
            return False
        next_character = candidate[len(alias)]
        return next_character in "_-" or next_character.isspace()

    def identify_device(
        self, name: str, device=None, mac: str | None = None
    ) -> dict | None:
        normalized = (name or "").strip().upper()
        if not normalized:
            return None

        candidate_names = self._candidate_names(normalized)
        scored_models: list[tuple[int, dict]] = []
        for model in self.get_supported_models():
            matched_alias_lengths = [
                len(alias)
                for alias in self._model_aliases(model["model_id"])
                if any(
                    self._matches_alias(candidate, alias)
                    for candidate in candidate_names
                )
            ]
            if matched_alias_lengths:
                scored_models.append((max(matched_alias_lengths), model))

        if not scored_models:
            return None

        longest_match = max(score for score, _model in scored_models)
        best_models = {
            model["model_id"]: model
            for score, model in scored_models
            if score == longest_match
        }
        if len(best_models) != 1:
            return None
        return next(iter(best_models.values()))

    def get_client(self, device, hardware_info: dict, profile, settings):
        return PhomemoClient(device, hardware_info, profile, settings)
