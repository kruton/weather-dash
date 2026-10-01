"""Lossless encoding of epdoptimize's native device colors."""

import io
import re
from struct import iter_unpack

from PIL import Image

INKY_57_SIZE = (600, 448)
INKY_57_COLORS = {
    (0, 0, 0): 0, (255, 255, 255): 1, (0, 255, 0): 2,
    (0, 0, 255): 3, (255, 0, 0): 4, (255, 255, 0): 5,
    (255, 128, 0): 6,
}


def inky_57_frame(png_data: bytes) -> bytes:
    """Encode the 5.7-inch PicoGraphics framebuffer: three 1-bit planes."""
    with Image.open(io.BytesIO(png_data)) as source:
        if source.size != INKY_57_SIZE:
            raise ValueError("Image dimensions do not match the 5.7-inch display")
        if source.convert("RGBA").getchannel("A").getextrema() != (255, 255):
            raise ValueError("Image must be opaque")
        pixels = source.convert("RGB").tobytes()
    plane_size = INKY_57_SIZE[0] * INKY_57_SIZE[1] // 8
    output = bytearray(plane_size * 3)
    for index, color in enumerate(iter_unpack("BBB", pixels)):
        try:
            pen = INKY_57_COLORS[color]
        except KeyError as error:
            raise ValueError(f"Unexpected 5.7-inch device color: {color}") from error
        byte = index >> 3
        mask = 0x80 >> (index & 7)
        if pen & 4:
            output[byte] |= mask
        if pen & 2:
            output[plane_size + byte] |= mask
        if pen & 1:
            output[2 * plane_size + byte] |= mask
    return bytes(output)


def indexed_png(
    png_data: bytes, device_colors: list[str], size: tuple[int, int]
) -> bytes:
    """Repack RGB pixels as palette indices, without quantizing or dithering.

    Inky's PNG_POSTERISE decoder preserves indexed native colors. True-color
    PNGs take a different firmware path which dithers the pixels again.
    """
    if not 2 <= len(device_colors) <= 256 or any(
        re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None for color in device_colors
    ):
        raise ValueError("Invalid device palette")
    colors = [tuple(bytes.fromhex(color[1:])) for color in device_colors]
    indices = {color: index for index, color in enumerate(colors)}
    if len(indices) != len(colors):
        raise ValueError("Duplicate device colors")

    with Image.open(io.BytesIO(png_data)) as source:
        if source.size != size:
            raise ValueError("Processed image dimensions do not match the display")
        if source.convert("RGBA").getchannel("A").getextrema() != (255, 255):
            raise ValueError("Processed image must be opaque")
        image = source.convert("RGB")
        try:
            # Stream RGB triples instead of materializing a tuple per pixel
            # for the whole frame before performing the exact lookup.
            pixels = bytes(
                map(indices.__getitem__, iter_unpack("BBB", image.tobytes()))
            )
        except KeyError as error:
            raise ValueError(f"Unexpected device color: {error.args[0]}") from error

    result = Image.frombytes("P", size, pixels)
    result.putpalette(bytes(channel for color in colors for channel in color))
    output = io.BytesIO()
    result.save(output, format="PNG", bits=8)
    return output.getvalue()
