from __future__ import annotations

import os

from .base import Page, PageConverter
from .image import ImageConverter
from .pdf import PdfConverter
from .text import TextConverter

SUPPORTED_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".pdf",
    ".txt",
}


class PageLoader:
    def __init__(
        self,
        converters: dict[str, PageConverter] | None = None,
        text_font: str | None = None,
        text_columns: int | None = None,
        text_wrap: bool = True,
        trim_side_margins: bool = True,
        trim_top_bottom_margins: bool = True,
        pdf_pages: str | None = None,
        pdf_page_gap_px: int = 0,
    ) -> None:
        if converters is None:
            converters = {}
            image_converter = ImageConverter(
                trim_side_margins=trim_side_margins,
                trim_top_bottom_margins=trim_top_bottom_margins,
            )
            for ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                converters[ext] = image_converter
            converters[".pdf"] = PdfConverter(
                page_selection=pdf_pages,
                page_gap_px=pdf_page_gap_px,
                trim_side_margins=trim_side_margins,
                trim_top_bottom_margins=trim_top_bottom_margins,
            )
            converters[".txt"] = TextConverter(
                font_path=text_font,
                columns=text_columns,
                wrap_lines=text_wrap,
            )
        self._converters = converters

    @property
    def supported_extensions(self) -> set[str]:
        return set(self._converters.keys())

    def load(self, path: str, width: int) -> list[Page]:
        ext = os.path.splitext(path)[1].lower()
        converter = self._converters.get(ext)
        if not converter:
            raise ValueError(f"Unsupported file extension: {ext}")
        return converter.load(path, width)


def load_pages(path: str, width: int) -> list[Page]:
    return PageLoader().load(path, width)


__all__ = ["Page", "PageLoader", "SUPPORTED_EXTENSIONS", "load_pages"]
