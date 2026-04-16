from .base import BasePrinterClient
from .manifest import VendorManifest
from .registry import VendorRegistry

from .generic.manifest import GenericManifest
from .niimbot.manifest import NiimbotManifest
from .phomemo.manifest import PhomemoManifest

VendorRegistry.register(GenericManifest())
VendorRegistry.register(NiimbotManifest())
VendorRegistry.register(PhomemoManifest())

__all__ = ["BasePrinterClient", "VendorManifest", "VendorRegistry"]
