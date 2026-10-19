from types import SimpleNamespace

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from video_project_creator.config import AppConfig
from video_project_creator.errors import ResolveUnavailable
from video_project_creator.ui import MainWindow, UiState


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


class ReadyService:
    def __init__(self):
        self.created = []

    def check_resolve(self):
        return "21.1.1"

    def create(self, name, preset):
        self.created.append((name, preset))
        return SimpleNamespace(project_name=name, warnings=())


class UnavailableService:
    def check_resolve(self):
        raise ResolveUnavailable("Resolve is not running.")

    def create(self, name, preset):
        raise AssertionError("create must not run")


def wait_until(predicate, timeout_ms=2000):
    elapsed = 0
    while elapsed < timeout_ms:
        if predicate():
            return True
        QTest.qWait(25)
        elapsed += 25
    return predicate()


def test_window_becomes_ready_and_creates_project(qt_app):
    service = ReadyService()
    window = MainWindow(
        service=service,
        app_config=AppConfig(auto_close_on_success=False),
    )
    window.show()
    try:
        assert wait_until(lambda: window._state is UiState.READY)
        assert window.name_edit.hasFocus()

        window.name_edit.setText("Morning Matcha")
        window._radios["youtube"].setChecked(True)
        window._create()

        assert wait_until(lambda: window._state is UiState.SUCCESS)
        assert service.created == [("Morning Matcha", "youtube")]
        assert "Morning Matcha" in window.status_label.text()
    finally:
        window.close()


def test_window_auto_closes_after_success(qt_app):
    service = ReadyService()
    window = MainWindow(
        service=service,
        app_config=AppConfig(auto_close_on_success=True),
    )
    window.show()
    assert wait_until(lambda: window._state is UiState.READY)
    window.name_edit.setText("Morning Matcha")
    window._create()
    assert wait_until(lambda: window._state is UiState.SUCCESS)
    assert window.isVisible()
    QTest.qWait(2700)
    assert not window.isVisible()


def test_unavailable_resolve_shows_retry(qt_app):
    window = MainWindow(
        service=UnavailableService(),
        app_config=AppConfig(),
    )
    window.show()
    try:
        assert wait_until(lambda: window._state is UiState.RESOLVE_UNAVAILABLE)
        assert window.retry_button.isVisible()
        assert not window.primary_button.isEnabled()
        assert "Resolve is not running" in window.status_label.text()
    finally:
        window.close()


def test_invalid_name_stays_ready_and_shows_error(qt_app):
    service = ReadyService()
    window = MainWindow(
        service=service,
        app_config=AppConfig(auto_close_on_success=False),
    )
    window.show()
    try:
        assert wait_until(lambda: window._state is UiState.READY)
        window.name_edit.setText("   ")
        window._create()
        assert window._state is UiState.READY
        assert "Enter a project name" in window.status_label.text()
        assert service.created == []
    finally:
        window.close()
