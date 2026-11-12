"""Управление модулем улучшения качества изображения (v0.8.24).

Пожелание: «давай добавим модуль улучшения качества изображения (и
разрешения картинки) так-же как и другие, чтобы он качался с github
и мог быть установлен/обновлен и полностью удален».

Движок — **Real-ESRGAN** (`xinntao/Real-ESRGAN <https://github.com/xinntao/
Real-ESRGAN>`_) — самая живая открытая модель увеличения разрешения на
GitHub: веса лежат в релизах того же репозитория и качаются оттуда
напрямую (тот же принцип, что у big-lama из релизов Sanster/models).
Ре-ESRGAN — это GAN-модель: картинка не просто растягивается, а
достраивается — края предметов чётче, лица опрятнее, шум и артефакты
сжатия сглаживаются; есть отдельная лёгкая модель для аниме и рисованной
графики. Всё считается локально, без облаков и ключей.

* **RealESRGAN_x4plus** (~64 МБ, релиз v0.1.0) — универсальная ×4;
* **RealESRGAN_x4plus_anime_6B** (~17 МБ, релиз v0.2.2.4) — ×4 для аниме
  и рисованной графики, в 4 раза меньше блоков — заметно быстрее;
* **RealESRGAN_x2plus** (~64 МБ, релиз v0.2.1) — умеренная ×2, безопаснее
  для фотографий с мелкими деталями.

Архитектура RRDBNet вендорится сюда из BasicSR (BSD-3, автор Real-ESRGAN)
без пакета ``basicsr`` целиком — чистый torch: единственная pip-зависимость
модуля. torch — общий гость с модулем водяных знаков (тот же принцип,
что у opencv у rembg и iopaint): установка ставит его, только если его
ещё нет; удаление вычищает torch, ТОЛЬКО если модуль водяных знаков не
установлен; «Обновить модуль» torch не перекладывает вовсе (гигабайты и
общее достояние) — сверяются размеры весов выбранной модели с релизом
GitHub, изменившийся файл перекачивается.

Веса качаются при первом улучшении (как модели rembg) в собственный кэш
``~/.cache/ImageHunter/real-esrgan``; прогресс доезжает до статус-бара
сигналами (тот же приём, что у rembg — v0.7.15, и big-lama — v0.8.20).
Размер скачанного файла сверяется с релизом (адреса релизов неизменяемы,
размер — честная проверка целостности); «Удалить модуль» вычищает и
пакет, и кэш целиком — на диске не остаётся ничего своего.

Картинки обрабатываются плитками 256×256 с запасом 10 px (тот же приём,
что в штатном ``inference_realesrgan.py``): память не зависит от размера
картинки, ход плиток виден в строке статуса. Альфа-канал (PNG/WebP) не
выбрасывается: RGB растит модель, маска — Lanczos ×scale. Результат —
отдельный файл: ``X.ext`` → ``X_x4.ext``/``X_x2.ext`` рядом с оригиналом
(оригиналы никогда не перезаписываются); AVIF → PNG (как в закрашивании
v0.8.8); GIF и файлы без расширения — отказ (анимация и «безымянный»
формат не для покадрового апскейла); вход «уже результат» (``X_x4.*``)
тоже отказ — повторный прогон той же модели вырос бы в «X_x4_x4».
Предохранитель: результат больше 50 мегапикселей — честный отказ:
миллионные картинки и диск не радуют, и память.

Здесь только механика; надписи (i18n) и журнальные события — в
local_viewer, который этими задачами распоряжается. Тяжёлые зависимости
импортируются лениво: пока модуль не установлен, файл безопасно
импортируется в любом процессе (принцип rembg_manager, v0.7.12).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
import time
import urllib.request

from PIL import Image, ImageOps

from app.core.i18n import tr
from PySide6.QtCore import QObject, QRunnable, Signal

# доступные модели: (файл весов в релизе GitHub, ключ i18n с названием
# и размером). Порядок — как в меню: сначала универсальная по умолчанию.
UPSCALE_MODELS = (
    ("RealESRGAN_x4plus.pth", "viewer.up_model_x4plus"),
    ("RealESRGAN_x4plus_anime_6B.pth", "viewer.up_model_anime"),
    ("RealESRGAN_x2plus.pth", "viewer.up_model_x2plus"),
)
DEFAULT_MODEL = "RealESRGAN_x4plus.pth"
MODEL_KEY = "viewer/up_model"     # где хранится выбранная модель

# карта моделей — как в штатном inference_realesrgan.py: у anime_6B
# всего 6 RRDB-блоков (вместо 23), у x2plus вход идёт через pixel_unshuffle
_NET_PARAMS = {
    "RealESRGAN_x4plus.pth": dict(num_in_ch=3, num_out_ch=3, scale=4,
                                  num_feat=64, num_block=23, num_grow_ch=32),
    "RealESRGAN_x4plus_anime_6B.pth": dict(num_in_ch=3, num_out_ch=3, scale=4,
                                           num_feat=64, num_block=6,
                                           num_grow_ch=32),
    "RealESRGAN_x2plus.pth": dict(num_in_ch=3, num_out_ch=3, scale=2,
                                  num_feat=64, num_block=23, num_grow_ch=32),
}

# адреса весов: неизменяемые релизы GitHub (xinntao/Real-ESRGAN)
_RELEASE_TAGS = {
    "RealESRGAN_x4plus.pth": "v0.1.0",
    "RealESRGAN_x4plus_anime_6B.pth": "v0.2.2.4",
    "RealESRGAN_x2plus.pth": "v0.2.1",
}

# размеры файлов-весов по релизу (проверено 2026-11-12 GitHub API,
# repos/xinntao/Real-ESRGAN/releases): адрес релиза неизменяем, поэтому
# размер скачанного файла — честная проверка целостности
_ASSET_SIZES = {
    "RealESRGAN_x4plus.pth": 67_040_989,
    "RealESRGAN_x4plus_anime_6B.pth": 17_938_799,
    "RealESRGAN_x2plus.pth": 67_061_725,
}

# плитки апскейла: как в штатном inference_realesrgan.py (tile=0 — целиком;
# здесь фиксированная плитка, чтобы память не зависела от картинки)
TILE = 256
TILE_PAD = 10

# предохранитель результата: 50 МП — дальше и диск, и память не радуют
MAX_OUT_PIXELS = 50_000_000

_UP_SUFFIXES = {4: "_x4", 2: "_x2"}   # метка результата по масштабу модели

# квоты сжатия результатов — как в программе (JPEG 92 / WEBP 90,
# тот же приём, что у _save_array в watermark_manager)


def is_installed() -> bool:
    """Установлен ли torch в текущее окружение Python."""
    return importlib.util.find_spec("torch") is not None


def installed_version() -> str:
    """Версия установленного torch; "" — пакет не стоит/метаданных нет."""
    try:
        return importlib.metadata.version("torch")
    except Exception:   # noqa: BLE001 — PackageNotFoundError и битые метаданные
        return ""


def model_cache_dir() -> str:
    """Свой кэш весов: ~/.cache/ImageHunter/real-esrgan."""
    return os.path.join(os.path.expanduser("~"), ".cache", "ImageHunter",
                        "real-esrgan")


def model_file(fname: str) -> str:
    """Путь к скачанным весам; "" — модель ещё не скачивалась."""
    path = os.path.join(model_cache_dir(), fname)
    return path if os.path.isfile(path) else ""


def models_size() -> int:
    """Сколько байт занимают скачанные веса (для диалога удаления)."""
    d = model_cache_dir()
    if not os.path.isdir(d):
        return 0
    total = 0
    for root, _dirs, files in os.walk(d):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass   # файл успел исчезнуть — не беда
    return total


def model_scale(fname: str) -> int:
    """Масштаб модели (4 или 2) — из официальной карты моделей."""
    return int(_NET_PARAMS.get(fname, {}).get("scale", 4))


def remote_content_length(url: str) -> int:
    """Размер файла по HEAD-запросу; 0 — узнать не удалось."""
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "ImageHunter"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except (OSError, ValueError):
        return 0


def asset_url(fname: str) -> str:
    """Адрес весов модели в релизе GitHub."""
    return ("https://github.com/xinntao/Real-ESRGAN/releases/download/"
            f"{_RELEASE_TAGS[fname]}/{fname}")


def up_path(path: str, scale: int) -> str:
    """Имя файла-результата: ``X.ext`` → ``X_x4.ext``/``X_x2.ext`` рядом.

    Формат сохраняется (результат — непрозрачная либо с альфой картинка),
    кроме AVIF → PNG (как в закрашивании v0.8.8). Пустая строка — файл
    обрабатывать не нужно: GIF (анимация не для покадрового апскейла),
    без расширения или это уже результат (``X_x4.jpg``): повторный прогон
    дал бы «X_x4_x4.jpg», лучше сразу отказать.
    """
    stem, ext = os.path.splitext(path)
    low = ext.lower()
    if low in (".gif", ""):
        return ""
    if stem.endswith(tuple(s for s in _UP_SUFFIXES.values())):
        return ""
    if low == ".avif":
        return stem + _UP_SUFFIXES.get(scale, "_x4") + ".png"
    return stem + _UP_SUFFIXES.get(scale, "_x4") + ext


# ---------- сигналы фоновых задач ----------


class UpscaleSignals(QObject):
    """Все сигналы задач модуля; объект живёт в GUI-потоке (создаёт вьюер)."""

    install_done = Signal(bool, str)         # ok, хвост вывода pip при ошибке
    uninstall_done = Signal(bool, str, int)  # ok, хвост вывода, освобождено МБ
    update_done = Signal(bool, str, str)     # ok, что изменилось ("" — ничего), ошибка
    file_done = Signal(str, str, bool, str)  # путь, результат, ok, ошибка
    batch_done = Signal(int, int)            # с результатом, с ошибками
    file_start = Signal(str, int)            # путь, номер файла в пачке (с 1)
    phase = Signal(str, str, int, int)       # путь, код фазы, текущий, всего
    model_prepare = Signal(str)              # модель готовится (первый раз — качается)
    model_ready = Signal(str)                # модель готова — пошла обработка
    model_dl_start = Signal(str, int)        # модель, всего байт (0 — неизвестно)
    model_dl_progress = Signal(int, int)     # скачано байт, всего байт
    model_dl_done = Signal(str, int, int)    # модель, скачано байт, миллисекунды
    revert_done = Signal(list, list)         # удалённые результаты, [(путь, ошибка)]


# активная задача с объектом сигналов: скачивание весов докладывает ей
# (тот же приём, что в rembg_manager и watermark_manager)
_DL_REPORTER: "UpscaleSignals | None" = None


def _dl_emit(ev: str, *args) -> None:
    """Доложить о ходе работы активной задаче (если она есть)."""
    rep = _DL_REPORTER
    if rep is None:
        return
    try:
        getattr(rep, ev).emit(*args)
    except RuntimeError:
        pass   # объект сигналов уже удалён — не беда


def _ensure_stdio() -> None:
    """Подменить отсутствующие sys.stdout/stderr заглушками (v0.7.14).

    На Windows программа запускается без консоли (pythonw), и
    sys.stdout/sys.stderr равны None — библиотеки, пишущие в консоль,
    при этом падают. None подменяется заглушкой, пишущей в никуда;
    настоящая консоль не трогается, вызов идемпотентен."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                stub = open(os.devnull, "w", encoding="utf-8")
            except OSError:
                import io
                stub = io.StringIO()
            setattr(sys, name, stub)


def _stream_model(url: str, target: str, expected: int) -> None:
    """Скачать веса в ``target`` (через «.part») с докладом прогресса.

    Каждые ~0,3 с сигнал model_dl_progress доезжает до статус-бара.
    Размер скачанного файла сверяется с релизом (_ASSET_SIZES — адрес
    релиза неизменяем, размер не может «поменяться легально»): отличие —
    битая скачка, исключение наверх, «.part» подчищается.
    """
    tmp = target + ".part"
    t0 = time.monotonic()
    name = os.path.splitext(os.path.basename(target))[0]
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        import requests   # лениво: нужен только на этом пути
        total = remote_content_length(url)
        with requests.get(url, stream=True, timeout=(10, 120),
                          headers={"User-Agent": "ImageHunter"}) as r:
            r.raise_for_status()
            if total <= 0:
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
                    if total > 0 and now - last >= 0.3:   # не заваливаем GUI
                        last = now
                        _dl_emit("model_dl_progress", done, total)
        if total > 0:
            _dl_emit("model_dl_progress", done, total)   # финальные 100 %
        if expected and os.path.getsize(tmp) != expected:
            raise OSError(f"size mismatch: {os.path.getsize(tmp)} != {expected}")
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


def _ensure_model_downloaded(fname: str) -> str:
    """Веса модели должны лежать в кэше; путь или исключение.

    Уже скачанный файл не перекачивается (гонки не страшны). Прогресс
    докладывается сигналами активной задачи; при сетевой ошибке исключение
    уходит наверх — пачка честно репортит ошибку по каждому файлу.
    """
    target = os.path.join(model_cache_dir(), fname)
    if os.path.isfile(target):
        return target
    _stream_model(asset_url(fname), target, _ASSET_SIZES.get(fname, 0))
    return target


# ---------- задачи: установка / удаление модуля ----------


def _run_pip(args: list[str]) -> tuple[bool, str]:
    """pip текущего Python без окна терминала; вывод — в память.

    Тот же приём, что в rembg_manager (v0.7.12) и watermark_manager:
    текущий интерпретатор (sys.executable) — пакет попадает ровно в то
    окружение, где работает программа; шелла нет (список аргументов),
    окна нет (CREATE_NO_WINDOW).
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
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
    return False, " | ".join(tail) if tail else f"pip exit {proc.returncode}"


def _wm_installed() -> bool:
    """Стоит ли модуль водяных знаков (ему torch тоже нужен).

    Ленивая проверка без жёсткой связи: модуль соседа мог быть удалён
    из другой сборки программы."""
    try:
        from app.ui import watermark_manager
        return watermark_manager.is_installed()
    except Exception:   # noqa: BLE001 — сосед-модуль не критичен для решения
        return False


class InstallTask(QRunnable):
    """``pip install torch`` — если он ещё не стоит.

    torch — общий с модулем водяных знаков: если тот уже установлен,
    pip не запускается вовсе (модуль готов сразу, гигабайты не
    перекладываются). Тяжело (сотни мегабайт — гигабайты) — в рабочем
    потоке, интерфейс не замирает (принцип rembg_manager, v0.7.12).
    """

    def __init__(self, signals: UpscaleSignals) -> None:
        super().__init__()
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        if is_installed():
            self.signals.install_done.emit(True, "")   # torch уже стоит
            return
        ok, info = _run_pip(["install", "--disable-pip-version-check", "torch"])
        self.signals.install_done.emit(ok, info)


class UninstallTask(QRunnable):
    """``pip uninstall torch`` (если модуль водяных знаков не стоит) + кэш.

    torch, нужный соседу-модулю, не вычищается (принцип «чужое не
    вычищать», v0.7.12): уйдут только СВОИ веса из кэша — на диске не
    остаётся ничего, принадлежащего только этому модулю. Кэш вычищается
    даже если pip рапортует «not installed».
    """

    def __init__(self, signals: UpscaleSignals) -> None:
        super().__init__()
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        freed = models_size()
        if _wm_installed():
            # torch — общее достояние: сосед остаётся, веса — наши
            ok, info = True, ""
        else:
            ok, info = _run_pip(["uninstall", "-y", "torch"])
        shutil.rmtree(model_cache_dir(), ignore_errors=True)
        self.signals.uninstall_done.emit(ok, info, freed // (1024 * 1024))


class UpdateTask(QRunnable):
    """Проверить и обновить установленный модуль.

    * **torch не перекладывается** (в отличие от пакетов rembg/iopaint):
      это общее с модулем водяных знаков достояние счётом на гигабайты,
      обновлять его за спиной пользователя нельзя. Версия докладывается
      в итоге «как есть».
    * **Веса выбранной модели**: размер локального файла сверяется
      с релизом GitHub (HEAD-запрос); отличается — файл перекачивается
      заново, с прогрессом в статус-бар. Адрес релиза неизменяем, так
      что размер — честная проверка «вышло ли что-то новое».
    """

    def __init__(self, signals: UpscaleSignals, model: str) -> None:
        super().__init__()
        self.signals = signals
        self.model = model          # выбранные веса (какими пользуются)

    def run(self) -> None:  # рабочий поток
        ver = installed_version()
        if not ver:
            self.signals.update_done.emit(
                False, "", "torch: не удалось определить установленную версию")
            return
        short = self.model
        local = model_file(short)
        if local:
            size = remote_content_length(asset_url(short))
            if size <= 0:
                self.signals.update_done.emit(
                    True, tr("viewer.up_update_dl_fail", model=short,
                             ver=ver), "")
                return
            if size != os.path.getsize(local):
                try:
                    os.remove(local)
                    _ensure_model_downloaded(short)
                except Exception as exc:   # noqa: BLE001 — сеть/диск любые
                    self.signals.update_done.emit(
                        True, tr("viewer.up_update_dl_fail", model=short,
                                 ver=ver), str(exc))
                    return
                self.signals.update_done.emit(
                    True, tr("viewer.up_update_weights", model=short,
                             ver=ver), "")
            else:
                self.signals.update_done.emit(
                    True, tr("viewer.up_update_nothing", model=short,
                             ver=ver), "")
        else:
            self.signals.update_done.emit(
                True, tr("viewer.up_update_no_dl", model=short, ver=ver), "")


class RevertTask(QRunnable):
    """«Вернуть оригиналы»: убрать файлы-результаты только что пачки.

    Результаты «*_x4.ext» созданы программой секунды назад, оригиналы
    не тронуты — их можно удалить навсегда, не засоряя корзину. По сети
    удаление может идти секунды — в рабочем потоке (тот же приём,
    что у rembg — v0.7.15)."""

    def __init__(self, paths: list[str], signals: UpscaleSignals) -> None:
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


# ---------- конвейер: RRDBNet (Real-ESRGAN) ----------


def _torch_device() -> str:
    """cuda, если есть; иначе cpu (всё считается локально, без облаков)."""
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:   # noqa: BLE001 — без torch cpu-путь всё равно не дойдёт
        return "cpu"


# --- архитектура RRDBNet: вендор из BasicSR (BSD-3), xinntao/BasicSR ---
# (basicsr/archs/rrdbnet_arch.py, без реестра ARCH_REGISTRY и импорта
# соседей: make_layer развёрнут здесь, default_init_weights опущен —
# он нужен только при случайной инициализации для обучения, а мы всегда
# грузим готовые веса). Имена слоёв совпадают с весами релизов 1:1.

def _make_layer(block, n, **kwargs):
    """Слой из n одинаковых блоков (basicsr.utils.make_layer)."""
    import torch.nn as nn
    return nn.Sequential(*[block(**kwargs) for _ in range(n)])


def _build_rrdbnet(fname: str):
    """RRDBNet с параметрами официальной карты моделей (точка подмены тестов)."""
    import torch
    import torch.nn as nn
    from torch.nn import functional as F

    class ResidualDenseBlock(nn.Module):
        """Блок плотных связей ESRGAN (0.2 — эмпирический масштаб остатка)."""

        def __init__(self, num_feat=64, num_grow_ch=32):
            super().__init__()
            self.conv1 = nn.Conv2d(num_feat, num_grow_ch, 3, 1, 1)
            self.conv2 = nn.Conv2d(num_feat + num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv3 = nn.Conv2d(num_feat + 2 * num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv4 = nn.Conv2d(num_feat + 3 * num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv5 = nn.Conv2d(num_feat + 4 * num_grow_ch, num_feat, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            x1 = self.lrelu(self.conv1(x))
            x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
            x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
            x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
            x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
            return x5 * 0.2 + x

    class RRDB(nn.Module):
        """Residual in Residual Dense Block — три блока выше."""

        def __init__(self, num_feat, num_grow_ch=32):
            super().__init__()
            self.rdb1 = ResidualDenseBlock(num_feat, num_grow_ch)
            self.rdb2 = ResidualDenseBlock(num_feat, num_grow_ch)
            self.rdb3 = ResidualDenseBlock(num_feat, num_grow_ch)

        def forward(self, x):
            out = self.rdb1(x)
            out = self.rdb2(out)
            out = self.rdb3(out)
            return out * 0.2 + x

    class RRDBNet(nn.Module):
        """Сеть из RRDB-блоков; scale 2/1 идут через pixel_unshuffle
        (уменьшение картинки втрое-вчетверо уже сделано плотными блоками,
        поэтому у x2plus первый конверт принимает 12 каналов)."""

        def __init__(self, num_in_ch, num_out_ch, scale=4, num_feat=64,
                     num_block=23, num_grow_ch=32):
            super().__init__()
            self.scale = scale
            if scale == 2:
                num_in_ch = num_in_ch * 4
            elif scale == 1:
                num_in_ch = num_in_ch * 16
            self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
            self.body = _make_layer(RRDB, num_block, num_feat=num_feat,
                                    num_grow_ch=num_grow_ch)
            self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            # upsample
            self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            if self.scale == 2:
                feat = F.pixel_unshuffle(x, scale=2)
            elif self.scale == 1:
                feat = F.pixel_unshuffle(x, scale=4)
            else:
                feat = x
            feat = self.conv_first(feat)
            body_feat = self.conv_body(self.body(feat))
            feat = feat + body_feat
            # upsample: каждая ступень — ×2 (nearest + свёртка)
            feat = self.lrelu(self.conv_up1(
                F.interpolate(feat, scale_factor=2, mode="nearest")))
            feat = self.lrelu(self.conv_up2(
                F.interpolate(feat, scale_factor=2, mode="nearest")))
            out = self.conv_last(self.lrelu(self.conv_hr(feat)))
            return out

    params = dict(_NET_PARAMS[fname])
    return RRDBNet(**params)


def _load_net(fname: str):
    """Веса с диска в память: (сеть, устройство, масштаб). Точка подмены тестов.

    Модель качается при первом запуске (_ensure_model_downloaded — прогресс
    в статус-бар), параметры берутся из официальной карты моделей
    (_NET_PARAMS), загрузка строгая: чужой/битый файл не притворится
    моделью. Сеть переводится в режим вывода.
    """
    import torch

    path = _ensure_model_downloaded(fname)
    scale = int(_NET_PARAMS[fname]["scale"])
    net = _build_rrdbnet(fname)
    try:
        state = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:   # noqa: BLE001 — torch < 1.13 без weights_only
        state = torch.load(path, map_location="cpu")
    net.load_state_dict(state, strict=True)
    device = _torch_device()
    net = net.to(device).eval()
    return net, device, scale


def _to_tensor(img: Image.Image):
    """PIL → тензор float [1,C,H,W] в диапазоне 0–1."""
    import numpy as np
    import torch

    arr = np.asarray(img, dtype=np.uint8)
    t = torch.from_numpy(arr.copy()).float().div_(255.0)
    return t.permute(2, 0, 1).unsqueeze(0)   # HWC → CHW → [1,C,H,W]


def _to_image(t, mode: str) -> Image.Image:
    """Тензор [1,C,H,W] 0–1 → PIL uint8."""
    import numpy as np
    import torch

    arr = (t.squeeze(0).permute(1, 2, 0).clamp_(0.0, 1.0)
           .mul_(255.0).round_().to(torch.uint8).numpy())
    if arr.ndim == 2:
        return Image.fromarray(arr, "L")
    return Image.fromarray(arr, mode)


def _tiled(net, device, t, signals, path: str):
    """Апскейл плитками 256×256 с запасом 10 px (ход — в строку статуса).

    Тот же приём, что в штатном inference_realesrgan.py: картинка режется
    на шагающие внахлёст плитки, каждая обрабатывается с запасом, в
    результат вклеивается только «сердце» плитки — швов не видно, память
    не зависит от размера картинки. Целиком (одной плиткой) обрабатываются
    картинки, влезающие в TILE: их трогать резкой нет смысла. Вызов
    происходит внутри torch.inference_mode() у вызывающего кода.
    """
    import torch

    _c, h, w = t.shape[1], t.shape[2], t.shape[3]
    scale = int(getattr(net, "scale", 4))
    out_h, out_w = h * scale, w * scale
    result = t.new_zeros((1, t.shape[1], out_h, out_w))
    tile = min(TILE, h, w)
    pad = TILE_PAD
    # плитки идут с шагом tile (последние добираются до края) — как в
    # штатной реализации: без нахлёста шага нахлёст даёт задвоение
    ys = list(range(0, max(h - tile, 0) + 1, tile)) or [0]
    if ys[-1] != max(h - tile, 0):
        ys.append(max(h - tile, 0))
    xs = list(range(0, max(w - tile, 0) + 1, tile)) or [0]
    if xs[-1] != max(w - tile, 0):
        xs.append(max(w - tile, 0))
    total = len(ys) * len(xs)
    idx = 0
    for y0 in ys:
        for x0 in xs:
            idx += 1
            signals.phase.emit(path, "tile", idx, total)
            y1, x1 = max(0, y0 - pad), max(0, x0 - pad)
            y2, x2 = min(h, y0 + tile + pad), min(w, x0 + tile + pad)
            piece = net(t[:, :, y1:y2, x1:x2].to(device)).detach().float().cpu()
            # в результат идёт «сердце» плитки — без запаса по краям
            oy, ox = (y0 - y1) * scale, (x0 - x1) * scale
            th = min((y0 + tile) * scale, out_h) - y0 * scale
            tw = min((x0 + tile) * scale, out_w) - x0 * scale
            result[:, :, y0 * scale:y0 * scale + th,
                   x0 * scale:x0 * scale + tw] = \
                piece[:, :, oy:oy + th, ox:ox + tw]
    return result


def _save_result(img: Image.Image, out_path: str) -> None:
    """Записать результат по расширению (JPEG 92 / WEBP 90 — как в программе).

    JPEG и BMP альфу не умеют — картинка кладётся на белый фон (тот же
    приём, что в image_saver); PNG/WEBP/TIFF сохраняют альфу как есть."""
    ext = os.path.splitext(out_path)[1].lower()
    if img.mode == "RGBA" and ext in (".jpg", ".jpeg", ".bmp"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        img = bg
    if ext in (".jpg", ".jpeg"):
        img.save(out_path, "JPEG", quality=92)
    elif ext == ".webp":
        img.save(out_path, "WEBP", quality=90)
    else:   # PNG / BMP / TIFF
        img.save(out_path)


def _upscale_image(src: str, out: str, net, device: str, scale: int,
                   signals: UpscaleSignals) -> None:
    """Один файл: чтение → апскейл (плитки) → альфа → запись результата.

    Чтение и запись — здесь же, в рабочем потоке (принцип v0.7.2).
    EXIF-разворот тот же, что у показа в ленте (exif_transpose), —
    результат совпадает с тем, что видел пользователь. Альфа-канал
    не выбрасывается: RGB растит модель, маска — Lanczos ×scale
    (модель обучена на RGB, маске хватает классического ресайза).
    """
    import torch

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        has_alpha = im.mode in ("RGBA", "LA", "PA")
        base = im.convert("RGBA") if has_alpha else im.convert("RGB")
        out_w, out_h = base.width * scale, base.height * scale
        if out_w * out_h > MAX_OUT_PIXELS:
            raise ValueError(
                f"результат {out_w}×{out_h} ({out_w * out_h // 1_000_000} МП) "
                f"больше предела {MAX_OUT_PIXELS // 1_000_000} МП")
        alpha = None
        if has_alpha:
            alpha = base.getchannel("A").resize((out_w, out_h),
                                                Image.LANCZOS)
        rgb = base.convert("RGB")
        t = _to_tensor(rgb)
        # вывод целиком под inference_mode: без построения графа — заметно
        # меньше памяти и быстрее; result живёт только внутри контекста
        with torch.inference_mode():
            out_t = _tiled(net, device, t, signals, src)
            result = _to_image(out_t, "RGB")
        if alpha is not None:
            result = result.convert("RGBA")
            result.putalpha(alpha)
        _save_result(result, out)


class UpscaleTask(QRunnable):
    """Прогнать файлы через Real-ESRGAN одной сессией.

    Модель грузится в память один раз на пачку — повторная загрузка
    весов на каждый файл растянула бы обработку в разы. Чтение исходников
    и запись результатов — здесь же, в рабочем потоке: на сетевом диске
    GUI не замораживается (принцип v0.7.2). Оригиналы никогда не
    перезаписываются: результат — отдельный файл «*_x4.ext»/«*_x2.ext».
    """

    def __init__(self, jobs: list[tuple[str, str]], model: str,
                 signals: UpscaleSignals) -> None:
        super().__init__()
        self.jobs = jobs            # (исходный путь, путь результата)
        self.model = model
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        global _DL_REPORTER
        _DL_REPORTER = self.signals   # доклад скачивания весов — в статус-бар
        try:
            self._run_inner()
        finally:
            _DL_REPORTER = None

    def _run_inner(self) -> None:
        _ensure_stdio()   # pythonw: без этого падают консольные прогресс-бары
        self.signals.model_prepare.emit(self.model)
        try:
            net, device, scale = _load_net(self.model)
        except Exception as exc:   # noqa: BLE001 — сеть/веса/окружение любые
            for path, _out in self.jobs:
                self.signals.file_done.emit(path, "", False, str(exc))
            self.signals.batch_done.emit(0, len(self.jobs))
            return
        self.signals.model_ready.emit(self.model)
        ok = fail = 0
        for idx, (path, out) in enumerate(self.jobs, 1):
            # начало файла — в строку статуса (v0.8.20): до file_done
            # модель считает секунды, и прогресс замирал на «N/M»
            self.signals.file_start.emit(path, idx)
            try:
                _upscale_image(path, out, net, device, scale, self.signals)
                ok += 1
                self.signals.file_done.emit(path, out, True, "")
            except Exception as exc:  # noqa: BLE001 — файл/формат могут быть любыми
                fail += 1
                self.signals.file_done.emit(path, "", False, str(exc))
        self.signals.batch_done.emit(ok, fail)
