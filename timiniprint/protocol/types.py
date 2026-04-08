from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence


class PixelFormat(str, Enum):
    BW1 = "bw1"
    GRAY4 = "gray4"
    GRAY8 = "gray8"


class ImageEncoding(str, Enum):
    LEGACY_RAW = "legacy_raw"
    LEGACY_RLE = "legacy_rle"
    V5X_DOT = "v5x_dot"
    V5X_GRAY = "v5x_gray"
    V5C_A4 = "v5c_a4"
    V5C_A5 = "v5c_a5"
    DCK_DEFAULT = "dck_default"


@dataclass(frozen=True)
class ImagePipelineConfig:
    formats: tuple[PixelFormat, ...]
    encoding: ImageEncoding

    def __post_init__(self) -> None:
        if not self.formats:
            raise ValueError("Image pipeline formats must not be empty")
        normalized = tuple(
            value if isinstance(value, PixelFormat) else PixelFormat(str(value))
            for value in self.formats
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("Image pipeline formats must be unique")
        object.__setattr__(self, "formats", normalized)

    @property
    def default_format(self) -> PixelFormat:
        return self.formats[0]

    def supports(self, pixel_format: PixelFormat) -> bool:
        return pixel_format in self.formats

    def with_default_format(self, pixel_format: PixelFormat) -> "ImagePipelineConfig":
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


@dataclass(frozen=True)
class RasterBuffer:
    """Row-major pixel buffer used by protocol-specific encoders."""

    pixels: Sequence[int]
    width: int
    pixel_format: PixelFormat = PixelFormat.BW1

    def validate(self) -> None:
        if self.width <= 0:
            raise ValueError("Width must be greater than zero")
        if len(self.pixels) % self.width != 0:
            raise ValueError("Pixels length must be a multiple of width")

        if self.pixel_format == PixelFormat.BW1:
            invalid = next((value for value in self.pixels if value not in (0, 1)), None)
            if invalid is not None:
                raise ValueError("BW1 raster values must be 0 or 1")
            return

        upper_bound = 15 if self.pixel_format == PixelFormat.GRAY4 else 255
        invalid = next((value for value in self.pixels if value < 0 or value > upper_bound), None)
        if invalid is not None:
            raise ValueError(f"{self.pixel_format.value} raster values must fit in 0..{upper_bound}")

    @property
    def height(self) -> int:
        self.validate()
        return len(self.pixels) // self.width

    def slice_rows(self, start_row: int, row_count: int) -> "RasterBuffer":
        if start_row < 0 or row_count < 0:
            raise ValueError("Row offsets must be non-negative")
        start = start_row * self.width
        end = start + (row_count * self.width)
        return RasterBuffer(
            pixels=list(self.pixels[start:end]),
            width=self.width,
            pixel_format=self.pixel_format,
        )

    def packed_bytes(self) -> bytes:
        self.validate()
        if self.pixel_format == PixelFormat.GRAY8:
            return bytes(self.pixels)
        if self.pixel_format == PixelFormat.GRAY4:
            packed = bytearray()
            pixels = list(self.pixels)
            if len(pixels) % 2 != 0:
                raise ValueError("GRAY4 raster length must be even")
            for idx in range(0, len(pixels), 2):
                packed.append((pixels[idx] << 4) | pixels[idx + 1])
            return bytes(packed)
        raise ValueError("Only grayscale rasters can be packed into bytes")


@dataclass(frozen=True)
class RasterSet:
    rasters: Mapping[PixelFormat, RasterBuffer]

    def validate(self) -> None:
        if not self.rasters:
            raise ValueError("Raster set must not be empty")

        width = None
        height = None
        for pixel_format, raster in self.rasters.items():
            raster.validate()
            if pixel_format != raster.pixel_format:
                raise ValueError("Raster set keys must match raster pixel formats")
            if width is None:
                width = raster.width
                height = raster.height
                continue
            if raster.width != width or raster.height != height:
                raise ValueError("All rasters in a raster set must have matching dimensions")

    @property
    def width(self) -> int:
        self.validate()
        return next(iter(self.rasters.values())).width

    @property
    def height(self) -> int:
        self.validate()
        return next(iter(self.rasters.values())).height

    def get(self, pixel_format: PixelFormat) -> RasterBuffer | None:
        return self.rasters.get(pixel_format)

    def require(self, pixel_format: PixelFormat) -> RasterBuffer:
        raster = self.get(pixel_format)
        if raster is None:
            raise ValueError(f"Missing {pixel_format.value} raster in raster set")
        return raster

    @classmethod
    def from_single(cls, raster: RasterBuffer) -> "RasterSet":
        raster.validate()
        return cls(rasters={raster.pixel_format: raster})
