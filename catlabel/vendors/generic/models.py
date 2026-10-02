from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

from ...protocol.families import get_protocol_definition
from ...protocol.family import ProtocolFamily
from ...protocol.types import ImageEncoding, ImagePipelineConfig
from ...raster import PixelFormat
from .catalog_snapshot import load_snapshot

DATA_DIR = Path(__file__).resolve().parent / "data"
MODELS_PATH = DATA_DIR / "catalog_models.json"
UNSUPPORTED_PATH = DATA_DIR / "catalog_unsupported.json"
PROFILES_PATH = DATA_DIR / "catalog_profiles.json"
PAPER_PRESETS_PATH = DATA_DIR / "catalog_paper_presets.json"
SOURCE_PATH = DATA_DIR / "catalog_source.json"

_NON_GENERIC_FAMILIES = {"niimbot", "phomemo_esc"}
_FAMILY_ALIASES = {
    "tiny": "legacy",
    "tiny_prefixed": "legacy_prefixed",
}
_ENCODING_ALIASES = {
    "tiny_raw": "legacy_raw",
    "tiny_rle": "legacy_rle",
}
_MAC_ADDRESS_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


class WhitespaceMode(StrEnum):
    REMOVE = "remove"
    TRIM = "trim"
    PRESERVE = "preserve"


def _normalized_name(
    value: str,
    *,
    casefold: bool = False,
    whitespace_mode: WhitespaceMode = WhitespaceMode.REMOVE,
) -> str:
    if whitespace_mode is WhitespaceMode.PRESERVE:
        normalized = value
    elif whitespace_mode is WhitespaceMode.TRIM:
        normalized = value.strip()
    else:
        normalized = re.sub(r"\s+", "", value)
    return normalized.casefold() if casefold else normalized


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    """Narrow heterogeneous JSON objects at the parser boundary."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Catalog {field_name} must be an object with string keys")
    return value


def _optional_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    return {} if value is None else _mapping(value, field_name)


def _integer_tiers(value: object, field_name: str) -> dict[str, int]:
    tiers = _optional_mapping(value, field_name)
    result: dict[str, int] = {}
    for key, raw_value in tiers.items():
        if type(raw_value) is not int:
            raise ValueError(f"Catalog {field_name}.{key} must be an integer")
        result[key] = raw_value
    return result


def _entries(value: object, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"Catalog {field_name} must be a list of objects")
    return tuple(_mapping(item, field_name) for item in value)


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise ValueError(f"Catalog {field_name} must be a list of strings")
    return tuple(value)


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"Catalog {field_name} must be a string")
    return value


def _normalized_mac(value: str | None) -> str:
    return re.sub(r"[^0-9A-F]", "", str(value or "").upper())


def _catalog_family(value: object) -> ProtocolFamily:
    normalized = _FAMILY_ALIASES.get(str(value or "tiny"), str(value or "tiny"))
    return ProtocolFamily.from_value(normalized)


def _catalog_encoding(value: object) -> ImageEncoding:
    normalized = _ENCODING_ALIASES.get(str(value), str(value))
    return ImageEncoding(normalized)


def _family_default_pipeline(family: ProtocolFamily) -> ImagePipelineConfig:
    return get_protocol_definition(family).behavior.default_image_pipeline


def _normalize_legacy_toprint_profile(
    profile: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Keep old source snapshots usable after separating their ToPrint dialects."""
    migrations = {
        "toprint_tspl_p1": ("eleph_tspl", "toprint_tspl"),
        "toprint_hprt_esc_zl1": ("eleph_hprt_esc", "toprint_hprt_esc"),
    }
    migration = migrations.get(str(profile.get("profile_key", "")))
    if migration is None:
        return profile
    old_family, new_family = migration
    protocol = _mapping(profile["protocol_default"], "default protocol")
    if protocol.get("type") != old_family:
        return profile
    normalized = dict(profile)
    normalized["protocol_default"] = {**protocol, "type": new_family}
    pipeline = _optional_mapping(
        profile.get("default_image_pipeline"), "image pipeline"
    )
    old_encoding = (
        "eleph_tspl_bitmap" if old_family == "eleph_tspl" else "eleph_hprt_esc_raster"
    )
    if pipeline.get("encoding") == old_encoding:
        new_encoding = (
            "toprint_tspl_bitmap"
            if new_family == "toprint_tspl"
            else "toprint_hprt_esc_raster"
        )
        normalized["default_image_pipeline"] = {**pipeline, "encoding": new_encoding}
    return normalized


def _pipeline_from_entry(
    entry: Mapping[str, Any] | None,
    family: ProtocolFamily,
) -> ImagePipelineConfig:
    if not entry:
        return _family_default_pipeline(family)
    formats = tuple(
        PixelFormat(item) for item in _strings(entry.get("formats", ()), "formats")
    )
    encoding_value = entry.get("encoding")
    default = _family_default_pipeline(family)
    return ImagePipelineConfig(
        formats=formats or default.formats,
        encoding=default.encoding
        if encoding_value is None
        else _catalog_encoding(encoding_value),
    )


def _middle(tiers: Mapping[str, int] | None, default: int) -> int:
    if not tiers:
        return default
    for key in ("middle", "low", "high"):
        if tiers.get(key) is not None:
            return int(tiers[key])
    return default


def _tier(tiers: Mapping[str, int] | None, key: str, default: int) -> int:
    if not tiers:
        return default
    value = tiers.get(key)
    return default if value is None else int(value)


@dataclass(frozen=True)
class PaperPreset:
    key: str
    label: str
    paper_width_px: int
    render_width_px: int
    left_padding_px: int = 0
    paper_mode: str | None = None
    max_height_px: int | None = None
    render_height_px: int | None = None
    rotation_degrees: int = 0


@dataclass(frozen=True)
class DetectionRule:
    display_name: str
    exact_names: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    mac_suffixes: tuple[str, ...] = ()
    whitespace_mode: WhitespaceMode = WhitespaceMode.REMOVE

    def match_score(
        self,
        name: str,
        address: str | None,
        *,
        casefold: bool,
    ) -> tuple[int, int, int, int, int] | None:
        candidate = _normalized_name(
            name, casefold=casefold, whitespace_mode=self.whitespace_mode
        )
        if not candidate:
            return None

        mac = _normalized_mac(address)
        suffixes = tuple(_normalized_mac(value) for value in self.mac_suffixes)
        if suffixes:
            if not address or not _MAC_ADDRESS_RE.match(str(address).strip()):
                return None
            if not mac or not any(mac.endswith(value) for value in suffixes):
                return None

        best: tuple[int, int, int, int, int] | None = None
        for value in self.exact_names:
            normalized = _normalized_name(
                value, casefold=casefold, whitespace_mode=self.whitespace_mode
            )
            if candidate == normalized:
                score = _detection_specificity(
                    value,
                    exact=True,
                    has_mac=bool(suffixes),
                    whitespace_mode=self.whitespace_mode,
                )
                best = max(best or score, score)
        for value in self.prefixes:
            normalized = _normalized_name(
                value, casefold=casefold, whitespace_mode=self.whitespace_mode
            )
            if normalized and candidate.startswith(normalized):
                score = _detection_specificity(
                    value,
                    exact=False,
                    has_mac=bool(suffixes),
                    whitespace_mode=self.whitespace_mode,
                )
                best = max(best or score, score)
        return best


def _detection_specificity(
    trigger: str,
    *,
    exact: bool,
    has_mac: bool,
    whitespace_mode: WhitespaceMode = WhitespaceMode.REMOVE,
) -> tuple[int, int, int, int, int]:
    normalized = _normalized_name(trigger, whitespace_mode=whitespace_mode)
    trigger_length = (
        len(normalized[:-1]) if normalized.endswith(("-", "_")) else len(normalized)
    )
    return (
        trigger_length,
        int(has_mac),
        int(exact),
        len(normalized),
        sum(1 for char in normalized if char.isupper()),
    )


class PrinterModelMatchSource(Enum):
    HEAD_NAME = "head_name"
    MODEL_NO = "model_no"
    ALIAS = "alias"


class PrinterModelAliasKind(Enum):
    HEAD_NAME = "head_name"
    MAC = "mac"


@dataclass(frozen=True)
class PrinterModel:
    model_no: str
    profile_key: str
    head_name: str
    marketing_name: str | None
    detection_rules: tuple[DetectionRule, ...]
    origin_app_packages: tuple[str, ...]
    protocol_family: ProtocolFamily
    protocol_variant: str | None
    image_pipeline: ImagePipelineConfig
    paper_presets: tuple[PaperPreset, ...]
    size: int
    paper_size: int
    print_size: int
    one_length: int
    dev_dpi: int
    img_print_speed: int
    text_print_speed: int
    img_mtu: int
    interval_ms: int
    thin_energy: int
    moderation_energy: int
    deepen_energy: int
    text_energy: int
    has_id: bool
    use_spp: bool
    can_print_label: bool
    label_value: str
    back_paper_num: int
    post_print_feed_count: int
    can_change_mtu: bool = False
    ble_mtu_request: int | None = None
    a4xii: bool = False
    add_mor_pix: bool | None = None
    supported_paper_modes: tuple[str, ...] = ()
    runtime_variant: str | None = None
    runtime_density_profile_key: str | None = None
    runtime_density: Mapping[str, object] | None = None
    profile_density: Mapping[str, object] | None = None
    runtime_capabilities: Mapping[str, object] = field(default_factory=dict)
    testing: bool = False
    testing_note: str | None = None
    vendor: str = "generic"
    media_type: str = "continuous"
    min_density: int | None = None
    default_density: int | None = None
    max_density: int | None = None
    max_speed: int | None = None
    min_energy: int | None = None
    max_energy: int | None = None
    model: int = 0
    paper_num: int = 0
    marketing_names: tuple[str, ...] = ()
    origin_ids: tuple[str, ...] = ()
    detection_ambiguity_group: str | None = None

    @property
    def width(self) -> int:
        return self.print_size

    def paper_preset(self, key: str | None = None) -> PaperPreset:
        if not self.paper_presets:
            raise ValueError(f"Printer model {self.model_no!r} has no paper presets")
        if key is None:
            return self.paper_presets[0]
        for preset in self.paper_presets:
            if preset.key == key:
                return preset
        raise ValueError(
            f"Printer model {self.model_no!r} does not support paper preset {key!r}"
        )


@dataclass(frozen=True)
class PrinterModelMatch:
    model: PrinterModel
    source: PrinterModelMatchSource
    alias_kind: PrinterModelAliasKind | None = None
    protocol_family: ProtocolFamily = ProtocolFamily.LEGACY
    protocol_variant: str | None = None
    image_pipeline: ImagePipelineConfig = field(
        default_factory=lambda: _family_default_pipeline(ProtocolFamily.LEGACY)
    )
    testing: bool = False
    testing_note: str | None = None
    conflict_models: tuple[str, ...] = ()

    @property
    def used_alias(self) -> bool:
        return self.source is PrinterModelMatchSource.ALIAS

    @property
    def has_brand_conflict(self) -> bool:
        return bool(self.conflict_models)


@dataclass(frozen=True)
class _UnsupportedModel:
    model_key: str
    detection_rules: tuple[DetectionRule, ...]
    detection_ambiguity_group: str | None = None


class PrinterModelRegistry:
    _cache: dict[tuple[Path, ...], PrinterModelRegistry] = {}

    def __init__(
        self,
        models: Iterable[PrinterModel],
        unsupported: Iterable[_UnsupportedModel],
        deferred: Iterable[_UnsupportedModel] = (),
        *,
        source_metadata: Mapping[str, object],
    ) -> None:
        self._models = tuple(models)
        self._source_unsupported = tuple(unsupported)
        self._deferred = tuple(deferred)
        self.source_metadata = dict(source_metadata)
        self._by_key = {model.model_no: model for model in self._models}

    @classmethod
    def load(
        cls,
        models_path: Path = MODELS_PATH,
        profiles_path: Path = PROFILES_PATH,
        paper_presets_path: Path = PAPER_PRESETS_PATH,
        unsupported_path: Path = UNSUPPORTED_PATH,
    ) -> PrinterModelRegistry:
        paths = (models_path, profiles_path, paper_presets_path, unsupported_path)
        default_paths = (
            MODELS_PATH,
            PROFILES_PATH,
            PAPER_PRESETS_PATH,
            UNSUPPORTED_PATH,
        )
        snapshot_path = DATA_DIR / "catalog_snapshot.json"
        use_snapshot = (
            all(
                path.resolve() == default.resolve()
                for path, default in zip(paths, default_paths, strict=True)
            )
            and snapshot_path.exists()
        )
        key = tuple(
            path.resolve() for path in ((snapshot_path,) if use_snapshot else paths)
        )
        cached = cls._cache.get(key)
        if cached is not None:
            return cached

        if use_snapshot:
            bundle = load_snapshot(snapshot_path)
            catalogs = _mapping(bundle["catalogs"], "catalogs")
            profiles_raw = catalogs["catalog_profiles.json"]
            presets_raw = catalogs["catalog_paper_presets.json"]
            models_raw = catalogs["catalog_models.json"]
            unsupported_raw = catalogs["catalog_unsupported.json"]
            source_metadata = _mapping(bundle["source"], "source")
        else:
            profiles_raw = json.loads(profiles_path.read_text(encoding="utf-8"))
            presets_raw = json.loads(paper_presets_path.read_text(encoding="utf-8"))
            models_raw = json.loads(models_path.read_text(encoding="utf-8"))
            unsupported_raw = json.loads(unsupported_path.read_text(encoding="utf-8"))
            source_metadata = _mapping(
                json.loads(SOURCE_PATH.read_text(encoding="utf-8")), "source"
            )

        profiles = {
            str(item["profile_key"]): _normalize_legacy_toprint_profile(item)
            for item in _entries(profiles_raw, "profiles")
        }
        presets = {
            name: cls._parse_paper_preset(name, _mapping(value, "paper preset"))
            for name, value in _mapping(presets_raw, "paper presets").items()
        }

        models: list[PrinterModel] = []
        deferred: list[_UnsupportedModel] = []
        for item in _entries(models_raw, "models"):
            profile = profiles.get(str(item.get("profile_key", "")))
            if profile is None:
                raise ValueError(
                    f"Catalog model {item.get('model_key')!r} references missing profile "
                    f"{item.get('profile_key')!r}"
                )
            protocol_override = _optional_mapping(
                item.get("protocol_override"), "protocol override"
            )
            profile_protocol = _mapping(profile["protocol_default"], "default protocol")
            family_name = str(protocol_override.get("type") or profile_protocol["type"])
            if family_name in _NON_GENERIC_FAMILIES:
                deferred.append(cls._unavailable_model(item))
                continue
            try:
                family = _catalog_family(family_name)
                behavior = get_protocol_definition(family).behavior
            except (ValueError, KeyError):
                deferred.append(cls._unavailable_model(item))
                continue
            if not behavior.implemented:
                deferred.append(cls._unavailable_model(item))
                continue
            model = cls._parse_model(item, profile, presets, family)
            models.append(model)

        unsupported = [
            cls._unavailable_model(item)
            for item in _entries(unsupported_raw, "unsupported models")
        ]
        registry = cls(
            models,
            unsupported,
            deferred,
            source_metadata=source_metadata,
        )
        cls._cache[key] = registry
        return registry

    @staticmethod
    def _parse_paper_preset(key: str, raw: Mapping[str, Any]) -> PaperPreset:
        return PaperPreset(
            key=key,
            label=str(raw.get("label") or key.replace("_", " ").title()),
            paper_width_px=int(raw["paper_width_px"]),
            render_width_px=int(raw["render_width_px"]),
            left_padding_px=int(raw.get("left_padding_px") or 0),
            paper_mode=None
            if raw.get("paper_mode") in (None, "")
            else str(raw["paper_mode"]),
            max_height_px=None
            if raw.get("max_height_px") in (None, "")
            else int(raw["max_height_px"]),
            render_height_px=None
            if raw.get("render_height_px") in (None, "")
            else int(raw["render_height_px"]),
            rotation_degrees=int(raw.get("rotation_degrees") or 0),
        )

    @classmethod
    def _unavailable_model(cls, item: Mapping[str, Any]) -> _UnsupportedModel:
        return _UnsupportedModel(
            model_key=str(item["model_key"]),
            detection_rules=cls._parse_detection_rules(item),
            detection_ambiguity_group=_optional_string(
                item.get("detection_ambiguity_group"), "detection ambiguity group"
            ),
        )

    @staticmethod
    def _parse_detection_rules(item: Mapping[str, Any]) -> tuple[DetectionRule, ...]:
        rules: list[DetectionRule] = []
        whitespace_mode = WhitespaceMode(item.get("whitespace_mode", "remove"))
        for entry in _entries(item.get("detections", ()), "detections"):
            nested = "detection" in entry or "name" in entry
            detection = (
                _optional_mapping(entry.get("detection"), "detection")
                if nested
                else entry
            )
            exact_names = _strings(detection.get("exact_names", ()), "exact names")
            prefixes = _strings(detection.get("prefixes", ()), "prefixes")
            marketing_names = _strings(
                entry.get("marketing_names", ()), "marketing names"
            )
            if nested:
                display_name = str(entry.get("name") or item.get("model_key") or "")
            elif marketing_names:
                display_name = marketing_names[0]
            elif exact_names or prefixes:
                public_name = (exact_names or prefixes)[0].strip()
                display_name = (
                    public_name[:-1]
                    if public_name.endswith(("-", "_"))
                    else public_name
                )
            else:
                display_name = str(item.get("model_key") or "")
            if nested and not exact_names and not prefixes and display_name:
                exact_names = (display_name,)
            rules.append(
                DetectionRule(
                    display_name=display_name,
                    exact_names=exact_names,
                    prefixes=prefixes,
                    mac_suffixes=_strings(
                        detection.get("mac_suffixes", ()), "MAC suffixes"
                    ),
                    whitespace_mode=whitespace_mode,
                )
            )
        return tuple(rules)

    @classmethod
    def _parse_model(
        cls,
        item: Mapping[str, Any],
        profile: Mapping[str, Any],
        presets: Mapping[str, PaperPreset],
        family: ProtocolFamily,
    ) -> PrinterModel:
        profile_protocol = _optional_mapping(
            profile.get("protocol_default"), "default protocol"
        )
        protocol_override = _optional_mapping(
            item.get("protocol_override"), "protocol override"
        )
        protocol_variant = protocol_override.get(
            "packets_type"
        ) or protocol_override.get("variant")
        if protocol_variant is None:
            protocol_variant = profile_protocol.get(
                "packets_type"
            ) or profile_protocol.get("variant")

        pipeline_override = item.get("image_pipeline_override")
        configured_pipeline = (
            pipeline_override
            if pipeline_override is not None
            else profile.get("default_image_pipeline")
        )
        if configured_pipeline is not None:
            configured_pipeline = _mapping(configured_pipeline, "image pipeline")
        profile_family = _catalog_family(profile_protocol.get("type"))
        if family != profile_family and not item.get("image_pipeline_override"):
            image_pipeline = _family_default_pipeline(family)
        else:
            image_pipeline = _pipeline_from_entry(
                None
                if configured_pipeline is None
                else _mapping(configured_pipeline, "image pipeline"),
                family,
            )

        paper_presets = tuple(
            presets[str(key)]
            for key in _strings(
                profile.get("paper_presets", ()), "profile paper presets"
            )
            if str(key) in presets
        )
        if not paper_presets:
            raise ValueError(
                f"Catalog profile {profile['profile_key']!r} has no valid paper preset"
            )
        default_paper = paper_presets[0]

        defaults = _optional_mapping(profile.get("print_defaults"), "print defaults")
        speeds = _optional_mapping(defaults.get("speed"), "print speeds")
        energy = _optional_mapping(defaults.get("energy"), "print energy")
        image_energy = _integer_tiers(energy.get("image"), "image energy")
        text_energy = _integer_tiers(energy.get("text"), "text energy")
        image_speed = int(speeds.get("image") or 0)
        text_speed = int(speeds.get("text") or image_speed)

        runtime_key = item.get("profile_runtime_preset_key")
        runtime_preset = None
        if runtime_key:
            runtime_preset = next(
                (
                    candidate
                    for candidate in _entries(
                        profile.get("runtime_presets", ()), "runtime presets"
                    )
                    if candidate.get("key") == runtime_key
                ),
                None,
            )
            if runtime_preset is None:
                raise ValueError(
                    f"Catalog model {item['model_key']!r} references missing runtime preset "
                    f"{runtime_key!r}"
                )

        rules = cls._parse_detection_rules(item)
        first_name = next(
            (rule.display_name for rule in rules if rule.display_name),
            str(item["model_key"]),
        )
        supported_modes = tuple(
            dict.fromkeys(
                preset.paper_mode
                for preset in paper_presets
                if preset.paper_mode is not None
            )
        )
        density_defaults = (
            None
            if defaults.get("density") is None
            else _mapping(defaults["density"], "profile density")
        )
        runtime_density = (
            None
            if runtime_preset is None or runtime_preset.get("density") is None
            else _mapping(runtime_preset["density"], "runtime density")
        )
        # Runtime presets override profile density in upstream. Keep the
        # effective image tiers separate from the V5G wire-protocol ceiling:
        # these are model-tuned defaults, not hard user-input limits.
        effective_density = runtime_density or density_defaults
        image_density_raw = (
            None if effective_density is None else effective_density.get("image")
        )
        image_density = (
            None
            if image_density_raw is None
            else _integer_tiers(image_density_raw, "image density")
        )
        density_values = (
            [int(value) for value in image_density.values()]
            if isinstance(image_density, Mapping)
            else []
        )
        minimum_density = min(density_values, default=None)
        default_density = (
            _middle(image_density, 0) if isinstance(image_density, Mapping) else None
        )
        maximum_density = max(density_values, default=None)
        marketing_names = (
            *_strings(item.get("marketing_names", ()), "marketing names"),
            *(
                name
                for entry in _entries(item.get("detections", ()), "detections")
                for name in _strings(
                    entry.get("marketing_names", ()), "marketing names"
                )
            ),
        )
        legacy_marketing_name = _optional_string(
            item.get("marketing_name"), "marketing name"
        )
        modern_origins = _strings(item.get("origin_ids", ()), "origin IDs")
        legacy_origins = _strings(
            item.get("origin_app_packages", ()), "origin app packages"
        )
        stream = _optional_mapping(profile.get("stream"), "stream")

        return PrinterModel(
            model_no=str(item["model_key"]),
            profile_key=str(profile["profile_key"]),
            head_name=first_name,
            marketing_name=marketing_names[0]
            if marketing_names
            else legacy_marketing_name,
            marketing_names=marketing_names,
            detection_rules=rules,
            origin_app_packages=tuple(
                dict.fromkeys((*legacy_origins, *modern_origins))
            ),
            origin_ids=modern_origins,
            detection_ambiguity_group=_optional_string(
                item.get("detection_ambiguity_group"), "detection ambiguity group"
            ),
            protocol_family=family,
            protocol_variant=None
            if protocol_variant in (None, "")
            else str(protocol_variant),
            image_pipeline=image_pipeline,
            paper_presets=paper_presets,
            size=int(profile.get("size") or 0),
            paper_size=default_paper.paper_width_px,
            print_size=default_paper.render_width_px,
            one_length=int(profile.get("one_length") or 0),
            dev_dpi=int(profile.get("dev_dpi") or 203),
            img_print_speed=image_speed,
            text_print_speed=text_speed,
            img_mtu=int(stream.get("chunk_size") or 128),
            interval_ms=int(stream.get("delay_ms") or 0),
            thin_energy=_tier(image_energy, "low", 0),
            moderation_energy=_middle(image_energy, 0),
            deepen_energy=_tier(image_energy, "high", _middle(image_energy, 0)),
            text_energy=_middle(text_energy, _middle(image_energy, 0)),
            has_id=bool(profile.get("has_id")),
            use_spp=bool(profile.get("use_spp")),
            can_print_label=bool(profile.get("can_print_label")),
            label_value=str(profile.get("label_value") or "0"),
            back_paper_num=int(profile.get("back_paper_num") or 0),
            post_print_feed_count=int(profile.get("post_print_feed_count") or 0),
            can_change_mtu=profile.get("ble_mtu_request") is not None,
            ble_mtu_request=None
            if profile.get("ble_mtu_request") is None
            else int(profile["ble_mtu_request"]),
            a4xii=bool(profile.get("a4xii")),
            supported_paper_modes=supported_modes,
            runtime_variant=None
            if runtime_preset is None
            else _optional_string(
                runtime_preset.get("control_algorithm"), "runtime variant"
            ),
            runtime_density_profile_key=None
            if runtime_key is None
            else str(runtime_key),
            runtime_density=runtime_density,
            profile_density=density_defaults,
            runtime_capabilities={}
            if runtime_preset is None
            else dict(
                _optional_mapping(
                    runtime_preset.get("capabilities"), "runtime capabilities"
                )
            ),
            min_density=minimum_density,
            default_density=default_density,
            max_density=maximum_density,
            max_speed=max(image_speed, text_speed, 1),
            min_energy=max(1, _tier(image_energy, "low", 1)),
            max_energy=max(1, _tier(image_energy, "high", _middle(image_energy, 1))),
        )

    @property
    def models(self) -> list[PrinterModel]:
        return list(self._models)

    @property
    def unsupported_model_count(self) -> int:
        return len(self._source_unsupported)

    @property
    def deferred_model_count(self) -> int:
        return len(self._deferred)

    def get(self, model_no: str) -> PrinterModel | None:
        normalized = str(model_no or "").casefold()
        for key, model in self._by_key.items():
            if key.casefold() == normalized:
                return model
        return None

    def get_by_head_name(self, head_name: str) -> PrinterModel | None:
        if not head_name:
            return None
        direct = self.get(head_name)
        if direct is not None:
            return direct
        for model in self._models:
            for rule in model.detection_rules:
                normalized = _normalized_name(
                    head_name, casefold=True, whitespace_mode=rule.whitespace_mode
                )
                if (
                    normalized
                    and _normalized_name(
                        rule.display_name,
                        casefold=True,
                        whitespace_mode=rule.whitespace_mode,
                    )
                    == normalized
                ):
                    return model
        return None

    def detect_from_device_name(
        self,
        name: str,
        address: str | None = None,
    ) -> PrinterModel | None:
        match = self.detect_with_origin(name, address)
        return None if match is None else match.model

    def detect_with_origin(
        self,
        name: str,
        address: str | None = None,
    ) -> PrinterModelMatch | None:
        if not name:
            return None
        # A shared group is catalog evidence that advertised names cannot
        # select a protocol safely, even when casing or specificity differs.
        groups: dict[str, set[str]] = {}
        for candidates in (
            self._supported_candidates(name, address, casefold=True),
            self._deferred_candidates(name, address, casefold=True),
            self._unsupported_candidates(name, address, casefold=True),
        ):
            for _, candidate_model, _ in candidates:
                group = candidate_model.detection_ambiguity_group
                if group and group.strip():
                    model_id = (
                        candidate_model.model_no
                        if isinstance(candidate_model, PrinterModel)
                        else candidate_model.model_key
                    )
                    groups.setdefault(group, set()).add(model_id)
        if any(len(model_ids) > 1 for model_ids in groups.values()):
            return None
        for casefold in (False, True):
            supported = self._supported_candidates(name, address, casefold=casefold)
            deferred = self._deferred_candidates(name, address, casefold=casefold)
            unsupported = self._unsupported_candidates(name, address, casefold=casefold)
            if not supported and not deferred and not unsupported:
                continue
            supported.sort(key=lambda item: item[0], reverse=True)
            deferred.sort(key=lambda item: item[0], reverse=True)
            unsupported.sort(key=lambda item: item[0], reverse=True)
            best_supported = supported[0][0] if supported else None
            best_deferred = deferred[0][0] if deferred else None
            best_unsupported = unsupported[0][0] if unsupported else None
            best_catalog_supported = (
                max(
                    value
                    for value in (best_supported, best_deferred)
                    if value is not None
                )
                if best_supported is not None or best_deferred is not None
                else None
            )
            if (
                best_supported is None
                or (
                    best_unsupported is not None
                    and best_catalog_supported is not None
                    and best_unsupported > best_catalog_supported
                )
                or (best_deferred is not None and best_deferred >= best_supported)
            ):
                return None
            winners = [item for item in supported if item[0] == best_supported]
            unique_models = {item[1].model_no: item[1] for item in winners}
            if len(unique_models) != 1:
                return None
            score, model, rule = winners[0]
            return PrinterModelMatch(
                model=model,
                source=PrinterModelMatchSource.HEAD_NAME,
                alias_kind=(
                    PrinterModelAliasKind.MAC
                    if score[2]
                    else PrinterModelAliasKind.HEAD_NAME
                ),
                protocol_family=model.protocol_family,
                protocol_variant=model.protocol_variant,
                image_pipeline=model.image_pipeline,
                testing=model.testing,
                testing_note=model.testing_note,
            )
        return None

    def _supported_candidates(
        self,
        name: str,
        address: str | None,
        *,
        casefold: bool,
    ) -> list[tuple[tuple[int, int, int, int, int], PrinterModel, DetectionRule]]:
        matches = []
        for model in self._models:
            for rule in model.detection_rules:
                score = rule.match_score(name, address, casefold=casefold)
                if score is not None:
                    matches.append((score, model, rule))
        return matches

    def _unsupported_candidates(
        self,
        name: str,
        address: str | None,
        *,
        casefold: bool,
    ) -> list[tuple[tuple[int, int, int, int, int], _UnsupportedModel, DetectionRule]]:
        matches = []
        for model in self._source_unsupported:
            for rule in model.detection_rules:
                score = rule.match_score(name, address, casefold=casefold)
                if score is not None:
                    matches.append((score, model, rule))
        return matches

    def _deferred_candidates(
        self,
        name: str,
        address: str | None,
        *,
        casefold: bool,
    ) -> list[tuple[tuple[int, int, int, int, int], _UnsupportedModel, DetectionRule]]:
        matches = []
        for model in self._deferred:
            for rule in model.detection_rules:
                score = rule.match_score(name, address, casefold=casefold)
                if score is not None:
                    matches.append((score, model, rule))
        return matches
