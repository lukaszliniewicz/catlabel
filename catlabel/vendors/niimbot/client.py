import asyncio
from typing import List

from PIL import Image

from ..base import BasePrinterClient
from ...app.vendors.niimbot.printer import PrinterClient


class _FakeBleakDevice:
    def __init__(self, address: str, name: str):
        self.address = address
        self.name = name


class NiimbotClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings):
        super().__init__(device, hardware_info, printer_profile, settings)

        ble_address = device.address
        if hasattr(device, "ble_endpoint") and device.ble_endpoint:
            ble_address = device.ble_endpoint.address

        device_name = getattr(device, "name", None) or hardware_info.get("model_id") or "Niimbot Printer"
        fake_device = _FakeBleakDevice(ble_address, device_name)
        self.printer = PrinterClient(fake_device)

    async def connect(self) -> bool:
        return await self.printer.connect()

    async def disconnect(self) -> None:
        await self.printer.disconnect()

    async def print_images(self, images: List[Image.Image], split_mode: bool = False) -> None:
        print_width_px = self.hardware_info["width_px"]
        final_images = []

        for img in images:
            if img.width > print_width_px:
                ratio = print_width_px / float(img.width)
                new_height = max(1, int(img.height * ratio))
                img = img.resize((print_width_px, new_height), Image.Resampling.LANCZOS)
            final_images.append(img)

        default_density = int(self.hardware_info.get("default_energy", 3) or 3)
        max_allowed = max(1, int(self.hardware_info.get("max_density", 5) or 5))
        raw_density = (
            self.printer_profile.energy
            if self.printer_profile and self.printer_profile.energy not in (None, 0)
            else default_density
        )
        density = max(1, min(int(raw_density), max_allowed))

        for img in final_images:
            await self.printer.print_image(img, density=density, quantity=1)
            await asyncio.sleep(1.0)
