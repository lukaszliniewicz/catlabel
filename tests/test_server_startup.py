from __future__ import annotations

import unittest
from types import SimpleNamespace

from catlabel.__main__ import open_browser_when_ready


class ServerStartupTests(unittest.TestCase):
    def test_explicit_lan_url_is_used_after_startup(self) -> None:
        server = SimpleNamespace(started=True, should_exit=False)
        opened_urls: list[str] = []
        opened = open_browser_when_ready(
            server,
            8000,
            browser_url="http://192.168.1.20:8000",
            browser_open=opened_urls.append,
        )
        self.assertTrue(opened)
        self.assertEqual(opened_urls, ["http://192.168.1.20:8000"])

    def test_browser_opens_only_after_server_reports_ready(self) -> None:
        server = SimpleNamespace(started=False, should_exit=False)
        opened_urls: list[str] = []
        sleeps: list[float] = []

        def mark_ready(delay: float) -> None:
            sleeps.append(delay)
            server.started = True

        opened = open_browser_when_ready(
            server,
            8123,
            poll_interval=0.25,
            browser_open=opened_urls.append,
            sleeper=mark_ready,
        )

        self.assertTrue(opened)
        self.assertEqual(sleeps, [0.25])
        self.assertEqual(opened_urls, ["http://localhost:8123"])

    def test_browser_does_not_open_if_server_exits_during_startup(self) -> None:
        server = SimpleNamespace(started=False, should_exit=False)
        opened_urls: list[str] = []

        def stop_server(_delay: float) -> None:
            server.should_exit = True

        opened = open_browser_when_ready(
            server,
            8000,
            browser_open=opened_urls.append,
            sleeper=stop_server,
        )

        self.assertFalse(opened)
        self.assertEqual(opened_urls, [])


if __name__ == "__main__":
    unittest.main()
