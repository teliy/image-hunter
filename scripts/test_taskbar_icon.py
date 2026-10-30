"""Оффлайн-тест иконки в панели задач Windows (v0.3.6).

Проверяем три вещи:
1. на Linux функция _set_windows_taskbar_identity() — тихий no-op;
2. на «Windows» (симуляция) процессу назначается AppUserModelID
   "ImageHunter.ImageHunter" — именно это заставляет панель задач
   брать иконку окна, а не стандартный значок pythonw.exe;
3. иконка приложения из ресурсов многоразмерная (есть 256 px) —
   панель задач и ярлык получат чёткий значок.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_taskbar_icon.py
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import main as entry  # noqa: E402  (точка входа — там AppUserModelID)

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    # 1. на Linux — no-op, ничего не ломает
    orig_platform = sys.platform
    try:
        sys.platform = orig_platform  # страховка
        entry._set_windows_taskbar_identity()
        check("на Linux вызов безопасен (no-op)", True)
    except Exception as e:                                   # pragma: no cover
        check("на Linux вызов безопасен (no-op)", False, repr(e))

    # 2. симуляция Windows: ctypes подменяем заглушкой до импорта внутри функции
    calls: list[str] = []

    class FakeShell:
        @staticmethod
        def SetCurrentProcessExplicitAppUserModelID(app_id: str) -> None:
            calls.append(app_id)

    class FakeWinDLL:
        def __init__(self) -> None:
            self.shell32 = FakeShell()

    class FakeCtypes(types.ModuleType):
        def __init__(self) -> None:
            super().__init__("ctypes")
            self.windll = FakeWinDLL()

    fake = FakeCtypes()
    saved_module = sys.modules.get("ctypes")
    try:
        sys.modules["ctypes"] = fake
        sys.platform = "win32"
        entry._set_windows_taskbar_identity()
    finally:
        sys.platform = orig_platform
        if saved_module is not None:
            sys.modules["ctypes"] = saved_module
        else:
            sys.modules.pop("ctypes", None)
    check("на Windows назначается AppUserModelID",
          calls == [entry._APP_ID], f"calls={calls}")
    check("AppUserModelID = ImageHunter.ImageHunter",
          entry._APP_ID == "ImageHunter.ImageHunter", entry._APP_ID)

    # 3. иконка из ресурсов: многоразмерная, 256 px присутствует
    from app.ui.app_icon import icon
    ic = icon()
    sizes = sorted(s.width() for s in ic.availableSizes())
    check("иконка из ресурсов не пустая", not ic.isNull())
    check("в иконке есть размер 256 px", 256 in sizes, f"sizes={sizes}")
    check("в иконке есть размер 32 px (панель задач)", 32 in sizes, f"sizes={sizes}")

    # 4. ресурсы лежат там, куда смотрит ярлык установщика (app/resources/)
    from app.ui.app_icon import RES_DIR
    ico = RES_DIR / "app_icon.ico"
    check("app/resources/app_icon.ico существует", ico.exists(), str(ico))

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
