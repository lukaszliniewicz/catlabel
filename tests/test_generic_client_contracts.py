from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from catlabel.transport.bluetooth import SppBackend
from catlabel.vendors.generic.client import (
    GenericClient,
    _blackening_level_for_density,
    _GenericBackendConnection,
)


class _AttachBackend(SppBackend):
    def __init__(self) -> None:
        self.attach_calls: list[tuple[object, float]] = []

    async def attach_runtime_controller(
        self,
        runtime_controller: object,
        *,
        timeout: float = 1.0,
    ) -> None:
        self.attach_calls.append((runtime_controller, timeout))


class GenericClientContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_runtime_attach_is_awaited_and_forwards_timeout(self) -> None:
        backend = _AttachBackend()
        connection = _GenericBackendConnection(backend, chunk_size=64, delay_ms=0)
        controller = object()

        await connection.attach_runtime_controller(controller, timeout=0.25)

        self.assertEqual(backend.attach_calls, [(controller, 0.25)])

    def test_effective_image_pipeline_rejects_missing_model(self) -> None:
        client = GenericClient(
            SimpleNamespace(name="", address="", model=None),
            {"model_id": "missing"},
            SimpleNamespace(paper_mode=None),
            SimpleNamespace(speed=0, energy=0, feed_lines=0),
        )
        client.model = None

        with self.assertRaises(HTTPException) as raised:
            client._effective_image_pipeline()

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(raised.exception.detail, "Unable to resolve printer model.")

    def test_density_levels_accept_supported_scalar_types(self) -> None:
        values = (50, 50.9, "50", b"50", bytearray(b"50"))
        for value in values:
            with self.subTest(value=type(value).__name__):
                self.assertEqual(
                    _blackening_level_for_density(
                        25,
                        {"low": value, "middle": 100, "high": 150},
                    ),
                    1,
                )

    def test_density_levels_reject_unsupported_and_unconvertible_values(self) -> None:
        for value in (object(), "not-an-integer"):
            with (
                self.subTest(value=type(value).__name__),
                self.assertRaisesRegex(ValueError, "image density level 'low'"),
            ):
                _blackening_level_for_density(
                    25,
                    {"low": value, "middle": 100, "high": 150},
                )


if __name__ == "__main__":
    unittest.main()
