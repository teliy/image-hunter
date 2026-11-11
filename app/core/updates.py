"""Проверка обновлений и запуск установщика прямо из интерфейса.

Версия сверяется с main-веткой репозитория (raw.githubusercontent.com, без
токена — репозиторий публичный). Обновление выполняет штатный установщик
(installer/install.ps1 | installer/install.sh) в отдельном процессе, который
переживает закрытие приложения; после установки Image Hunter перезапускается.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request

from PySide6.QtCore import QObject, QRunnable, Signal

RAW_URL = "https://raw.githubusercontent.com/teliy/image-hunter/main/app/__init__.py"
PYPI_URL = "https://pypi.org/pypi/{pkg}/json"


class UpdatesSignals(QObject):
    done = Signal(str)   # версия из репозитория; "" — получить не удалось


def pypi_latest(package: str) -> str:
    """Свежая версия pip-пакета на PyPI; "" — узнать не удалось (нет сети).

    Общий помощник проверки обновлений (v0.8.15): сама программа сверяет
    версию с main-веткой репозитория, а подключаемые модули (rembg,
    водяные знаки) — свои пакеты с PyPI. Таймаут короткий: проверка идёт
    в рабочем потоке и не должна висеть минутами.
    """
    try:
        req = urllib.request.Request(
            PYPI_URL.format(pkg=package), headers={"User-Agent": "ImageHunter"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read(1 << 20).decode("utf-8", "replace"))
        return str((data.get("info") or {}).get("version") or "")
    except (OSError, ValueError):
        return ""


def version_tuple(s: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def is_newer(remote: str, local: str) -> bool:
    a, b = version_tuple(remote), version_tuple(local)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


class VersionCheckTask(QRunnable):
    """Скачивает app/__init__.py из main-ветки и вытаскивает номер версии."""

    def __init__(self, signals: UpdatesSignals):
        super().__init__()
        self.signals = signals

    def run(self) -> None:
        ver = ""
        try:
            req = urllib.request.Request(RAW_URL, headers={"User-Agent": "ImageHunter"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                text = resp.read(65536).decode("utf-8", "replace")
            m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
            if m:
                ver = m.group(1)
        except OSError:
            pass
        self.signals.done.emit(ver)


def _app_root() -> str:
    # updates.py → app/core → app → корень приложения
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def installer_path() -> str:
    """Путь к штатному установщику рядом с приложением (если найден)."""
    root = _app_root()
    name = "install.ps1" if os.name == "nt" else "install.sh"
    for cand in (os.path.join(root, "installer", name), os.path.join(root, name)):
        if os.path.exists(cand):
            return cand
    return ""


def _app_dir_of(inst: str) -> str:
    """Папка установки по пути установщика: installer/install.ps1 → родитель installer/."""
    d = os.path.dirname(inst)
    if os.path.basename(d).lower() == "installer":
        return os.path.dirname(d)
    return d


def _restart_block() -> list[str]:
    """Строки перезапуска приложения — без лишнего консольного окна.

    pythonw.exe относится к оконной подсистеме, консоль ему не нужна.
    Пути подставляет сам батник из переменных окружения (IH_APP_DIR),
    поэтому в файле нет ни одного символа вне ASCII — cmd читает батник
    в OEM-кодировке, и путь с кириллицей в нём просто нельзя записать.
    Раньше перезапуск шёл через ImageHunter.bat, и cmd открывал для него
    отдельное окно, остававшееся висеть после обновления."""
    return [
        'if exist "%IH_APP_DIR%\\.venv\\Scripts\\pythonw.exe" (',
        '  start "" "%IH_APP_DIR%\\.venv\\Scripts\\pythonw.exe" "%IH_APP_DIR%\\main.py"',
        ') else if exist "%IH_APP_DIR%\\ImageHunter.bat" (',
        '  start "" "%IH_APP_DIR%\\ImageHunter.bat"',
        ")",
    ]


def win_log_path() -> str:
    """Журнал обновления на Windows (рядом с батником — во временной папке)."""
    return os.path.join(tempfile.gettempdir(), "ImageHunter_update.log")


def _update_script() -> str:
    """Содержимое временного батника обновления (CRLF, только ASCII).

    Батник выполняется в СКРЫТОМ консольном сеансе (cmd запускается с
    CREATE_NO_WINDOW) — терминальных окон на экране нет ни во время
    обновления, ни после него. Поэтому:
    - вывод установщика пишется в журнал (win_log_path), а не на экран;
    - при сбое вместо консоли показывается обычный диалог с ошибкой и
      путём к журналу (powershell работает в том же скрытом сеансе и
      окна терминала не создаёт; диалог держит сеанс до нажатия OK).
    Все пути батник берёт из переменных окружения (IH_APP_DIR, IH_INST,
    IH_LOG) — см. _restart_block."""
    lines = [
        "@echo off",
        'cd /d "%IH_APP_DIR%"',
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%IH_INST%" '
        '-Update -AssumeYes > "%IH_LOG%" 2>&1',
        "set IH_RC=%errorlevel%",
    ]
    lines += _restart_block()
    lines += [
        'if "%IH_RC%"=="0" goto :ok',
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Add-Type "
        "-AssemblyName System.Windows.Forms; [void][System.Windows.Forms."
        "MessageBox]::Show('Image Hunter update FAILED. Details: %IH_LOG%',"
        "'Image Hunter update',0,16)\"",
        ":ok",
    ]
    return "\r\n".join(lines) + "\r\n"


def run_update_and_restart() -> bool:
    """Запускает установщик в режиме обновления отдельным (переживающим) процессом.

    Windows: обновление идёт ПОЛНОСТЬЮ БЕЗ окон — cmd запускается с
    CREATE_NO_WINDOW, вывод установщика пишется в журнал (win_log_path),
    при сбое показывается обычный диалог, а не терминал. Раньше установка
    шла в видимом окне консоли (до v0.7.4 — и вовсе в двух-трёх: служебный
    cmd, окно установки и перезапуск через ImageHunter.bat), и окна
    оставались на экране после обновления. Приложение перезапускается
    напрямую через pythonw.exe (оконная подсистема, консоль не нужна).
    Linux/macOS: фоновый процесс, лог — в update.log рядом с программой,
    затем автозапуск.
    """
    inst = installer_path()
    if not inst:
        return False
    app_dir = _app_dir_of(inst)
    try:
        if os.name == "nt":
            script = os.path.join(tempfile.gettempdir(), "ImageHunter_update.bat")
            with open(script, "w", encoding="ascii") as f:
                f.write(_update_script())
            # Пути — через окружение: в батнике не может быть символов вне
            # ASCII, а папка установки/имя пользователя бывают с кириллицей.
            env = dict(os.environ)
            env["IH_APP_DIR"] = app_dir
            env["IH_INST"] = inst
            env["IH_LOG"] = win_log_path()
            subprocess.Popen(["cmd", "/c", script],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                             close_fds=True, env=env)
        else:
            log = os.path.join(app_dir, "update.log")
            restart = ""
            launcher = os.path.expanduser("~/.local/bin/image-hunter")
            if os.path.exists(launcher):
                restart = f'; sleep 1; nohup "{launcher}" >/dev/null 2>&1 &'
            subprocess.Popen(
                ["bash", "-c", f'IH_DIR="{app_dir}" bash "{inst}" --update >> "{log}" 2>&1{restart}'],
                start_new_session=True)
        return True
    except OSError:
        return False
