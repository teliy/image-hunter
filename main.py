"""Image Hunter — просмотр изображений, поиск картинок в поисковиках и их скачивание.

Точка входа приложения.
"""
import sys

from app import __version__

_APP_ID = "ImageHunter.ImageHunter"   # как QSettings-организация: единый идентификатор


def _set_windows_taskbar_identity() -> None:
    """Явный AppUserModelID — без него панель задач Windows показывает
    стандартный значок pythonw.exe вместо иконки приложения.

    Windows группирует кнопки панели задач по «приложениям». Для скрипта,
    запущенного через pythonw.exe, таким приложением считается сам Python,
    и кнопка получает его стандартную иконку, даже если у окна значок свой.
    SetCurrentProcessExplicitAppUserModelID объявляет процесс отдельным
    приложением — после этого панель задач берёт иконку из значка окна
    (QApplication.setWindowIcon). Вызов обязателен ДО создания QApplication
    и первого окна, иначе он не подействует.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_ID)
    except Exception:
        pass    # не критично: останется стандартный значок pythonw.exe


def main() -> int:
    if "--version" in sys.argv:
        print(f"Image Hunter {__version__}")
        return 0

    _set_windows_taskbar_identity()   # до QApplication — см. докстринг

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
