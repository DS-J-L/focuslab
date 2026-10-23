"Light and dark palettes, labels and the stylesheet. Wording avoids scores and diagnoses."

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TypeVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QFormLayout, QWidget

from focuslab.domain.activity import Category
from focuslab.domain.models import CameraStatus, FocusState
from focuslab.i18n import LocalizedMapping

K = TypeVar("K")

STATE_LABELS = LocalizedMapping(
    {
        FocusState.ON_TASK: "Task-related activity (estimated)",
        FocusState.POSSIBLY_OFF_TASK: "Possibly off task",
        FocusState.AWAY: "Away (estimated)",
        FocusState.BREAK: "Break",
        FocusState.UNKNOWN: "Cannot determine",
    }
)

SHORT_LABELS = LocalizedMapping(
    {
        FocusState.ON_TASK: "Task-related",
        FocusState.POSSIBLY_OFF_TASK: "Possibly off task",
        FocusState.AWAY: "Away",
        FocusState.BREAK: "Break",
        FocusState.UNKNOWN: "Cannot determine",
    }
)

CORRECTION_LABELS = LocalizedMapping(
    {
        FocusState.ON_TASK: "I was working normally",
        FocusState.BREAK: "I was taking a break",
        FocusState.AWAY: "I was away",
        FocusState.POSSIBLY_OFF_TASK: "I was off task",
    }
)

CAMERA_LABELS = LocalizedMapping(
    {
        CameraStatus.OFF: "Camera off",
        CameraStatus.STARTING: "Opening camera…",
        CameraStatus.RUNNING: "Camera in use",
        CameraStatus.NO_DEVICE: "Cannot open camera (check device and permissions)",
        CameraStatus.DISCONNECTED: "Camera disconnected — retrying connection",
        CameraStatus.MODEL_MISSING: "Face model missing — using PC activity only",
        CameraStatus.MODEL_ERROR: "Face model error — using PC activity only",
    }
)

SELF_REPORT_LABELS = LocalizedMapping(
    {"ACHIEVED": "Achieved", "PARTIAL": "Partially achieved", "NOT_ACHIEVED": "Not achieved"}
)

CATEGORY_LABELS = LocalizedMapping(
    {
        Category.DEVELOPMENT: "Development",
        Category.STUDY: "Study",
        Category.DOCUMENTATION: "Documentation",
        Category.RESEARCH: "Research",
        Category.COMMUNICATION: "Communication",
        Category.ENTERTAINMENT: "Entertainment",
        Category.GAMING: "Gaming",
        Category.PRODUCTIVITY: "Productivity tools",
        Category.BREAK: "Break / inactive",
        Category.UNKNOWN: "Unclassified",
    }
)

THEMES = ("light", "dark", "system")
THEME_LABELS = LocalizedMapping({"light": "Light", "dark": "Dark", "system": "Follow Windows"})


@dataclass(frozen=True)
class Palette:
    """Every color the interface uses. ``tests/unit/test_theme_contrast.py`` checks that each
    text color is readable on the backgrounds it is drawn on (WCAG 2.x contrast)."""

    dark: bool
    window: str  # page background, title bar, dialogs
    surface: str  # cards, group boxes, buttons, lists, popovers
    field: str  # text inputs
    text: str
    muted: str  # secondary text
    hint: str  # card hints
    heading: str  # group box titles
    border: str  # cards and group boxes
    control_border: str  # buttons
    field_border: str
    field_border_hover: str
    hover: str
    pressed: str
    disabled_text: str
    disabled_bg: str
    placeholder: str
    accent: str  # primary button fill
    accent_hover: str
    accent_disabled: str
    on_accent: str  # text on the accent fill
    accent_text: str  # accent-colored text, focus rings and chart bars on surfaces
    selection: str
    selection_text: str
    list_hover: str
    header_bg: str
    header_text: str
    gridline: str
    scroll: str
    scroll_hover: str
    track: str  # empty timeline and progress groove
    meter: str  # progress fill behind a percentage written over it
    check_border: str  # unchecked check boxes
    tooltip: str
    sidebar: str
    sidebar_text: str
    sidebar_hover: str
    sidebar_selected: str
    sidebar_selected_text: str
    brand_sub: str
    return_bg: str
    return_text: str
    return_border: str
    notice_bg: str
    notice_border: str
    notice_text: str
    danger: str  # warnings and destructive buttons, as text
    caption_inactive: str  # title bar glyphs while the window is in the background
    caption_hover: str  # #AARRGGBB wash over a caption button
    caption_down: str
    shadow: str  # #AARRGGBB, one stroke of the popover's soft shadow
    preview_bg: str
    preview_text: str
    badge_idle: str  # state badge before the first estimate
    badge_idle_text: str
    on_state: str  # text on a state badge
    # The session overlay floats over other programs: a dark panel in both themes.
    overlay_bg: str
    overlay_text: str
    overlay_status: str
    overlay_time: str
    overlay_button: str
    overlay_button_hover: str
    overlay_paused: str
    states: Mapping[FocusState, str]
    categories: Mapping[Category, str]


_OVERLAY = {
    "overlay_bg": "rgba(31, 36, 48, 238)",
    "overlay_text": "#FFFFFF",
    "overlay_status": "#A0A9BC",
    "overlay_time": "#E6E9EF",
    "overlay_button": "#C9CED8",
    "overlay_button_hover": "#343F60",
    "overlay_paused": "#969EB0",
}

LIGHT = Palette(
    dark=False,
    window="#F5F6F8",
    surface="#FFFFFF",
    field="#FCFDFF",
    text="#1F2430",
    muted="#636B7D",
    hint="#666F82",
    heading="#3C4861",
    border="#E3E6EC",
    control_border="#D5D9E0",
    field_border="#D9DFEA",
    field_border_hover="#B1BDD2",
    hover="#F0F3FA",
    pressed="#E7ECF8",
    disabled_text="#A3A9B5",
    disabled_bg="#F2F3F5",
    placeholder="#6B7385",
    accent="#3B5BDB",
    accent_hover="#324FC2",
    accent_disabled="#A9B6E8",
    on_accent="#FFFFFF",
    accent_text="#3B5BDB",
    selection="#E3E8F7",
    selection_text="#2E49AB",
    list_hover="#F3F5FA",
    header_bg="#F5F7FB",
    header_text="#5D687E",
    gridline="#EEF0F3",
    scroll="#CCD3E0",
    scroll_hover="#AAB5C8",
    track="#EEF0F3",
    meter="#AFC0F7",
    check_border="#878FA0",
    tooltip="#FFFFFF",
    sidebar="#1F2430",
    sidebar_text="#C9CED8",
    sidebar_hover="#2B3242",
    sidebar_selected="#343F60",
    sidebar_selected_text="#FFFFFF",
    brand_sub="#A0A9BC",
    return_bg="#2B3242",
    return_text="#E4E8F0",
    return_border="#3B4560",
    notice_bg="#FFF8E6",
    notice_border="#F1D79B",
    notice_text="#6B5216",
    danger="#C92A2A",
    caption_inactive="#7D8699",
    caption_hover="#0D000000",
    caption_down="#16000000",
    shadow="#071F2430",
    preview_bg="#1F2430",
    preview_text="#A0A9BC",
    badge_idle="#E6E9EF",
    badge_idle_text="#3A4150",
    on_state="#FFFFFF",
    **_OVERLAY,
    states={
        FocusState.ON_TASK: "#26875B",
        FocusState.POSSIBLY_OFF_TASK: "#B4690E",
        FocusState.AWAY: "#5F6A7D",
        FocusState.BREAK: "#4473D0",
        FocusState.UNKNOWN: "#848C9A",
    },
    categories={
        Category.DEVELOPMENT: "#3B5BDB",
        Category.STUDY: "#26875B",
        Category.DOCUMENTATION: "#0B8A66",
        Category.RESEARCH: "#1C7ED6",
        Category.COMMUNICATION: "#AE3EC9",
        Category.ENTERTAINMENT: "#D9480F",
        Category.GAMING: "#E03131",
        Category.PRODUCTIVITY: "#5C7CFA",
        Category.BREAK: "#6E7785",
        Category.UNKNOWN: "#848C9A",
    },
)

DARK = Palette(
    dark=True,
    window="#15181E",
    surface="#1E222A",
    field="#191C23",
    text="#E6E9EF",
    muted="#A2AABA",
    hint="#98A1B3",
    heading="#C5CCDA",
    border="#2B313C",
    control_border="#3A414E",
    field_border="#363D49",
    field_border_hover="#4D5668",
    hover="#272C36",
    pressed="#2E3440",
    disabled_text="#5F6777",
    disabled_bg="#1A1D23",
    placeholder="#8C95A7",
    accent="#3B5BDB",
    accent_hover="#4A68E3",
    accent_disabled="#2E3A66",
    on_accent="#FFFFFF",
    accent_text="#8FA5FF",
    selection="#2C3A63",
    selection_text="#E6E9EF",
    list_hover="#232833",
    header_bg="#1A1E25",
    header_text="#A2AABA",
    gridline="#2A2F39",
    scroll="#3A414E",
    scroll_hover="#4D5668",
    track="#2A2F39",
    meter="#3B5BDB",
    check_border="#737C8D",
    tooltip="#262B35",
    sidebar="#101217",
    sidebar_text="#B9C0CD",
    sidebar_hover="#1C2029",
    sidebar_selected="#2C3A63",
    sidebar_selected_text="#FFFFFF",
    brand_sub="#8D96A9",
    return_bg="#1C2029",
    return_text="#E4E8F0",
    return_border="#343C4F",
    notice_bg="#33291A",
    notice_border="#6B5A2E",
    notice_text="#F1D79B",
    danger="#FF7B7B",
    caption_inactive="#7F889A",
    caption_hover="#1AFFFFFF",
    caption_down="#2AFFFFFF",
    shadow="#14000000",
    preview_bg="#0E1014",
    preview_text="#8C94A6",
    badge_idle="#2B313C",
    badge_idle_text="#C9CED8",
    on_state="#111318",
    **_OVERLAY,
    states={
        FocusState.ON_TASK: "#3DB884",
        FocusState.POSSIBLY_OFF_TASK: "#E9A23B",
        FocusState.AWAY: "#A3ACBC",
        FocusState.BREAK: "#76A0F2",
        FocusState.UNKNOWN: "#6E7686",
    },
    categories={
        Category.DEVELOPMENT: "#6F8CF5",
        Category.STUDY: "#3DB884",
        Category.DOCUMENTATION: "#20C997",
        Category.RESEARCH: "#4DABF7",
        Category.COMMUNICATION: "#C77DDB",
        Category.ENTERTAINMENT: "#F0803C",
        Category.GAMING: "#F06565",
        Category.PRODUCTIVITY: "#A5B4FC",
        Category.BREAK: "#8C95A5",
        Category.UNKNOWN: "#6E7686",
    },
)

_active = LIGHT
_choice = "light"


def colors() -> Palette:
    "The palette of the theme in use; painters read it on every paint."
    return _active


class _ThemeColors(Mapping[K, str]):
    "A color table that always answers from the palette in use, like ``LocalizedMapping``."

    def __init__(self, table: Callable[[Palette], Mapping[K, str]]) -> None:
        self._table = table

    def __getitem__(self, key: K) -> str:
        return self._table(_active)[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._table(_active))

    def __len__(self) -> int:
        return len(self._table(_active))


STATE_COLORS: Mapping[FocusState, str] = _ThemeColors(lambda p: p.states)
CATEGORY_COLORS: Mapping[Category, str] = _ThemeColors(lambda p: p.categories)
ACTIVE_COLORS: Mapping[str, str] = _ThemeColors(lambda p: {"active": p.accent_text})
ACCENT = LIGHT.accent  # the tray icon sits on the taskbar, not on a FocusLab page
_ICONS = Path(__file__).with_name("icons").as_posix()
_font_loaded = False


def resolve_theme(choice: str, app: QApplication) -> Palette:
    "``system`` follows the Windows app mode (light where Qt cannot tell, e.g. off-screen)."
    if choice == "system":
        return DARK if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT
    return DARK if choice == "dark" else LIGHT


def apply_theme(app: QApplication, choice: str = "light") -> None:
    """Bundled font, Fusion style, and the palette and stylesheet of ``choice`` (see THEMES).

    Applying again switches the theme live: the stylesheet repolishes every widget, painters
    read ``colors()``, and pages rebuild their charts on their next refresh. Qt's own palette is
    set too, so menus, combo popups and message boxes match the stylesheet in either mode."""
    global _active, _choice, _font_loaded
    _choice = choice if choice in THEMES else "light"
    hints = app.styleHints()
    if _choice == "system":
        hints.unsetColorScheme()
    _active = resolve_theme(_choice, app)
    if _choice != "system":
        hints.setColorScheme(Qt.ColorScheme.Dark if _active.dark else Qt.ColorScheme.Light)
    if not _font_loaded:
        font_id = QFontDatabase.addApplicationFontFromData(
            files("focuslab.ui").joinpath("fonts/PretendardVariable.ttf").read_bytes()
        )
        families = QFontDatabase.applicationFontFamilies(font_id)
        font = QFont()
        font.setFamilies([*families[:1], "Pretendard", "Malgun Gothic", "Segoe UI"])
        font.setPointSizeF(10)
        app.setFont(font)
        hints.colorSchemeChanged.connect(lambda _scheme: _follow_windows(app))
        _font_loaded = True
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    app.setPalette(qt_palette(_active))
    app.setStyleSheet(stylesheet(_active))


def _follow_windows(app: QApplication) -> None:
    "Windows switched between light and dark apps while FocusLab runs."
    if _choice == "system" and resolve_theme("system", app) is not _active:
        apply_theme(app, "system")


def qt_palette(p: Palette) -> QPalette:
    roles = QPalette.ColorRole
    palette = QPalette()
    for role, color in {
        roles.Window: p.window,
        roles.WindowText: p.text,
        roles.Base: p.surface,
        roles.AlternateBase: p.list_hover,
        roles.ToolTipBase: p.tooltip,
        roles.ToolTipText: p.text,
        roles.PlaceholderText: p.placeholder,
        roles.Text: p.text,
        roles.Button: p.surface,
        roles.ButtonText: p.text,
        roles.BrightText: p.danger,
        roles.Light: p.hover,
        roles.Midlight: p.border,
        roles.Mid: p.control_border,
        roles.Dark: p.field_border_hover,
        roles.Shadow: "#000000",
        roles.Highlight: p.accent,
        roles.HighlightedText: p.on_accent,
        roles.Link: p.accent_text,
        roles.LinkVisited: p.accent_text,
    }.items():
        palette.setColor(role, QColor(color))
    disabled = QPalette.ColorGroup.Disabled
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        palette.setColor(disabled, role, QColor(p.disabled_text))
    palette.setColor(disabled, roles.Button, QColor(p.disabled_bg))
    return palette


def set_style_flag(widget: QWidget, name: str, value: object) -> None:
    "Set a dynamic property the stylesheet selects on; restyle only when it changed."
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def style_form(form: QFormLayout) -> None:
    """Give labels and fields the same alignment and rhythm across pages."""
    form.setHorizontalSpacing(20)
    form.setVerticalSpacing(16)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)


def stylesheet(p: Palette) -> str:
    badges = "\n".join(
        f'QLabel#StateBadge[state="{state.value}"] {{ background: {color}; color: {p.on_state}; }}'
        for state, color in p.states.items()
    )
    return f"""
QWidget {{ color: {p.text}; }}
QMainWindow, QStackedWidget > QWidget, #PageContent {{ background: {p.window}; }}
QDialog, QMessageBox, QMenu {{ background: {p.window}; }}
QMenu::item:selected {{ background: {p.selection}; color: {p.text}; }}
QToolTip {{ background: {p.tooltip}; color: {p.text}; border: 1px solid {p.control_border};
            padding: 6px 10px; }}
QAbstractItemView {{ background: {p.surface}; selection-background-color: {p.selection};
                     selection-color: {p.text}; }}
#Sidebar {{ background: {p.sidebar}; border: none; }}
#Sidebar QListWidget {{ background: transparent; border: none; color: {p.sidebar_text};
                        font-size: 14px; outline: 0; padding: 8px 0; }}
#Sidebar QListWidget::item {{ padding: 13px 16px; border-radius: 8px; margin: 3px 12px; }}
#Sidebar QListWidget::item:hover {{ background: {p.sidebar_hover}; }}
#Sidebar QListWidget::item:selected {{ background: {p.sidebar_selected};
    color: {p.sidebar_selected_text}; font-weight: 600; }}
QPushButton#Clock {{ background: transparent; border: none; padding: 0; text-align: left;
                     min-height: 46px;
                     font-size: 34px; font-weight: 700; }}
QPushButton#Clock:hover {{ color: {p.accent_text}; }}
#Brand {{ color: {p.sidebar_selected_text}; font-size: 20px; font-weight: 700;
          padding: 28px 24px 8px 24px; }}
#TitleBar {{ background: {p.window}; }}
#BrandSub {{ color: {p.brand_sub}; font-size: 12px; padding: 0 24px 20px 24px; }}
#PageTitle {{ font-size: 24px; font-weight: 700; padding-bottom: 4px; }}
#Muted {{ color: {p.muted}; }}
#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
#CardTitle {{ color: {p.muted}; font-size: 12px; }}
#CardTag {{ color: {p.accent_text}; font-size: 11px; font-weight: 700; }}
#CardValue {{ font-size: 24px; font-weight: 700; padding: 3px 0; }}
#CardHint {{ color: {p.hint}; font-size: 12px; }}
#Notice {{ background: {p.notice_bg}; border: 1px solid {p.notice_border}; border-radius: 8px;
           padding: 8px 10px; color: {p.notice_text}; }}
#CameraOn {{ color: {p.danger}; font-weight: 700; }}
QLabel[warning="true"], QLabel#Notice[warning="true"] {{ color: {p.danger}; font-weight: 700; }}
QLabel#CameraPreview {{ background: {p.preview_bg}; color: {p.preview_text};
                        border-radius: 8px; }}
QLabel#StateBadge {{ background: {p.badge_idle}; color: {p.badge_idle_text};
    border-radius: 12px; font-size: 20px; font-weight: 700; padding: 10px 16px; }}
{badges}
QPushButton {{ background: {p.surface}; border: 1px solid {p.control_border}; border-radius: 8px;
               padding: 8px 14px; min-height: 20px; font-weight: 500; }}
QPushButton:hover {{ background: {p.hover}; border-color: {p.field_border_hover}; }}
QPushButton:pressed {{ background: {p.pressed}; }}
QPushButton:focus, QToolButton:focus {{ border: 1px solid {p.accent_text}; }}
QPushButton:disabled {{ color: {p.disabled_text}; background: {p.disabled_bg}; }}
QPushButton#Primary {{ background: {p.accent}; color: {p.on_accent}; border: 1px solid {p.accent};
                       font-weight: 600;
                       padding: 10px 22px; }}
QPushButton#Primary:hover {{ background: {p.accent_hover}; }}
QPushButton#Primary:disabled {{ background: {p.accent_disabled}; }}
QPushButton#Danger {{ color: {p.danger}; }}
QPushButton#Fab {{ background: {p.accent}; color: {p.on_accent}; border: none; border-radius: 28px;
                   padding: 0; font-size: 28px; font-weight: 400; }}
QPushButton#Fab[running="true"] {{ padding: 0 24px; font-size: 14px; font-weight: 600; }}
QPushButton#Fab:hover {{ background: {p.accent_hover}; }}
QPushButton#Fab:focus {{ border: 2px solid {p.accent_text if p.dark else p.accent_disabled}; }}
#PopoverTitle {{ font-size: 16px; font-weight: 700; }}
QScrollArea#PopoverScroll, #PopoverContent {{ background: transparent; border: none; }}
QPushButton#Disclosure {{ text-align: left; padding: 8px 12px; }}
#Sidebar QPushButton#SessionReturn {{ background: {p.return_bg}; color: {p.return_text};
    border: 1px solid {p.return_border}; border-radius: 8px; padding: 10px 14px; text-align: left;
    font-size: 12px; }}
#Sidebar QPushButton#SessionReturn:hover {{ background: {p.sidebar_selected}; }}
#Sidebar QPushButton#SessionReturn[current="true"] {{ background: {p.sidebar_selected};
    color: {p.sidebar_selected_text}; border-color: {p.accent}; font-weight: 600; }}
QToolButton {{ background: {p.surface}; border: 1px solid {p.control_border}; border-radius: 8px;
               padding: 8px 12px; min-height: 20px; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{
    background: {p.field}; border: 1px solid {p.field_border}; border-radius: 8px;
    padding: 9px 12px; selection-background-color: {p.selection}; selection-color: {p.text};
    font-weight: 400; }}
QLineEdit, QSpinBox, QComboBox {{ min-height: 20px; }}
QLineEdit {{ placeholder-text-color: {p.placeholder}; }}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover, QPlainTextEdit:hover {{
    border-color: {p.field_border_hover}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {p.accent_text}; background: {p.surface}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled {{
    color: {p.disabled_text}; background: {p.disabled_bg}; border-color: {p.border}; }}
QComboBox {{ padding-right: 36px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right;
                       width: 30px; border: none; }}
QComboBox::down-arrow {{ image: url("{_ICONS}/chevron-down.svg"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ padding: 6px; border: 1px solid {p.field_border}; outline: 0; }}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 4px 8px; }}
QSpinBox {{ padding-right: 32px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border;
    width: 28px; border: none; border-left: 1px solid {p.border}; }}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {p.hover}; }}
QSpinBox::up-arrow {{ image: url("{_ICONS}/chevron-up.svg"); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url("{_ICONS}/chevron-down.svg"); width: 12px; height: 12px; }}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{ image: none; }}
QCheckBox, QRadioButton {{ spacing: 8px; padding: 3px 0; font-weight: 400; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {p.check_border};
                        border-radius: 4px; background: {p.field}; }}
QCheckBox::indicator:hover {{ border-color: {p.accent_text}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent};
                                image: url("{_ICONS}/check.svg"); }}
QCheckBox::indicator:disabled {{ background: {p.disabled_bg}; border-color: {p.border}; }}
QCheckBox::indicator:checked:disabled {{ background: {p.accent_disabled};
                                         border-color: {p.accent_disabled}; }}
QListWidget, QTableWidget {{ background: {p.surface}; border: 1px solid {p.border};
    border-radius: 8px; padding: 6px; outline: 0; font-weight: 400;
    selection-background-color: {p.selection}; selection-color: {p.selection_text}; }}
QListWidget::item {{ padding: 7px 10px; border-radius: 5px; }}
QListWidget::item:hover {{ background: {p.list_hover}; }}
QListWidget::item:selected {{ background: {p.selection}; color: {p.selection_text}; }}
QHeaderView::section {{ background: {p.header_bg}; color: {p.header_text};
    border: none; border-bottom: 1px solid {p.border}; padding: 9px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {p.header_bg}; border: none; }}
QTableWidget {{ gridline-color: {p.gridline}; }}
QGroupBox {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px;
             margin-top: 20px; padding: 22px 18px 18px 18px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 18px; padding: 0 6px; color: {p.heading}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.scroll}; border-radius: 3px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {p.scroll_hover}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QProgressBar {{ border: none; background: {p.track}; border-radius: 4px; height: 8px;
                text-align: center; }}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}
QProgressBar[textVisible="true"]::chunk {{ background: {p.meter}; }}
#Overlay {{ background: {p.overlay_bg}; border-radius: 14px; }}
#Overlay QLabel {{ color: {p.overlay_text}; background: transparent; }}
#Overlay QLabel#OverlayStatus {{ color: {p.overlay_text}; font-size: 12px; font-weight: 600; }}
#Overlay QLabel#OverlayTime {{ color: {p.overlay_time}; font-size: 19px; font-weight: 700; }}
#Overlay QLabel[paused="true"], #Overlay QLabel#OverlayTime[paused="true"] {{
    color: {p.overlay_paused}; }}
#Overlay QPushButton {{ background: transparent; border: none; border-radius: 6px;
                       color: {p.overlay_button}; padding: 2px 6px; min-height: 0;
                       font-size: 14px; }}
#Overlay QPushButton:hover {{ color: {p.overlay_text}; background: {p.overlay_button_hover}; }}
"""
