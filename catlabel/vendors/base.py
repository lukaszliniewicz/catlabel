from abc import ABC, abstractmethod
from typing import List

from PIL import Image


class BasePrinterClient(ABC):
    def __init__(self, device, hardware_info: dict, printer_profile, settings):
        self.device = device
        self.hardware_info = hardware_info
        self.printer_profile = printer_profile
        self.settings = settings
        self.last_error = None

    @abstractmethod
    async def connect(self) -> bool:
        """Establishes connection to the physical printer."""
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully tears down connection."""
        raise NotImplementedError

    @abstractmethod
    async def print_images(self, images: List[Image.Image], split_mode: bool = False) -> None:
        """Slices/pads the images based on hardware constraints and sends them."""
        raise NotImplementedError
