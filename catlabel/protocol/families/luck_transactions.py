"""Reply contracts for Luck normal and A4 control commands.

Reply rules in this module follow the pinned TiMini-Print protocol at
76b3171bb956603277f7d97863d7e607d3de2e89.

Copyright 2026 Daniel Banecki
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from ..steps import ProtocolReplyExpectation, ProtocolReplyMatcher, ProtocolStep

QUERY_TIMEOUT_SEC = 3.0
NORMAL_FINALIZE_TIMEOUT_SEC = 70.0
LUJIANG_A4_FINALIZE_TIMEOUT_SEC = 120.0


def _finalized(reply: bytes | None) -> bool:
    # A leading NUL is a status byte, not padding around a print ACK.
    return bool(reply and (reply.startswith(b"OK") or reply[0] == 0xAA))


_DENSITY_REPLY = ProtocolReplyMatcher(
    complete=lambda reply: len(reply) >= 2,
    matches=lambda reply: reply == b"OK",
)
_OK_PREFIX_REPLY = ProtocolReplyMatcher(
    complete=lambda reply: len(reply) >= 2,
    matches=lambda reply: bool(reply and reply.startswith(b"OK")),
)
# Busy, cover, paper, battery and the two overheating bits block a new job.
_STATUS_ERROR_MASK = 0x01 | 0x02 | 0x04 | 0x08 | 0x10 | 0x40
_STATUS_REPLY = ProtocolReplyMatcher(
    complete=bool,
    matches=lambda reply: bool(reply) and not reply[0] & _STATUS_ERROR_MASK,
)
_FINALIZE_REPLY = ProtocolReplyMatcher(complete=_finalized, matches=_finalized)


def status_query() -> ProtocolStep:
    """Read status, ignoring the charging and unused high bits."""
    return ProtocolStep.query(
        "status",
        b"\x10\xff\x40",
        expect=ProtocolReplyExpectation.STATUS_ZERO,
        timeout_sec=QUERY_TIMEOUT_SEC,
        include_in_payload=False,
        reply_matcher=_STATUS_REPLY,
    )


def density_setting(packet: bytes) -> ProtocolStep:
    """Set density and require the released exact ``OK`` response."""
    return ProtocolStep.query(
        "density",
        packet,
        expect=ProtocolReplyExpectation.OK,
        timeout_sec=QUERY_TIMEOUT_SEC,
        reply_matcher=_DENSITY_REPLY,
    )


def paper_setting(packet: bytes, *, wait_for_reply: bool = True) -> ProtocolStep:
    """Set media; when queried, reserve a response window without requiring ACK."""
    if not wait_for_reply:
        return ProtocolStep.send("paper type", packet)
    return ProtocolStep.query(
        "paper type",
        packet,
        expect=ProtocolReplyExpectation.OK,
        timeout_sec=QUERY_TIMEOUT_SEC,
        reply_matcher=_OK_PREFIX_REPLY,
        reply_required=False,
    )


def finalize(packet: bytes, *, timeout_sec: float) -> ProtocolStep:
    """Finalize a bitmap job and require an OK-prefixed or AA reply."""
    return ProtocolStep.query(
        "finalize",
        packet,
        expect=ProtocolReplyExpectation.OK_OR_AA,
        timeout_sec=timeout_sec,
        reply_matcher=_FINALIZE_REPLY,
    )
