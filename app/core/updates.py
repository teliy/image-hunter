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


def run_update_and_restart() -> bool:
    """Запускает установщик в режиме обновления отдельным (переживающим) процессом.

    Windows: новое окно консоли с прогрессом установки, после завершения
    приложение перезапускается. Linux/macOS: фоновый процесс, лог — в
    update.log рядом с программой, затем автозапуск.
    """
    inst = installer_path()
    if not inst:
        return False
    app_dir = os.path.dirname(os.path.dirname(inst))   # installer/.. = папка установки
    try:
        if os.name == "nt":
            bat_path = os.path.join(app_dir, "ImageHunter.bat")
            script = os.path.join(tempfile.gettempdir(), "ImageHunter_update.bat")
            lines = [
                "@echo off",
                "title Image Hunter update",
                f'powershell -NoProfile -ExecutionPolicy Bypass -File "{inst}" -Update -AssumeYes',
            ]
            if os.path.exists(bat_path):
                lines.append(f'start "" "{bat_path}"')
            with open(script, "w", encoding="ascii") as f:
                f.write("\r\n".join(lines) + "\r\n")
            subprocess.Popen(["cmd", "/c", "start", "", script], close_fds=True)
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
