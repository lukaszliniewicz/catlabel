"""Validation helpers for the generic printer catalog snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, NoReturn, cast

UPSTREAM_REPOSITORY = "https://github.com/Dejniel/TiMini-Print"
UPSTREAM_LICENSE = "Apache-2.0"
CATALOG_FILENAMES = (
    "catalog_models.json",
    "catalog_unsupported.json",
    "catalog_profiles.json",
    "catalog_paper_presets.json",
    "catalog_origin_apps.json",
)
MODERN_CATALOG_FILENAMES = tuple(
    name for name in CATALOG_FILENAMES if name != "catalog_unsupported.json"
)
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_WHITESPACE_MODES = {"remove", "trim", "preserve"}
_ROTATIONS = {0, 90, 180, 270}


def _fail(path: str, message: str) -> NoReturn:
    raise ValueError(f"Invalid catalog snapshot at {path}: {message}")


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "expected an object")
    return cast(dict[str, Any], value)


def _list(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, "expected a list")
    return cast(list[Any], value)


def _exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(repr(key) for key in actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing keys {missing!r}")
        if unexpected:
            details.append(f"unexpected keys {unexpected!r}")
        _fail(path, "; ".join(details))


def _nonempty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "expected a non-empty string")
    return value


def _positive_integer(value: object, path: str) -> None:
    if type(value) is not int or value < 1:
        _fail(path, "expected a positive integer")


def _string_list(value: object, path: str) -> list[str]:
    result: list[str] = []
    for index, item in enumerate(_list(value, path)):
        result.append(_nonempty_string(item, f"{path}[{index}]"))
    return result


def _validate_detections(
    entry: dict[str, Any], path: str, model_key: str, *, modern: bool = False
) -> None:
    detections = _list(entry.get("detections"), f"{path}.detections")
    if not detections:
        _fail(f"{path}.detections", "expected a non-empty list")

    for index, raw_rule in enumerate(detections):
        rule_path = f"{path}.detections[{index}]"
        rule = _mapping(raw_rule, rule_path)
        is_legacy_nested = "name" in rule or "detection" in rule

        if is_legacy_nested:
            _nonempty_string(rule.get("name") or model_key, f"{rule_path}.name")
            detection = _mapping(rule.get("detection"), f"{rule_path}.detection")
        else:
            detection = rule

        exact_names = _string_list(
            detection.get("exact_names", []),
            f"{rule_path}.exact_names",
        )
        prefixes = _string_list(
            detection.get("prefixes", []),
            f"{rule_path}.prefixes",
        )
        _string_list(
            detection.get("mac_suffixes", []),
            f"{rule_path}.mac_suffixes",
        )

        substrings: list[str] = []
        if modern:
            if is_legacy_nested and set(rule) - {
                "name",
                "detection",
                "marketing_names",
            }:
                _fail(rule_path, "unknown nested detection fields")
            allowed = {
                "exact_names",
                "prefixes",
                "mac_suffixes",
                "marketing_names",
                "substrings",
                "name_pattern",
                "manufacturer_data_suffixes",
                "manufacturer_data_lengths",
            }
            if set(detection) - allowed:
                _fail(
                    rule_path,
                    f"unknown detection fields {sorted(set(detection) - allowed)!r}",
                )
            substrings = _string_list(
                detection.get("substrings", []), f"{rule_path}.substrings"
            )
            pattern = detection.get("name_pattern")
            if "name_pattern" in detection:
                pattern = _nonempty_string(pattern, f"{rule_path}.name_pattern")
                try:
                    re.compile(pattern)
                except re.error as error:
                    _fail(f"{rule_path}.name_pattern", str(error))
            if substrings and pattern is None:
                _fail(
                    rule_path,
                    "substring detection requires a constraining name_pattern",
                )
            suffixes = _string_list(
                detection.get("manufacturer_data_suffixes", []),
                f"{rule_path}.manufacturer_data_suffixes",
            )
            for suffix in suffixes:
                if not re.fullmatch(r"(?:[0-9a-fA-F]{2})+", suffix):
                    _fail(
                        rule_path,
                        "manufacturer suffixes must be even-length hexadecimal strings",
                    )
            lengths = _list(
                detection.get("manufacturer_data_lengths", []),
                f"{rule_path}.manufacturer_data_lengths",
            )
            for length in lengths:
                _positive_integer(length, f"{rule_path}.manufacturer_data_lengths")
            if (
                bool(suffixes) != bool(lengths)
                or ("manufacturer_data_suffixes" in detection and not suffixes)
                or ("manufacturer_data_lengths" in detection and not lengths)
            ):
                _fail(
                    rule_path,
                    "manufacturer detection requires both suffixes and lengths",
                )

        if not exact_names and not prefixes and not substrings and is_legacy_nested:
            fallback = rule.get("name") or model_key
            _nonempty_string(fallback, f"{rule_path}.name")
            continue
        if not exact_names and not prefixes and not substrings:
            _fail(rule_path, "requires at least one exact name or prefix")


def _validate_model_entries(
    value: object,
    path: str,
    origin_ids: set[str],
    *,
    modern: bool = False,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, raw_entry in enumerate(_list(value, path)):
        entry_path = f"{path}[{index}]"
        entry = _mapping(raw_entry, entry_path)
        model_key = _nonempty_string(entry.get("model_key"), f"{entry_path}.model_key")
        if model_key in identifiers:
            _fail(f"{entry_path}.model_key", f"duplicate model key {model_key!r}")
        identifiers.add(model_key)

        if "whitespace_mode" in entry:
            whitespace_mode = entry["whitespace_mode"]
            if (
                not isinstance(whitespace_mode, str)
                or whitespace_mode not in _WHITESPACE_MODES
            ):
                _fail(
                    f"{entry_path}.whitespace_mode",
                    f"expected one of {sorted(_WHITESPACE_MODES)!r}",
                )

        for origin_field in ("origin_app_packages", "origin_ids"):
            if origin_field not in entry:
                continue
            origins = _string_list(entry[origin_field], f"{entry_path}.{origin_field}")
            for origin_index, origin in enumerate(origins):
                if origin not in origin_ids:
                    _fail(
                        f"{entry_path}.{origin_field}[{origin_index}]",
                        f"unknown origin {origin!r}",
                    )

        _validate_detections(entry, entry_path, model_key, modern=modern)
        entries.append(entry)
    return entries


def _validate_profiles(
    value: object, preset_ids: set[str]
) -> dict[str, dict[str, Any]]:
    path = "catalogs.catalog_profiles.json"
    profiles: dict[str, dict[str, Any]] = {}
    for index, raw_profile in enumerate(_list(value, path)):
        profile_path = f"{path}[{index}]"
        profile = _mapping(raw_profile, profile_path)
        profile_key = _nonempty_string(
            profile.get("profile_key"), f"{profile_path}.profile_key"
        )
        if profile_key in profiles:
            _fail(
                f"{profile_path}.profile_key", f"duplicate profile key {profile_key!r}"
            )

        _positive_integer(profile.get("size"), f"{profile_path}.size")
        _positive_integer(profile.get("dev_dpi"), f"{profile_path}.dev_dpi")

        paper_presets = _string_list(
            profile.get("paper_presets"),
            f"{profile_path}.paper_presets",
        )
        if not paper_presets:
            _fail(f"{profile_path}.paper_presets", "expected at least one paper preset")
        for preset_index, preset_key in enumerate(paper_presets):
            if preset_key not in preset_ids:
                _fail(
                    f"{profile_path}.paper_presets[{preset_index}]",
                    f"unknown paper preset {preset_key!r}",
                )

        if "runtime_presets" in profile:
            runtime_presets = _list(
                profile["runtime_presets"],
                f"{profile_path}.runtime_presets",
            )
            for preset_index, raw_preset in enumerate(runtime_presets):
                runtime_preset = _mapping(
                    raw_preset,
                    f"{profile_path}.runtime_presets[{preset_index}]",
                )
                _nonempty_string(
                    runtime_preset.get("key"),
                    f"{profile_path}.runtime_presets[{preset_index}].key",
                )

        profiles[profile_key] = profile
    return profiles


def _validate_paper_presets(value: object, *, modern: bool = False) -> set[str]:
    path = "catalogs.catalog_paper_presets.json"
    presets = _mapping(value, path)
    preset_ids: set[str] = set()
    for key, raw_preset in presets.items():
        preset_key = _nonempty_string(key, f"{path} key")
        preset = _mapping(raw_preset, f"{path}.{preset_key}")
        _positive_integer(
            preset.get("paper_width_px"), f"{path}.{preset_key}.paper_width_px"
        )
        _positive_integer(
            preset.get("render_width_px"), f"{path}.{preset_key}.render_width_px"
        )
        for optional_dimension in ("render_height_px", "max_height_px"):
            dimension = preset.get(optional_dimension)
            if dimension is not None:
                _positive_integer(
                    dimension, f"{path}.{preset_key}.{optional_dimension}"
                )
        if "rotation_degrees" in preset:
            rotation = preset["rotation_degrees"]
            if type(rotation) is not int or rotation not in _ROTATIONS:
                _fail(
                    f"{path}.{preset_key}.rotation_degrees",
                    f"expected one of {sorted(_ROTATIONS)!r}",
                )
        if modern:
            allowed = {
                "label",
                "paper_mode",
                "paper_width_px",
                "render_width_px",
                "left_padding_px",
                "render_height_px",
                "max_height_px",
                "rotation_degrees",
                "top_padding_px",
                "raster_height_px",
            }
            if set(preset) - allowed:
                _fail(f"{path}.{preset_key}", "unknown paper geometry fields")
            for dimension in ("left_padding_px", "top_padding_px"):
                padding = preset.get(dimension, 0)
                if type(padding) is not int or padding < 0:
                    _fail(
                        f"{path}.{preset_key}.{dimension}",
                        "expected a nonnegative integer",
                    )
            raster_height = preset.get("raster_height_px")
            if "raster_height_px" in preset:
                _positive_integer(
                    raster_height, f"{path}.{preset_key}.raster_height_px"
                )
            if (
                preset["render_width_px"] + preset.get("left_padding_px", 0)
                > preset["paper_width_px"]
            ):
                _fail(
                    f"{path}.{preset_key}",
                    "render width plus padding exceeds paper width",
                )
            top = preset.get("top_padding_px", 0)
            height = preset.get("render_height_px")
            if top and raster_height is None:
                _fail(
                    f"{path}.{preset_key}", "top padding requires a fixed raster height"
                )
            if (
                raster_height is not None
                and height is not None
                and height + top > raster_height
            ):
                _fail(
                    f"{path}.{preset_key}",
                    "render height plus padding exceeds raster height",
                )
            maximum = preset.get("max_height_px")
            if maximum is not None and height is not None and height + top > maximum:
                _fail(
                    f"{path}.{preset_key}",
                    "render height plus padding exceeds maximum height",
                )
            if (
                maximum is not None
                and raster_height is not None
                and raster_height > maximum
            ):
                _fail(f"{path}.{preset_key}", "raster height exceeds maximum height")
        preset_ids.add(preset_key)
    return preset_ids


def _validate_origins(value: object) -> set[str]:
    path = "catalogs.catalog_origin_apps.json"
    origins = _mapping(value, path)
    result: set[str] = set()
    for origin_id, app_name in origins.items():
        result.add(_nonempty_string(origin_id, f"{path} key"))
        _nonempty_string(app_name, f"{path}.{origin_id}")
    return result


def _validate_source(value: object, filenames: set[str]) -> dict[str, Any]:
    source = _mapping(value, "source")
    _exact_keys(
        source, {"repository", "revision", "commit", "license", "files"}, "source"
    )
    repository = _nonempty_string(source["repository"], "source.repository")
    normalized_repository = repository.rstrip("/").removesuffix(".git").casefold()
    if normalized_repository != UPSTREAM_REPOSITORY.casefold():
        _fail(
            "source.repository",
            f"expected the known TiMini-Print URL {UPSTREAM_REPOSITORY!r}",
        )
    _nonempty_string(source["revision"], "source.revision")
    commit = _nonempty_string(source["commit"], "source.commit")
    if not _COMMIT_RE.fullmatch(commit):
        _fail("source.commit", "expected a 40-character hexadecimal Git commit")
    if source["license"] != UPSTREAM_LICENSE:
        _fail("source.license", f"expected {UPSTREAM_LICENSE!r}")

    source_files = _mapping(source["files"], "source.files")
    _exact_keys(source_files, filenames, "source.files")
    for destination, upstream_path in source_files.items():
        _nonempty_string(upstream_path, f"source.files.{destination}")

    return source


def validate_snapshot(snapshot: object) -> dict[str, Any]:
    """Validate a catalog bundle and return it without normalizing source data."""

    bundle = _mapping(snapshot, "root")
    if type(bundle.get("schema_version")) is int and bundle["schema_version"] == 2:
        return _validate_modern_snapshot(bundle)
    _exact_keys(bundle, {"schema_version", "source", "catalogs"}, "root")
    if type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1:
        _fail("schema_version", "expected integer schema version 1")

    _validate_source(bundle["source"], set(CATALOG_FILENAMES))

    catalogs = _mapping(bundle["catalogs"], "catalogs")
    _exact_keys(catalogs, set(CATALOG_FILENAMES), "catalogs")
    origin_ids = _validate_origins(catalogs["catalog_origin_apps.json"])
    preset_ids = _validate_paper_presets(catalogs["catalog_paper_presets.json"])
    profiles = _validate_profiles(catalogs["catalog_profiles.json"], preset_ids)
    models = _validate_model_entries(
        catalogs["catalog_models.json"],
        "catalogs.catalog_models.json",
        origin_ids,
    )
    unsupported = _validate_model_entries(
        catalogs["catalog_unsupported.json"],
        "catalogs.catalog_unsupported.json",
        origin_ids,
    )

    model_ids = {entry["model_key"] for entry in models}
    unsupported_ids = {entry["model_key"] for entry in unsupported}
    overlap = model_ids & unsupported_ids
    if overlap:
        _fail(
            "catalogs",
            f"supported and unsupported model keys overlap: {sorted(overlap)!r}",
        )

    _validate_profile_references(models, profiles)

    return bundle


def load_snapshot(path: Path) -> dict[str, Any]:
    """Read and validate a snapshot JSON file."""

    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid catalog snapshot JSON at {path}: {error}") from error
    return validate_snapshot(snapshot)


def policy_sha256(models: object, origins: object) -> str:
    """Digest retained veto records independently of their new upstream bundle."""
    payload = json.dumps(
        {"models": models, "origins": origins},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def validate_detection_policy(value: object) -> dict[str, Any]:
    policy = _mapping(value, "detection_policy")
    _exact_keys(policy, {"source", "models", "origins", "sha256"}, "detection_policy")
    _validate_source(policy["source"], {"catalog_unsupported.json"})
    origins = _validate_origins(policy["origins"])
    _validate_model_entries(
        policy["models"], "detection_policy.models", origins, modern=True
    )
    if policy["sha256"] != policy_sha256(policy["models"], policy["origins"]):
        _fail("detection_policy.sha256", "does not match retained models and origins")
    return policy


def _validate_profile_references(
    models: list[dict[str, Any]], profiles: dict[str, dict[str, Any]]
) -> None:
    for index, model in enumerate(models):
        model_path = f"catalogs.catalog_models.json[{index}]"
        profile_key = _nonempty_string(
            model.get("profile_key"), f"{model_path}.profile_key"
        )
        profile = profiles.get(profile_key)
        if profile is None:
            _fail(f"{model_path}.profile_key", f"unknown profile {profile_key!r}")
        runtime_key = model.get("profile_runtime_preset_key")
        if runtime_key is not None:
            runtime_key = _nonempty_string(
                runtime_key, f"{model_path}.profile_runtime_preset_key"
            )
            runtime_presets = profile.get("runtime_presets", [])
            runtime_keys = {preset["key"] for preset in runtime_presets}
            if runtime_key not in runtime_keys:
                _fail(
                    f"{model_path}.profile_runtime_preset_key",
                    f"unknown runtime preset {runtime_key!r} for profile {profile_key!r}",
                )


def _validate_modern_snapshot(bundle: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        bundle, {"schema_version", "source", "catalogs", "detection_policy"}, "root"
    )
    _validate_source(bundle["source"], set(MODERN_CATALOG_FILENAMES))
    catalogs = _mapping(bundle["catalogs"], "catalogs")
    _exact_keys(catalogs, set(MODERN_CATALOG_FILENAMES), "catalogs")
    origins = _validate_origins(catalogs["catalog_origin_apps.json"])
    presets = _validate_paper_presets(
        catalogs["catalog_paper_presets.json"], modern=True
    )
    profiles = _validate_profiles(catalogs["catalog_profiles.json"], presets)
    models = _validate_model_entries(
        catalogs["catalog_models.json"],
        "catalogs.catalog_models.json",
        origins,
        modern=True,
    )
    _validate_profile_references(models, profiles)
    validate_detection_policy(bundle["detection_policy"])
    return bundle
