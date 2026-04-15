from .base import BasePrinterClient


def get_printer_client_class(vendor: str):
    normalized_vendor = str(vendor or "generic").strip().lower()

    if normalized_vendor == "niimbot":
        from .niimbot.client import NiimbotClient

        return NiimbotClient

    if normalized_vendor == "phomemo":
        from .phomemo.client import PhomemoClient

        return PhomemoClient

    from .generic.client import GenericClient

    return GenericClient


__all__ = ["BasePrinterClient", "get_printer_client_class"]
