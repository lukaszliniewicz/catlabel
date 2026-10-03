from __future__ import annotations

import asyncio
import unittest
from collections.abc import Awaitable, Callable
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from catlabel.api import routes_print
from catlabel.core.resource_limits import ResourceLimitError
from catlabel.printing.admission import DeviceAdmission, canonical_device_address
from catlabel.vendors import VendorRegistry


class _FakeClient:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.print_calls = 0
        self.print_arguments: list[tuple[list[object], bool, bool]] = []
        self.connect_hook: Callable[[], Awaitable[bool]] | None = None
        self.print_hook: Callable[[], Awaitable[None]] | None = None
        self.disconnect_hook: Callable[[], Awaitable[None]] | None = None
        self.validation_error: ResourceLimitError | None = None
        self.planned_labels: int | None = None

    def validate_images(self, images: list[object], split_mode: bool = False) -> int:
        if self.validation_error is not None:
            raise self.validation_error
        return self.planned_labels if self.planned_labels is not None else len(images)

    async def connect(self) -> bool:
        self.connect_calls += 1
        if self.connect_hook is not None:
            return await self.connect_hook()
        return True

    async def print_images(
        self, images: list[object], split_mode: bool = False, dither: bool = True
    ) -> None:
        self.print_calls += 1
        self.print_arguments.append((images, split_mode, dither))
        if self.print_hook is not None:
            await self.print_hook()

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.disconnect_hook is not None:
            await self.disconnect_hook()


class _PrintFailure(RuntimeError):
    def __init__(self, message: str, *, stage: str, delivery_uncertain: bool) -> None:
        super().__init__(message)
        self.stage = stage
        self.delivery_uncertain = delivery_uncertain


def _error_detail(failure: HTTPException) -> dict[str, Any]:
    if not isinstance(failure.detail, dict):
        raise AssertionError("expected a structured print error detail")
    return cast(dict[str, Any], failure.detail)


class PrintAdmissionRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

        for target, value in (
            ("engine", self.engine),
            ("_scanned_devices_cache", []),
            ("printer_admission", DeviceAdmission()),
        ):
            patcher = patch.object(routes_print, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.clients: dict[str, _FakeClient] = {}
        self.devices: list[SimpleNamespace] = []
        self.scan_calls = 0

        async def scan_with_failures(**_kwargs):
            self.scan_calls += 1
            return self.devices, []

        scan_patcher = patch.object(
            routes_print.SppBackend,
            "scan_with_failures",
            staticmethod(scan_with_failures),
        )
        scan_patcher.start()
        self.addCleanup(scan_patcher.stop)

        identify_patcher = patch.object(
            VendorRegistry,
            "identify_device",
            return_value={"vendor": "generic", "model_id": "test"},
        )
        identify_patcher.start()
        self.addCleanup(identify_patcher.stop)

        manifest = SimpleNamespace(get_client=self._get_client)
        manifest_patcher = patch.object(
            VendorRegistry, "get_manifest", return_value=manifest
        )
        manifest_patcher.start()
        self.addCleanup(manifest_patcher.stop)

        for logger_method in ("error", "exception"):
            logger_patcher = patch.object(routes_print.logger, logger_method)
            logger_patcher.start()
            self.addCleanup(logger_patcher.stop)

        self.device, self.client = self._add_device("AA:BB:CC:DD:EE:FF")
        routes_print._scanned_devices_cache = [self.device]

    def _add_device(self, address: str) -> tuple[SimpleNamespace, _FakeClient]:
        device = SimpleNamespace(
            name="Test Printer",
            address=address,
            paired=True,
        )
        client = _FakeClient()
        self.devices.append(device)
        self.clients[canonical_device_address(address)] = client
        return device, client

    def _get_client(self, device, *_args):
        return self.clients[canonical_device_address(device.address)]

    async def _execute(self, address: str = "AA:BB:CC:DD:EE:FF", images=None):
        return await routes_print.execute_print_jobs(
            address,
            [object()] if images is None else images,
        )

    async def _execute_error(self, address: str = "AA:BB:CC:DD:EE:FF") -> HTTPException:
        with self.assertRaises(HTTPException) as raised:
            await self._execute(address)
        return raised.exception

    async def test_equivalent_mac_contender_is_rejected_before_scan_or_connect(self):
        printing = asyncio.Event()
        release = asyncio.Event()

        async def hold_print() -> None:
            printing.set()
            await release.wait()

        self.client.print_hook = hold_print
        first_job = asyncio.create_task(self._execute())
        await asyncio.wait_for(printing.wait(), timeout=2)
        # Force a would-be contender to need discovery if admission were later.
        routes_print._scanned_devices_cache = []

        try:
            busy = await self._execute_error("aa-bb-cc-dd-ee-ff")
            detail = _error_detail(busy)
            self.assertEqual(busy.status_code, 409)
            self.assertEqual(detail["stage"], "admission")
            self.assertFalse(detail["delivery_uncertain"])
            self.assertEqual(self.scan_calls, 0)
            self.assertEqual(self.client.connect_calls, 1)
        finally:
            release.set()
            first_receipt = await first_job

        self.assertEqual(first_receipt["status"], "submitted")

    async def test_different_printers_can_print_concurrently(self):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        second_started = asyncio.Event()

        async def hold_first_print() -> None:
            first_started.set()
            await release_first.wait()

        async def start_second_print() -> None:
            second_started.set()

        first_device = self.device
        first_client = self.client
        first_client.print_hook = hold_first_print
        second_device, second_client = self._add_device("11:22:33:44:55:66")
        second_client.print_hook = start_second_print
        routes_print._scanned_devices_cache = [first_device, second_device]

        first_job = asyncio.create_task(self._execute(first_device.address))
        await asyncio.wait_for(first_started.wait(), timeout=2)
        second_job = asyncio.create_task(self._execute(second_device.address))
        try:
            await asyncio.wait_for(second_started.wait(), timeout=2)
        finally:
            release_first.set()
            first_receipt, second_receipt = await asyncio.gather(first_job, second_job)

        self.assertEqual(first_receipt["status"], "submitted")
        self.assertEqual(second_receipt["status"], "submitted")
        self.assertEqual(first_client.connect_calls, 1)
        self.assertEqual(second_client.connect_calls, 1)

    async def test_owned_route_claims_before_preparation_and_rejects_same_mac(self):
        preparing = asyncio.Event()
        release_preparation = asyncio.Event()
        images: list[Image.Image] = []

        async def block_render(*_args):
            preparing.set()
            await release_preparation.wait()
            image = Image.new("RGB", (2, 2), (1, 2, 3))
            images.append(image)
            return [image]

        request = routes_print.DirectPrintRequest(
            mac_address=self.device.address, canvas_state={}
        )
        with patch.object(
            routes_print,
            "render_via_browser_async",
            new=AsyncMock(side_effect=block_render),
        ) as render:
            first_job = asyncio.create_task(routes_print.print_direct(request))
            try:
                await asyncio.wait_for(preparing.wait(), timeout=2)
                with self.assertRaises(HTTPException) as raised:
                    await asyncio.wait_for(
                        routes_print.print_direct(request), timeout=2
                    )
                self.assertEqual(raised.exception.status_code, 409)
                self.assertEqual(_error_detail(raised.exception)["stage"], "admission")
                render.assert_awaited_once()
                self.assertEqual(self.client.connect_calls, 0)
            except BaseException:
                release_preparation.set()
                if not first_job.done():
                    first_job.cancel()
                with suppress(BaseException):
                    await first_job
                raise
            release_preparation.set()

            receipt = await first_job

        self.assertEqual(receipt["status"], "submitted")
        self.assertEqual(receipt["mac_address"], self.device.address)
        self.assertEqual(self.client.print_calls, 1)
        self.assertEqual(len(images), 1)
        with self.assertRaises(ValueError):
            images[0].getpixel((0, 0))

    async def test_distinct_printer_routes_can_prepare_concurrently(self):
        first_device = self.device
        second_device, first_other_client = self._add_device("11:22:33:44:55:66")
        routes_print._scanned_devices_cache = [first_device, second_device]
        render_started = [asyncio.Event(), asyncio.Event()]
        release_preparation = asyncio.Event()
        images: list[Image.Image] = []
        render_count = 0

        async def block_each_render(*_args):
            nonlocal render_count
            index = render_count
            render_count += 1
            render_started[index].set()
            await release_preparation.wait()
            image = Image.new("RGB", (2, 2), (index, index, index))
            images.append(image)
            return [image]

        first_request = routes_print.DirectPrintRequest(
            mac_address=first_device.address, canvas_state={}
        )
        second_request = routes_print.DirectPrintRequest(
            mac_address=second_device.address, canvas_state={}
        )
        with patch.object(
            routes_print,
            "render_via_browser_async",
            new=AsyncMock(side_effect=block_each_render),
        ) as render:
            first_job = asyncio.create_task(routes_print.print_direct(first_request))
            second_job = asyncio.create_task(routes_print.print_direct(second_request))
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(event.wait() for event in render_started)),
                    timeout=2,
                )
                self.assertEqual(render_count, 2)
                self.assertEqual(self.client.connect_calls, 0)
                self.assertEqual(first_other_client.connect_calls, 0)
            finally:
                release_preparation.set()

            first_receipt, second_receipt = await asyncio.gather(first_job, second_job)
            self.assertEqual(render.await_count, 2)

        self.assertEqual(first_receipt["status"], "submitted")
        self.assertEqual(second_receipt["status"], "submitted")
        self.assertEqual(self.client.connect_calls, 1)
        self.assertEqual(first_other_client.connect_calls, 1)
        self.assertEqual(len(images), 2)
        for image in images:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))

    async def test_opaque_ids_differing_in_punctuation_are_independent(self):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        second_started = asyncio.Event()

        async def hold_first_print() -> None:
            first_started.set()
            await release_first.wait()

        async def start_second_print() -> None:
            second_started.set()

        first_device, first_client = self._add_device("WinRT:Device/A-B")
        second_device, second_client = self._add_device("winrt:device/ab")
        first_client.print_hook = hold_first_print
        second_client.print_hook = start_second_print
        routes_print._scanned_devices_cache = [first_device, second_device]

        first_job = asyncio.create_task(self._execute(first_device.address))
        await asyncio.wait_for(first_started.wait(), timeout=2)
        second_job = asyncio.create_task(self._execute(second_device.address))
        try:
            await asyncio.wait_for(second_started.wait(), timeout=2)
        finally:
            release_first.set()
            first_receipt, second_receipt = await asyncio.gather(first_job, second_job)

        self.assertEqual(first_receipt["status"], "submitted")
        self.assertEqual(second_receipt["status"], "submitted")
        self.assertEqual(first_client.connect_calls, 1)
        self.assertEqual(second_client.connect_calls, 1)

    async def test_false_connect_disconnects_and_releases_the_address(self):
        async def refuse_connection() -> bool:
            return False

        self.client.connect_hook = refuse_connection
        failure = await self._execute_error()
        detail = _error_detail(failure)

        self.assertEqual(failure.status_code, 503)
        self.assertEqual(detail["stage"], "connect")
        self.assertFalse(detail["delivery_uncertain"])
        self.assertEqual(self.client.disconnect_calls, 1)
        self.assertEqual(self.client.print_calls, 0)

        self.client.connect_hook = None
        receipt = await self._execute()
        self.assertEqual(receipt["status"], "submitted")

    async def test_connect_exception_disconnects_and_releases_the_address(self):
        async def fail_connection() -> bool:
            raise PermissionError("Bluetooth access denied")

        self.client.connect_hook = fail_connection
        failure = await self._execute_error()
        detail = _error_detail(failure)

        self.assertEqual(failure.status_code, 503)
        self.assertEqual(detail["stage"], "connect")
        self.assertEqual(detail["error"], "Bluetooth access denied")
        self.assertFalse(detail["delivery_uncertain"])
        self.assertEqual(self.client.disconnect_calls, 1)

        self.client.connect_hook = None
        receipt = await self._execute()
        self.assertEqual(receipt["status"], "submitted")

    async def test_owned_images_close_after_print_failure(self):
        image = Image.new("RGB", (2, 2), (3, 4, 5))

        async def fail_write() -> None:
            raise RuntimeError("printer rejected the owned image")

        self.client.print_hook = fail_write
        request = routes_print.DirectPrintRequest(
            mac_address=self.device.address, canvas_state={}
        )
        with (
            patch.object(
                routes_print,
                "render_via_browser_async",
                new=AsyncMock(return_value=[image]),
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            await routes_print.print_direct(request)

        self.assertEqual(_error_detail(raised.exception)["stage"], "print")
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    async def test_cancellation_during_connect_disconnects_and_releases_claim(self):
        connecting = asyncio.Event()
        hold_connection = asyncio.Event()

        async def hold_first_connection() -> bool:
            if self.client.connect_calls == 1:
                connecting.set()
                await hold_connection.wait()
            return True

        self.client.connect_hook = hold_first_connection
        first_job = asyncio.create_task(self._execute())
        await asyncio.wait_for(connecting.wait(), timeout=2)
        first_job.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first_job

        self.assertEqual(self.client.disconnect_calls, 1)
        self.client.connect_hook = None
        receipt = await self._execute()
        self.assertEqual(receipt["status"], "submitted")

    async def test_cancellation_during_print_disconnects_and_releases_claim(self):
        printing = asyncio.Event()
        hold_print = asyncio.Event()

        async def hold_first_print() -> None:
            if self.client.print_calls == 1:
                printing.set()
                await hold_print.wait()

        self.client.print_hook = hold_first_print
        first_job = asyncio.create_task(self._execute())
        await asyncio.wait_for(printing.wait(), timeout=2)
        first_job.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first_job

        self.assertEqual(self.client.disconnect_calls, 1)
        self.client.print_hook = None
        receipt = await self._execute()
        self.assertEqual(receipt["status"], "submitted")

    async def test_repeated_cancel_during_disconnect_holds_claim_and_closes_owned_image(
        self,
    ):
        printing = asyncio.Event()
        release_print = asyncio.Event()
        disconnecting = asyncio.Event()
        release_disconnect = asyncio.Event()
        image = Image.new("RGB", (2, 2), (6, 7, 8))

        async def hold_print() -> None:
            printing.set()
            await release_print.wait()

        async def hold_disconnect() -> None:
            disconnecting.set()
            await release_disconnect.wait()

        self.client.print_hook = hold_print
        self.client.disconnect_hook = hold_disconnect
        request = routes_print.DirectPrintRequest(
            mac_address=self.device.address, canvas_state={}
        )
        with patch.object(
            routes_print,
            "render_via_browser_async",
            new=AsyncMock(return_value=[image]),
        ) as render:
            first_job = asyncio.create_task(routes_print.print_direct(request))
            try:
                await asyncio.wait_for(printing.wait(), timeout=2)
                first_job.cancel("print-cancel-first")
                await asyncio.wait_for(disconnecting.wait(), timeout=2)
                first_job.cancel("print-cancel-second")
                await asyncio.sleep(0.05)
                self.assertFalse(first_job.done())

                with self.assertRaises(HTTPException) as busy:
                    await routes_print.print_direct(request)
                self.assertEqual(busy.exception.status_code, 409)
                self.assertEqual(_error_detail(busy.exception)["stage"], "admission")
                render.assert_awaited_once()

                release_print.set()
                release_disconnect.set()
                with self.assertRaises(asyncio.CancelledError) as raised:
                    await asyncio.wait_for(first_job, timeout=2)
                self.assertEqual(raised.exception.args, ("print-cancel-first",))
            finally:
                release_print.set()
                release_disconnect.set()
                if not first_job.done():
                    first_job.cancel()
                    with suppress(BaseException):
                        await asyncio.wait_for(first_job, timeout=2)

        with self.assertRaises(ValueError):
            image.getpixel((0, 0))
        self.assertEqual(self.client.disconnect_calls, 1)
        self.client.print_hook = None
        self.client.disconnect_hook = None
        receipt = await self._execute()
        self.assertEqual(receipt["status"], "submitted")

    async def test_cancel_during_success_disconnect_drains_and_holds_claim(self):
        disconnecting = asyncio.Event()
        release_disconnect = asyncio.Event()

        async def hold_disconnect() -> None:
            disconnecting.set()
            await release_disconnect.wait()

        self.client.disconnect_hook = hold_disconnect
        first_job = asyncio.create_task(self._execute())
        try:
            await asyncio.wait_for(disconnecting.wait(), timeout=2)
            self.assertEqual(self.client.print_calls, 1)
            first_job.cancel("disconnect-cancel-first")
            await asyncio.sleep(0.05)
            self.assertFalse(first_job.done())

            busy = await self._execute_error()
            self.assertEqual(busy.status_code, 409)
            self.assertEqual(_error_detail(busy)["stage"], "admission")

            release_disconnect.set()
            with self.assertRaises(asyncio.CancelledError) as raised:
                await asyncio.wait_for(first_job, timeout=2)
            self.assertEqual(raised.exception.args, ("disconnect-cancel-first",))
        finally:
            release_disconnect.set()
            if not first_job.done():
                first_job.cancel()
                with suppress(BaseException):
                    await asyncio.wait_for(first_job, timeout=2)
        self.client.disconnect_hook = None
        receipt = await self._execute()
        self.assertEqual(receipt["status"], "submitted")

    async def test_disconnect_error_does_not_hide_print_failure_or_retain_claim(self):
        async def fail_print() -> None:
            raise RuntimeError("printer rejected the write")

        async def fail_disconnect() -> None:
            raise RuntimeError("disconnect failed")

        self.client.print_hook = fail_print
        self.client.disconnect_hook = fail_disconnect
        failure = await self._execute_error()
        detail = _error_detail(failure)

        self.assertEqual(failure.status_code, 500)
        self.assertEqual(detail["stage"], "print")
        self.assertEqual(detail["error"], "printer rejected the write")
        self.assertTrue(detail["delivery_uncertain"])

        self.client.print_hook = None
        receipt = await self._execute()
        self.assertEqual(receipt["status"], "submitted")
        self.assertEqual(self.client.disconnect_calls, 2)

    async def test_print_uncertainty_preserves_explicit_false_and_unknown_true(self):
        async def fail_before_write() -> None:
            raise _PrintFailure(
                "printer rejected setup",
                stage="setup",
                delivery_uncertain=False,
            )

        self.client.print_hook = fail_before_write
        setup_failure = await self._execute_error()
        setup_detail = _error_detail(setup_failure)
        self.assertEqual(setup_detail["stage"], "setup")
        self.assertFalse(setup_detail["delivery_uncertain"])

        async def fail_during_write() -> None:
            raise RuntimeError("connection lost after the write started")

        self.client.print_hook = fail_during_write
        write_failure = await self._execute_error()
        write_detail = _error_detail(write_failure)
        self.assertEqual(write_detail["stage"], "print")
        self.assertTrue(write_detail["delivery_uncertain"])

    async def test_validation_rejection_precedes_connect_and_releases_claim(self):
        self.client.validation_error = ResourceLimitError("split job exceeds limit")
        failure = await self._execute_error()
        self.assertEqual(failure.status_code, 422)
        self.assertEqual(_error_detail(failure)["stage"], "validation")
        self.assertFalse(_error_detail(failure)["delivery_uncertain"])
        self.assertEqual(self.client.connect_calls, 0)
        self.assertEqual(self.client.print_calls, 0)
        self.assertEqual(self.client.disconnect_calls, 0)
        self.client.validation_error = None
        self.assertEqual((await self._execute())["status"], "submitted")

    async def test_receipt_uses_preflight_split_label_count(self):
        self.client.planned_labels = 3
        receipt = await self._execute(images=[object()])
        self.assertEqual(receipt["submitted"], 3)
        self.assertEqual(receipt["physical_completion"], "unverified")

    async def test_success_receipt_reports_submission_count_not_physical_printing(self):
        images = [object(), object(), object()]
        receipt = await self._execute(images=images)

        self.assertEqual(receipt["status"], "submitted")
        self.assertEqual(receipt["submitted"], len(images))
        self.assertEqual(receipt["physical_completion"], "unverified")
        self.assertNotIn("printed", receipt)
        self.assertEqual(self.client.print_arguments[0][0], images)

    async def test_borrowed_execute_print_jobs_does_not_close_inputs(self):
        class BorrowedImage:
            def __init__(self) -> None:
                self.close_calls = 0

            def close(self) -> None:
                self.close_calls += 1

        image = BorrowedImage()
        receipt = await routes_print.execute_print_jobs(self.device.address, [image])

        self.assertEqual(receipt["status"], "submitted")
        self.assertEqual(image.close_calls, 0)
        self.assertIs(self.client.print_arguments[0][0][0], image)


if __name__ == "__main__":
    unittest.main()
