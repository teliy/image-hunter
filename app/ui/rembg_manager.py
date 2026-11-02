"""Управление модулем удаления фона rembg (v0.7.12).

`rembg <https://github.com/danielgatis/rembg>`_ — самый живой открытый
проект удаления фона: код под MIT, всё считается локально через ONNX
Runtime, без облаков и ключей. Ставится pip-ом прямо из программы:
первый клик по «🪄 Удалить фон» предлагает установку ``rembg[cpu]``.

Установка и удаление идут в рабочем потоке (QRunnable + QThreadPool,
как все фоновые задачи программы): pip может качать сотни мегабайт
минутами, интерфейс замирать не должен. pip запускается через
``subprocess`` без шелла (список аргументов — ничего не подставится) и
без окна терминала (CREATE_NO_WINDOW, тот же приём, что в updates).

Пакет не тянет ML-модели: выбранная модель (REMBG_MODELS) скачивается
автоматически при первом удалении фона и кэшируется в домашней папке
(``~/.rembg``; у старых версий — ``~/.u2net``). «Удалить модуль»
вычищает и пакет, и кэш моделей целиком — на диске не остаётся ничего.

Здесь только механика; все надписи (i18n) и журнальные события — в
local_viewer, который этими задачами распоряжается.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QObject, QRunnable, Signal

# доступные модели: (id для rembg/QSettings, ключ i18n с названием и размером)
REMBG_MODELS = (
    ("u2netp", "viewer.rembg_model_u2netp"),
    ("u2net", "viewer.rembg_model_u2net"),
    ("isnet-general-use", "viewer.rembg_model_isnet"),
)
DEFAULT_MODEL = "u2netp"          # 4.7 МБ — резвый первый запуск, качество дотягивает u2net
MODEL_KEY = "viewer/rembg_model"  # где хранится выбранная модель
_NOBG_SUFFIX = "_nobg"            # метка результата: X.jpg -> X_nobg.png


def is_installed() -> bool:
    """Установлен ли пакет rembg в текущее окружение Python."""
    return importlib.util.find_spec("rembg") is not None


def model_cache_dirs() -> list[str]:
    """Где rembg кэширует модели: ~/.rembg и ~/.u2net (старые версии)."""
    home = os.path.expanduser("~")
    return [os.path.join(home, d) for d in (".rembg", ".u2net")]


def models_size() -> int:
    """Сколько байт занимают скачанные модели (для диалога удаления)."""
    total = 0
    for d in model_cache_dirs():
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass   # файл успел исчезнуть — не беда
    return total


def nobg_path(path: str) -> str:
    """Имя файла-результата: ``X.ext`` → ``X_nobg.png`` рядом с оригиналом.

    Пустая строка — файл уже результат (``X_nobg.png``): повторная
    обработка дала бы ``X_nobg_nobg.png``, лучше сразу отказать."""
    stem, _ext = os.path.splitext(path)
    if stem.endswith(_NOBG_SUFFIX):
        return ""
    return stem + _NOBG_SUFFIX + ".png"


# ---------- сигналы фоновых задач ----------


class RembgSignals(QObject):
    """Все сигналы rembg-задач; объект живёт в GUI-потоке (создаёт вьюер)."""

    install_done = Signal(bool, str)        # ok, хвост вывода pip при ошибке
    uninstall_done = Signal(bool, str, int)  # ok, хвост вывода, освобождено МБ
    file_done = Signal(str, str, bool, str)  # путь, результат, ok, ошибка
    batch_done = Signal(int, int)            # готово, с ошибками


# ---------- задачи: установка / удаление пакета ----------


def _run_pip(args: list[str]) -> tuple[bool, str]:
    """pip текущего Python без окна терминала; вывод — в память.

    Текущий интерпретатор (sys.executable) — пакет попадает ровно в то
    окружение, где работает программа. Шелла нет: список аргументов.
    """
    cmd = [sys.executable, "-m", "pip", *args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, ""
    # для сообщения хватит последних строк вывода (там, где причина)
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
    return False, " | ".join(tail) if tail else f"pip exit {proc.returncode}"


class InstallTask(QRunnable):
    """``pip install rembg[cpu]`` — библиотека + ONNX Runtime для CPU."""

    def __init__(self, signals: RembgSignals) -> None:
        super().__init__()
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        ok, info = _run_pip(["install", "--disable-pip-version-check",
                             "rembg[cpu]"])
        self.signals.install_done.emit(ok, info)


class UninstallTask(QRunnable):
    """``pip uninstall`` пакета и ONNX Runtime + чистка кэша моделей.

    Модели вычищаются даже если pip рапортует «not installed»: цель —
    после удаления на диске не остаётся ничего."""

    def __init__(self, signals: RembgSignals) -> None:
        super().__init__()
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        ok, info = _run_pip(["uninstall", "-y", "rembg", "onnxruntime"])
        freed = 0
        for d in model_cache_dirs():
            freed += _dir_size(d)
            shutil.rmtree(d, ignore_errors=True)
        self.signals.uninstall_done.emit(ok, info, freed // (1024 * 1024))


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# ---------- задача: удаление фона у пачки файлов ----------


class RemoveBgTask(QRunnable):
    """Прогнать файлы через rembg одной сессией.

    Сессия (модель в памяти) создаётся один раз на пачку — повторная
    загрузка модели на каждый файл растянула бы обработку в разы.
    Чтение исходников и запись результатов — здесь же, в рабочем
    потоке: на сетевом диске GUI не замораживается (принцип v0.7.2).
    """

    def __init__(self, jobs: list[tuple[str, str]], model: str,
                 signals: RembgSignals) -> None:
        super().__init__()
        self.jobs = jobs            # (исходный путь, путь результата)
        self.model = model
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        try:
            from rembg import remove, new_session
        except Exception as exc:   # noqa: BLE001 — наверх уйдёт текст
            for path, _out in self.jobs:
                self.signals.file_done.emit(path, "", False, str(exc))
            self.signals.batch_done.emit(0, len(self.jobs))
            return
        ok = fail = 0
        try:
            session = new_session(self.model)   # при первом запуске скачает модель
        except Exception as exc:  # noqa: BLE001
            for path, _out in self.jobs:
                self.signals.file_done.emit(path, "", False, str(exc))
            self.signals.batch_done.emit(0, len(self.jobs))
            return
        for path, out in self.jobs:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                result = remove(data, session=session)
                with open(out, "wb") as f:
                    f.write(result)
                ok += 1
                self.signals.file_done.emit(path, out, True, "")
            except Exception as exc:  # noqa: BLE001 — файл/формат могут быть любыми
                fail += 1
                self.signals.file_done.emit(path, "", False, str(exc))
        self.signals.batch_done.emit(ok, fail)
