from __future__ import annotations

from dataclasses import dataclass

from ..raster import PixelFormat
from .family import ProtocolStrEnum


class ImageEncoding(ProtocolStrEnum):
    LEGACY_RAW = "legacy_raw"
    LEGACY_RLE = "legacy_rle"
    LUCK_NORMAL_RAW = "luck_normal_raw"
    LUCK_NORMAL_COMPRESSED = "luck_normal_compressed"
    LUCK_NORMAL_GRAY = "luck_normal_gray"
    V5G_DOT = "v5g_dot"
    V5G_GRAY = "v5g_gray"
    V5X_DOT = "v5x_dot"
    V5X_GRAY = "v5x_gray"
    V5C_A4 = "v5c_a4"
    V5C_A5 = "v5c_a5"
    DCK_DEFAULT = "dck_default"
    ELEPH_HPRT_ESC_RASTER = "eleph_hprt_esc_raster"
    ELEPH_TSPL_BITMAP = "eleph_tspl_bitmap"
    TOPRINT_HPRT_ESC_RASTER = "toprint_hprt_esc_raster"
    TOPRINT_TSPL_BITMAP = "toprint_tspl_bitmap"
    YK_ASTRA_P1_RAW = "yk_astra_p1_raw"
    INSTAPRINT_CORE_RASTER = "instaprint_core_raster"
    FUNNY_LX_RASTER = "funny_lx_raster"
    PHOMEMO_ESC_RASTER = "phomemo_esc_raster"


class PaperMode(ProtocolStrEnum):
    PLAIN = "plain"
    A4_SHEET = "a4_sheet"
    TAG = "tag"
    BLACK_TAG = "black_tag"
    FOLDER = "folder"
    TATTOO = "tattoo"
    CIRCLE_TAG = "circle_tag"

    @property
    def label(self) -> str:
        labels = {
            PaperMode.PLAIN: "Plain roll",
            PaperMode.A4_SHEET: "A4 sheet",
            PaperMode.TAG: "Tag",
            PaperMode.BLACK_TAG: "Black tag",
            PaperMode.FOLDER: "Folder",
            PaperMode.TATTOO: "Tattoo",
            PaperMode.CIRCLE_TAG: "Circle tag",
        }
        return labels[self]


class PageFlow(ProtocolStrEnum):
    PAGED = "paged"
    CONTINUOUS = "continuous"


@dataclass(frozen=True)
class ImagePipelineConfig:
    formats: tuple[PixelFormat, ...]
    encoding: ImageEncoding

    def __post_init__(self) -> None:
        if not self.formats:
            raise ValueError("Image pipeline formats must not be empty")
        normalized = tuple(_normalize_pixel_format(value) for value in self.formats)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Image pipeline formats must be unique")
        object.__setattr__(self, "formats", normalized)

    @property
    def default_format(self) -> PixelFormat:
        return self.formats[0]

    def supports(self, pixel_format: PixelFormat) -> bool:
        return pixel_format in self.formats

    def with_default_format(self, pixel_format: PixelFormat) -> ImagePipelineConfig:
        if pixel_format not in self.formats:
            raise ValueError(
                f"Image pipeline does not support raster format {pixel_format.value}"
            )
        if pixel_format == self.formats[0]:
            return self
        reordered = (pixel_format,) + tuple(
            value for value in self.formats if value != pixel_format
        )
        return ImagePipelineConfig(formats=reordered, encoding=self.encoding)


def _normalize_pixel_format(value: object) -> PixelFormat:
    return value if isinstance(value, PixelFormat) else PixelFormat(str(value))
