from __future__ import annotations

import unittest
from collections import deque
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from catlabel import reporting
from catlabel.printing.runtime.base import PreparedRuntimeContext, RuntimeController
from catlabel.printing.runtime.printmaster_esc import PrintMasterRuntimeController
from catlabel.printing.runtime.session import RuntimeConnectionSession
from catlabel.printing.send import send_prepared_job
from catlabel.protocol import (
    ProtocolFamily,
    ProtocolJob,
    ProtocolStep,
    ProtocolWriteChannel,
)
from catlabel.transport.bluetooth import SppBackend
from catlabel.transport.bluetooth.types import DeviceInfo
from catlabel.vendors.generic import client as generic_client_module
from catlabel.vendors.generic.client import GenericClient
from catlabel.vendors.generic.manifest import GenericManifest
from catlabel.vendors.generic.models import PrinterModelRegistry


class _PrintMasterConnection:
    def __init__(
        self,
        *,
        can_wait: bool = True,
        notifications_by_write: tuple[tuple[bytes, ...], ...] = (),
    ) -> None:
        self._can_wait = can_wait
        self._notification_batches = deque(notifications_by_write)
        self._controller: RuntimeController | None = None
        self._runtime_session: RuntimeConnectionSession | None = None
        self._notification_callback: Callable[[bytes], None] | None = None
        self._initialized = False
        self.writes: list[bytes] = []
        self.active_at_write: list[bool] = []
        self.notification_observations: list[tuple[bytes, bool]] = []
        self.wait_calls = 0
        self.wait_timeouts: list[float] = []

    @property
    def notify_started(self) -> bool:
        return self._can_wait

    def can_wait_for_notification(self) -> bool:
        return self._can_wait

    async def attach_runtime_controller(
        self, controller: RuntimeController, *, timeout: float = 1.0
    ) -> None:
        if controller is self._controller and self._initialized:
            return
        if self._controller is not None:
            controller.adopt_previous(self._controller)
        self._controller = controller
        self._runtime_session = RuntimeConnectionSession(
            self, reporter=reporting.DUMMY_REPORTER
        )
        self.register_notify_callback(self._dispatch_notification)
        await controller.initialize_connection(
            self._runtime_session,
            mtu_size=128,
            timeout=timeout,
        )
        self._initialized = True

    def register_notify_callback(
        self, callback: Callable[[bytes], None] | None
    ) -> None:
        self._notification_callback = callback

    def _scope_active(self) -> bool:
        if self._controller is None:
            return False
        return self._controller.debug_snapshot().get("active") is True

    def _dispatch_notification(self, payload: bytes) -> None:
        if self._controller is None or self._runtime_session is None:
            raise AssertionError("notification arrived before controller attachment")
        self._controller.handle_notification(self._runtime_session, payload)

    def deliver_notification(self, payload: bytes) -> None:
        active = self._scope_active()
        self.notification_observations.append((payload, active))
        if self._notification_callback is None:
            raise AssertionError("the notification callback was not registered")
        self._notification_callback(payload)

    def _record_write(self, payload: bytes) -> None:
        self.writes.append(payload)
        self.active_at_write.append(self._scope_active())
        if self._notification_batches:
            for notification in self._notification_batches.popleft():
                self.deliver_notification(notification)

    async def send(self, job: ProtocolJob) -> None:
        if job.steps:
            raise AssertionError("the raw-payload fixture received protocol steps")
        self._record_write(job.payload)

    async def send_standard_payload(self, data: bytes) -> None:
        self._record_write(data)

    async def wait_for_notification(
        self,
        _label: str,
        _match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        _ = required
        self.wait_calls += 1
        self.wait_timeouts.append(timeout)
        return None


def _printmaster_device(variant: str = "printmaster_m110") -> SimpleNamespace:
    return SimpleNamespace(
        protocol_family=ProtocolFamily.PHOMEMO_ESC,
        protocol_variant=variant,
    )


class SendPreparedPrintMasterIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_bytes_and_standard_steps_prearm_scope_for_fragmented_completion(
        self,
    ) -> None:
        jobs = (
            ProtocolJob(payload=b"raster bytes", wait_for_completion=True),
            ProtocolJob(
                steps=(
                    ProtocolStep.send(
                        "raster",
                        b"standard raster bytes",
                        write_channel=ProtocolWriteChannel.STANDARD,
                    ),
                ),
                wait_for_completion=True,
            ),
        )

        for job in jobs:
            with self.subTest(has_steps=bool(job.steps)):
                connection = _PrintMasterConnection(
                    notifications_by_write=((b"\x0f", b"\x0c"),)
                )
                await send_prepared_job(
                    _printmaster_device(), connection, job, timeout=0.01
                )

                self.assertEqual(connection.writes, [job.payload])
                self.assertEqual(connection.active_at_write, [True])
                self.assertEqual(
                    connection.notification_observations,
                    [(b"\x0f", True), (b"\x0c", True)],
                )
                self.assertEqual(connection.wait_calls, 0)

    async def test_completion_then_fault_in_one_live_notification_is_fatal(self):
        connection = _PrintMasterConnection(
            notifications_by_write=((b"\x0f", b"\x0c\x05\x99"),)
        )
        job = ProtocolJob(payload=b"raster bytes", wait_for_completion=True)

        with self.assertRaisesRegex(RuntimeError, "cover_open"):
            await send_prepared_job(
                _printmaster_device(), connection, job, timeout=0.01
            )

        self.assertEqual(connection.writes, [job.payload])
        self.assertEqual(
            connection.notification_observations,
            [(b"\x0f", True), (b"\x0c\x05\x99", True)],
        )
        self.assertEqual(connection.wait_calls, 0)

    async def test_live_fault_is_still_fatal_when_completion_wait_is_not_requested(
        self,
    ) -> None:
        connection = _PrintMasterConnection(notifications_by_write=((b"\x06\x88",),))
        job = ProtocolJob(payload=b"raster bytes", wait_for_completion=False)

        with self.assertRaisesRegex(RuntimeError, "paper_out"):
            await send_prepared_job(
                _printmaster_device(), connection, job, timeout=0.01
            )

        self.assertEqual(connection.writes, [job.payload])
        self.assertEqual(connection.notification_observations, [(b"\x06\x88", True)])
        self.assertEqual(connection.wait_calls, 0)

    async def test_unobservable_waiting_session_fails_before_any_write(self):
        connection = _PrintMasterConnection(can_wait=False)
        job = ProtocolJob(
            steps=(
                ProtocolStep.send(
                    "raster",
                    b"standard raster bytes",
                    write_channel=ProtocolWriteChannel.STANDARD,
                ),
            ),
            wait_for_completion=True,
        )

        with self.assertRaisesRegex(RuntimeError, "observer unavailable"):
            await send_prepared_job(
                _printmaster_device(), connection, job, timeout=0.01
            )

        self.assertEqual(connection.writes, [])
        self.assertEqual(connection.wait_calls, 0)

    async def test_stale_partial_reply_cannot_complete_next_job(self):
        connection = _PrintMasterConnection(
            notifications_by_write=((b"\x0c",), (b"\x0f\x0c",))
        )
        controller = PrintMasterRuntimeController()
        runtime_context = PreparedRuntimeContext(runtime_controller=controller)
        await connection.attach_runtime_controller(controller, timeout=0.01)
        connection.deliver_notification(b"\x0f")

        with self.assertRaisesRegex(RuntimeError, "completion timed out"):
            await send_prepared_job(
                _printmaster_device(),
                connection,
                ProtocolJob(payload=b"first page", wait_for_completion=True),
                timeout=0.01,
                runtime_context=runtime_context,
            )

        self.assertEqual(connection.wait_calls, 1)
        await send_prepared_job(
            _printmaster_device(),
            connection,
            ProtocolJob(payload=b"next page", wait_for_completion=True),
            timeout=0.01,
            runtime_context=runtime_context,
        )

        self.assertEqual(connection.writes, [b"first page", b"next page"])
        self.assertEqual(
            connection.notification_observations,
            [
                (b"\x0f", False),
                (b"\x0c", True),
                (b"\x0f\x0c", True),
            ],
        )
        self.assertEqual(connection.wait_calls, 1)


class _PassiveClassicBackend(SppBackend):
    def __init__(self) -> None:
        super().__init__()
        self.notification_callback: Callable[[bytes], None] | None = None
        self.writes: list[bytes] = []
        self.active_at_write: list[bool] = []
        self.client: GenericClient | None = None
        self.attempts: list[tuple[DeviceInfo, ...]] = []

    def can_receive_passively(self) -> bool:
        return True

    def can_wait_for_notification(self) -> bool:
        return True

    def register_notify_callback(
        self, callback: Callable[[bytes], None] | None
    ) -> None:
        self.notification_callback = callback

    async def connect_attempts(
        self,
        attempts: list[DeviceInfo],
        pairing_hint: bool | None = None,
    ) -> None:
        _ = pairing_hint
        self.attempts.append(tuple(attempts))

    async def write(
        self,
        data: bytes,
        chunk_size: int,
        delay_ms: int = 0,
        interval_ms: int | None = None,
    ) -> None:
        _ = chunk_size, delay_ms, interval_ms
        self.writes.append(bytes(data))
        if self.client is None or self.client._runtime_connection is None:
            raise AssertionError("generic runtime connection was not initialized")
        controller = self.client._runtime_connection._controller
        if controller is None:
            raise AssertionError("PrintMaster controller was not attached")
        self.active_at_write.append(controller.debug_snapshot().get("active") is True)
        if self.notification_callback is None:
            raise AssertionError(
                "generic client did not register a notification callback"
            )
        # Deliver a fragmented completion through the callback installed by the
        # generic client's passive Classic connection wrapper.
        self.notification_callback(b"\x0f")
        self.notification_callback(b"\x0c")

    async def disconnect(self) -> None:
        self.register_notify_callback(None)


class GenericPrintMasterClientIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def _print_two_pages(self, variant: str, profile_energy: int | None) -> None:
        model = PrinterModelRegistry.load().get(variant)
        self.assertIsNotNone(model)
        if model is None:
            self.fail(f"missing catalog model {variant}")

        name = "M120" if variant == "printmaster_m120" else "M110"
        device = SimpleNamespace(
            name=name,
            address="00:11:22:33:44:55",
            paired=True,
            model=model,
        )
        hardware_info = GenericManifest().identify_device(
            device.name, device, device.address
        )
        self.assertIsNotNone(hardware_info)
        if hardware_info is None:
            self.fail(f"{name} should resolve through the generic manifest")

        client = GenericClient(
            device,
            hardware_info,
            SimpleNamespace(
                paper_mode=None,
                speed=None,
                energy=profile_energy,
                feed_lines=None,
            ),
            SimpleNamespace(speed=10, energy=5000, feed_lines=50),
        )
        backend = _PassiveClassicBackend()
        backend.client = client
        client.backend = backend
        images = [
            Image.new("RGB", (384, 2), "white"),
            Image.new("RGB", (384, 2), "black"),
        ]
        send_spy = AsyncMock(wraps=generic_client_module.send_prepared_job)
        sleep_spy = AsyncMock()

        try:
            with (
                patch.object(
                    generic_client_module,
                    "send_prepared_job",
                    new=send_spy,
                ),
                patch.object(generic_client_module.asyncio, "sleep", new=sleep_spy),
            ):
                await client.print_images(images, dither=False)
        finally:
            await client.disconnect()
            for image in images:
                image.close()

        self.assertEqual(len(send_spy.await_args_list), 2)
        jobs = [call.args[2] for call in send_spy.await_args_list]
        self.assertTrue(all(job.wait_for_completion for job in jobs))
        self.assertEqual(len(backend.writes), 2)
        self.assertEqual(backend.active_at_write, [True, True])
        self.assertEqual(sleep_spy.await_count, 0)

        density_command = b"\x1f\x11\x02\x03"
        speed_prefix = b"\x1f\x11\x23"
        density_prefix = b"\x1f\x11\x02"
        multi_page_command = b"\x1f\x11\x21\x01"
        for payload in backend.writes:
            with self.subTest(variant=variant, profile_energy=profile_energy):
                init_index = payload.index(b"\x1b\x40")
                after_init = payload[init_index + 2 :]
                if variant == "printmaster_m120":
                    self.assertTrue(after_init.startswith(multi_page_command))
                else:
                    self.assertFalse(after_init.startswith(multi_page_command))
                    self.assertNotIn(multi_page_command, payload)

                self.assertNotIn(speed_prefix, payload)
                self.assertNotIn(b"\x1b\x4a", payload)
                self.assertNotIn(b"\x1b\x64", payload)
                if profile_energy == 3:
                    self.assertTrue(payload.startswith(density_command + b"\x1b\x40"))
                    self.assertEqual(payload.count(density_command), 1)
                else:
                    self.assertNotIn(density_prefix, payload)

    async def test_public_m110_and_m120_paths_respect_page_and_setting_contracts(
        self,
    ) -> None:
        for variant in ("printmaster_m110", "printmaster_m120"):
            for profile_energy in (None, 3):
                with self.subTest(variant=variant, profile_energy=profile_energy):
                    await self._print_two_pages(variant, profile_energy)


if __name__ == "__main__":
    unittest.main()
