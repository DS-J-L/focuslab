"Colors, labels and the application stylesheet. Wording avoids scores and diagnoses."

from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QFormLayout

from focuslab.domain.activity import Category
from focuslab.domain.models import CameraStatus, FocusState
from focuslab.i18n import LocalizedMapping

STATE_COLORS = {
    FocusState.ON_TASK: "#2E9E6B",
    FocusState.POSSIBLY_OFF_TASK: "#E39B2D",
    FocusState.AWAY: "#7D8796",
    FocusState.BREAK: "#4F7FD9",
    FocusState.UNKNOWN: "#CDD2DA",
}

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

CATEGORY_COLORS = {
    Category.DEVELOPMENT: "#3B5BDB",
    Category.STUDY: "#2E9E6B",
    Category.DOCUMENTATION: "#0CA678",
    Category.RESEARCH: "#1C7ED6",
    Category.COMMUNICATION: "#AE3EC9",
    Category.ENTERTAINMENT: "#E8590C",
    Category.GAMING: "#E03131",
    Category.PRODUCTIVITY: "#5C7CFA",
    Category.BREAK: "#ADB5BD",
    Category.UNKNOWN: "#DEE2E6",
}

ACCENT = "#3B5BDB"
_ICONS = Path(__file__).with_name("icons").as_posix()


def apply_theme(app: QApplication) -> None:
    """Light theme with the bundled font, for both installed and frozen desktop builds.

    The stylesheet is a light design: keep Qt's palette light even in Windows dark mode,
    otherwise popups and unstyled areas get dark backgrounds under the dark stylesheet text."""
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    font_id = QFontDatabase.addApplicationFontFromData(
        files("focuslab.ui").joinpath("fonts/PretendardVariable.ttf").read_bytes()
    )
    families = QFontDatabase.applicationFontFamilies(font_id)
    font = QFont()
    font.setFamilies([*families[:1], "Pretendard", "Malgun Gothic", "Segoe UI"])
    font.setPointSizeF(10)
    app.setFont(font)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)


def style_form(form: QFormLayout) -> None:
    """Give labels and fields the same alignment and rhythm across pages."""
    form.setHorizontalSpacing(20)
    form.setVerticalSpacing(16)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

STYLESHEET = f"""
QWidget {{ color: #1F2430; }}
QMainWindow, QStackedWidget > QWidget, #PageContent {{ background: #F5F6F8; }}
QDialog, QMessageBox, QMenu {{ background: #F5F6F8; }}
QMenu::item:selected {{ background: #E3E8F7; }}
QToolTip {{ background: white; color: #1F2430; border: 1px solid #D5D9E0;
            padding: 6px 10px; }}
QAbstractItemView {{ background: white; selection-background-color: #E3E8F7;
                     selection-color: #1F2430; }}
#Sidebar {{ background: #1F2430; border: none; }}
#Sidebar QListWidget {{ background: transparent; border: none; color: #C9CED8; font-size: 14px;
                        outline: 0; padding: 8px 0; }}
#Sidebar QListWidget::item {{ padding: 13px 16px; border-radius: 8px; margin: 3px 12px; }}
#Sidebar QListWidget::item:hover {{ background: #2B3242; }}
#Sidebar QListWidget::item:selected {{ background: #343F60; color: white; font-weight: 600; }}
QPushButton#Clock {{ background: transparent; border: none; padding: 0; text-align: left;
                     min-height: 46px;
                     font-size: 34px; font-weight: 700; }}
QPushButton#Clock:hover {{ color: {ACCENT}; }}
#Brand {{ color: white; font-size: 20px; font-weight: 700; padding: 28px 24px 8px 24px; }}
#TitleBar {{ background: #F5F6F8; }}
#BrandSub {{ color: #A0A9BC; font-size: 12px; padding: 0 24px 20px 24px; }}
#PageTitle {{ font-size: 24px; font-weight: 700; padding-bottom: 4px; }}
#Muted {{ color: #6B7385; }}
#Card {{ background: white; border: 1px solid #E3E6EC; border-radius: 12px; }}
#CardTitle {{ color: #6B7385; font-size: 12px; }}
#CardTag {{ color: {ACCENT}; font-size: 11px; font-weight: 700; }}
#CardValue {{ font-size: 24px; font-weight: 700; padding: 3px 0; }}
#CardHint {{ color: #778196; font-size: 12px; }}
#Notice {{ background: #FFF8E6; border: 1px solid #F1D79B; border-radius: 8px; padding: 8px 10px;
           color: #6B5216; }}
#CameraOn {{ color: #C92A2A; font-weight: 700; }}
QPushButton {{ background: white; border: 1px solid #D5D9E0; border-radius: 8px;
               padding: 8px 14px; min-height: 20px; font-weight: 500; }}
QPushButton:hover {{ background: #F0F3FA; border-color: #B8C4DF; }}
QPushButton:pressed {{ background: #E7ECF8; }}
QPushButton:focus, QToolButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton:disabled {{ color: #A3A9B5; background: #F2F3F5; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT};
                       font-weight: 600;
                       padding: 10px 22px; }}
QPushButton#Primary:hover {{ background: #324FC2; }}
QPushButton#Primary:disabled {{ background: #A9B6E8; }}
QPushButton#Danger {{ color: #C92A2A; }}
QPushButton#Fab {{ background: {ACCENT}; color: white; border: none; border-radius: 28px;
                   padding: 0; font-size: 28px; font-weight: 400; }}
QPushButton#Fab[running="true"] {{ padding: 0 24px; font-size: 14px; font-weight: 600; }}
QPushButton#Fab:hover {{ background: #324FC2; }}
QPushButton#Fab:focus {{ border: 2px solid #A9B6E8; }}
#PopoverTitle {{ font-size: 16px; font-weight: 700; }}
QScrollArea#PopoverScroll, #PopoverContent {{ background: transparent; border: none; }}
QPushButton#Disclosure {{ text-align: left; padding: 8px 12px; }}
#Sidebar QPushButton#SessionReturn {{ background: #2B3242; color: #E4E8F0;
    border: 1px solid #3B4560; border-radius: 8px; padding: 10px 14px; text-align: left;
    font-size: 12px; }}
#Sidebar QPushButton#SessionReturn:hover {{ background: #343F60; }}
#Sidebar QPushButton#SessionReturn[current="true"] {{ background: #343F60; color: white;
    border-color: {ACCENT}; font-weight: 600; }}
QToolButton {{ background: white; border: 1px solid #D5D9E0; border-radius: 8px;
               padding: 8px 12px; min-height: 20px; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{
    background: #FCFDFF; border: 1px solid #D9DFEA; border-radius: 8px;
    padding: 9px 12px; selection-background-color: #DFE6FF; selection-color: #1F2430;
    font-weight: 400; }}
QLineEdit, QSpinBox, QComboBox {{ min-height: 20px; }}
QLineEdit {{ placeholder-text-color: #929BAD; }}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover, QPlainTextEdit:hover {{
    border-color: #B1BDD2; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT}; background: white; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled {{
    color: #929BAD; background: #F1F3F7; border-color: #E1E5ED; }}
QComboBox {{ padding-right: 36px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right;
                       width: 30px; border: none; }}
QComboBox::down-arrow {{ image: url("{_ICONS}/chevron-down.svg"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ padding: 6px; border: 1px solid #D9DFEA; outline: 0; }}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 4px 8px; }}
QSpinBox {{ padding-right: 32px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border;
    width: 28px; border: none; border-left: 1px solid #E3E7F0; }}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #EEF2FC; }}
QSpinBox::up-arrow {{ image: url("{_ICONS}/chevron-up.svg"); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url("{_ICONS}/chevron-down.svg"); width: 12px; height: 12px; }}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{ image: none; }}
QCheckBox, QRadioButton {{ spacing: 8px; padding: 3px 0; font-weight: 400; }}
QListWidget, QTableWidget {{ background: white; border: 1px solid #DEE3ED;
    border-radius: 8px; padding: 6px; outline: 0; font-weight: 400;
    selection-background-color: #EBF0FF; selection-color: #2E49AB; }}
QListWidget::item {{ padding: 7px 10px; border-radius: 5px; }}
QListWidget::item:hover {{ background: #F3F5FA; }}
QListWidget::item:selected {{ background: #EBF0FF; color: #2E49AB; }}
QHeaderView::section {{ background: #F5F7FB; color: #626E84;
    border: none; border-bottom: 1px solid #E3E7F0; padding: 9px 8px; font-weight: 600; }}
QTableWidget {{ gridline-color: #EEF0F3; }}
QGroupBox {{ background: white; border: 1px solid #E3E6EC; border-radius: 12px; margin-top: 20px;
             padding: 22px 18px 18px 18px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 18px; padding: 0 6px; color: #3C4861; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CCD3E0; border-radius: 3px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #AAB5C8; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QProgressBar {{ border: none; background: #E6E9EF; border-radius: 4px; height: 8px;
                text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
"""
