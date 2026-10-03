from __future__ import annotations

import unittest
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

from catlabel.printing.runtime.factory import runtime_controller_for_device
from catlabel.printing.runtime.luck_a41 import LuckA41RuntimeController
from catlabel.printing.send import send_prepared_job
from catlabel.protocol.families.base import PrintJobRequest
from catlabel.protocol.families.luck_normal_a4 import RECIPE
from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.job import ProtocolJob
from catlabel.protocol.runtime import (
    RuntimeControlRange,
    RuntimePrintCapabilities,
    RuntimePrintControls,
)
from catlabel.protocol.steps import ProtocolReplyExpectation, ProtocolStepOperation
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet


def _capabilities(
    density: RuntimeControlRange | None = None,
    speed: RuntimeControlRange | None = None,
) -> RuntimePrintCapabilities:
    if density is None:
        density = RuntimeControlRange(low=1, default=8, high=15)
    return RuntimePrintCapabilities(
        print_controls=RuntimePrintControls(density=density, speed=speed)
    )


def _request(
    *,
    variant: str = "luckp_a41",
    density: int | None = 8,
    speed: int = 4,
    capabilities: RuntimePrintCapabilities | None = None,
) -> PrintJobRequest:
    return PrintJobRequest(
        raster_set=RasterSet.from_single(RasterBuffer([1] * 8, 8, PixelFormat.BW1)),
        image_pipeline=RECIPE.default_image_pipeline,
        is_text=False,
        speed=speed,
        energy=10000,
        blackening=3,
        lsb_first=False,
        protocol_family=ProtocolFamily.LUCK_NORMAL_A4,
        protocol_variant=variant,
        feed_padding=0,
        dev_dpi=203,
        density=density,
        runtime_capabilities=capabilities,
    )


def _job(request: PrintJobRequest) -> ProtocolJob:
    steps = tuple(RECIPE.build_steps(request))
    return ProtocolJob(
        payload=b"".join(step.data for step in steps if step.include_in_payload),
        steps=steps,
    )


class TransactionConnection:
    def __init__(self, *, overrides: dict[bytes, bytes | None] | None = None) -> None:
        self.overrides = overrides or {}
        self.events: list[tuple[str, bytes, float | None]] = []

    def can_query_control_packet(self) -> bool:
        return True

    def can_send_control_packet_wait_notification(self) -> bool:
        return False

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float,
        reply_complete: Callable[[bytes], bool],
    ) -> bytes | None:
        self.events.append(("query", packet, timeout))
        return self.overrides.get(
            packet, b"\x00" if packet == b"\x10\xff\x40" else b"OK"
        )

    async def send_standard_payload(self, data: bytes) -> None:
        self.events.append(("send", data, None))


class LuckA41ControlTests(unittest.IsolatedAsyncioTestCase):
    def test_runtime_control_ranges_validate_and_capabilities_keep_positions(
        self,
    ) -> None:
        value = RuntimeControlRange(low=0, default=128, high=255)
        self.assertEqual((value.low, value.default, value.high), (0, 128, 255))
        for args in (
            (True, 1, 2),
            (0, cast(int, 1.0), 2),
            (0, 1, False),
            (-1, 0, 1),
            (0, 1, 256),
            (2, 1, 3),
            (0, 3, 2),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                RuntimeControlRange(*args)

        controls = RuntimePrintControls(density=value, speed=None)
        capabilities = RuntimePrintCapabilities(False, 12, controls)
        self.assertIs(capabilities.print_controls, controls)
        self.assertIsNone(controls.speed)

    def test_factory_selects_only_luckp_a41_a4_variant(self) -> None:
        device = SimpleNamespace(
            protocol_family=ProtocolFamily.LUCK_NORMAL_A4,
            protocol_variant="luckp_a41",
        )
        self.assertIsInstance(
            runtime_controller_for_device(device), LuckA41RuntimeController
        )

        for family, variant in (
            (ProtocolFamily.LUCK_NORMAL_A4, "luckp_a42"),
            (ProtocolFamily.LUCK_NORMAL_A4, "lujiang_a4"),
            (ProtocolFamily.LUCK_NORMAL_A4, "apa41"),
            (ProtocolFamily.LUCK_NORMAL_A4, "APA41"),
            (ProtocolFamily.LUCK_NORMAL, "luckp_a41"),
        ):
            with self.subTest(family=family, variant=variant):
                candidate = SimpleNamespace(
                    protocol_family=family, protocol_variant=variant
                )
                self.assertNotIsInstance(
                    runtime_controller_for_device(candidate),
                    LuckA41RuntimeController,
                )

    def test_speed_command_and_range_checks_apply_only_to_probed_a41(self) -> None:
        capabilities = _capabilities(
            speed=RuntimeControlRange(low=0, default=4, high=8)
        )
        steps = RECIPE.build_steps(_request(capabilities=capabilities))
        labels = [step.label for step in steps]
        density_index = labels.index("density")
        speed_index = labels.index("speed")
        status_index = labels.index("status")
        speed = steps[speed_index]

        self.assertLess(density_index, speed_index)
        self.assertLess(speed_index, status_index)
        self.assertEqual(speed.data, b"\x10\xff\xc0\x04")
        self.assertIs(speed.operation, ProtocolStepOperation.QUERY)
        self.assertIs(speed.expect, ProtocolReplyExpectation.OK)
        self.assertTrue(speed.reply_required)
        self.assertEqual(speed.timeout_sec, 3.0)
        self.assertIsNotNone(speed.reply_matcher)
        assert speed.reply_matcher is not None
        assert speed.reply_matcher.matches is not None
        self.assertFalse(speed.reply_matcher.complete(b"O"))
        self.assertTrue(speed.reply_matcher.matches(b"OK extra"))
        self.assertEqual(RECIPE.dialect.set_speed(0), b"\x10\xff\xc0\x00")
        self.assertEqual(RECIPE.dialect.set_speed(255), b"\x10\xff\xc0\xff")
        for invalid_speed in (-1, 256, True):
            with (
                self.subTest(invalid_speed=invalid_speed),
                self.assertRaises(ValueError),
            ):
                RECIPE.dialect.set_speed(invalid_speed)

        controls = capabilities.print_controls
        assert controls is not None
        for requested_density, requested_speed, message in (
            (0, 4, "density"),
            (16, 4, "density"),
            (8, 9, "speed"),
        ):
            with (
                self.subTest(
                    density=requested_density,
                    speed=requested_speed,
                    message=message,
                ),
                self.assertRaisesRegex(ValueError, message),
            ):
                RECIPE.build_steps(
                    _request(
                        density=requested_density,
                        speed=requested_speed,
                        capabilities=RuntimePrintCapabilities(print_controls=controls),
                    )
                )

        old_controls = _capabilities(
            density=RuntimeControlRange(low=0, default=1, high=2), speed=None
        )
        old_steps = RECIPE.build_steps(
            _request(density=1, speed=255, capabilities=old_controls)
        )
        self.assertNotIn("speed", [step.label for step in old_steps])

        uncached_steps = RECIPE.build_steps(_request(capabilities=None))
        self.assertEqual(
            [step.label for step in uncached_steps[:3]], ["density", "status", "enable"]
        )
        self.assertNotIn("speed", [step.label for step in uncached_steps])

        for variant in ("luckp_a42", "lujiang_a4"):
            with self.subTest(variant=variant):
                other_variant_steps = RECIPE.build_steps(
                    _request(variant=variant, capabilities=capabilities)
                )
                self.assertNotIn("speed", [step.label for step in other_variant_steps])

    async def test_speed_ack_failure_stops_before_enable_and_raster(self) -> None:
        job = _job(
            _request(capabilities=_capabilities(speed=RuntimeControlRange(0, 4, 8)))
        )
        device = SimpleNamespace(
            protocol_family=ProtocolFamily.LUCK_NORMAL_A4,
            protocol_variant="luckp_a41",
        )
        speed_packet = b"\x10\xff\xc0\x04"
        for reply in (None, b"NO"):
            with self.subTest(reply=reply):
                connection = TransactionConnection(overrides={speed_packet: reply})

                with self.assertRaisesRegex(RuntimeError, "speed"):
                    await send_prepared_job(device, connection, job)

                self.assertIn(("query", speed_packet, 3.0), connection.events)
                self.assertFalse(
                    any(
                        event[0] == "send"
                        and event[1]
                        in {
                            b"\x10\xff\xf1\x03",
                            next(
                                step.data
                                for step in job.steps
                                if step.label == "bitmap"
                            ),
                        }
                        for event in connection.events
                    )
                )


if __name__ == "__main__":
    unittest.main()
