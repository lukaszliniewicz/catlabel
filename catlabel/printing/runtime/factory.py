from __future__ import annotations

from typing import Any

from ...protocol.family import ProtocolFamily
from .base import RuntimeController
from .funny_lx import FunnyLxRuntimeController
from .luck_a41 import LuckA41RuntimeController
from .luck_normal import LuckNormalRuntimeController
from .printmaster_esc import PrintMasterRuntimeController
from .tiny import TinyRuntimeController
from .v5c import V5CRuntimeController
from .v5g import V5GRuntimeController
from .v5x import V5XRuntimeController
from .yk_astra_p1 import AstraP1RuntimeController


def runtime_controller_for_device(
    device: Any,
    *,
    protocol_family: ProtocolFamily | str | None = None,
    bluetooth_address: str | None = None,
) -> RuntimeController | None:
    """Select live-session behavior from a resolved device/model in printing."""

    family = ProtocolFamily.from_value(
        protocol_family or getattr(device, "protocol_family", None)
    )
    if family in {ProtocolFamily.LEGACY, ProtocolFamily.LEGACY_PREFIXED}:
        return TinyRuntimeController()
    if family is ProtocolFamily.YK_ASTRA_P1:
        return AstraP1RuntimeController(
            paper_query_on_valid=getattr(device, "protocol_variant", None) == "s001"
        )
    if family is ProtocolFamily.V5G:
        density_profile = getattr(device, "runtime_density_profile", None)
        return V5GRuntimeController(
            helper_kind=getattr(device, "runtime_variant", None),
            density_profile_key=(
                getattr(device, "runtime_density_profile_key", None)
                or getattr(density_profile, "profile_key", None)
            ),
            density_profile=(density_profile or getattr(device, "profile", None)),
            density_levels=getattr(device, "runtime_density", None),
        )
    if family is ProtocolFamily.V5X:
        return V5XRuntimeController()
    if family is ProtocolFamily.V5C:
        return V5CRuntimeController()
    if family is ProtocolFamily.PHOMEMO_ESC and getattr(
        device, "protocol_variant", None
    ) in {"printmaster_m110", "printmaster_m120"}:
        return PrintMasterRuntimeController()
    if family is ProtocolFamily.LUCK_NORMAL and getattr(
        device, "protocol_variant", None
    ) in {"lujiang_normal", "lujiang_normal_h"}:
        return LuckNormalRuntimeController(protocol_variant=device.protocol_variant)
    if (
        family is ProtocolFamily.LUCK_NORMAL_A4
        and getattr(device, "protocol_variant", None) == "luckp_a41"
    ):
        return LuckA41RuntimeController()
    if family is ProtocolFamily.FUNNY_LX:
        return FunnyLxRuntimeController(
            bluetooth_address=(bluetooth_address or getattr(device, "address", ""))
        )
    return None
