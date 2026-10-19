"""Colors, labels and the application stylesheet. Wording avoids scores and diagnoses."""

from focuslab.domain.models import CameraStatus, FocusState

STATE_COLORS = {
    FocusState.ON_TASK: "#2E9E6B",
    FocusState.POSSIBLY_OFF_TASK: "#E39B2D",
    FocusState.AWAY: "#7D8796",
    FocusState.BREAK: "#4F7FD9",
    FocusState.UNKNOWN: "#CDD2DA",
}

STATE_LABELS = {
    FocusState.ON_TASK: "작업 관련 활동(추정)",
    FocusState.POSSIBLY_OFF_TASK: "이탈 의심",
    FocusState.AWAY: "자리 비움(추정)",
    FocusState.BREAK: "휴식",
    FocusState.UNKNOWN: "판단 불가",
}

SHORT_LABELS = {
    FocusState.ON_TASK: "작업 관련",
    FocusState.POSSIBLY_OFF_TASK: "이탈 의심",
    FocusState.AWAY: "자리 비움",
    FocusState.BREAK: "휴식",
    FocusState.UNKNOWN: "판단 불가",
}

CORRECTION_LABELS = {
    FocusState.ON_TASK: "정상 작업이었음",
    FocusState.BREAK: "휴식이었음",
    FocusState.AWAY: "자리를 비웠음",
    FocusState.POSSIBLY_OFF_TASK: "실제로 이탈했음",
}

CAMERA_LABELS = {
    CameraStatus.OFF: "카메라 꺼짐",
    CameraStatus.STARTING: "카메라 여는 중…",
    CameraStatus.RUNNING: "카메라 사용 중",
    CameraStatus.NO_DEVICE: "카메라를 열 수 없음 (장치·권한 확인)",
    CameraStatus.DISCONNECTED: "카메라 연결 끊김 — 재연결 시도 중",
    CameraStatus.MODEL_MISSING: "얼굴 모델 없음 — PC 활동만 사용",
    CameraStatus.MODEL_ERROR: "얼굴 모델 오류 — PC 활동만 사용",
}

SELF_REPORT_LABELS = {
    "ACHIEVED": "달성",
    "PARTIAL": "일부 달성",
    "NOT_ACHIEVED": "미달성",
}

ACCENT = "#3B5BDB"

STYLESHEET = f"""
QWidget {{ color: #1F2430; }}
QMainWindow, QStackedWidget > QWidget {{ background: #F5F6F8; }}
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
