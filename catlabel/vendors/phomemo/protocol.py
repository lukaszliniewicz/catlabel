def density_to_heat_time(density: int) -> int:
    """Map density 1-8 to heat time values (~40-200)."""
    heat_times = [40, 60, 80, 100, 120, 140, 160, 200]
    return heat_times[max(0, min(7, density - 1))]


class CMD:
    INIT = b"\x1b\x40"

    @staticmethod
    def FEED(dots: int) -> bytes:
        return bytes([0x1B, 0x4A, dots])

    @staticmethod
    def DENSITY(level: int) -> bytes:
        return bytes([0x1D, 0x7C, level])

    @staticmethod
    def HEAT_SETTINGS(max_dots: int, heat_time: int, heat_interval: int) -> bytes:
        return bytes([0x1B, 0x37, max_dots, heat_time, heat_interval])

    @staticmethod
    def RASTER_HEADER(width_bytes: int, height_lines: int) -> bytes:
        return bytes(
            [
                0x1D,
                0x76,
                0x30,
                0x00,
                width_bytes,
                0x00,
                height_lines & 0xFF,
                (height_lines >> 8) & 0xFF,
            ]
        )


class M02_CMD:
    PREFIX = b"\x10\xff\xfe\x01"


class M04_CMD:
    @staticmethod
    def DENSITY(level: int) -> bytes:
        return bytes([0x1F, 0x11, 0x02, level])

    @staticmethod
    def HEAT(param: int) -> bytes:
        return bytes([0x1F, 0x11, 0x37, param])

    INIT = b"\x1f\x11\x0b"

    @staticmethod
    def COMPRESSION(mode: int) -> bytes:
        return bytes([0x1F, 0x11, 0x35, mode])

    @staticmethod
    def RASTER_HEADER(width_bytes: int, height_lines: int) -> bytes:
        return bytes(
            [
                0x1D,
                0x76,
                0x30,
                0x00,
                width_bytes % 256,
                width_bytes // 256,
                height_lines % 256,
                height_lines // 256,
            ]
        )

    FEED = b"\x1b\x64\x02"


class M110_CMD:
    @staticmethod
    def SPEED(speed: int) -> bytes:
        return bytes([0x1B, 0x4E, 0x0D, speed])

    @staticmethod
    def DENSITY(density: int) -> bytes:
        return bytes([0x1B, 0x4E, 0x04, density])

    @staticmethod
    def MEDIA_TYPE(type_val: int) -> bytes:
        return bytes([0x1F, 0x11, type_val])

    FOOTER = b"\x1f\xf0\x05\x00\x1f\xf0\x03\x00"


class D_CMD:
    @staticmethod
    def HEADER(width_bytes: int, rows: int) -> bytes:
        return bytes(
            [
                0x1B,
                0x40,
                0x1D,
                0x76,
                0x30,
                0x00,
                width_bytes % 256,
                width_bytes // 256,
                rows % 256,
                rows // 256,
            ]
        )

    END = b"\x1b\x64\x00"


class P12_CMD:
    INIT_SEQUENCE = [
        b"\x1f\x11\x38",
        b"\x1f\x11\x11\x1f\x11\x12\x1f\x11\x09\x1f\x11\x13",
        b"\x1f\x11\x09",
        b"\x1f\x11\x19\x1f\x11\x11",
        b"\x1f\x11\x19",
        b"\x1f\x11\x07",
    ]

    @staticmethod
    def HEADER(width_bytes: int, rows: int) -> bytes:
        return bytes(
            [
                0x1B,
                0x40,
                0x1D,
                0x76,
                0x30,
                0x00,
                width_bytes % 256,
                width_bytes // 256,
                rows % 256,
                rows // 256,
            ]
        )

    FEED = b"\x1b\x64\x0d"


class TSPL:
    @staticmethod
    def SIZE(width_mm: int, height_mm: int) -> bytes:
        return f"SIZE {width_mm} mm, {height_mm} mm\r\n".encode()

    @staticmethod
    def GAP(gap_mm: int) -> bytes:
        return f"GAP {gap_mm} mm, 0 mm\r\n".encode()

    OFFSET = b"OFFSET -3 mm\r\n"

    @staticmethod
    def DENSITY(level: int) -> bytes:
        return f"DENSITY {level}\r\n".encode()

    @staticmethod
    def SPEED(speed: int) -> bytes:
        return f"SPEED {speed}\r\n".encode()

    @staticmethod
    def DIRECTION(dir_val: int) -> bytes:
        return f"DIRECTION {dir_val}\r\n".encode()

    CLS = b"CLS\r\n"

    @staticmethod
    def BITMAP_HEADER(x: int, y: int, width_bytes: int, height_dots: int) -> bytes:
        return f"BITMAP {x},{y},{width_bytes},{height_dots},0,".encode()

    @staticmethod
    def PRINT(copies: int = 1) -> bytes:
        return f"PRINT {copies}\r\n".encode()

    END = b"END\r\n"
