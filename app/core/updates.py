"""Проверка обновлений и запуск установщика прямо из интерфейса.

Версия сверяется с main-веткой репозитория (raw.githubusercontent.com, без
токена — репозиторий публичный). Обновление выполняет штатный установщик
(installer/install.ps1 | installer/install.sh) в отдельном процессе, который
переживает закрытие приложения; после установки Image Hunter перезапускается.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import urllib.request

from PySide6.QtCore import QObject, QRunnable, Signal

RAW_URL = "https://raw.githubusercontent.com/teliy/image-hunter/main/app/__init__.py"


class UpdatesSignals(QObject):
    done = Signal(str)   # версия из репозитория; "" — получить не удалось


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


def _restart_line(app_dir: str) -> str:
    """Строка перезапуска приложения — без лишнего консольного окна.

    pythonw.exe относится к оконной подсистеме, консоль ему не нужна.
    Раньше перезапуск шёл через ImageHunter.bat, и cmd открывал для него
    отдельное окно, остававшееся висеть после обновления.
    """
    pyw = os.path.join(app_dir, ".venv", "Scripts", "pythonw.exe")
    if os.path.exists(pyw):
        return f'start "" "{pyw}" "{os.path.join(app_dir, "main.py")}"'
    bat = os.path.join(app_dir, "ImageHunter.bat")
    if os.path.exists(bat):
        return f'start "" "{bat}"'
    return ""


def _update_script(inst: str, app_dir: str) -> str:
    """Содержимое временного батника обновления (CRLF, только ASCII)."""
    lines = [
        "@echo off",
        "title Image Hunter update",
        f'cd /d "{app_dir}"',
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "{inst}" -Update -AssumeYes',
        "set IH_RC=%errorlevel%",
    ]
    restart = _restart_line(app_dir)
    if restart:
        lines.append(restart)
    # при сбое окно остаётся с текстом ошибки до нажатия клавиши (иначе conhost
    # мгновенно закрывает его вместе с причиной сбоя); при успехе ветка не
    # выполняется и окно закрывается само
    lines += [
        'if not "%IH_RC%"=="0" (',
        "  echo.",
        "  echo Update FAILED - see messages above.",
        "  echo To retry: run ImageHunter.bat update from the app folder.",
        "  echo.",
        "  pause",
        ")",
    ]
    return "\r\n".join(lines) + "\r\n"


def run_update_and_restart() -> bool:
    """Запускает установщик в режиме обновления отдельным (переживающим) процессом.

    Windows: ровно ОДНО окно консоли с прогрессом установки — закрывается само,
    когда установка закончилась (при сбое остаётся с текстом ошибки до нажатия
    клавиши). Приложение перезапускается напрямую через pythonw.exe. Раньше
    и запуск (`cmd /c start`), и перезапуск (через ImageHunter.bat) открывали
    по лишнему консольному окну — после обновления они оставались на экране.
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
                f.write(_update_script(inst, app_dir))
            # Одно окно консоли на всю установку. Прежний запуск
            # `cmd /c start "" script` открывал сразу две консоли: служебную
            # (гасла через мгновение) и само окно установки.
            subprocess.Popen(["cmd", "/c", script],
                             creationflags=subprocess.CREATE_NEW_CONSOLE,
                             close_fds=True)
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
