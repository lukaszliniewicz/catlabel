from abc import ABC, abstractmethod

from .base import BasePrinterClient


class VendorManifest(ABC):
    @property
    @abstractmethod
    def vendor_id(self) -> str: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    @abstractmethod
    def get_supported_models(self) -> list[dict]:
        """Returns hardware_info dictionaries for manual setup."""
        raise NotImplementedError

    @abstractmethod
    def get_presets(self) -> list[dict]:
        """Returns the default presets specific to this vendor."""
        raise NotImplementedError

    @abstractmethod
    def identify_device(
        self,
        name: str,
        device=None,
        mac: str | None = None,
    ) -> dict | None:
        """Returns a hardware_info dictionary if this vendor claims the device."""
        raise NotImplementedError

    def get_fallback_info(self) -> dict:
        """Only a manifest registered as the generic fallback must implement this."""
        raise NotImplementedError(f"{self.vendor_id} has no generic fallback")

    @abstractmethod
    def get_client(
        self, device, hardware_info: dict, profile, settings
    ) -> BasePrinterClient:
        """Returns the instantiated printer client for this vendor."""
        raise NotImplementedError
