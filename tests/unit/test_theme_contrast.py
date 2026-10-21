"""WCAG 2.x contrast of every text color on the backgrounds it is drawn on, in both themes."""

import re
from pathlib import Path

import pytest

from focuslab.ui import theme
from focuslab.ui.theme import DARK, LIGHT, Palette

BODY = 4.5  # body, muted and small text
LARGE = 3.0  # large titles and button text
MARK = 3.0  # state and category colors as text (legend dots) or thin marks
TABLE_TINT = 70  # alpha of a state color behind report table cells (report_page._tint)


def rgba(color: str) -> tuple[float, float, float, float]:
    "``#RRGGBB``, Qt's ``#AARRGGBB`` or ``rgba(r, g, b, a)`` as 0..255 channels and 0..1 alpha."
    if color.startswith("rgba("):
        r, g, b, a = (float(v) for v in color[5:-1].split(","))
        return r, g, b, a / 255
    digits = color.lstrip("#")
    alpha = 1.0
    if len(digits) == 8:
        alpha, digits = int(digits[:2], 16) / 255, digits[2:]
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), alpha


def over(color: str, backdrop: str) -> str:
    "The opaque color of ``color`` painted over the opaque ``backdrop``."
    r, g, b, a = rgba(color)
    br, bg, bb, _ = rgba(backdrop)
    mixed = (round(c * a + d * (1 - a)) for c, d in ((r, br), (g, bg), (b, bb)))
    return "#" + "".join(f"{c:02X}" for c in mixed)


def luminance(color: str) -> float:
    def linear(channel: float) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b, a = rgba(color)
    assert a == 1.0, f"{color} is translucent; flatten it with over() first"
    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)


def contrast(foreground: str, background: str) -> float:
    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def pairs(p: Palette) -> list[tuple[str, str, str, float]]:
    "(what, text color, background, minimum ratio) for everything the interface draws."
    out = []
    for back in ("window", "surface"):
        for fore in ("text", "muted", "hint", "heading", "danger", "accent_text"):
            out.append((f"{fore} on {back}", getattr(p, fore), getattr(p, back), BODY))
    out += [
        ("text on field", p.text, p.field, BODY),
        ("placeholder on field", p.placeholder, p.field, BODY),
        ("text on tooltip", p.text, p.tooltip, BODY),
        ("button text on hover", p.text, p.hover, BODY),
        ("button text on pressed", p.text, p.pressed, BODY),
        ("danger button text on hover", p.danger, p.hover, BODY),
        ("menu text on selection", p.text, p.selection, BODY),
        ("list selection text", p.selection_text, p.selection, BODY),
        ("list hover text", p.text, p.list_hover, BODY),
        ("table header", p.header_text, p.header_bg, BODY),
        ("notice", p.notice_text, p.notice_bg, BODY),
        ("failing-save banner", p.danger, p.notice_bg, BODY),
        ("sidebar items", p.sidebar_text, p.sidebar, BODY),
        ("hovered sidebar item", p.sidebar_text, p.sidebar_hover, BODY),
        ("selected sidebar item", p.sidebar_selected_text, p.sidebar_selected, BODY),
        ("brand subtitle", p.brand_sub, p.sidebar, BODY),
        ("session return button", p.return_text, p.return_bg, BODY),
        ("camera preview placeholder", p.preview_text, p.preview_bg, BODY),
        ("waiting state badge", p.badge_idle_text, p.badge_idle, LARGE),
        ("primary button", p.on_accent, p.accent, LARGE),
        ("hovered primary button", p.on_accent, p.accent_hover, LARGE),
        ("title bar glyphs", p.text, p.window, MARK),
        ("inactive title bar glyphs", p.caption_inactive, p.window, MARK),
        ("hovered title bar glyphs", p.text, over(p.caption_hover, p.window), MARK),
        ("pressed title bar glyphs", p.text, over(p.caption_down, p.window), MARK),
        ("chart bars and timeline ticks", p.accent_text, p.surface, MARK),
        ("percentage over the progress fill", p.text, p.meter, BODY),
        ("percentage over the progress groove", p.text, p.track, BODY),
        ("check mark", p.on_accent, p.accent, MARK),
        ("unchecked box on cards", p.check_border, p.surface, MARK),
        ("unchecked box on dialogs", p.check_border, p.window, MARK),
        ("selected timeline outline", p.text, p.track, MARK),
    ]
    # The overlay panel is slightly translucent: check it over a black and a white desktop.
    for desktop in ("#000000", "#FFFFFF"):
        panel = over(p.overlay_bg, desktop)
        for fore in ("overlay_text", "overlay_status", "overlay_time", "overlay_button"):
            out.append((f"{fore} over {desktop}", getattr(p, fore), panel, BODY))
        out.append((f"paused clock over {desktop}", p.overlay_paused, panel, BODY))
    out.append(("hovered overlay button", p.overlay_text, p.overlay_button_hover, BODY))
    for state, color in p.states.items():
        out.append((f"{state} badge text", p.on_state, color, LARGE))
        out.append((f"{state} legend on window", color, p.window, MARK))
        out.append((f"{state} legend and timeline on cards", color, p.surface, MARK))
        tint = over(f"#{TABLE_TINT:02X}{color.lstrip('#')}", p.surface)
        out.append((f"{state} report table cell", p.text, tint, BODY))
    for category, color in p.categories.items():
        out.append((f"{category} legend on window", color, p.window, MARK))
        out.append((f"{category} legend and timeline on cards", color, p.surface, MARK))
    return out


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_every_text_color_is_readable_on_its_background(palette):
    failures = [
        f"{what}: {fore} on {back} = {contrast(fore, back):.2f} < {minimum}"
        for what, fore, back, minimum in pairs(palette)
        if contrast(fore, back) < minimum
    ]
    assert not failures, "\n".join(failures)


def test_contrast_math_matches_wcag_reference_values():
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
    assert contrast("#767676", "#FFFFFF") == pytest.approx(4.54, abs=0.01)
    assert over("#80FFFFFF", "#000000") == "#808080"


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_state_and_category_colors_stay_distinct(palette):
    for table in (palette.states, palette.categories):
        values = [c.upper() for c in table.values()]
        assert len(set(values)) == len(values)


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_stylesheet_uses_only_palette_colors(palette):
    known = {
        str(v).upper()
        for v in vars(palette).values()
        if isinstance(v, str) and v.startswith(("#", "rgba"))
    }
    known |= {c.upper() for c in (*palette.states.values(), *palette.categories.values())}
    used = set(re.findall(r"#[0-9A-Fa-f]{6}\b|rgba\([^)]*\)", theme.stylesheet(palette)))
    assert {c.upper() for c in used} <= known


def test_no_hard_coded_colors_outside_the_theme():
    """Pages and widgets take colors from the palette. The parrot drawings keep their own
    colors (they sit on their own panels and bubbles), and the tray icon sits on the taskbar."""
    ui = Path(theme.__file__).parent
    allowed = {ui / "theme.py", ui / "tray.py"}
    offenders = [
        f"{path.relative_to(ui)}: {match}"
        for path in ui.rglob("*.py")
        if path not in allowed and "mascot" not in path.parts
        for match in re.findall(r"#[0-9A-Fa-f]{6}\b|QColor\(\"white\"\)", path.read_text("utf-8"))
    ]
    assert not offenders, offenders
