from __future__ import annotations

import logging
import os
import sys
import traceback

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, __version__
from .app.container import ServiceContainer
from .infrastructure.diagnostics.logging import log_event
from .ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    QCoreApplication.setOrganizationName("Kájovo")
    QCoreApplication.setOrganizationDomain("kajovo.cz")
    QCoreApplication.setApplicationName("KajovoKarty")
    QCoreApplication.setApplicationVersion(__version__)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    arguments = list(sys.argv if argv is None else argv)
    smoke_test = "--smoke-test" in arguments
    arguments = [value for value in arguments if value != "--smoke-test"]
    app = QApplication(arguments)
    app.setApplicationDisplayName(APP_NAME)
    container: ServiceContainer | None = None
    try:
        container = ServiceContainer.build()
        log_event(container.logger, logging.INFO, "APP_START", "KájovoKarty se spouští", version=__version__)
        window = MainWindow(container)
        window.show()
        if smoke_test:
            app.processEvents()
            window.refresh_all()
            app.processEvents()
            window.close()
            return 0
        exit_code = app.exec()
        log_event(container.logger, logging.INFO, "APP_STOP", "KájovoKarty se ukončuje", exit_code=exit_code)
        return int(exit_code)
    except Exception as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if container is not None:
            log_event(container.logger, logging.ERROR, "APP_FATAL", "Aplikace skončila chybou", error_type=type(exc).__name__)
            log_path = container.paths.logs
        else:
            log_path = os.path.expandvars(r"%LOCALAPPDATA%\KajovoKarty\logs")
        QMessageBox.critical(None, "KájovoKarty – chyba", f"Aplikaci se nepodařilo spustit.\n\n{exc}\n\nDiagnostické logy: {log_path}")
        sys.stderr.write(detail)
        return 1
    finally:
        if container is not None:
            container.close()


if __name__ == "__main__":
    raise SystemExit(main())
