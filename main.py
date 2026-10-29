"""Image Hunter — просмотр изображений, поиск картинок в поисковиках и их скачивание.

Точка входа приложения.
"""
import sys

from PySide6.QtWidgets import QApplication

from app import __version__
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Image Hunter")
    app.setOrganizationName("ImageHunter")
    app.setApplicationVersion(__version__)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
