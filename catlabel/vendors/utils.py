from collections.abc import Iterable
from typing import TypeGuard


def _is_iterable(value: object) -> TypeGuard[Iterable[object]]:
    return isinstance(value, Iterable) or callable(
        getattr(type(value), "__getitem__", None)
    )


def _models_list(value: object) -> list[object]:
    if _is_iterable(value):
        return list(value)
    raise TypeError(f"'{type(value).__name__}' object is not iterable")


def _safe_positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _registry_models(registry):
    models_attr = getattr(registry, "models", None)
    if callable(models_attr):
        return _models_list(models_attr())
    if models_attr is None:
        return []
    return _models_list(models_attr)


def find_model_in_registry(registry, name: str):
    normalized = (name or "").strip()
    if not normalized:
        return None

    search_names = [normalized]
    tokenized = (
        normalized.replace("_", " ")
        .replace("/", " ")
        .replace("-", " ")
        .replace("(", " ")
        .replace(")", " ")
        .split()
    )
    derived_names = []
    if tokenized:
        derived_names.extend(
            candidate
            for candidate in (
                tokenized[-1],
                tokenized[0],
                "".join(tokenized),
                " ".join(tokenized[-2:]) if len(tokenized) > 1 else "",
                "".join(tokenized[-2:]) if len(tokenized) > 1 else "",
            )
            if candidate
        )

    for candidate_name in derived_names:
        if candidate_name not in search_names:
            search_names.append(candidate_name)

    def _find_single(candidate_name: str):
        get_method = getattr(registry, "get", None)
        if callable(get_method):
            for lookup_name in (
                candidate_name,
                candidate_name.upper(),
                candidate_name.lower(),
            ):
                model = get_method(lookup_name)
                if model:
                    return model

        normalized_upper = candidate_name.upper()
        exact_match = None
        prefix_match = None

        for model in _registry_models(registry):
            model_no = str(getattr(model, "model_no", "") or "").strip()
            head_name = str(getattr(model, "head_name", "") or "").strip().strip("-")
            candidates = [
                candidate.upper() for candidate in (model_no, head_name) if candidate
            ]

            if normalized_upper in candidates:
                exact_match = model
                break

            if any(
                candidate.startswith(normalized_upper)
                or normalized_upper.startswith(candidate)
                or normalized_upper.endswith(candidate)
                for candidate in candidates
            ):
                prefix_match = prefix_match or model

        return exact_match or prefix_match

    for candidate_name in search_names:
        model = _find_single(candidate_name)
        if model:
            return model

    return None


def extract_raw_hardware_info(model) -> dict:
    width_px = max(
        1,
        int(
            getattr(model, "width", 0)
            or getattr(model, "print_size", 0)
            or getattr(model, "paper_size", 0)
            or 384
        ),
    )
    dpi = _safe_positive_int(getattr(model, "dev_dpi", 0), 203)

    default_speed = max(0, int(getattr(model, "img_print_speed", 0) or 0))
    text_speed = max(0, int(getattr(model, "text_print_speed", 0) or 0))
    max_speed = max(default_speed, text_speed, 1)

    min_energy = _safe_positive_int(getattr(model, "thin_energy", 0), 1)
    default_energy = _safe_positive_int(getattr(model, "moderation_energy", 0), 5000)
    default_energy = max(min_energy, default_energy)
    max_energy = _safe_positive_int(getattr(model, "deepen_energy", 0), default_energy)
    max_energy = max(default_energy, max_energy)

    model_no = str(getattr(model, "model_no", "") or "generic")
    vendor = str(getattr(model, "vendor", "generic") or "generic")
    media_type = str(getattr(model, "media_type", "continuous") or "continuous")
    model_min_energy = getattr(model, "min_energy", None)
    model_max_energy = getattr(model, "max_energy", None)
    model_max_speed = getattr(model, "max_speed", None)
    protocol_family = getattr(model, "protocol_family", "legacy")
    protocol_variant = getattr(model, "protocol_variant", None)
    from ..protocol.family import ProtocolFamily

    protocol_family = getattr(protocol_family, "value", protocol_family)
    supported_paper_modes = tuple(getattr(model, "supported_paper_modes", ()) or ())
    if not supported_paper_modes:
        try:
            from ..protocol.families import get_protocol_behavior

            family = ProtocolFamily.from_value(protocol_family)
            behavior = get_protocol_behavior(family)
            if behavior.supported_paper_modes_resolver is not None:
                supported_paper_modes = tuple(
                    mode.value
                    for mode in behavior.supported_paper_modes_resolver(
                        protocol_variant
                    )
                )
            else:
                supported_paper_modes = tuple(
                    mode.value for mode in behavior.supported_paper_modes
                )
        except Exception:
            supported_paper_modes = ()

    def _paper_mode_label(value: str) -> str:
        try:
            from ..protocol.types import PaperMode

            return PaperMode(value).label
        except Exception:
            return str(value).replace("_", " ").title()

    reported_default_energy = default_energy
    if vendor == "phomemo":
        reported_default_energy = min(
            _safe_positive_int(getattr(model, "max_density", 0), 8),
            6,
        )
    display_name = (
        str(getattr(model, "head_name", "") or "").strip().strip("-_") or model_no
    )
    is_printmaster = protocol_family == "phomemo_esc" and protocol_variant in {
        "printmaster_m110",
        "printmaster_m120",
    }
    return {
        "name": f"{display_name} (PrintMaster, experimental)"
        if is_printmaster
        else display_name,
        "support_state": "experimental" if is_printmaster else "supported",
        "support_note": getattr(model, "testing_note", None),
        "vendor": vendor,
        "width_px": width_px,
        "width_mm": round(width_px / dpi * 25.4, 1),
        "dpi": dpi,
        "model": model_no,
        "model_no": model_no,
        "model_id": model_no,
        "default_speed": default_speed,
        "default_energy": reported_default_energy,
        "min_energy": (
            _safe_positive_int(model_min_energy, min_energy)
            if model_min_energy is not None
            else min_energy
        ),
        "max_energy": (
            _safe_positive_int(model_max_energy, max_energy)
            if model_max_energy is not None
            else max_energy
        ),
        "max_speed": (
            max(1, int(model_max_speed or 0))
            if model_max_speed is not None
            else max_speed
        ),
        "max_density": getattr(model, "max_density", None),
        "min_density": getattr(model, "min_density", None),
        "default_density": getattr(model, "default_density", None),
        "media_type": media_type,
        "protocol_family": str(protocol_family or "legacy"),
        "protocol_variant": protocol_variant,
        "supported_paper_modes": [
            {"value": str(mode), "label": _paper_mode_label(str(mode))}
            for mode in supported_paper_modes
        ],
    }
