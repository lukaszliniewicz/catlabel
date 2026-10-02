from __future__ import annotations

from .base import Page, RasterConverter


class ImageConverter(RasterConverter):
    def load(self, path: str, width: int) -> list[Page]:
        img = self._load_image(path)
        img = self._normalize_image(img)
        img = self._maybe_trim_margins(img)
        img = self._resize_to_width(img, width)
        return [Page(img, dither=True, is_text=False)]
