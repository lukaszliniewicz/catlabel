from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ...raster import PixelFormat, RasterBuffer, RasterSet
from ..family import ProtocolFamily, ProtocolSpec
from ..packet import prefixed_packet_length
from ..plan import ProtocolPlan
from ..runtime import RuntimePrintCapabilities
from ..types import ImageEncoding, ImagePipelineConfig, PageFlow, PaperMode

ManualMotionBuilder = Callable[[int, ProtocolFamily, str | None], bytes]

FamilyJobBuilder = Callable[["PrintJobRequest"], "bytes | ProtocolPlan | None"]
PaperModeResolver = Callable[[str | None], tuple[PaperMode, ...]]


@dataclass(frozen=True)
class ProtocolBehavior:
    implemented: bool = True
    default_image_pipeline: ImagePipelineConfig = field(
        default_factory=lambda: ImagePipelineConfig(
            formats=(PixelFormat.BW1,),
            encoding=ImageEncoding.LEGACY_RAW,
        )
    )
    image_encoding_support: Mapping[ImageEncoding, tuple[PixelFormat, ...]] = field(
        default_factory=dict
    )
    supported_protocol_variants: tuple[str, ...] = ()
    supported_paper_modes: tuple[PaperMode, ...] = ()
    supported_paper_modes_resolver: PaperModeResolver | None = None
    advance_paper_builder: ManualMotionBuilder | None = None
    retract_paper_builder: ManualMotionBuilder | None = None
    job_builder: FamilyJobBuilder | None = None


@dataclass(frozen=True)
class PrintJobRequest:
    raster_set: RasterSet
    image_pipeline: ImagePipelineConfig
    is_text: bool
    speed: int
    energy: int
    blackening: int
    lsb_first: bool
    protocol_family: ProtocolFamily
    protocol_variant: str | None
    feed_padding: int
    dev_dpi: int
    can_print_label: bool = False
    density: int | None = None
    post_print_feed_count: int = 2
    paper_mode: PaperMode | None = None
    page_index: int = 1
    page_count: int = 1
    left_padding_pixels: int = 0
    one_length: int = 0
    a4xii: bool = False
    a4_sheet_max_height: int | None = None
    runtime_capabilities: RuntimePrintCapabilities | None = None
    page_flow: PageFlow = PageFlow.PAGED

    def __post_init__(self) -> None:
        if not isinstance(self.page_flow, PageFlow):
            object.__setattr__(self, "page_flow", PageFlow(self.page_flow))

    def require_raster(self, pixel_format: PixelFormat) -> RasterBuffer:
        return self.raster_set.require(pixel_format)

    @property
    def default_raster(self) -> RasterBuffer:
        return self.require_raster(self.image_pipeline.default_format)

    @property
    def width(self) -> int:
        return self.default_raster.width

    @property
    def height(self) -> int:
        return self.default_raster.height

    @property
    def is_first_page(self) -> bool:
        return self.page_index <= 1

    @property
    def is_last_page(self) -> bool:
        return self.page_index >= self.page_count

    @property
    def starts_media_page(self) -> bool:
        return self.page_flow is PageFlow.PAGED or self.is_first_page

    @property
    def ends_media_page(self) -> bool:
        return self.page_flow is PageFlow.PAGED or self.is_last_page


@dataclass(frozen=True)
class SplitWritePlan:
    commands: tuple[bytes, ...]
    bulk_payload: bytes
    trailing_commands: tuple[bytes, ...]


@dataclass(frozen=True)
class ProtocolDefinition:
    spec: ProtocolSpec
    behavior: ProtocolBehavior


def split_prefixed_bulk_stream(
    data: bytes,
    protocol_family: ProtocolFamily | str,
    trailing_packets: tuple[bytes, ...] = (),
) -> SplitWritePlan:
    family = ProtocolFamily.from_value(protocol_family)
    if not family.uses_prefixed_packets:
        return SplitWritePlan((data,), b"", ())
    commands: list[bytes] = []
    trailing_commands: list[bytes] = []
    offset = 0

    while True:
        packet_len = prefixed_packet_length(data, offset, family)
        if packet_len is None:
            break
        commands.append(data[offset : offset + packet_len])
        offset += packet_len

    if offset == len(data):
        return SplitWritePlan(tuple(commands), b"", tuple(trailing_commands))

    tail = len(data)
    for packet in trailing_packets:
        if data.endswith(packet) and tail - len(packet) >= offset:
            trailing_commands.insert(0, packet)
            tail -= len(packet)

    bulk_payload = data[offset:tail]
    if not commands and not trailing_commands:
        return SplitWritePlan((data,), b"", ())
    return SplitWritePlan(tuple(commands), bulk_payload, tuple(trailing_commands))
