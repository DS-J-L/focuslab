"""Separate, explicit consent prompts for automatic recording, PC activity and camera."""

from PySide6.QtWidgets import QMessageBox, QWidget

ACTIVITY_TEXT = (
    "세션 중에만 다음을 1초마다 읽습니다.\n\n"
    "• 맨 앞 창의 프로세스 이름 (예: code.exe)\n"
    "• 마지막 키보드·마우스 입력 이후 경과 시간\n"
    "• 화면 잠금 여부\n\n"
    "창 제목, 문서 이름, URL, 키 입력 내용, 화면은 읽거나 저장하지 않습니다.\n"
    "동의하지 않으면 PC 활동 없이 (카메라만으로) 관찰하며 대부분 '판단 불가'로 표시됩니다."
)

RECORDING_TEXT = (
    "FocusLab이 실행 중인 동안 세션을 시작하지 않아도 PC 사용 기록을 자동으로 남깁니다.\n\n"
    "• 맨 앞 프로그램의 실행 파일 이름과 제품 이름 (예: code.exe, Visual Studio Code)\n"
    "• 프로그램을 쓰기 시작·끝낸 시각과 전환 횟수\n"
    "• 화면 잠금 여부\n\n"
    "창 제목, 실행 파일 경로, 문서 이름, URL, 키 입력 내용, 화면은 읽거나 저장하지 않습니다.\n"
    "기록은 이 PC에만 저장되며 설정에서 언제든 끄고 삭제할 수 있습니다."
)

CAMERA_TEXT = (
    "카메라는 직접 시작한 세션 동안에만 켜지고, 일시정지·종료 시 즉시 해제됩니다.\n\n"
    "• 영상은 메모리에서만 처리되며 저장·전송되지 않습니다.\n"
    "• 얼굴이 보이는지와 머리 방향 각도만 계산해 1초 단위 상태 추정에 씁니다.\n"
    "• 얼굴 신원 식별, 감정 인식, 진단을 하지 않습니다.\n"
    "• 저장되는 것은 상태와 근거 코드뿐입니다.\n\n"
    "설정에서 언제든 동의를 철회할 수 있습니다."
)


def ask(parent: QWidget, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(title)
    box.setInformativeText(text)
    agree = box.addButton("동의하고 사용", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("사용 안 함", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is agree


def ask_activity_consent(parent: QWidget) -> bool:
    return ask(parent, "PC 활동 관찰 동의", ACTIVITY_TEXT)


def ask_camera_consent(parent: QWidget) -> bool:
    return ask(parent, "카메라 관찰 동의", CAMERA_TEXT)


def ask_recording_consent(parent: QWidget) -> bool:
    return ask(parent, "자동 활동 기록 동의", RECORDING_TEXT)
