"""A little conversation in the sidebar, chosen locally without reading activity data."""

import random

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import QLabel, QWidget

from focuslab.i18n import tr

ROTATE_MS = 10 * 60 * 1000

# English message IDs, with the conversational Korean wording in locales/ko.json.
# Questions invite reflection; they never claim to know what the user did or felt.
PROMPTS = (
    "What did you use your laptop for today?",
    "How many minutes did you focus today?",
    "What are you working on right now?",
    "What was the first thing you started today?",
    "Is there something you'd like to finish today?",
    "How is your work going?",
    "What took up most of your time today?",
    "Did your mind wander for a moment?",
    "Shall we ease back into what you were doing?",
    "If you did just one thing now, what would it be?",
    "Did you learn anything new today?",
    "Where did you leave off?",
    "What's one thing you learned today?",
    "Is there a part you're stuck on?",
    "Where would be a good place to pick up again?",
    "Shall we start with one small task?",
    "Is there too much on your list today?",
    "What's on your mind right now?",
    "It's okay to take a break and come back.",
    "How about a sip of water?",
    "Are your shoulders feeling tense?",
    "Shall we look away from the screen for a moment?",
    "Is there a topic you're curious about lately?",
    "Is there something you'd like to learn?",
    "Did an idea just come to you?",
    "Shall we jot it down before you forget?",
    "Is there a task you've been putting off?",
    "Shall we tidy up a little before starting?",
    "How does this pace feel?",
    "What would you like to spend your time on today?",
    "Have you made a little progress since earlier?",
    "Which part of your work do you enjoy most?",
    "Was anything easier than you expected today?",
    "What took longer than you expected?",
    "What stands out from your day?",
    "Is there something you'd like to try again?",
    "What shall we start with today?",
    "Do you need some focus time or a break?",
    "How are you feeling today?",
    "Shall we pause and take a breath?",
    "How would you sum up today's work in one line?",
    "What are you planning to do next?",
    "What helps you get started when it's difficult?",
    "Did anything go better than expected today?",
    "How far along are you now?",
    "When are you planning to wrap up today?",
    "Shall we finish one thing, then take a break?",
    "Is your workspace comfortable?",
    "Is there something you want to remember tomorrow?",
    "It's nice to see you today.",
)


class SidebarPrompt(QLabel):
    """Shuffle all 50 before reusing any; rotate quietly while the window is visible."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="BrandSub")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self._rng = random.Random()
        self._remaining: list[str] = []
        self.message: str | None = None
        self._timer = QTimer(self, interval=ROTATE_MS)
        self._timer.timeout.connect(self._on_timeout)
        self.advance()

    def advance(self) -> None:
        if not self._remaining:
            self._remaining = list(PROMPTS)
            self._rng.shuffle(self._remaining)
            if self._remaining[-1] == self.message:
                self._remaining[0], self._remaining[-1] = self._remaining[-1], self._remaining[0]
        self.message = self._remaining.pop()
        self.setText(tr(self.message))

    def _on_timeout(self) -> None:
        if self.isVisible() and not self.window().isMinimized():
            self.advance()

    def stop(self) -> None:
        self._timer.stop()

    def _reserve_space(self) -> None:
        # Three lines fit the complete catalog at the sidebar's existing 200 px width.
        # Reserve the same height for every prompt so the navigation never jumps.
        margins = self.contentsMargins()
        self.setFixedHeight(self.fontMetrics().lineSpacing() * 3 + margins.top() + margins.bottom())

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._reserve_space()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._reserve_space()
        self._timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        self.stop()
        super().hideEvent(event)
