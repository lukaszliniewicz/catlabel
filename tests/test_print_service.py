from __future__ import annotations

import hashlib
import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from catlabel.core.models import PrinterProfile
from catlabel.core.resource_limits import ResourceLimitError
from catlabel.services import print_executor, printers
from catlabel.services.printers import PrinterProfileUpdate, ServiceError


class PrinterServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def test_profile_read_is_pure_until_defaults_are_requested(self) -> None:
        profile = printers.get_printer_profile(
            "AA:BB:CC:DD:EE:FF", db_engine=self.engine
        )
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.mac_address, "AA:BB:CC:DD:EE:FF")
        with Session(self.engine) as session:
            self.assertIsNone(
                session.exec(
                    select(PrinterProfile).where(
                        PrinterProfile.mac_address == profile.mac_address
                    )
                ).first()
            )

        persisted = printers.get_printer_profile(
            "AA:BB:CC:DD:EE:FF", db_engine=self.engine, create_defaults=True
        )
        self.assertIsNotNone(persisted)
        assert persisted is not None

        updated = printers.update_printer_profile(
            persisted.mac_address,
            PrinterProfileUpdate(speed=4, paper_mode="plain"),
            db_engine=self.engine,
        )
        self.assertEqual(updated.speed, 4)
        self.assertEqual(updated.paper_mode, "plain")

        with self.assertRaises(ServiceError) as raised:
            printers.update_printer_profile(
                persisted.mac_address,
                PrinterProfileUpdate(paper_mode="unsupported"),
                db_engine=self.engine,
            )
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Unsupported paper mode")

    async def test_scan_filters_devices_and_updates_the_supplied_cache(self) -> None:
        supported = SimpleNamespace(
            name="Phomemo M02",
            address="AA:BB:CC:DD:EE:FF",
            paired=True,
            transport=SimpleNamespace(value="ble"),
        )
        generic = SimpleNamespace(
            name="Unrecognized",
            address="11:22:33:44:55:66",
            paired=False,
            transport=SimpleNamespace(value="classic"),
        )
        failure = SimpleNamespace(error=OSError("BLE adapter unavailable"))
        calls: list[dict[str, Any]] = []

        class Scanner:
            @staticmethod
            async def scan_with_failures(**kwargs):
                calls.append(kwargs)
                return [supported, generic], [failure]

        registry = SimpleNamespace(
            identify_device=lambda name, *_args: (
                {"vendor": "generic", "model_id": "generic"}
                if name == "Unrecognized"
                else {"vendor": "phomemo", "model_id": "M02"}
            )
        )
        cache: list[Any] = [generic]

        result = await printers.scan_printers(
            scanner=Scanner,
            cache=cache,
            vendor_registry=registry,
        )

        self.assertEqual(calls, [{"include_classic": True, "include_ble": True}])
        self.assertEqual(cache, [supported])
        self.assertEqual(result["failures"], ["BLE adapter unavailable"])
        self.assertEqual(
            result["devices"],
            [
                {
                    "vendor": "phomemo",
                    "model_id": "M02",
                    "name": "Phomemo M02",
                    "address": "AA:BB:CC:DD:EE:FF",
                    "display_address": "AA:BB:CC:DD:EE:FF",
                    "paired": True,
                    "transport": "ble",
                }
            ],
        )

    def test_catalog_hash_uses_canonical_model_json(self) -> None:
        models = [{"name": "B", "id": 2}, {"id": 1, "name": "A"}]
        payload = json.dumps(
            models,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        with patch.object(
            printers.VendorRegistry, "get_all_models", return_value=models
        ):
            self.assertEqual(
                printers.hardware_catalog_hash(), hashlib.sha256(payload).hexdigest()
            )

    async def test_delivery_hook_runs_after_preflight_and_before_connect(self) -> None:
        device = SimpleNamespace(
            name="Fixture Printer", address="AA:BB:CC:DD:EE:FF", paired=True
        )
        events: list[str] = []
        captured: dict[str, Any] = {}

        class Client:
            def validate_images(self, images, split_mode=False):
                events.append("preflight")
                return len(images)

            async def connect(self):
                events.append("connect")
                return True

            async def print_images(self, images, split_mode=False, dither=True):
                events.append("print")

            async def disconnect(self):
                events.append("disconnect")

        client = Client()

        class Manifest:
            def get_client(self, _device, _hardware, profile, settings):
                captured["profile"] = profile
                captured["settings"] = settings
                return client

        registry = SimpleNamespace(
            identify_device=lambda *_args: {
                "vendor": "generic",
                "model_id": "fixture-model",
            },
            get_manifest=lambda _vendor: Manifest(),
            get_all_models=lambda: [{"model_id": "fixture-model"}],
        )
        image = Image.new("RGB", (1, 1))

        async def start_delivery() -> None:
            events.append("delivery-start")

        receipt = await print_executor.execute_owned_print_jobs(
            device.address,
            lambda: _images(image),
            dither=False,
            devices_cache=[device],
            vendor_registry=registry,
            frozen_settings={"speed": 7},
            frozen_profile={"energy": 900},
            expected_hardware={
                "vendor": "generic",
                "model_id": "fixture-model",
                "catalog_sha256": printers.hardware_catalog_hash(
                    vendor_registry=registry
                ),
            },
            on_delivery_start=start_delivery,
        )

        self.assertEqual(
            events,
            ["preflight", "delivery-start", "connect", "print", "disconnect"],
        )
        self.assertEqual(captured["profile"].energy, 900)
        self.assertEqual(captured["settings"].speed, 7)
        self.assertEqual(receipt["status"], "submitted")
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    async def test_expected_hardware_mismatch_stops_before_client_creation(
        self,
    ) -> None:
        device = SimpleNamespace(
            name="Fixture Printer", address="AA:BB:CC:DD:EE:FF", paired=True
        )
        created: list[bool] = []

        class Manifest:
            def get_client(self, *_args):
                created.append(True)
                raise AssertionError("client must not be created for a stale identity")

        registry = SimpleNamespace(
            identify_device=lambda *_args: {
                "vendor": "generic",
                "model_id": "current-model",
            },
            get_manifest=lambda _vendor: Manifest(),
            get_all_models=lambda: [{"model_id": "current-model"}],
        )
        image = Image.new("RGB", (1, 1))

        with self.assertRaises(ServiceError) as raised:
            await print_executor.execute_owned_print_jobs(
                device.address,
                lambda: _images(image),
                devices_cache=[device],
                vendor_registry=registry,
                frozen_settings={},
                frozen_profile={},
                expected_hardware={"model_id": "stale-model"},
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail["code"], "printer_capabilities_changed"
        )
        self.assertFalse(raised.exception.detail["delivery_uncertain"])
        self.assertEqual(created, [])
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    async def test_preflight_failure_does_not_start_delivery_hook(self) -> None:
        device = SimpleNamespace(
            name="Fixture Printer", address="AA:BB:CC:DD:EE:FF", paired=True
        )
        events: list[str] = []

        class Client:
            def validate_images(self, _images, split_mode=False):
                raise ResourceLimitError("too many rendered labels")

            async def connect(self):
                events.append("connect")
                return True

            async def disconnect(self):
                events.append("disconnect")

        class Manifest:
            def get_client(self, *_args):
                return Client()

        registry = SimpleNamespace(
            identify_device=lambda *_args: {
                "vendor": "generic",
                "model_id": "fixture-model",
            },
            get_manifest=lambda _vendor: Manifest(),
            get_all_models=lambda: [],
        )
        image = Image.new("RGB", (1, 1))

        async def start_delivery() -> None:
            events.append("delivery-start")

        with self.assertRaises(ServiceError) as raised:
            await print_executor.execute_owned_print_jobs(
                device.address,
                lambda: _images(image),
                devices_cache=[device],
                vendor_registry=registry,
                frozen_settings={},
                frozen_profile={},
                on_delivery_start=start_delivery,
            )

        self.assertEqual(raised.exception.detail["stage"], "validation")
        self.assertEqual(events, [])
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    async def test_delivery_hook_failure_is_reported_unsent_and_skips_connect(
        self,
    ) -> None:
        device = SimpleNamespace(
            name="Fixture Printer", address="AA:BB:CC:DD:EE:FF", paired=True
        )
        events: list[str] = []

        class Client:
            def validate_images(self, images, split_mode=False):
                events.append("preflight")
                return len(images)

            async def connect(self):
                events.append("connect")
                return True

            async def disconnect(self):
                events.append("disconnect")

        class Manifest:
            def get_client(self, *_args):
                return Client()

        registry = SimpleNamespace(
            identify_device=lambda *_args: {
                "vendor": "generic",
                "model_id": "fixture-model",
            },
            get_manifest=lambda _vendor: Manifest(),
            get_all_models=lambda: [],
        )
        image = Image.new("RGB", (1, 1))

        async def start_delivery() -> None:
            events.append("delivery-start")
            raise OSError("could not persist state")

        with self.assertRaises(ServiceError) as raised:
            await print_executor.execute_owned_print_jobs(
                device.address,
                lambda: _images(image),
                devices_cache=[device],
                vendor_registry=registry,
                frozen_settings={},
                frozen_profile={},
                on_delivery_start=start_delivery,
            )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["stage"], "delivery_start")
        self.assertFalse(raised.exception.detail["delivery_uncertain"])
        self.assertEqual(events, ["preflight", "delivery-start"])
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))


async def _images(image: Image.Image) -> list[Image.Image]:
    return [image]


if __name__ == "__main__":
    unittest.main()
