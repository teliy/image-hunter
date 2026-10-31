"""Оффлайн-тест сценария «обновление из приложения» на Windows (v0.7.4).

Репорт: после обновления из приложения оставались открытые терминалы.
Прежний запуск `cmd /c start "" script` открывал сразу ДВЕ консоли
(служебный cmd + окно установки), а перезапуск приложения шёл через
ImageHunter.bat — ещё одно окно. Проверяем, что теперь:

- установка идёт в одном окне консоли (CREATE_NEW_CONSOLE, без cmd /c start);
- перезапуск — напрямую через pythonw.exe (оконная подсистема, консоль не
  нужна); ImageHunter.bat — только запасной вариант;
- при успехе окно установки закрывается само, при сбое — остаётся с текстом
  ошибки до нажатия клавиши (pause), чтобы причину можно было прочитать;
- батник в ASCII и CRLF (как ожидает cmd), возвращает False без установщика.

Запуск: python scripts/test_update_flow.py
"""

import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import updates  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def make_app_dir(with_pythonw: bool = True, with_bat: bool = True) -> str:
    d = tempfile.mkdtemp(prefix="ih_upd_")
    os.makedirs(os.path.join(d, ".venv", "Scripts"), exist_ok=True)
    open(os.path.join(d, "main.py"), "w").close()
    if with_pythonw:
        open(os.path.join(d, ".venv", "Scripts", "pythonw.exe"), "w").close()
    if with_bat:
        open(os.path.join(d, "ImageHunter.bat"), "w").close()
    return d


def main() -> None:
    src = inspect.getsource(updates)

    # --- одно окно консоли вместо двух -----------------------------------
    check("нет старого запуска cmd /c start (две консоли)",
          '"/c", "start"' not in src)
    check("запуск установки одним окном (CREATE_NEW_CONSOLE)",
          "CREATE_NEW_CONSOLE" in src and '["cmd", "/c", script]' in src)

    # --- папка установки по пути установщика ------------------------------
    check("app_dir: установщик в installer\\ → родитель",
          updates._app_dir_of(os.path.join("C:", "ih", "installer", "install.ps1"))
          == os.path.join("C:", "ih"))
    check("app_dir: установщик в корне → сама папка",
          updates._app_dir_of(os.path.join("C:", "ih", "install.ps1"))
          == os.path.join("C:", "ih"))

    # --- штатный перезапуск: pythonw, без ImageHunter.bat ------------------
    d = make_app_dir()
    inst = os.path.join(d, "installer", "install.ps1")
    script = updates._update_script(inst, d)
    pyw = os.path.join(d, ".venv", "Scripts", "pythonw.exe")
    check("перезапуск напрямую через pythonw.exe",
          f'start "" "{pyw}" "{os.path.join(d, "main.py")}"' in script)
    check("перезапуск не через ImageHunter.bat",
          f'start "" "{os.path.join(d, "ImageHunter.bat")}"' not in script)
    check("установщик запускается с -Update -AssumeYes",
          "-Update -AssumeYes" in script and inst in script)
    check("окно установки с заголовком", "title Image Hunter update" in script)
    check("рабочая папка приложения (cd /d)", f'cd /d "{d}"' in script)
    check("код возврата установщика сохранён",
          "%errorlevel%" in script and "%IH_RC%" in script)

    # --- успех/сбой: окно закрывается само, ошибку видно -------------------
    check("ветка ошибки только при ненулевом коде",
          'if not "%IH_RC%"=="0" (' in script)
    check("при сбое окно ждёт нажатия клавиши (pause)",
          "pause" in script and "Update FAILED" in script)

    # --- формат батника -----------------------------------------------------
    try:
        script.encode("ascii")
        ascii_ok = True
    except UnicodeEncodeError:
        ascii_ok = False
    check("батник только ASCII (cmd читает в OEM-кодировке)", ascii_ok)
    check("батник в CRLF без голых LF",
          "\r\n" in script and "\n" not in script.replace("\r\n", ""))

    # --- запасные варианты перезапуска --------------------------------------
    d2 = make_app_dir(with_pythonw=False)
    s2 = updates._update_script(inst, d2)
    check("нет pythonw → запасной запуск через ImageHunter.bat",
          f'start "" "{os.path.join(d2, "ImageHunter.bat")}"' in s2)
    d3 = make_app_dir(with_pythonw=False, with_bat=False)
    s3 = updates._update_script(inst, d3)
    check("нет ни pythonw, ни bat → строки перезапуска нет",
          'start "" ' not in s3 and "pause" in s3)

    # --- без установщика обновление не запускается ---------------------------
    saved = updates.installer_path
    updates.installer_path = lambda: ""
    try:
        check("нет установщика → run_update_and_restart() == False",
              updates.run_update_and_restart() is False)
    finally:
        updates.installer_path = saved

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} — " + "; ".join(FAILURES))
        sys.exit(1)
    print("Все проверки пройдены.")


if __name__ == "__main__":
    main()
