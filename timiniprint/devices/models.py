from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, Optional, List, Tuple, Set

from ..protocol.family import ProtocolFamily

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "printer_models.json"
ALIAS_PATH = DATA_PATH.with_name("printer_model_aliases.json")

class PrinterModelAliasNormalizer:
    _whitespace_re = re.compile(r"\s+")
    _non_hex_re = re.compile(r"[^0-9A-F]")
    _mac_like_re = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")

    @classmethod
    def normalize_alias_name(cls, value: str) -> str:
        return cls._whitespace_re.sub("", value).upper()

    @classmethod
    def normalize_mac_candidate(cls, value: str) -> str:
        return cls._non_hex_re.sub("", value.upper())

    @classmethod
    def is_mac_like_address(cls, value: str) -> bool:
        return bool(cls._mac_like_re.match(value.strip()))


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
    model: int
    size: int
    paper_size: int
    print_size: int
    one_length: int
    head_name: str
    can_change_mtu: bool
    dev_dpi: int
    img_print_speed: int
    text_print_speed: int
    img_mtu: int
    new_compress: bool
    paper_num: int
    interval_ms: int
    thin_energy: int
    moderation_energy: int
    deepen_energy: int
    text_energy: int
    has_id: bool
    use_spp: bool
    protocol_family: ProtocolFamily
    can_print_label: bool
    label_value: str
    back_paper_num: int
    a4xii: bool = False
    add_mor_pix: Optional[bool] = None
    # Experimental entries are family-based proxies derived from third-party apps.
    testing: bool = False
    testing_note: Optional[str] = None

    @property
    def width(self) -> int:
        return self.print_size


@dataclass(frozen=True)
class PrinterModelMatch:
    model: PrinterModel
    source: PrinterModelMatchSource
    alias_kind: Optional[PrinterModelAliasKind] = None
    protocol_family: ProtocolFamily = ProtocolFamily.LEGACY
    testing: bool = False
    testing_note: Optional[str] = None
    conflict_models: Tuple[str, ...] = ()

    @property
    def used_alias(self) -> bool:
        return self.source is PrinterModelMatchSource.ALIAS

    @property
    def has_brand_conflict(self) -> bool:
        return bool(self.conflict_models)


@dataclass(frozen=True)
class PrinterModelAliasMatch:
    target_head_name: str
    kind: PrinterModelAliasKind
    protocol_family: Optional[ProtocolFamily] = None
    testing: bool = False
    testing_note: Optional[str] = None


@dataclass(frozen=True)
class PrinterModelHeadAlias:
    prefixes: List[str]
    map_model_head_name: str
    protocol_family: Optional[ProtocolFamily] = None
    testing: bool = False
    testing_note: Optional[str] = None
    _normalized_prefixes: Tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        normalized = tuple(
            PrinterModelAliasNormalizer.normalize_alias_name(prefix) for prefix in self.prefixes
        )
        object.__setattr__(self, "_normalized_prefixes", normalized)

    def match_length(self, normalized_name: str) -> int:
        longest = 0
        for prefix in self._normalized_prefixes:
            if normalized_name.startswith(prefix):
                longest = max(longest, len(prefix))
        return longest


@dataclass(frozen=True)
class PrinterModelMacAlias:
    suffixes: List[str]
    map_model_head_name: str
    only_for_targets: Tuple[str, ...] = ()
    protocol_family: Optional[ProtocolFamily] = None
    testing: bool = False
    testing_note: Optional[str] = None
    _normalized_suffixes: Tuple[str, ...] = field(init=False, repr=False)
    _normalized_targets: Tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        normalized = tuple(suffix.upper() for suffix in self.suffixes)
        object.__setattr__(self, "_normalized_suffixes", normalized)
        object.__setattr__(self, "_normalized_targets", tuple(self.only_for_targets))

    def matches(self, address: Optional[str]) -> bool:
        if not address:
            return False
        if not PrinterModelAliasNormalizer.is_mac_like_address(address):
            return False
        candidates = [address.strip().upper()]
        normalized = PrinterModelAliasNormalizer.normalize_mac_candidate(address)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
        for suffix in self._normalized_suffixes:
            for candidate in candidates:
                if candidate.endswith(suffix):
                    return True
        return False

    def applies_to(self, target_head_name: str) -> bool:
        if not self._normalized_targets:
            return True
        return target_head_name in self._normalized_targets


class PrinterModelAliasRegistry:
    def __init__(
        self,
        head_aliases: Iterable[PrinterModelHeadAlias],
        mac_aliases: Iterable[PrinterModelMacAlias],
    ) -> None:
        self._head_aliases = list(head_aliases)
        self._mac_aliases = list(mac_aliases)

    @classmethod
    def load(cls, path: Path) -> "PrinterModelAliasRegistry":
        if not path.exists():
            return cls([], [])
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Alias file must contain a JSON list")
        head_aliases, mac_aliases = cls._parse(raw)
        return cls(head_aliases, mac_aliases)

    @staticmethod
    def _parse(
        raw: List[object],
    ) -> Tuple[List[PrinterModelHeadAlias], List[PrinterModelMacAlias]]:
        head_aliases: List[PrinterModelHeadAlias] = []
        mac_aliases: List[PrinterModelMacAlias] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise ValueError("Alias entries must be JSON objects")
            if "head_name" in entry:
                head_name = entry.get("head_name") or {}
                if not isinstance(head_name, dict):
                    raise ValueError("Alias head_name must be a JSON object")
                prefixes = head_name.get("prefixes")
                if prefixes is None:
                    prefix = head_name.get("prefix")
                    if not prefix:
                        raise ValueError("Alias head_name missing prefix")
                    prefixes = [prefix]
                map_model_head_name = entry.get("map_model_head_name") or head_name.get(
                    "map_model_head_name"
                )
                if not map_model_head_name:
                    raise ValueError("Alias entry missing map_model_head_name")
                head_aliases.append(
                    PrinterModelHeadAlias(
                        prefixes=list(prefixes),
                        map_model_head_name=map_model_head_name,
                        protocol_family=PrinterModelAliasRegistry._parse_protocol_family(entry),
                        testing=bool(entry.get("testing", False)),
                        testing_note=entry.get("testing_note"),
                    )
                )
                continue
            if "mac" in entry:
                mac_entry = entry.get("mac") or {}
                if not isinstance(mac_entry, dict):
                    raise ValueError("Alias mac must be a JSON object")
                suffixes = mac_entry.get("suffixes")
                if suffixes is None:
                    suffix = mac_entry.get("suffix")
                    if not suffix:
                        raise ValueError("Alias mac missing suffix")
                    suffixes = [suffix]
                map_model_head_name = entry.get("map_model_head_name") or mac_entry.get(
                    "map_model_head_name"
                )
                if not map_model_head_name:
                    raise ValueError("Alias entry missing map_model_head_name")
                mac_aliases.append(
                    PrinterModelMacAlias(
                        suffixes=list(suffixes),
                        map_model_head_name=map_model_head_name,
                        only_for_targets=tuple(entry.get("only_for_targets", ())),
                        protocol_family=PrinterModelAliasRegistry._parse_protocol_family(entry),
                        testing=bool(entry.get("testing", False)),
                        testing_note=entry.get("testing_note"),
                    )
                )
                continue
            raise ValueError("Alias entry must include head_name or mac")
        return head_aliases, mac_aliases

    @staticmethod
    def _parse_protocol_family(entry: Dict[str, object]) -> Optional[ProtocolFamily]:
        value = entry.get("protocol_family")
        if not value:
            return None
        return ProtocolFamily.from_value(str(value))

    def resolve(self, name: str, address: Optional[str]) -> Optional[PrinterModelAliasMatch]:
        if not name or not self._head_aliases:
            return None
        normalized_name = PrinterModelAliasNormalizer.normalize_alias_name(name)
        match = None
        match_prefix_len = 0
        for alias in self._head_aliases:
            prefix_len = alias.match_length(normalized_name)
            if prefix_len > match_prefix_len:
                match = alias
                match_prefix_len = prefix_len
        if not match:
            return None
        target = match.map_model_head_name
        match_kind = PrinterModelAliasKind.HEAD_NAME
        protocol_family = match.protocol_family
        testing = match.testing
        testing_note = match.testing_note
        for mac_alias in self._mac_aliases:
            if mac_alias.matches(address) and mac_alias.applies_to(target):
                target = mac_alias.map_model_head_name
                match_kind = PrinterModelAliasKind.MAC
                protocol_family = mac_alias.protocol_family or protocol_family
                testing = mac_alias.testing
                testing_note = mac_alias.testing_note
                break
        return PrinterModelAliasMatch(
            target_head_name=target,
            kind=match_kind,
            protocol_family=protocol_family,
            testing=testing,
            testing_note=testing_note,
        )

    def resolve_all(self, name: str, address: Optional[str]) -> List[PrinterModelAliasMatch]:
        if not name or not self._head_aliases:
            return []
        normalized_name = PrinterModelAliasNormalizer.normalize_alias_name(name)
        matches: List[PrinterModelAliasMatch] = []
        seen: Set[Tuple[str, PrinterModelAliasKind]] = set()
        for alias in self._head_aliases:
            if alias.match_length(normalized_name) <= 0:
                continue
            head_match = PrinterModelAliasMatch(
                target_head_name=alias.map_model_head_name,
                kind=PrinterModelAliasKind.HEAD_NAME,
                protocol_family=alias.protocol_family,
                testing=alias.testing,
                testing_note=alias.testing_note,
            )
            key = (head_match.target_head_name, head_match.kind)
            if key not in seen:
                matches.append(head_match)
                seen.add(key)
            for mac_alias in self._mac_aliases:
                if not mac_alias.matches(address) or not mac_alias.applies_to(alias.map_model_head_name):
                    continue
                mac_match = PrinterModelAliasMatch(
                    target_head_name=mac_alias.map_model_head_name,
                    kind=PrinterModelAliasKind.MAC,
                    protocol_family=mac_alias.protocol_family,
                    testing=mac_alias.testing,
                    testing_note=mac_alias.testing_note,
                )
                key = (mac_match.target_head_name, mac_match.kind)
                if key not in seen:
                    matches.append(mac_match)
                    seen.add(key)
        return matches


class PrinterModelRegistry:
    _cache: Dict[Tuple[Path, Path], "PrinterModelRegistry"] = {}

    def __init__(self, models: Iterable[PrinterModel], alias_registry: PrinterModelAliasRegistry) -> None:
        self._models = list(models)
        self._aliases = alias_registry

    @classmethod
    def load(cls, path: Path = DATA_PATH) -> "PrinterModelRegistry":
        alias_path = path.with_name(ALIAS_PATH.name)
        key = (path.resolve(), alias_path.resolve())
        cached = cls._cache.get(key)
        if cached:
            return cached
        raw = json.loads(path.read_text(encoding="utf-8"))
        models = [cls._parse_model(item) for item in raw]
        alias_registry = PrinterModelAliasRegistry.load(alias_path)
        registry = cls(models, alias_registry)
        cls._cache[key] = registry
        return registry

    @staticmethod
    def _parse_model(item: Dict[str, object]) -> PrinterModel:
        payload = dict(item)
        family_value = payload.pop("protocol_family", None)
        if family_value is None:
            protocol_family = ProtocolFamily.LEGACY
        else:
            protocol_family = ProtocolFamily.from_value(str(family_value))
        payload["protocol_family"] = protocol_family
        return PrinterModel(**payload)

    @property
    def models(self) -> List[PrinterModel]:
        return list(self._models)

    def get(self, model_no: str) -> Optional[PrinterModel]:
        for model in self._models:
            if model.model_no == model_no:
                return model
        return None

    def get_by_head_name(self, head_name: str) -> Optional[PrinterModel]:
        if not head_name:
            return None
        for model in self._models:
            if model.head_name and model.head_name == head_name:
                return model
        for model in self._models:
            if model.model_no == head_name:
                return model
        target = head_name.lower()
        for model in self._models:
            if model.head_name and model.head_name.lower() == target:
                return model
        for model in self._models:
            if model.model_no.lower() == target:
                return model
        return None

    def detect_from_device_name(self, name: str, address: Optional[str] = None) -> Optional[PrinterModel]:
        match = self.detect_with_origin(name, address)
        if not match:
            return None
        return match.model

    def detect_with_origin(self, name: str, address: Optional[str] = None) -> Optional[PrinterModelMatch]:
        if not name:
            return None
        (
            exact_head_matches,
            exact_model_no_matches,
            head_matches,
            model_no_matches,
            alias_match,
            alias_matches,
        ) = self._collect_matches(name, address)
        conflict_models = self._conflict_models(
            exact_head_matches,
            exact_model_no_matches,
            alias_matches,
        )
        if exact_head_matches:
            match = max(exact_head_matches, key=lambda model: len(model.head_name))
            return PrinterModelMatch(
                model=match,
                source=PrinterModelMatchSource.HEAD_NAME,
                protocol_family=match.protocol_family,
                testing=match.testing,
                testing_note=match.testing_note,
                conflict_models=conflict_models(match.model_no),
            )
        if exact_model_no_matches:
            match = max(exact_model_no_matches, key=lambda model: len(model.model_no))
            return PrinterModelMatch(
                model=match,
                source=PrinterModelMatchSource.MODEL_NO,
                protocol_family=match.protocol_family,
                testing=match.testing,
                testing_note=match.testing_note,
                conflict_models=conflict_models(match.model_no),
            )
        if head_matches:
            match = max(head_matches, key=lambda model: len(model.head_name))
            return PrinterModelMatch(
                model=match,
                source=PrinterModelMatchSource.HEAD_NAME,
                protocol_family=match.protocol_family,
                testing=match.testing,
                testing_note=match.testing_note,
                conflict_models=conflict_models(match.model_no),
            )
        if model_no_matches:
            match = max(model_no_matches, key=lambda model: len(model.model_no))
            return PrinterModelMatch(
                model=match,
                source=PrinterModelMatchSource.MODEL_NO,
                protocol_family=match.protocol_family,
                testing=match.testing,
                testing_note=match.testing_note,
                conflict_models=conflict_models(match.model_no),
            )
        return self._detect_from_alias(alias_match, alias_matches)

    def _detect_from_alias(
        self,
        alias_match: Optional[PrinterModelAliasMatch],
        alias_matches: List[PrinterModelAliasMatch],
    ) -> Optional[PrinterModelMatch]:
        if not alias_match:
            return None
        conflict_models = self._conflict_models([], [], alias_matches)
        model = self.get_by_head_name(alias_match.target_head_name)
        if not model:
            return None
        return PrinterModelMatch(
            model=model,
            source=PrinterModelMatchSource.ALIAS,
            alias_kind=alias_match.kind,
            protocol_family=alias_match.protocol_family or model.protocol_family,
            testing=alias_match.testing or model.testing,
            testing_note=alias_match.testing_note or model.testing_note,
            conflict_models=conflict_models(model.model_no),
        )

    def _collect_matches(
        self, name: str, address: Optional[str]
    ) -> Tuple[
        List[PrinterModel],
        List[PrinterModel],
        List[PrinterModel],
        List[PrinterModel],
        Optional[PrinterModelAliasMatch],
        List[PrinterModelAliasMatch],
    ]:
        exact_head_matches = self._matching_models(name, key="head_name", case_sensitive=True)
        if exact_head_matches:
            exact_model_no_matches = []
        else:
            exact_model_no_matches = self._matching_models(name, key="model_no", case_sensitive=True)
        head_matches: List[PrinterModel] = []
        model_no_matches: List[PrinterModel] = []
        if not exact_head_matches and not exact_model_no_matches:
            head_matches = self._matching_models(name, key="head_name", case_sensitive=False)
        if not exact_head_matches and not exact_model_no_matches and not head_matches:
            model_no_matches = self._matching_models(name, key="model_no", case_sensitive=False)
        alias_match = self._aliases.resolve(name, address)
        alias_matches = self._aliases.resolve_all(name, address)
        return (
            exact_head_matches,
            exact_model_no_matches,
            head_matches,
            model_no_matches,
            alias_match,
            alias_matches,
        )

    def _matching_models(
        self, name: str, *, key: str, case_sensitive: bool
    ) -> List[PrinterModel]:
        matches: List[PrinterModel] = []
        if case_sensitive:
            for model in self._models:
                candidate = getattr(model, key)
                if candidate and name.startswith(candidate):
                    matches.append(model)
            return matches

        name_lower = name.lower()
        for model in self._models:
            candidate = getattr(model, key)
            if candidate and name_lower.startswith(candidate.lower()):
                matches.append(model)
        return matches

    def _conflict_models(
        self,
        head_matches: List[PrinterModel],
        model_no_matches: List[PrinterModel],
        alias_matches: List[PrinterModelAliasMatch],
    ):
        all_model_nos = {model.model_no for model in head_matches}
        all_model_nos.update(model.model_no for model in model_no_matches)
        for alias_match in alias_matches:
            if not alias_match.testing:
                continue
            model = self.get_by_head_name(alias_match.target_head_name)
            if model:
                all_model_nos.add(model.model_no)

        def others(selected_model_no: str) -> Tuple[str, ...]:
            return tuple(sorted(model_no for model_no in all_model_nos if model_no != selected_model_no))

        return others
