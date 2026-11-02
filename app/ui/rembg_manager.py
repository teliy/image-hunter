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
(``~/.rembg``; у старых версий — ``~/.u2net``). Скачивание перехватывается
(hook_model_downloads): пока модели нет в кэше, файл качается здесь —
через requests, с докладом прогресса сигналами (статусная строка видит
«Скачивается модель u2netp: 1,2 МБ из 4,7 МБ (26 %)»), а штатный pooch
потом только проверяет хеш. «Удалить модуль»
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
import time

import requests

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


def _ensure_stdio() -> None:
    """Подменить отсутствующие sys.stdout/stderr заглушками (v0.7.14).

    На Windows программа запускается без консоли (pythonw), и
    sys.stdout/sys.stderr равны None. Библиотеки, пишущие в консоль,
    при этом падают: скачивание модели rembg идёт через pooch → tqdm,
    а tqdm пишет прогресс в sys.stderr и умирает с «'NoneType' object
    has no attribute 'write'» — у пользователя модель не скачивалась
    и удаление фона не работало вовсе (репорт после 0.7.12). None
    подменяется заглушкой, пишущей в никуда; настоящая консоль не
    трогается, вызов идемпотентен."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                stub = open(os.devnull, "w", encoding="utf-8")
            except OSError:
                import io
                stub = io.StringIO()
            setattr(sys, name, stub)


# ---------- сигналы фоновых задач ----------


class RembgSignals(QObject):
    """Все сигналы rembg-задач; объект живёт в GUI-потоке (создаёт вьюер)."""

    install_done = Signal(bool, str)        # ok, хвост вывода pip при ошибке
    uninstall_done = Signal(bool, str, int)  # ok, хвост вывода, освобождено МБ
    file_done = Signal(str, str, bool, str)  # путь, результат, ok, ошибка
    batch_done = Signal(int, int)            # готово, с ошибками
    revert_done = Signal(list, list)         # удалённые результаты, [(путь, ошибка)]
    # жизнь модели (v0.7.15): статусная строка рассказывает про скачивание
    model_prepare = Signal(str)              # модель готовится (грузится в память)
    model_ready = Signal(str)                # модель готова — началась обработка
    model_dl_start = Signal(str, int)        # модель, всего байт (0 — неизвестно)
    model_dl_progress = Signal(int, int)     # скачано байт, всего байт
    model_dl_done = Signal(str, int, int)    # модель, скачано байт, миллисекунды


# активная задача с объектом сигналов: pooch-перехват докладывает прогресс ей
_DL_REPORTER: "RembgSignals | None" = None


def _dl_emit(ev: str, *args) -> None:
    """Доложить о скачивании модели активной задаче (если она есть)."""
    rep = _DL_REPORTER
    if rep is None:
        return
    try:
        getattr(rep, ev).emit(*args)
    except RuntimeError:
        pass   # объект сигналов уже удалён — не беда


def _stream_model(url: str, target: str) -> None:
    """Скачать модель в ``target`` (через «.part») с докладом прогресса.

    Штатно модель качает pooch, но его прогресс живёт в консоли: у
    программы её нет (pythonw, v0.7.14) и из интерфейса она не видна —
    пользователь сидит в тишине, пока качаются 5–176 МБ. Здесь свой
    потоковый download через requests: каждые ~0,25 с сигнал
    model_dl_progress доезжает до статус-бара. При любой ошибке «.part»
    подчищается, исключение уходит наверх — вызывающий код отдаст
    скачивание штатному pooch."""
    tmp = target + ".part"
    t0 = time.monotonic()
    name = os.path.splitext(os.path.basename(target))[0]
    try:
        # папки кэша ещё нет при первом запуске: pooch создаёт её лениво,
        # когда качает сам — наш канал идёт раньше и должен создать сам
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with requests.get(url, stream=True, timeout=(10, 120),
                          headers={"User-Agent": "ImageHunter"}) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            _dl_emit("model_dl_start", name, total)
            done, last = 0, 0.0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(65536):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last >= 0.25:   # не заваливаем GUI-очередь
                        last = now
                        _dl_emit("model_dl_progress", done, total)
            _dl_emit("model_dl_progress", done, total)   # финальные 100 %
        os.replace(tmp, target)
        _dl_emit("model_dl_done", name, done,
                 int((time.monotonic() - t0) * 1000))
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _make_retrieve_wrapper(orig, accepts_progressbar: bool):
    """Обёртка pooch.retrieve: своё скачивание + доклад, потом оригинал.

    Оригинал зовётся всегда — он проверит хеш скачанного файла и при
    порче перекачает сам (уже без консольного прогресса)."""

    def retrieve(url, known_hash=None, fname=None, path=None,
                 processor=None, downloader=None, progressbar=True, **kw):
        target = os.path.join(path, fname) if (path and fname) else None
        if target and not os.path.exists(target):
            try:
                _stream_model(url, target)
            except Exception:   # noqa: BLE001 — наш канал не вышел, скачает pooch
                pass            # «.part» уже подчищен в _stream_model
        args = dict(fname=fname, path=path, processor=processor,
                    downloader=downloader)
        if accepts_progressbar:
            args["progressbar"] = False   # tqdm в консоли больше не нужен
        return orig(url, known_hash=known_hash, **args, **kw)

    return retrieve


def hook_model_downloads() -> None:
    """Показывать скачивание модели rembg в интерфейсе (v0.7.15).

    rembg качает модель через pooch.retrieve, чей прогресс (tqdm) пишется
    в консоль — которой у pythonw-версии нет и которая из программы не
    видна. Мы один раз за жизнь процесса подменяем pooch.retrieve своей
    обёрткой: пока файла модели нет в кэше — качаем сами с сигналами
    прогресса, дальше всё равно зовём оригинал (проверка хеша, докачка).
    Вызов идемпотентен и безопасен, если pooch не установлен."""
    try:
        import pooch
    except Exception:   # noqa: BLE001 — перехватывать нечего
        return
    if getattr(pooch, "_imagehunter_hook", False):
        return   # уже перехвачено — двойная обёртка дала бы рекурсию
    try:
        import inspect
        accepts_pb = "progressbar" in inspect.signature(pooch.retrieve).parameters
    except (TypeError, ValueError):
        accepts_pb = True
    orig = pooch.retrieve
    pooch.retrieve = _make_retrieve_wrapper(orig, accepts_pb)
    pooch._imagehunter_hook = True   # type: ignore[attr-defined]


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


class RevertTask(QRunnable):
    """«Вернуть оригиналы»: убрать файлы-результаты только что пачки (v0.7.15).

    Результаты «*_nobg.png» созданы программой секунды назад, оригиналы
    не тронуты — их можно удалить навсегда, не засоряя корзину. По сети
    удаление может идти секунды, поэтому — как все файловые операции —
    в рабочем потоке."""

    def __init__(self, paths: list[str], signals: RembgSignals) -> None:
        super().__init__()
        self.paths = list(paths)
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        removed: list[str] = []
        errors: list[tuple[str, str]] = []
        for p in self.paths:
            try:
                os.remove(p)
                removed.append(p)
            except OSError as exc:
                errors.append((p, str(exc)))
        self.signals.revert_done.emit(removed, errors)


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
        global _DL_REPORTER
        _DL_REPORTER = self.signals   # перехват докладывает прогресс сюда
        try:
            self._run_inner()
        finally:
            _DL_REPORTER = None

    def _run_inner(self) -> None:
        _ensure_stdio()   # pythonw: без этого падает скачивание модели (tqdm)
        # прогресс скачивания модели — в статусную строку (v0.7.15);
        # перехват безвреден, если pooch нет, и ставится один раз
        hook_model_downloads()
        try:
            from rembg import remove, new_session
        except Exception as exc:   # noqa: BLE001 — наверх уйдёт текст
            for path, _out in self.jobs:
                self.signals.file_done.emit(path, "", False, str(exc))
            self.signals.batch_done.emit(0, len(self.jobs))
            return
        self.signals.model_prepare.emit(self.model)
        ok = fail = 0
        try:
            session = new_session(self.model)   # при первом запуске скачает модель
        except Exception as exc:  # noqa: BLE001
            for path, _out in self.jobs:
                self.signals.file_done.emit(path, "", False, str(exc))
            self.signals.batch_done.emit(0, len(self.jobs))
            return
        self.signals.model_ready.emit(self.model)
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
