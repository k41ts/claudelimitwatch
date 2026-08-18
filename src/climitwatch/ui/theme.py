"""Palettes and shared widgets for the overlay.

Two looks ship: ``cyberpunk`` (default -- Edgerunners-flavoured neon on near
black, chamfered corners, segmented meters) and ``dark`` (plain, quiet). All
colors go through :data:`palette`, so widgets never hardcode one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPolygonF
from PySide6.QtWidgets import QWidget

from ..models import SEVERITY_DANGER, SEVERITY_WARNING


@dataclass(frozen=True)
class Palette:
    name: str
    bg: QColor
    bg_panel: QColor
    border: QColor
    text: QColor
    text_dim: QColor
    track: QColor
    normal: QColor
    warning: QColor
    danger: QColor
    stale: QColor
    accent: QColor
    #: Corner cut in px; 0 keeps plain rounded corners.
    chamfer: int = 0
    radius: int = 10
    scanlines: bool = False
    segmented_meter: bool = False
    glow: bool = False
    uppercase: bool = False
    mono_font: str = ""
    letter_spacing: float = 0.0

    def severity(self, severity: str) -> QColor:
        return {
            "normal": self.normal,
            SEVERITY_WARNING: self.warning,
            SEVERITY_DANGER: self.danger,
            "stale": self.stale,
        }.get(severity, self.normal)


CYBERPUNK = Palette(
    name="cyberpunk",
    bg=QColor(8, 8, 12, 238),
    bg_panel=QColor(10, 10, 14),
    border=QColor(252, 238, 10, 150),
    text=QColor(236, 240, 241),
    text_dim=QColor(120, 134, 148),
    track=QColor(30, 32, 42),
    normal=QColor(0, 229, 255),
    warning=QColor(252, 238, 10),
    danger=QColor(255, 45, 120),
    stale=QColor(90, 96, 110),
    accent=QColor(252, 238, 10),
    chamfer=9,
    scanlines=True,
    segmented_meter=True,
    glow=True,
    uppercase=True,
    mono_font="Consolas",
    letter_spacing=0.6,
)

DARK = Palette(
    name="dark",
    bg=QColor(24, 24, 27, 235),
    bg_panel=QColor(24, 24, 27),
    border=QColor(63, 63, 70),
    text=QColor(244, 244, 245),
    text_dim=QColor(161, 161, 170),
    track=QColor(63, 63, 70),
    normal=QColor(74, 222, 128),
    warning=QColor(250, 204, 21),
    danger=QColor(248, 113, 113),
    stale=QColor(113, 113, 122),
    accent=QColor(96, 165, 250),
    radius=10,
)

PALETTES = {p.name: p for p in (CYBERPUNK, DARK)}

palette: Palette = CYBERPUNK


def pal() -> Palette:
    """Active palette. Call it -- do not bind the global at import time."""
    return palette


def set_theme(name: str) -> Palette:
    """Switch the active palette; unknown names fall back to cyberpunk."""
    global palette
    palette = PALETTES.get(name, CYBERPUNK)
    return palette


def severity_color(severity: str) -> QColor:
    return palette.severity(severity)


def value_font(size: int = 9, bold: bool = True) -> QFont:
    font = QFont(palette.mono_font or "Segoe UI", size)
    font.setBold(bold)
    if palette.letter_spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, palette.letter_spacing)
    return font


def label_text(text: str) -> str:
    return text.upper() if palette.uppercase else text


def panel_style() -> str:
    p = palette
    accent = p.accent.name()
    return f"""
QWidget {{
    background-color: {p.bg_panel.name()};
    color: {p.text.name()};
    font-family: "Segoe UI";
    font-size: 12px;
}}
QLabel[dim="true"] {{ color: {p.text_dim.name()}; }}
QLabel[heading="true"] {{
    font-size: 13px;
    font-weight: 700;
    color: {accent};
    letter-spacing: 1px;
}}
QPushButton {{
    background-color: {"#12121a" if p.name == "cyberpunk" else "#27272a"};
    border: 1px solid {p.border.name()};
    border-radius: {0 if p.chamfer else 6}px;
    padding: 5px 12px;
    font-weight: 600;
    letter-spacing: {p.letter_spacing}px;
}}
QPushButton:hover {{ background-color: {accent}; color: #08080c; }}
QPushButton:disabled {{ color: {p.text_dim.name()}; border-color: {p.track.name()}; }}
QLineEdit, QSpinBox, QComboBox {{
    background-color: {"#12121a" if p.name == "cyberpunk" else "#27272a"};
    border: 1px solid {p.border.name()};
    border-radius: {0 if p.chamfer else 6}px;
    padding: 4px 6px;
    selection-background-color: {accent};
    selection-color: #08080c;
}}
QCheckBox {{ spacing: 6px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""


# Kept for callers that imported the constant form.
PANEL_STYLE = panel_style()


# --- painting helpers -------------------------------------------------------


def chamfer_path(rect: QRectF, cut: float) -> QPainterPath:
    """Rectangle with the top-left and bottom-right corners sliced off."""
    path = QPainterPath()
    path.moveTo(rect.left() + cut, rect.top())
    path.lineTo(rect.right(), rect.top())
    path.lineTo(rect.right(), rect.bottom() - cut)
    path.lineTo(rect.right() - cut, rect.bottom())
    path.lineTo(rect.left(), rect.bottom())
    path.lineTo(rect.left(), rect.top() + cut)
    path.closeSubpath()
    return path


def shell_path(rect: QRectF) -> QPainterPath:
    if palette.chamfer:
        return chamfer_path(rect, palette.chamfer)
    path = QPainterPath()
    path.addRoundedRect(rect, palette.radius, palette.radius)
    return path


def _glow(painter: QPainter, path: QPainterPath, color: QColor, steps: int = 3) -> None:
    """Cheap neon bloom: a few translucent strokes fanning out from the shape."""
    for step in range(steps, 0, -1):
        glow = QColor(color)
        glow.setAlpha(int(46 / step))
        pen = painter.pen()
        pen.setColor(glow)
        pen.setWidthF(step * 2.4)
        painter.setPen(pen)
        painter.drawPath(path)


def draw_scanlines(painter: QPainter, rect: QRectF, spacing: int = 3) -> None:
    line = QColor(0, 0, 0, 46)
    painter.setPen(line)
    y = rect.top()
    while y < rect.bottom():
        painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        y += spacing


def round_rect_background(widget: QWidget, color: QColor | None = None) -> None:
    """Paint the frameless shell: fill, scanlines, border, corner accent."""
    p = palette
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
    path = shell_path(rect)

    painter.fillPath(path, color or p.bg)
    if p.scanlines:
        painter.save()
        painter.setClipPath(path)
        draw_scanlines(painter, rect)
        painter.restore()

    pen = painter.pen()
    pen.setColor(p.border)
    pen.setWidthF(1.2)
    painter.setPen(pen)
    painter.drawPath(path)

    if p.chamfer:
        # Accent tick along the sliced corners.
        pen.setColor(p.accent)
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(rect.left(), rect.top() + p.chamfer),
            QPointF(rect.left() + p.chamfer, rect.top()),
        )
        painter.drawLine(
            QPointF(rect.right() - p.chamfer, rect.bottom()),
            QPointF(rect.right(), rect.bottom() - p.chamfer),
        )
    painter.end()


class MeterBar(QWidget):
    """Usage meter: slanted neon segments (cyberpunk) or a slim bar (dark)."""

    def __init__(self, parent: QWidget | None = None, height: int = 8, segments: int = 10) -> None:
        super().__init__(parent)
        self._percent = 0.0
        self._severity = "normal"
        self._segments = segments
        self.setFixedHeight(height)
        self.setMinimumWidth(44)

    def set_value(self, percent: float, severity: str = "normal") -> None:
        changed = percent != self._percent or severity != self._severity
        self._percent = max(0.0, min(100.0, percent))
        self._severity = severity
        if changed:
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = severity_color(self._severity)
        if palette.segmented_meter:
            self._paint_segments(painter, color)
        else:
            self._paint_bar(painter, color)
        painter.end()

    def _paint_bar(self, painter: QPainter, color: QColor) -> None:
        radius = self.height() / 2
        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        painter.fillPath(track, palette.track)
        if self._percent > 0:
            fill = QPainterPath()
            fill.addRoundedRect(
                QRectF(0, 0, self.width() * self._percent / 100.0, self.height()), radius, radius
            )
            painter.fillPath(fill, color)

    def _paint_segments(self, painter: QPainter, color: QColor) -> None:
        count = self._segments
        gap = 2.0
        skew = min(3.0, self.height() * 0.45)
        total = self.width()
        seg_w = (total - gap * (count - 1)) / count
        lit = self._percent / 100.0 * count

        for index in range(count):
            left = index * (seg_w + gap)
            shape = QPolygonF(
                [
                    QPointF(left + skew, 0),
                    QPointF(left + seg_w, 0),
                    QPointF(left + seg_w - skew, self.height()),
                    QPointF(left, self.height()),
                ]
            )
            path = QPainterPath()
            path.addPolygon(shape)
            path.closeSubpath()

            fraction = max(0.0, min(1.0, lit - index))
            if fraction <= 0:
                painter.fillPath(path, palette.track)
                continue

            tint = QColor(color)
            if fraction < 1:
                tint.setAlpha(int(110 + 145 * fraction))
            if palette.glow:
                painter.save()
                _glow(painter, path, color, steps=2)
                painter.restore()
            painter.fillPath(path, tint)


def elide(text: str, limit: int = 22) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# Backwards-compatible module-level colors (read at import time by older code).
BG = palette.bg
BORDER = palette.border
TEXT = palette.text
TEXT_DIM = palette.text_dim

__all__ = [
    "CYBERPUNK",
    "DARK",
    "MeterBar",
    "PALETTES",
    "Palette",
    "chamfer_path",
    "elide",
    "label_text",
    "pal",
    "panel_style",
    "round_rect_background",
    "set_theme",
    "severity_color",
    "shell_path",
    "value_font",
]
