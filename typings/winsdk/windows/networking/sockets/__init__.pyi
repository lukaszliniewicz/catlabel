from __future__ import annotations

from collections.abc import Awaitable

from ...storage.streams import IInputStream, IOutputStream
from .. import HostName

class StreamSocket:
    input_stream: IInputStream | None
    output_stream: IOutputStream | None

    def __init__(self) -> None: ...
    def connect_async(
        self, remote_host_name: HostName | None, remote_service_name: str, /
    ) -> Awaitable[None]: ...
    def close(self) -> None: ...
