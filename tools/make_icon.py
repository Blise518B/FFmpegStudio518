"""Generates ffmpeg_studio/assets/icon.ico — neon play glyph on dark tile."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).parent.parent / "ffmpeg_studio" / "assets" / "icon.ico"


def draw(size: int) -> QImage:
    """Dark rounded tile, neon-green border, filled play triangle, film dots."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0
    accent = QColor("#31f272")
    dark = QColor("#0a0c0a")

    # tile
    p.setBrush(dark)
    p.setPen(QPen(accent, 12 * s))
    p.drawRoundedRect(QRectF(10 * s, 10 * s, 236 * s, 236 * s), 44 * s, 44 * s)

    # film sprocket dots down the left edge
    p.setPen(Qt.NoPen)
    p.setBrush(accent)
    for y in (64, 128, 192):
        p.drawEllipse(QRectF(38 * s, (y - 9) * s, 18 * s, 18 * s))

    # play triangle
    tri = QPolygonF([QPointF(102 * s, 74 * s), QPointF(206 * s, 128 * s),
                     QPointF(102 * s, 182 * s)])
    p.drawPolygon(tri)

    p.end()
    return img


def main() -> None:
    QApplication(sys.argv[:1])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = draw(256)
    if not img.save(str(OUT), "ICO"):
        raise SystemExit("failed to write ico")
    img.save(str(OUT.with_suffix(".png")), "PNG")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
