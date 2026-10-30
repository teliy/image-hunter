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

    from app.core import applog
    from app.ui.app_icon import icon as app_icon
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Image Hunter")
    app.setOrganizationName("ImageHunter")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())       # значок «фото с лупой» из ресурсов
    applog.setup()                      # с этого момента события пишутся в «Журнал»
    applog.event("log.event.start", version=__version__)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
