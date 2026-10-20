"Colors, labels and the application stylesheet. Wording avoids scores and diagnoses."

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

STYLESHEET = f"""
QWidget {{ color: #1F2430; }}
QMainWindow, QStackedWidget > QWidget, #PageContent {{ background: #F5F6F8; }}
QDialog, QMessageBox, QMenu {{ background: #F5F6F8; }}
QMenu::item:selected {{ background: #E3E8F7; }}
QToolTip {{ background: white; color: #1F2430; border: 1px solid #D5D9E0; }}
QAbstractItemView {{ background: white; selection-background-color: #E3E8F7;
                     selection-color: #1F2430; }}
#Sidebar {{ background: #1F2430; border: none; }}
#Sidebar QListWidget {{ background: transparent; border: none; color: #C9CED8; font-size: 14px;
                        outline: 0; }}
#Sidebar QListWidget::item {{ padding: 12px 18px; border-radius: 8px; margin: 2px 8px; }}
#Sidebar QListWidget::item:selected {{ background: #343B4C; color: white; }}
#Brand {{ color: white; font-size: 18px; font-weight: 700; padding: 18px 18px 4px 18px; }}
#BrandSub {{ color: #8C94A6; font-size: 11px; padding: 0 18px 14px 18px; }}
#PageTitle {{ font-size: 22px; font-weight: 700; }}
#Muted {{ color: #6B7385; }}
#Card {{ background: white; border: 1px solid #E3E6EC; border-radius: 12px; }}
#CardTitle {{ color: #6B7385; font-size: 12px; }}
#CardTag {{ color: {ACCENT}; font-size: 11px; font-weight: 700; }}
#CardValue {{ font-size: 22px; font-weight: 700; }}
#CardHint {{ color: #8C94A6; font-size: 11px; }}
#Notice {{ background: #FFF8E6; border: 1px solid #F1D79B; border-radius: 8px; padding: 8px 10px;
           color: #6B5216; }}
#CameraOn {{ color: #C92A2A; font-weight: 700; }}
QPushButton {{ background: white; border: 1px solid #D5D9E0; border-radius: 8px;
               padding: 7px 14px; }}
QPushButton:hover {{ background: #EEF1F6; }}
QPushButton:disabled {{ color: #A3A9B5; background: #F2F3F5; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-weight: 700;
                       padding: 10px 22px; }}
QPushButton#Primary:hover {{ background: #324FC2; }}
QPushButton#Primary:disabled {{ background: #A9B6E8; }}
QPushButton#Danger {{ color: #C92A2A; }}
QToolButton {{ background: white; border: 1px solid #D5D9E0; border-radius: 8px;
               padding: 7px 14px; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QListWidget, QTableWidget {{
    background: white; border: 1px solid #D5D9E0; border-radius: 6px; padding: 4px; }}
QHeaderView::section {{ background: #F0F2F5; border: none; padding: 6px; font-weight: 600; }}
QTableWidget {{ gridline-color: #EEF0F3; }}
QGroupBox {{ background: white; border: 1px solid #E3E6EC; border-radius: 12px; margin-top: 14px;
             padding: 14px 12px 12px 12px; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
QProgressBar {{ border: none; background: #E6E9EF; border-radius: 4px; height: 8px;
                text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
"""
