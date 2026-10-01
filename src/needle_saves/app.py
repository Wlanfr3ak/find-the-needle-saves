"""Application entry point."""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .config import Config
    from .i18n import set_language
    from .ui.main_window import MainWindow

    config = Config()
    set_language(config.get("language", "en"))

    app = QApplication(sys.argv)
    app.setApplicationName("find-the-needle-saves")
    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
