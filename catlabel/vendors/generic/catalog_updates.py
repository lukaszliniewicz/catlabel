"""Apply the explicitly selected Luck A4 update to the immutable base catalog."""

from __future__ import annotations

import copy
from typing import Any, cast

from .catalog_snapshot import validate_snapshot

BASE_COMMIT = "f676917257b5d1f869e0f13beff03785258e2a2e"
LUCK_UPDATE_COMMIT = "76b3171bb956603277f7d97863d7e607d3de2e89"
LUCK_UPDATE_FILENAME = "luck_a4_updates.json"
ALLOWED_MODEL_KEYS = frozenset({"luck_apa41", "luck_apa49"})
BASE_PROFILE_KEYS = frozenset(
    {
        "luck_a40",
        "luck_a41_luckp",
        "luck_a42_luckp",
        "luck_a49h",
        "luck_a4_compressed_tattoo",
        "luck_a4_compressed_tattoo_96",
        "luck_a4_compressed_tattoo_96_dense",
        "luck_a80h_way1",
        "luck_apl86",
        "luck_apl86h",
        "luck_d80",
        "luck_d80h",
        "luck_lujiang_a4",
        "luck_lujiang_a4_dense",
        "luck_u8",
    }
)
ALLOWED_PROFILE_KEYS = BASE_PROFILE_KEYS | {"luck_apa41"}
ALLOWED_PRESET_KEYS = frozenset(
    {
        "blacktag_1616r",
        "blacktag_1648r",
        "blacktag_2496r",
        "tag_1616r",
        "tag_1648r",
        "tag_2496r",
        "tattoo_1616r",
        "tattoo_1648r",
        "tattoo_2496r",
        "luck_a4_folder_a4",
        "luck_a4_folder_a5",
        "luck_a4_folder_letter",
        "luck_a4_folder_legal",
        "luck_a4_folder_a4_300dpi",
        "luck_a4_folder_a5_300dpi",
        "luck_a4_folder_letter_300dpi",
        "luck_a4_folder_legal_300dpi",
        "luck_a4_roll_56mm",
        "luck_a4_roll_77mm",
        "luck_a4_roll_107mm",
        "luck_a4_roll_148mm",
        "luck_a4_roll_210mm",
        "luck_a4_roll_216mm",
        "luck_a4_roll_56mm_300dpi",
        "luck_a4_roll_77mm_300dpi",
        "luck_a4_roll_107mm_300dpi",
        "luck_a4_roll_148mm_300dpi",
        "luck_a4_roll_210mm_300dpi",
        "luck_a4_roll_216mm_300dpi",
    }
)
_UPDATE_KEYS = {
    "schema_version",
    "base_commit",
    "commit",
    "models",
    "profiles",
    "paper_presets",
}


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(
            f"Invalid Luck A4 updates {field}: expected an object with string keys"
        )
    entries = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in entries):
        raise ValueError(f"Invalid Luck A4 updates {field}: expected string keys")
    return cast(dict[str, Any], value)


def _records(value: object, field: str, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"Invalid Luck A4 updates {field}: expected a list")
    records: dict[str, dict[str, Any]] = {}
    for raw in cast(list[object], value):
        record = _object(raw, field)
        identifier = record.get(key)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"Invalid Luck A4 updates {field}: missing {key}")
        if identifier in records:
            raise ValueError(
                f"Invalid Luck A4 updates {field}: duplicate {identifier!r}"
            )
        records[identifier] = record
    return records


def _preset_keys(profile: dict[str, Any]) -> set[str]:
    raw = profile.get("paper_presets")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "Invalid Luck A4 updates profile paper_presets: expected nonempty string list"
        )
    keys: set[str] = set()
    for key in cast(list[object], raw):
        if not isinstance(key, str) or not key:
            raise ValueError(
                "Invalid Luck A4 updates profile paper_presets: expected nonempty strings"
            )
        keys.add(key)
    return keys


def _validate_pipeline(raw: object, field: str) -> None:
    pipeline = _object(raw, field)
    if pipeline.get("formats") != ["bw1"]:
        raise ValueError(
            f"Invalid Luck A4 updates {field}: only bw1 format is approved"
        )
    encoding = pipeline.get("encoding")
    if not isinstance(encoding, str) or encoding not in {
        "luck_normal_raw",
        "luck_normal_compressed",
    }:
        raise ValueError(
            f"Invalid Luck A4 updates {field}: unapproved Luck A4 encoding"
        )


def apply_luck_updates(bundle: object, updates: object) -> dict[str, Any]:
    """Validate and merge the fixed Luck A4 scope without mutating either input."""
    base = validate_snapshot(bundle)
    if base["source"]["commit"] != BASE_COMMIT:
        raise ValueError("Luck A4 updates require the pinned v0.8.1 base commit")
    overlay = _object(updates, "root")
    if set(overlay) != _UPDATE_KEYS:
        raise ValueError(
            "Invalid Luck A4 updates: unexpected or missing top-level keys"
        )
    if type(overlay["schema_version"]) is not int or overlay["schema_version"] != 1:
        raise ValueError("Invalid Luck A4 updates: expected schema_version 1")
    if overlay["base_commit"] != BASE_COMMIT or overlay["commit"] != LUCK_UPDATE_COMMIT:
        raise ValueError(
            "Invalid Luck A4 updates: commits do not match the selected pins"
        )

    models = _records(overlay["models"], "models", "model_key")
    profiles = _records(overlay["profiles"], "profiles", "profile_key")
    presets = _object(overlay["paper_presets"], "paper_presets")
    if frozenset(models) != ALLOWED_MODEL_KEYS:
        raise ValueError(
            "Invalid Luck A4 updates: expected only luck_apa41 and luck_apa49"
        )
    if frozenset(profiles) != ALLOWED_PROFILE_KEYS:
        raise ValueError(
            "Invalid Luck A4 updates: expected the 16 selected Luck A4 profiles"
        )

    base_catalogs = _object(base["catalogs"], "base catalogs")
    base_profiles = _records(
        base_catalogs["catalog_profiles.json"], "base profiles", "profile_key"
    )
    base_models = _records(
        base_catalogs["catalog_models.json"], "base models", "model_key"
    )
    if "luck_apa41" not in base_models or not set(base_profiles) >= BASE_PROFILE_KEYS:
        raise ValueError(
            "Luck A4 updates base is missing the selected original records"
        )
    for key in BASE_PROFILE_KEYS:
        if (
            _object(base_profiles[key].get("protocol_default"), "base protocol").get(
                "type"
            )
            != "luck_normal_a4"
        ):
            raise ValueError(
                f"Luck A4 updates base profile {key!r} is outside the approved protocol"
            )

    referenced_presets: set[str] = set()
    for key, profile in profiles.items():
        protocol = _object(profile.get("protocol_default"), f"{key}.protocol_default")
        expected_protocol = (
            base_profiles[key]["protocol_default"]
            if key in BASE_PROFILE_KEYS
            else {"type": "luck_normal_a4", "packets_type": "lujiang_a4"}
        )
        if protocol != expected_protocol:
            raise ValueError(f"Invalid Luck A4 updates {key}: unapproved protocol")
        _validate_pipeline(
            profile.get("default_image_pipeline"), f"{key}.default_image_pipeline"
        )
        referenced_presets.update(_preset_keys(profile))
    if set(presets) != referenced_presets or frozenset(presets) != ALLOWED_PRESET_KEYS:
        raise ValueError(
            "Invalid Luck A4 updates: presets must match selected profile references exactly"
        )
    base_presets = _object(
        base_catalogs["catalog_paper_presets.json"], "base paper presets"
    )
    if any(
        key in base_presets and base_presets[key] != preset
        for key, preset in presets.items()
    ):
        raise ValueError(
            "Invalid Luck A4 updates: original paper presets must stay unchanged"
        )
    for key, model in models.items():
        profile_key = model.get("profile_key")
        if not isinstance(profile_key, str) or profile_key not in ALLOWED_PROFILE_KEYS:
            raise ValueError(
                f"Invalid Luck A4 updates {key}: unapproved profile reference"
            )
        if "protocol_override" in model:
            protocol = _object(model["protocol_override"], f"{key}.protocol_override")
            # Neither selected source model overrides its profile recipe.
            if protocol:
                raise ValueError(
                    f"Invalid Luck A4 updates {key}: unapproved protocol override"
                )
        if "image_pipeline_override" in model:
            _validate_pipeline(
                model["image_pipeline_override"], f"{key}.image_pipeline_override"
            )

    merged = copy.deepcopy(base)
    catalogs = _object(merged["catalogs"], "catalogs")
    catalogs["catalog_models.json"] = [
        models.pop(key, item) for key, item in base_models.items()
    ]
    catalogs["catalog_models.json"].extend(models.values())
    catalogs["catalog_profiles.json"] = [
        profiles.pop(key, item) for key, item in base_profiles.items()
    ]
    catalogs["catalog_profiles.json"].extend(profiles.values())
    catalogs["catalog_paper_presets.json"].update(copy.deepcopy(presets))
    # Deep-copy replacements too: returned mutable JSON must never alias the overlay.
    return validate_snapshot(copy.deepcopy(merged))
