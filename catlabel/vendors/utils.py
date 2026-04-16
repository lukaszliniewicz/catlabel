def _safe_positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _registry_models(registry):
    models_attr = getattr(registry, "models", None)
    if callable(models_attr):
        return list(models_attr())
    if models_attr is None:
        return []
    return list(models_attr)


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
            for lookup_name in (candidate_name, candidate_name.upper(), candidate_name.lower()):
                model = get_method(lookup_name)
                if model:
                    return model

        normalized_upper = candidate_name.upper()
        exact_match = None
        prefix_match = None

        for model in _registry_models(registry):
            model_no = str(getattr(model, "model_no", "") or "").strip()
            head_name = str(getattr(model, "head_name", "") or "").strip().strip("-")
            candidates = [candidate.upper() for candidate in (model_no, head_name) if candidate]

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
    if hasattr(protocol_family, "value"):
        protocol_family = protocol_family.value

    reported_default_energy = default_energy
    if vendor == "phomemo":
        reported_default_energy = min(
            _safe_positive_int(getattr(model, "max_density", 0), 8),
            6,
        )

    return {
        "name": str(getattr(model, "head_name", "") or "").strip().strip("-") or model_no,
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
        "media_type": media_type,
        "protocol_family": str(protocol_family or "legacy"),
    }
