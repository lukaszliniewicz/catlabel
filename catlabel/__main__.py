import threading
import time
import webbrowser

import uvicorn

from .core.server_security import ServerSecurity


def open_browser_when_ready(
    server,
    port: int,
    *,
    poll_interval: float = 0.1,
    browser_url: str | None = None,
    browser_open=None,
    sleeper=None,
) -> bool:
    """Open CatLabel only after Uvicorn has completed application startup."""
    browser_open = browser_open or webbrowser.open
    sleeper = sleeper or time.sleep

    while not server.started:
        if server.should_exit:
            return False
        sleeper(poll_interval)

    browser_open(browser_url or f"http://localhost:{port}")
    return True


def main() -> None:
    settings = ServerSecurity.from_environment()
    port = settings.port
    config = uvicorn.Config(
        "catlabel.api.main:app",
        host=settings.host,
        port=port,
        reload=False,
    )
    server = uvicorn.Server(config)
    threading.Thread(
        target=open_browser_when_ready,
        args=(server, port),
        kwargs={"browser_url": settings.browser_url},
        daemon=True,
    ).start()
    server.run()


if __name__ == "__main__":
    main()
