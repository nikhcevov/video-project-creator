"""Single-window PySide6 interface."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig, load_config
from .errors import ProjectCreatorError, ResolveUnavailable, ValidationError
from .presets import DEFAULT_PRESET_ID, PRESETS
from .project_service import ProjectService
from .filesystem import validate_project_name

_log = logging.getLogger(__name__)


class UiState(Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    CREATING = "creating"
    SUCCESS = "success"
    ERROR = "error"
    RESOLVE_UNAVAILABLE = "resolve_unavailable"


class FunctionWorker(QThread):
    """Run a blocking callable away from the Qt UI thread."""

    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, function: Callable[[], Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._function = function

    def run(self) -> None:
        try:
            result = self._function()
        except Exception as exc:  # reported on the UI thread through a signal
            self.failed.emit(exc)
        else:
            self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: ProjectService | None = None,
        app_config: AppConfig | None = None,
    ) -> None:
        super().__init__()
        self._service = service if service is not None else ProjectService()
        self._config = app_config if app_config is not None else load_config()
        self._state = UiState.INITIALIZING
        self._workers: set[FunctionWorker] = set()
        self._finished_workers: list[FunctionWorker] = []
        self._radios: dict[str, QRadioButton] = {}

        self._build_ui()
        self._start_check()

    def _build_ui(self) -> None:
        self.setWindowTitle("New Video Project")
        self.setWindowIcon(
            QIcon.fromTheme(
                "applications-multimedia",
                QIcon.fromTheme("video-x-generic"),
            )
        )
        self.setMinimumWidth(460)
        self.resize(480, 440)

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel("New Video Project")
        title_font = title.font()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        name_label = QLabel("Project name")
        layout.addWidget(name_label)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Morning Matcha")
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.returnPressed.connect(self._primary_clicked)
        layout.addWidget(self.name_edit)

        format_label = QLabel("Video format")
        layout.addWidget(format_label)

        self._group = QButtonGroup(self)
        for preset in PRESETS.values():
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(1)

            radio = QRadioButton(preset.label)
            description = QLabel(preset.description)
            description.setContentsMargins(22, 0, 0, 0)

            self._group.addButton(radio)
            self._radios[preset.id] = radio
            radio.toggled.connect(
                lambda checked, label=description: label.setEnabled(checked)
            )
            row_layout.addWidget(radio)
            row_layout.addWidget(description)
            layout.addWidget(row)

        default_preset = (
            self._config.default_preset
            if self._config.default_preset in self._radios
            else DEFAULT_PRESET_ID
        )
        self._radios[default_preset].setChecked(True)

        layout.addSpacing(4)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self._start_check)
        self.retry_button.hide()
        buttons.addWidget(self.retry_button)

        self.primary_button = QPushButton("Create Project")
        self.primary_button.setDefault(True)
        self.primary_button.setMinimumHeight(36)
        self.primary_button.setMinimumWidth(150)
        self.primary_button.clicked.connect(self._primary_clicked)
        buttons.addWidget(self.primary_button)

        layout.addLayout(buttons)
        QTimer.singleShot(0, self.name_edit.setFocus)

    def _selected_preset(self) -> str:
        for preset_id, radio in self._radios.items():
            if radio.isChecked():
                return preset_id
        return DEFAULT_PRESET_ID

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet("color: #c0392b;" if error else "")
        self.status_label.setVisible(bool(text))

    def _apply_state(self, state: UiState) -> None:
        self._state = state
        creating = state is UiState.CREATING
        finished = state is UiState.SUCCESS
        unavailable = state is UiState.RESOLVE_UNAVAILABLE

        self.name_edit.setEnabled(not creating and not finished)
        for radio in self._radios.values():
            radio.setEnabled(not creating and not finished)

        self.primary_button.setEnabled(
            state in {UiState.READY, UiState.ERROR, UiState.SUCCESS}
        )
        self.primary_button.setText("Close" if finished else "Create Project")
        self.retry_button.setVisible(unavailable)
        self.progress.setVisible(state in {UiState.INITIALIZING, UiState.CREATING})
        self.primary_button.setDefault(state in {UiState.READY, UiState.ERROR})

        if state is not UiState.ERROR and state is not UiState.RESOLVE_UNAVAILABLE:
            self._set_status("")

    def _start_check(self) -> None:
        if self._state is UiState.CREATING:
            return
        self._apply_state(UiState.INITIALIZING)
        self._set_status("Checking DaVinci Resolve…")
        self._run(
            self._service.check_resolve,
            self._check_succeeded,
            self._check_failed,
        )

    def _check_succeeded(self, version: object) -> None:
        _log.info("Resolve connection check succeeded (version %s)", version)
        self._apply_state(UiState.READY)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _check_failed(self, error: object) -> None:
        _log.warning("Resolve connection check failed: %s", error)
        if isinstance(error, ResolveUnavailable):
            self._apply_state(UiState.RESOLVE_UNAVAILABLE)
            self._set_status(error.user_message, error=True)
        else:
            self._apply_state(UiState.ERROR)
            text = (
                error.user_message
                if isinstance(error, ProjectCreatorError)
                else "DaVinci Resolve could not be checked. See the application log."
            )
            self._set_status(text, error=True)

    def _primary_clicked(self) -> None:
        if self._state is UiState.SUCCESS:
            self.close()
            return
        if self._state is not UiState.READY and self._state is not UiState.ERROR:
            return
        self._create()

    def _create(self) -> None:
        if self._state is UiState.CREATING or self._state is UiState.INITIALIZING:
            return
        raw_name = self.name_edit.text()
        try:
            validate_project_name(raw_name)
        except ValidationError as exc:
            self._set_status(exc.user_message, error=True)
            self.name_edit.setFocus()
            return

        preset_id = self._selected_preset()
        self._apply_state(UiState.CREATING)
        self._set_status("Creating project…")
        self._run(
            lambda: self._service.create(raw_name, preset_id),
            self._create_succeeded,
            self._create_failed,
        )

    def _create_succeeded(self, result: object) -> None:
        project_name = getattr(result, "project_name", "Your project")
        warnings = getattr(result, "warnings", ())
        for warning in warnings:
            _log.warning("Project created with warning: %s", warning)
        _log.info("Project creation succeeded: %r", project_name)
        self._apply_state(UiState.SUCCESS)
        self._set_status(f'Project "{project_name}" created in DaVinci Resolve.')
        if self._config.auto_close_on_success:
            QTimer.singleShot(2500, self.close)

    def _create_failed(self, error: object) -> None:
        if isinstance(error, ResolveUnavailable):
            self._apply_state(UiState.RESOLVE_UNAVAILABLE)
            self._set_status(error.user_message, error=True)
        elif isinstance(error, ProjectCreatorError):
            self._apply_state(UiState.ERROR)
            self._set_status(error.user_message, error=True)
        else:
            _log.error("Unexpected project creation failure: %r", error)
            self._apply_state(UiState.ERROR)
            self._set_status(
                "The project could not be created. See the application log for details.",
                error=True,
            )
        self.name_edit.setFocus()

    def _run(
        self,
        function: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_failure: Callable[[Any], None],
    ) -> None:
        worker = FunctionWorker(function)
        self._workers.add(worker)
        worker.succeeded.connect(on_success)
        worker.failed.connect(on_failure)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _worker_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, FunctionWorker):
            self._workers.discard(worker)
            # Keep a reference until the window closes. Deleting a QThread from
            # inside its own finished signal can crash PySide6.
            self._finished_workers.append(worker)

    def closeEvent(self, event: Any) -> None:
        if self._state is UiState.CREATING:
            self._set_status("Please wait until project creation finishes.", error=False)
            event.ignore()
            return
        for worker in list(self._workers):
            if not worker.wait(3000):
                self._set_status("Please wait for DaVinci Resolve.", error=False)
                event.ignore()
                return
        event.accept()
