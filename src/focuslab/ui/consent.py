"Separate, explicit consent prompts for automatic recording, PC activity and camera."

from PySide6.QtWidgets import QMessageBox, QWidget

from focuslab.i18n import tr

ACTIVITY_TEXT = (
    "The following is read once per second during a focus session only.\n\n• "
    "Foreground process name (for example, code.exe)\n• Time since the last keyboard "
    "or mouse input\n• Whether the screen is locked\n\nWindow titles, document "
    "names, URLs, typed content, and screen contents are not read or saved.\nIf you "
    "decline, observation uses only the camera, if enabled, and most states will be "
    "unknown."
)

RECORDING_TEXT = (
    "While FocusLab is running, it automatically records PC use even without "
    "starting a focus session.\n\n• Foreground executable and product names (for "
    "example, code.exe, Visual Studio Code)\n• When program use starts and ends, and "
    "switch counts\n• Whether the screen is locked\n\nWindow titles, executable "
    "paths, document names, URLs, typed content, and screen contents are not "
    "recorded.\nRecords stay on this PC. You can disable recording and delete "
    "records in Settings at any time."
)

BROWSER_TEXT = (
    "With the FocusLab extension installed in Chrome or Edge, only the active tab's "
    "hostname\n(for example, github.com) is sent to FocusLab on this PC while the "
    "browser is in front.\n\n• Optional page-title collection requires separate consent.\n"
    "• Full URLs, paths, search terms, page contents, and "
    "browsing history are not sent or saved.\n• Background tabs and InPrivate / "
    "incognito windows are not recorded.\n• The extension communicates with FocusLab "
    "only through Native Messaging, without network access.\n\nWithdrawing consent "
    "stops receiving browser state and clears the stored current state."
)

PAGE_TITLES_TEXT = (
    "With separate permission, the title of the current Chrome/Edge tab will be saved "
    "alongside its hostname while that tab is visible and the browser is in front.\n\n"
    "Page titles may contain private document names or account information. "
    "Only local records are created, but exported activity records will include titles. "
    "Some sensitive and excluded sites are suppressed, not all possible private titles.\n\n"
    "This option is OFF by default. You can turn it off to delete all stored page titles "
    "without deleting your activity intervals. Full URLs and page contents are never collected."
)


CAMERA_TEXT = (
    "The camera runs only during focus sessions you start and is released when you "
    "pause or end a session.\n\n• Video is processed only in memory and is never "
    "saved or transmitted.\n• Face presence and head angles inform per-second state "
    "estimates.\n• No identity recognition, emotion recognition, or diagnosis is "
    "performed.\n• Only estimated states and evidence codes are saved.\n\nYou can "
    "withdraw consent in Settings at any time."
)


def ask(parent: QWidget, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(title)
    box.setInformativeText(text)
    agree = box.addButton(tr("Agree and enable"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(tr("Do not enable"), QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is agree


def ask_activity_consent(parent: QWidget) -> bool:
    return ask(parent, tr("PC activity observation consent"), tr(ACTIVITY_TEXT))


def ask_camera_consent(parent: QWidget) -> bool:
    return ask(parent, tr("Camera observation consent"), tr(CAMERA_TEXT))


def ask_browser_consent(parent: QWidget) -> bool:
    return ask(parent, tr("Browser site recording consent"), tr(BROWSER_TEXT))


def ask_page_titles_consent(parent: QWidget) -> bool:
    return ask(parent, tr("Optional page title recording"), tr(PAGE_TITLES_TEXT))


def ask_recording_consent(parent: QWidget) -> bool:
    return ask(parent, tr("Automatic activity recording consent"), tr(RECORDING_TEXT))
