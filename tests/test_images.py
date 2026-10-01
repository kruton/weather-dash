import io

import pytest
from PIL import Image

from weather_dash.images import indexed_png, inky_57_frame


def test_inky_57_frame_uses_three_msb_first_bitplanes():
    image = Image.new("RGB", (600, 448), "white")
    for x, y, color in ((0, 0, "black"), (7, 0, (0, 255, 0)),
                        (8, 0, "red"), (0, 1, (255, 128, 0))):
        image.putpixel((x, y), Image.new("RGB", (1, 1), color).getpixel((0, 0)))
    frame = inky_57_frame(png(image))
    plane = 600 * 448 // 8
    assert len(frame) == plane * 3
    assert frame[0] == 0 and frame[1] == 0x80
    assert frame[plane] == 0x01
    assert frame[2 * plane] == 0x7E
    assert frame[75] == 0x80
    assert frame[plane + 75] == 0x80
    assert frame[2 * plane + 75] == 0x7F


def test_inky_57_frame_rejects_unsupported_color():
    with pytest.raises(ValueError, match="Unexpected 5.7-inch device color"):
        inky_57_frame(png(Image.new("RGB", (600, 448), (12, 34, 56))))


def png(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize("width", [1, 7, 800])
@pytest.mark.parametrize(
    "palette",
    [
        ["#000000", "#ffffff"],
        ["#000000", "#ffffff", "#0000ff", "#00ff00", "#ff0000", "#ffff00"],
    ],
)
def test_repacking_preserves_every_pixel(width, palette):
    colors = [tuple(bytes.fromhex(color[1:])) for color in palette]
    image = Image.new("RGB", (width, 3))
    image.putdata([colors[index % len(colors)] for index in range(width * 3)])
    data = indexed_png(png(image), palette, image.size)
    with Image.open(io.BytesIO(data)) as result:
        assert result.mode == "P"
        assert result.size == image.size
        assert result.convert("RGB").tobytes() == image.tobytes()
        assert "transparency" not in result.info
    assert indexed_png(png(image), palette, image.size) == data


def test_repacking_rejects_unexpected_colors():
    image = Image.new("RGB", (1, 1), "red")
    with pytest.raises(ValueError, match="Unexpected device color"):
        indexed_png(png(image), ["#000000", "#ffffff"], image.size)


def test_repacking_rejects_transparency_and_wrong_size():
    image = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    with pytest.raises(ValueError, match="opaque"):
        indexed_png(png(image), ["#000000", "#ffffff"], image.size)
    with pytest.raises(ValueError, match="dimensions"):
        indexed_png(png(image), ["#000000", "#ffffff"], (2, 2))


@pytest.mark.parametrize(
    "palette", [[], ["#000000"], ["black", "white"], ["#000000", "#000000"]]
)
def test_repacking_rejects_invalid_palettes(palette):
    with pytest.raises(ValueError, match="palette|Duplicate"):
        indexed_png(png(Image.new("RGB", (1, 1))), palette, (1, 1))
