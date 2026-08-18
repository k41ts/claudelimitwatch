"""Generate assets/climitwatch.ico from the in-app meter design.

No external art: the icon is drawn with Qt, the same donut the tray uses, then
packed into a multi-size ICO so Windows has a crisp frame at every scale.

    python tools/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QBuffer, QByteArray, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)

BG = QColor(10, 10, 14)
TRACK = QColor(38, 40, 52)
RING = QColor(0, 229, 255)
ACCENT = QColor(252, 238, 10)

#: How much of the ring is lit -- a recognisable "meter", not a full circle.
FILLED_FRACTION = 0.62


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Rounded-square backplate so the glyph reads on light and dark taskbars.
    plate = QRectF(0.5, 0.5, size - 1, size - 1)
    painter.setPen(QPen(ACCENT, max(1.0, size * 0.035)))
    painter.setBrush(BG)
    painter.drawRoundedRect(plate, size * 0.22, size * 0.22)

    inset = size * 0.24
    ring_rect = QRectF(inset, inset, size - inset * 2, size - inset * 2)
    width = max(1.6, size * 0.11)

    painter.setBrush(QColor(0, 0, 0, 0))
    painter.setPen(QPen(TRACK, width))
    painter.drawArc(ring_rect, 0, 360 * 16)

    painter.setPen(QPen(RING, width))
    painter.drawArc(ring_rect, 90 * 16, -int(360 * 16 * FILLED_FRACTION))
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    # Keep the QByteArray alive: QBuffer only borrows it, so passing a
    # temporary leaves a dangling pointer (segfault on save).
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("PNG encoding failed")
    buffer.close()
    return bytes(data)


def build_ico(frames: dict[int, bytes], out: Path) -> None:
    """Pack PNG frames into an ICO (PNG-compressed entries, Vista+)."""
    count = len(frames)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + count * 16
    entries, blobs = b"", b""
    for size, payload in sorted(frames.items()):
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,  # 0 means 256
            0 if size >= 256 else size,
            0,  # palette
            0,  # reserved
            1,  # color planes
            32,  # bits per pixel
            len(payload),
            offset,
        )
        blobs += payload
        offset += len(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(header + entries + blobs)


def main() -> int:
    QApplication([])
    frames = {size: png_bytes(render(size)) for size in SIZES}
    out = ROOT / "assets" / "climitwatch.ico"
    build_ico(frames, out)
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(frames)} sizes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
