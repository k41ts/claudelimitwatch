"""Theme switching. Needs a QApplication because QColor/QFont touch Qt GUI."""

import pytest

pytest.importorskip("PySide6")

from climitwatch.config import Settings  # noqa: E402
from climitwatch.ui import theme  # noqa: E402


@pytest.fixture(autouse=True)
def restore_theme(qt_app):
    yield
    theme.set_theme("cyberpunk")


def test_default_theme_is_cyberpunk():
    assert Settings().theme == "cyberpunk"
    assert theme.pal().name == "cyberpunk"


def test_set_theme_switches_palette_and_stylesheet():
    theme.set_theme("dark")
    assert theme.pal().name == "dark"
    assert theme.pal().accent.name() in theme.panel_style()
    assert not theme.pal().uppercase

    theme.set_theme("cyberpunk")
    assert theme.pal().chamfer > 0
    assert theme.pal().segmented_meter
    assert theme.pal().accent.name() in theme.panel_style()


def test_unknown_theme_falls_back():
    assert theme.set_theme("vaporwave").name == "cyberpunk"


def test_label_text_follows_the_palette():
    theme.set_theme("cyberpunk")
    assert theme.label_text("5h left") == "5H LEFT"
    theme.set_theme("dark")
    assert theme.label_text("5h left") == "5h left"


def test_severity_colors_differ_per_theme():
    theme.set_theme("cyberpunk")
    cyber_normal = theme.severity_color("normal").name()
    theme.set_theme("dark")
    assert theme.severity_color("normal").name() != cyber_normal


def test_meter_accepts_values_in_both_themes():
    for name in ("cyberpunk", "dark"):
        theme.set_theme(name)
        meter = theme.MeterBar()
        meter.set_value(150, "danger")  # clamped, must not raise
        assert meter._percent == 100
