from .manifest import VendorManifest


class VendorRegistry:
    _plugins: dict[str, VendorManifest] = {}

    @classmethod
    def register(cls, plugin: VendorManifest):
        cls._plugins[plugin.vendor_id] = plugin

    @classmethod
    def get_all_models(cls) -> list[dict]:
        models: list[dict] = []
        for plugin in cls._plugins.values():
            models.extend(plugin.get_supported_models())
        models.sort(
            key=lambda model: (
                str(model.get("vendor_display", "")),
                str(model.get("name", "")).lower(),
                str(model.get("model_no", model.get("model_id", ""))).lower(),
            )
        )
        return models

    @classmethod
    def get_all_presets(cls) -> list[dict]:
        presets: list[dict] = []
        for plugin in cls._plugins.values():
            presets.extend(plugin.get_presets())
        return presets

    @classmethod
    def identify_device(cls, name: str, device=None, mac: str | None = None) -> dict:
        generic_plugin = cls._plugins.get("generic")
        if generic_plugin is None:
            raise KeyError("Generic vendor manifest is not registered")

        matches: list[dict] = []
        for vendor_id, plugin in cls._plugins.items():
            if vendor_id == "generic":
                continue
            info = plugin.identify_device(name, device, mac)
            if info:
                matches.append(info)

        info = generic_plugin.identify_device(name, device, mac)
        if info:
            matches.append(info)

        identities = {
            (match["vendor"], match["model_id"], match.get("protocol_family"))
            for match in matches
        }
        if len(identities) == 1:
            return {**matches[0], "detection_status": "recognized"}
        fallback = generic_plugin.get_fallback_info()
        if identities:
            return {
                **fallback,
                "detection_status": "ambiguous",
                "detection_candidates": sorted(
                    {f"{vendor}:{model}" for vendor, model, _family in identities}
                ),
            }
        return {**fallback, "detection_status": "unknown"}

    @classmethod
    def get_manifest(cls, vendor_id: str) -> VendorManifest:
        normalized_vendor = str(vendor_id or "generic").strip().lower()
        return cls._plugins.get(normalized_vendor, cls._plugins["generic"])
