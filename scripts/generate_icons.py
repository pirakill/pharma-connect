"""Generate PWA icons without external dependencies."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "pharmaconnect" / "static"
TEAL = (45, 212, 191)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def write_solid_png(path: Path, size: int, rgb: tuple[int, int, int]) -> None:
    raw_rows = []
    for _ in range(size):
        row = bytes([0]) + bytes(rgb) * size
        raw_rows.append(row)
    compressed = zlib.compress(b"".join(raw_rows), 9)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", compressed)
    png += _png_chunk(b"IEND", b"")
    path.write_bytes(png)


def main() -> None:
    STATIC.mkdir(parents=True, exist_ok=True)
    write_solid_png(STATIC / "icon-192.png", 192, TEAL)
    write_solid_png(STATIC / "icon-512.png", 512, TEAL)
    print(f"Wrote {STATIC / 'icon-192.png'} and {STATIC / 'icon-512.png'}")


if __name__ == "__main__":
    main()