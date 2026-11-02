"""Оффлайн-тест сценария «обновление из приложения» на Windows (v0.7.6).

Репорт: после обновления из приложения оставались открытыми 2 терминала,
появившиеся в процессе. v0.7.4 свёл их к одному окну с автозакрытием, но
окно всё равно мелькало (и оставалось при сбое). Проверяем, что теперь
терминалов НЕТ ВООБЩЕ:

- cmd запускается с CREATE_NO_WINDOW — скрытый сеанс, ноль окон;
- вывод установщика пишется в журнал (%TEMP%\\ImageHunter_update.log);
- при сбое показывается обычный диалог (MessageBox) с путём к журналу,
  а не консоль с pause;
- перезапуск — напрямую через pythonw.exe (оконная подсистема), ImageHunter.bat
  — запасной вариант; оба пути подставляют пути из переменных окружения,
  поэтому батник остаётся чистым ASCII даже при кириллице в путях;
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


def main() -> None:
    src = inspect.getsource(updates)

    # --- ноль видимых консолей -------------------------------------------
    check("нет старого запуска cmd /c start (две консоли)",
          '"/c", "start"' not in src)
    check("нет CREATE_NEW_CONSOLE (видимое окно установки)",
          "CREATE_NEW_CONSOLE" not in src)
    check("запуск в скрытом сеансе (CREATE_NO_WINDOW)",
          "CREATE_NO_WINDOW" in src and '["cmd", "/c", script]' in src)

    # --- журнал вместо экрана ----------------------------------------------
    script = updates._update_script()
    log = updates.win_log_path()
    check("вывод установщика пишется в журнал",
          f'> "%IH_LOG%" 2>&1' in script and "%IH_LOG%" in script)
    check("журнал — файл ImageHunter_update.log во временной папке",
          log.endswith("ImageHunter_update.log")
          and os.path.dirname(log) == tempfile.gettempdir())

    # --- папка установки по пути установщика ------------------------------
    check("app_dir: установщик в installer\\ → родитель",
          updates._app_dir_of(os.path.join("C:", "ih", "installer", "install.ps1"))
          == os.path.join("C:", "ih"))
    check("app_dir: установщик в корне → сама папка",
          updates._app_dir_of(os.path.join("C:", "ih", "install.ps1"))
          == os.path.join("C:", "ih"))

    # --- пути через окружение: батник чист ASCII ----------------------------
    check("пути берутся из IH_APP_DIR/IH_INST/IH_LOG (не вписаны в файл)",
          "%IH_APP_DIR%" in script and "%IH_INST%" in script
          and "%IH_LOG%" in script)
    check("в переменные окружения переданы установка, установщик и журнал",
          'env["IH_APP_DIR"]' in src and 'env["IH_INST"]' in src
          and 'env["IH_LOG"]' in src)

    # --- перезапуск: pythonw напрямую, bat — запасной -----------------------
    check("перезапуск напрямую через pythonw.exe (из IH_APP_DIR)",
          'start "" "%IH_APP_DIR%\\.venv\\Scripts\\pythonw.exe" '
          '"%IH_APP_DIR%\\main.py"' in script)
    check("запасной перезапуск через ImageHunter.bat",
          'start "" "%IH_APP_DIR%\\ImageHunter.bat"' in script)
    check("установщик запускается с -Update -AssumeYes",
          "-Update -AssumeYes" in script)
    check("рабочая папка приложения (cd /d)", 'cd /d "%IH_APP_DIR%"' in script)
    check("код возврата установщика сохранён",
          "%errorlevel%" in script and "%IH_RC%" in script)

    # --- сбой: диалог вместо консоли ----------------------------------------
    check("нет pause (консоль скрыта — некому нажимать клавишу)", "pause" not in script)
    check("нет title (окна нет — некого подписывать)", "title " not in script)
    check("при сбое показывается MessageBox с путём к журналу",
          "MessageBox" in script and "Image Hunter update FAILED" in script)
    check("при успехе ветка ошибки пропускается (goto :ok)",
          'if "%IH_RC%"=="0" goto :ok' in script and ":ok" in script)

    # --- батник остаётся ASCII даже при кириллице в путях -------------------
    # (пути в файл не вписываются — проверяем сам текст батника)
    try:
        script.encode("ascii")
        ascii_ok = True
    except UnicodeEncodeError:
        ascii_ok = False
    check("батник только ASCII (cmd читает в OEM-кодировке)", ascii_ok)
    check("батник в CRLF без голых LF",
          "\r\n" in script and "\n" not in script.replace("\r\n", ""))
    check("кириллический путь установки не ломает батник (пути в окружении)",
          updates._app_dir_of("C:/Установки/Картинки/installer/install.ps1")
          == "C:/Установки/Картинки")

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
