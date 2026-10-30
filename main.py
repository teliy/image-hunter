"""Image Hunter — просмотр изображений, поиск картинок в поисковиках и их скачивание.

Точка входа приложения.
"""
import sys

from app import __version__


def main() -> int:
    if "--version" in sys.argv:
        print(f"Image Hunter {__version__}")
        return 0

    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Image Hunter")
    app.setOrganizationName("ImageHunter")
    app.setApplicationVersion(__version__)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
