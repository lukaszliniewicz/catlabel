from .base import BasePrinterClient as BasePrinterClient
from .generic.manifest import GenericManifest
from .manifest import VendorManifest as VendorManifest
from .niimbot.manifest import NiimbotManifest
from .phomemo.manifest import PhomemoManifest
from .registry import VendorRegistry as VendorRegistry

VendorRegistry.register(GenericManifest())
VendorRegistry.register(NiimbotManifest())
VendorRegistry.register(PhomemoManifest())

__all__ = ["BasePrinterClient", "VendorManifest", "VendorRegistry"]
