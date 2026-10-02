from __future__ import annotations

import asyncio
import unittest
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from fastapi import HTTPException
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


if __name__ == "__main__":
    unittest.main()
