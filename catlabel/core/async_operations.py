"""Validate dynamically supplied asynchronous adapter operations."""

from collections.abc import Awaitable
from inspect import isawaitable
from typing import cast


async def await_operation(result: object, *, operation: str) -> object:
    """Await a checked external operation without assuming its return type."""
    if not isawaitable(result):
        raise TypeError(f"{operation} did not return an awaitable.")
    return await cast(Awaitable[object], result)


def optional_bytes(value: object, *, operation: str) -> bytes | None:
    """Enforce the byte-response contract at a dynamic adapter boundary."""
    if value is None or isinstance(value, bytes):
        return value
    raise TypeError(f"{operation} returned an invalid byte response.")
