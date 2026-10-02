from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from catlabel.printing.runtime.v5c import V5CRuntimeController
from catlabel.printing.runtime.v5g import V5GRuntimeController
from catlabel.printing.runtime.v5x import V5XRuntimeController
from catlabel.protocol.families.v5c import (
    V5C_CONNECT_INIT_PACKET,
    V5C_NOTIFY_PAUSE,
    V5C_NOTIFY_RESUME,
)
from catlabel.protocol.families.v5g import (
    V5G_CONNECT_QUERY_PACKET,
    V5G_TEMPERATURE_QUERY_PACKET,
)
from catlabel.protocol.families.v5x import (
    V5X_CONNECT_INIT_PACKET,
    V5X_NOTIFY_PAUSE_PACKETS,
    V5X_NOTIFY_RESUME_PACKETS,
)
from tests.runtime_session_fake import RuntimeSessionFake


class _FakeSession(RuntimeSessionFake):
    def __init__(self) -> None:
        self.control: list[bytes] = []
        self.flow: list[tuple[bool, bytes]] = []
        self.notification_queries: list[bytes] = []

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        self.control.append(packet)
        return True

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None:
        self.flow.append((paused, payload))

    def can_send_control_packet_wait_notification(self) -> bool:
        return True

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match,
        timeout: float,
        required: bool = True,
    ):
        self.notification_queries.append(packet)
        return None


class RuntimeOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_family_runtime_owns_connection_handshake(self) -> None:
        cases = (
            (V5GRuntimeController(), V5G_CONNECT_QUERY_PACKET),
            (V5CRuntimeController(), V5C_CONNECT_INIT_PACKET),
            (V5XRuntimeController(), V5X_CONNECT_INIT_PACKET),
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            for controller, expected in cases:
                with self.subTest(controller=type(controller).__name__):
                    session = _FakeSession()
                    await controller.initialize_connection(
                        session,
                        mtu_size=180,
                        timeout=0.1,
                    )
                    self.assertEqual(session.control, [expected])

    async def test_v5g_runtime_probes_temperature_with_atomic_query(self) -> None:
        controller = V5GRuntimeController()
        session = _FakeSession()

        await controller.after_initialize(session, timeout=1.0)

        self.assertEqual(session.notification_queries, [V5G_TEMPERATURE_QUERY_PACKET])

    async def test_family_runtime_owns_flow_markers(self) -> None:
        cases = (
            (V5CRuntimeController(), V5C_NOTIFY_PAUSE, V5C_NOTIFY_RESUME),
            (
                V5XRuntimeController(),
                next(iter(V5X_NOTIFY_PAUSE_PACKETS)),
                next(iter(V5X_NOTIFY_RESUME_PACKETS)),
            ),
        )
        for controller, pause, resume in cases:
            with self.subTest(controller=type(controller).__name__):
                session = _FakeSession()
                controller.handle_notification(session, pause)
                controller.handle_notification(session, resume)
                self.assertEqual(session.flow, [(True, pause), (False, resume)])


if __name__ == "__main__":
    unittest.main()
