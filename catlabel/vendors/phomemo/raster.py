from PIL import Image, ImageOps


def render_to_raster(
    image: Image.Image,
    width_bytes: int,
    rotate_cw: bool = False,
    invert: bool = False,
) -> tuple[bytes, int, int]:
    """Convert a PIL image to packed 1-bit raster bytes."""
    img = image.copy()

    if rotate_cw:
        img = img.rotate(-90, expand=True)

    if invert:
        img = ImageOps.invert(img.convert("L"))

    img = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)

    width_px = img.width
    height_px = img.height

    actual_width_bytes = (width_px + 7) // 8
    target_width_bytes = width_bytes if width_bytes > 0 else actual_width_bytes

    raster_data = bytearray()
    pixels = list(img.getdata())

    for y in range(height_px):
        row_start = y * width_px
        for byte_idx in range(target_width_bytes):
            byte_val = 0
            for bit_idx in range(8):
                px_x = byte_idx * 8 + bit_idx
                if px_x < width_px:
                    pixel = pixels[row_start + px_x]
                    is_black = 1 if pixel == 0 else 0
                    if is_black:
                        byte_val |= 1 << (7 - bit_idx)
            raster_data.append(byte_val)

    return bytes(raster_data), target_width_bytes, height_px
