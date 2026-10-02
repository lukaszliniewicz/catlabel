from abc import ABC, abstractmethod

from PIL import Image

from ..core.resource_limits import (
    MAX_PRINT_JOBS,
    ResourceLimitError,
    validate_image_budget,
)


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

    def validate_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
    ) -> int:
        """Validate source image count and aggregate pixel allocation."""
        image_count = len(images)
        if image_count > MAX_PRINT_JOBS:
            raise ResourceLimitError(
                f"At most {MAX_PRINT_JOBS} label images are allowed."
            )

        pixels = 0
        for image in images:
            pixels = validate_image_budget(image.width, image.height, pixels)
        return image_count

    @abstractmethod
    async def print_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
        dither: bool = True,
    ) -> None:
        """Slices/pads the images based on hardware constraints and sends them."""
        raise NotImplementedError
