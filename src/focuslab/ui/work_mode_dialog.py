"""Add or edit one of the user's own work modes: a name and the built-in mode it is estimated
like. Its allowed apps start from that mode's defaults and are edited in New session."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from focuslab.config import ESTIMATION_HINTS, MODE_LABELS
from focuslab.domain.models import SessionMode
from focuslab.i18n import tr
from focuslab.ui.theme import style_form
from focuslab.work_modes import BASES, MAX_NAME, WorkMode, clean_name, new_mode


class WorkModeDialog(QDialog):
    def __init__(
        self,
        taken: set[str],
        mode: WorkMode | None = None,
        parent: QWidget | None = None,
    ) -> None:
        "``taken`` holds the labels of the other modes; a new name may not repeat one."
        super().__init__(parent)
        self._mode = mode
        self._taken = {name.casefold() for name in taken}
        self.setWindowTitle(tr("Edit work mode") if mode else tr("Add work mode"))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        style_form(form)
        self.name = QLineEdit(mode.name if mode else "")
        self.name.setMaxLength(MAX_NAME)
        self.name.setPlaceholderText(tr("For example: Design, Language study, Exam prep"))
        form.addRow(tr("Name"), self.name)
        self.base = QComboBox()
        for base in BASES:
            self.base.addItem(MODE_LABELS[base], base.value)
        if mode:
            self.base.setCurrentIndex(max(0, self.base.findData(mode.base.value)))
        form.addRow(tr("Estimate like"), self.base)
        self.hint = QLabel(wordWrap=True, objectName="Muted")
        form.addRow("", self.hint)
        layout.addLayout(form)
        note = QLabel(
            tr(
                "Allowed apps start from the chosen mode's list. Change them when you start "
                "a session in this mode."
            ),
            wordWrap=True,
            objectName="Muted",
        )
        layout.addWidget(note)
        self.problem = QLabel(wordWrap=True, objectName="Muted")
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.save = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name.textChanged.connect(self._validate)
        self.base.currentIndexChanged.connect(self._base_changed)
        self._base_changed()
        self._validate()

    def _base_changed(self) -> None:
        self.hint.setText(ESTIMATION_HINTS[self.current_base()])

    def _validate(self) -> None:
        name = clean_name(self.name.text())
        duplicate = name.casefold() in self._taken
        self.problem.setText(tr("A work mode with this name already exists.") if duplicate else "")
        self.problem.setVisible(duplicate)
        self.save.setEnabled(bool(name) and not duplicate)

    def current_base(self) -> SessionMode:
        return SessionMode(self.base.currentData())

    def result_mode(self) -> WorkMode:
        name, base = clean_name(self.name.text()), self.current_base()
        if self._mode is None:
            return new_mode(name, base)
        return WorkMode(self._mode.key, base, name)
