from __future__ import annotations

import sys
import types


if "crc8" not in sys.modules:
    module = types.ModuleType("crc8")

    class _CRC8:
        def __init__(self) -> None:
            self._crc = 0

        def update(self, data: bytes) -> None:
            for b in data:
                self._crc ^= b
                for _ in range(8):
                    if self._crc & 0x80:
                        self._crc = ((self._crc << 1) ^ 0x07) & 0xFF
                    else:
                        self._crc = (self._crc << 1) & 0xFF

        def digest(self) -> bytes:
            return bytes([self._crc])

    module.crc8 = _CRC8
    sys.modules["crc8"] = module
