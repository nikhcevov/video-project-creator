"""Application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .config import load_config, projects_dir, setup_logging
from .ui import MainWindow

_log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    _log.info("Starting Video Project Creator")
    _log.info("Project storage: %s", projects_dir())

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("video-project-creator")
    app.setApplicationDisplayName("New Video Project")
    app.setDesktopFileName("video-project-creator")

    window = MainWindow(app_config=load_config())
    window.show()
    return app.exec()
