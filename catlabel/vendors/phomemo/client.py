from typing import List

from fastapi import HTTPException
from PIL import Image

from ..base import BasePrinterClient


class PhomemoClient(BasePrinterClient):
    async def connect(self) -> bool:
        raise HTTPException(
            status_code=501,
            detail="Phomemo vendor client is not implemented yet.",
        )

    async def disconnect(self) -> None:
        return None

    async def print_images(self, images: List[Image.Image], split_mode: bool = False) -> None:
        raise HTTPException(
            status_code=501,
            detail="Phomemo vendor client is not implemented yet.",
        )
