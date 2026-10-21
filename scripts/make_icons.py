"""Draw the app icons (static/icon-192.png and static/icon-512.png) with the standard library only.

Run once, by hand, after changing the drawing: `uv run python scripts/make_icons.py`. The PNG files
are committed, so the server never runs this.

The drawing is the page's own favicon: a blue dot, here on the page's near-black background. The
background fills the whole square and the dot stays inside the middle 80 %, so the same file works
as a "maskable" icon: Android may cut it to a circle or a rounded square and nothing is lost.

A PNG is a signature, then chunks (length, type, data, CRC). IHDR says the size and colour type,
IDAT holds the pixel rows, each row starting with a filter byte (0 = none), compressed with zlib.
"""

import struct
import zlib
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "ollagi" / "static"
BACKGROUND = (0x0B, 0x0B, 0x0C)  # the page's theme-color
DOT = (0x6D, 0x9E, 0xFF)         # the favicon's blue
DOT_RADIUS = 0.24                # of the icon's width; the safe zone for maskable icons is 0.40
SAMPLES = 4                      # 4 x 4 samples per pixel, so the dot's edge is smooth


def pixel(x: int, y: int, size: int) -> bytes:
    """The colour of one pixel: how much of it the dot covers, mixed with the background."""
    centre, radius = size / 2, DOT_RADIUS * size
    inside = 0
    for i in range(SAMPLES):
        for j in range(SAMPLES):
            dx = x + (i + 0.5) / SAMPLES - centre
            dy = y + (j + 0.5) / SAMPLES - centre
            inside += dx * dx + dy * dy <= radius * radius
    cover = inside / SAMPLES**2
    return bytes(round(b + (d - b) * cover) for b, d in zip(BACKGROUND, DOT))


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(size: int) -> bytes:
    rows = b"".join(b"\x00" + b"".join(pixel(x, y, size) for x in range(size)) for y in range(size))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8 bits per channel, colour type 2 = RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    for size in (192, 512):
        path = STATIC / f"icon-{size}.png"
        path.write_bytes(png(size))
        print(f"wrote {path} ({path.stat().st_size} bytes)")
