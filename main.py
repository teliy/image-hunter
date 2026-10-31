"""Image Hunter — просмотр изображений, поиск картинок в поисковиках и их скачивание.

Точка входа приложения.
"""
import os
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


# ---------- защита от зависаний QtWebEngine на «поломанном Wayland» ----------

# Qt печатает предупреждение о платформенных плагинах при создании QApplication;
# ловим его, чтобы понять окружение ещё ДО первого окна.
_qpa_warnings: list[str] = []


def _capture_qpa_warnings() -> None:
    """Запоминать предупреждения Qt о платформенных плагинах (см. ниже)."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        def handler(mode, _context, message) -> None:
            if mode == QtMsgType.QtWarningMsg and "platform plugin" in str(message):
                _qpa_warnings.append(str(message))

        qInstallMessageHandler(handler)
    except Exception:
        pass    # диагностика не должна мешать запуску


def wayland_fallback_failed(messages: list[str] | None = None) -> bool:
    """Сессия Wayland, но Qt-плагин wayland не загрузился (или не найден).

    Ровно этот случай виден в пользовательских отчётах строкой
    ``Could not load the Qt platform plugin "wayland" … even though it was
    found``: приложение продолжает работать через xcb (XWayland), но
    связка «QtWebEngine + графический драйвер» на таком гибриде известна
    зависаниями всего окна (тот же класс проблем, что у Anki и других
    QtWebEngine-программ).
    """
    msgs = _qpa_warnings if messages is None else messages
    for m in msgs:
        if "wayland" not in m:
            continue
        if ("Could not load the Qt platform plugin" in m
                or "Could not find the Qt platform plugin" in m):
            return True
    return False


def _apply_webengine_gpu_fix() -> bool:
    """Выключить GPU у встроенного браузера, если окружение склонно к зависаниям.

    Программный рендеринг страниц выдачи на современном процессоре незаметен,
    зато исключает целый класс зависаний, когда GPU-процесс Chromium
    deadlock'ится с драйвером (окно перестаёт отвечать целиком).

    Переопределение через переменные окружения:
    * ``IH_GPU=0`` — выключить GPU принудительно (даже если wayland в порядке);
    * ``IH_GPU=1`` — оставить GPU включённым, автодетект игнорировать;
    * свои флаги в ``QTWEBENGINE_CHROMIUM_FLAGS`` дополняются, а не затираются.
    """
    override = os.environ.get("IH_GPU", "").strip()
    if override == "1":
        return False
    if not (override == "0" or wayland_fallback_failed()):
        return False
    cur = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--disable-gpu" not in cur:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (cur + " --disable-gpu").strip()
    return True


def main() -> int:
    if "--version" in sys.argv:
        print(f"Image Hunter {__version__}")
        return 0

    _set_windows_taskbar_identity()   # до QApplication — см. докстринг

    from PySide6.QtWidgets import QApplication

    from app.core import applog
    from app.ui.app_icon import icon as app_icon
    from app.ui.main_window import MainWindow

    _capture_qpa_warnings()             # предупреждение печатается при создании QApplication
    app = QApplication(sys.argv)
    gpu_off = _apply_webengine_gpu_fix()   # ДО MainWindow — иначе WebEngine уже инициализируется
    app.setApplicationName("Image Hunter")
    app.setOrganizationName("ImageHunter")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())       # значок «фото с лупой» из ресурсов
    applog.setup()                      # с этого момента события пишутся в «Журнал»
    applog.event("log.event.start", version=__version__)
    if gpu_off:
        applog.event("log.event.gpu_off")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
