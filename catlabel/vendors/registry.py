from typing import Dict, List

from .manifest import VendorManifest


class VendorRegistry:
    _plugins: Dict[str, VendorManifest] = {}

    @classmethod
    def register(cls, plugin: VendorManifest):
        cls._plugins[plugin.vendor_id] = plugin

    @classmethod
    def get_all_models(cls) -> List[Dict]:
        models: List[Dict] = []
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
    def get_all_presets(cls) -> List[Dict]:
        presets: List[Dict] = []
        for plugin in cls._plugins.values():
            presets.extend(plugin.get_presets())
        return presets

    @classmethod
    def identify_device(cls, name: str, device=None, mac: str = None) -> Dict:
        generic_plugin = cls._plugins.get("generic")

        for vendor_id, plugin in cls._plugins.items():
            if vendor_id == "generic":
                continue
            info = plugin.identify_device(name, device, mac)
            if info:
                return info

        if generic_plugin is not None:
            info = generic_plugin.identify_device(name, device, mac)
            if info:
                return info
            return generic_plugin.get_fallback_info()

        raise KeyError("Generic vendor manifest is not registered")

    @classmethod
    def get_manifest(cls, vendor_id: str) -> VendorManifest:
        normalized_vendor = str(vendor_id or "generic").strip().lower()
        return cls._plugins.get(normalized_vendor, cls._plugins["generic"])
