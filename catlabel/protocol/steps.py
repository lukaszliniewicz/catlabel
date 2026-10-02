from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .family import ProtocolStrEnum


class ProtocolWriteChannel(ProtocolStrEnum):
    STANDARD = "standard"
    CONTROL = "control"
    BULK = "bulk"


class ProtocolStepOperation(ProtocolStrEnum):
    SEND = "send"
    QUERY = "query"
    WAIT = "wait"


class ProtocolReplyExpectation(ProtocolStrEnum):
    NONE = "none"
    OK = "ok"
    STATUS_ZERO = "status_zero"
    OK_OR_AA = "ok_or_aa"


@dataclass(frozen=True)
class ProtocolReplyMatcher:
    complete: Callable[[bytes], bool]
    matches: Callable[[bytes | None], bool] | None = None


@dataclass(frozen=True)
class ProtocolStep:
    """One stateless, named operation in a protocol execution plan."""

    label: str
    data: bytes
    operation: ProtocolStepOperation = ProtocolStepOperation.SEND
    expect: ProtocolReplyExpectation = ProtocolReplyExpectation.NONE
    timeout_sec: float | None = None
    include_in_payload: bool = True
    reply_matcher: ProtocolReplyMatcher | None = None
    repeat_interval_sec: float | None = None
    repeat_timeout_sec: float | None = None
    write_channel: ProtocolWriteChannel = ProtocolWriteChannel.STANDARD

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", bytes(self.data))
        object.__setattr__(self, "operation", ProtocolStepOperation(self.operation))
        object.__setattr__(self, "expect", ProtocolReplyExpectation(self.expect))
        write_channel = ProtocolWriteChannel(self.write_channel)
        object.__setattr__(self, "write_channel", write_channel)
        if (
            self.operation is not ProtocolStepOperation.SEND
            and write_channel is not ProtocolWriteChannel.STANDARD
        ):
            raise ValueError(
                "Protocol query and wait steps must use the standard write channel"
            )
        if self.timeout_sec is not None and self.timeout_sec < 0:
            raise ValueError("Protocol step timeout must be non-negative")
        if self.repeat_interval_sec is not None and self.repeat_interval_sec <= 0:
            raise ValueError("Protocol step repeat interval must be positive")
        if self.repeat_timeout_sec is not None and self.repeat_timeout_sec < 0:
            raise ValueError("Protocol step repeat timeout must be non-negative")

    @classmethod
    def send(
        cls,
        label: str,
        data: bytes,
        *,
        write_channel: ProtocolWriteChannel = ProtocolWriteChannel.STANDARD,
    ) -> ProtocolStep:
        return cls(label=label, data=data, write_channel=write_channel)

    @classmethod
    def query(
        cls,
        label: str,
        data: bytes,
        *,
        expect: ProtocolReplyExpectation,
        timeout_sec: float | None = None,
        include_in_payload: bool = True,
        reply_matcher: ProtocolReplyMatcher | None = None,
        repeat_interval_sec: float | None = None,
        repeat_timeout_sec: float | None = None,
    ) -> ProtocolStep:
        return cls(
            label=label,
            data=data,
            operation=ProtocolStepOperation.QUERY,
            expect=expect,
            timeout_sec=timeout_sec,
            include_in_payload=include_in_payload,
            reply_matcher=reply_matcher,
            repeat_interval_sec=repeat_interval_sec,
            repeat_timeout_sec=repeat_timeout_sec,
        )

    @classmethod
    def wait(
        cls,
        label: str,
        *,
        reply_matcher: ProtocolReplyMatcher,
        timeout_sec: float | None = None,
    ) -> ProtocolStep:
        return cls(
            label=label,
            data=b"",
            operation=ProtocolStepOperation.WAIT,
            timeout_sec=timeout_sec,
            include_in_payload=False,
            reply_matcher=reply_matcher,
        )


def reply_matches_expectation(
    expect: ProtocolReplyExpectation,
    reply: bytes | None,
) -> bool:
    expectation = ProtocolReplyExpectation(expect)
    if expectation is ProtocolReplyExpectation.NONE:
        return True
    if expectation is ProtocolReplyExpectation.OK:
        return bool(reply and reply.replace(b"\x00", b"").startswith(b"OK"))
    if expectation is ProtocolReplyExpectation.STATUS_ZERO:
        return bool(reply and reply[0] == 0)
    if expectation is ProtocolReplyExpectation.OK_OR_AA:
        return bool(
            reply
            and (
                reply.replace(b"\x00", b"").startswith(b"OK")
                or reply.lstrip(b"\x00").startswith(b"\xaa")
            )
        )
    raise ValueError(f"Unsupported protocol reply expectation: {expectation.value}")
