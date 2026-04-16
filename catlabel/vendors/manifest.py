from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from .base import BasePrinterClient


class VendorManifest(ABC):
    @property
    @abstractmethod
    def vendor_id(self) -> str:
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        ...

    @abstractmethod
    def get_supported_models(self) -> List[Dict]:
        """Returns hardware_info dictionaries for manual setup."""
        raise NotImplementedError

    @abstractmethod
    def get_presets(self) -> List[Dict]:
        """Returns the default presets specific to this vendor."""
        raise NotImplementedError

    @abstractmethod
    def identify_device(
        self,
        name: str,
        device=None,
        mac: Optional[str] = None,
    ) -> Optional[Dict]:
        """Returns a hardware_info dictionary if this vendor claims the device."""
        raise NotImplementedError

    @abstractmethod
    def get_client(self, device, hardware_info: dict, profile, settings) -> BasePrinterClient:
        """Returns the instantiated printer client for this vendor."""
        raise NotImplementedError
