"""Управление модулем удаления водяных знаков (v0.8.11).

Пожелание: «давай как модуль (который можно установить и удалить)
добавим из github самый лучший удаляльщик watermark».

Лучшее с GitHub связывается в один локальный конвейер из двух открытых
инструментов — тот же подход, что в D-Ogi/WatermarkRemover-AI:

* **Florence-2** (microsoft, через ``transformers``) — vision-language
  модель: задача ``<CAPTION_TO_PHRASE_GROUNDING>`` с фразой «watermark»
  находит надписи водяных знаков и отдаёт их прямоугольники;
* **LaMa из IOPaint** (Sanster/IOPaint) — самый живой инструмент
  inpainting'а на GitHub (позиционируется в т.ч. для «Erase … watermarks»):
  закрашивает найденные области, достраивая фон по соседям.

Установка идёт в два шага (v0.8.12): сам ``iopaint`` ставится с
``--no-deps`` — его метаданные требуют ровно ``Pillow==9.5.0``, а у этой
версии нет готовых сборок под Python 3.12/3.13, поэтому pip лезет собирать
старый исходник и падает («KeyError: '__version__'»); зависимости iopaint
берутся из ЕГО ЖЕ метаданных уже без требования Pillow — это библиотека
самой программы, она уже стоит, и модуль её не перекладывает (тот же
принцип, что при удалении: «numpy/Pillow бережены»). Вместе с ними
ставятся ``transformers`` и ``timm`` — детектор Florence-2; torch — самый
тяжёлый гость, счёт на гигабайты. Модели скачиваются при первом запуске:
LaMa (~200 МБ) — в кэш torch-hub, Florence-2 (base ~500 МБ / large ~1,6 ГБ)
— в кэш Hugging Face. «Удалить модуль» вычищает и пакеты, и кэши моделей —
но только СВОИ: big-lama.pt и Florence-2; кэши других моделей (и общие
библиотеки numpy/pillow, нужные программе и rembg) не трогаются.

Здесь только механика; все надписи (i18n) и журнальные события — в
local_viewer, который этими задачами распоряжается. Тяжёлые зависимости
импортируются лениво: пока модуль не установлен, файл безопасно
импортируется в любом процессе (принцип rembg_manager, v0.7.12).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import re
import shutil
import subprocess
import sys

from PIL import Image

from PySide6.QtCore import QObject, QRunnable, Signal

# фраза для Florence-2: что искать на картинке (как в WatermarkRemover-AI)
DETECT_PROMPT = "watermark"
_FLORENCE_TASK = "<CAPTION_TO_PHRASE_GROUNDING>"

# доступные детекторы: (id для Hugging Face, ключ i18n с названием и размером)
FLORENCE_MODELS = (
    ("microsoft/Florence-2-base", "viewer.wm_model_base"),
    ("microsoft/Florence-2-large", "viewer.wm_model_large"),
)
DEFAULT_MODEL = "microsoft/Florence-2-base"   # резвый первый запуск
MODEL_KEY = "viewer/wm_model"                 # где хранится выбранная модель

_NOWM_SUFFIX = "_nowm"            # метка результата: X.jpg -> X_nowm.jpg
MASK_MARGIN = 15                  # расширение бокса, px на сторону (аналог dilate)

# что ставит модуль: iopaint — конвейер LaMa, transformers/timm — Florence-2.
# iopaint ставится с --no-deps: его пин Pillow==9.5.0 не выполняется на
# Python 3.12/3.13 и валит всю установку (v0.8.12) — зависимости берутся
# из его же метаданных, уже без требования Pillow (_module_requirements)
_MAIN_PACKAGE = "iopaint"
_SIDE_PACKAGES = ("transformers", "timm")

# имя пакета из требования pip ("Pillow==9.5.0" → "pillow")
_REQ_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _req_name(raw: str) -> str:
    """Имя пакета из строки требования; пусто — разобрать не удалось."""
    m = _REQ_NAME_RE.match(raw.strip())
    return m.group(0).lower() if m else ""


def _iopaint_requires() -> list[str]:
    """Список требований pip из метаданных установленного iopaint.

    Отдельная точка подмены в тестах (в песочнице iopaint не стоит).
    """
    try:
        return list(importlib.metadata.requires(_MAIN_PACKAGE) or [])
    except Exception:   # noqa: BLE001 — нет пакета/метаданные побились
        return []


def _module_requirements() -> list[str]:
    """Зависимости iopaint для pip: его же список, но без требования Pillow.

    iopaint требует ровно ``Pillow==9.5.0``; у такой версии нет готовых
    сборок под Python 3.12/3.13, и pip, пытаясь собрать старый исходник,
    падает с «KeyError: '__version__'» (пожелание-репорт: «при установке
    модуля такая ошибка»). Pillow у программы уже стоит — требование
    выбрасывается, всё остальное берётся как сказал сам iopaint (маркеры
    окружения сохраняются, pip сам их оценит).
    """
    return [raw.strip() for raw in _iopaint_requires()
            if _req_name(raw) and _req_name(raw) != "pillow"]


# дистрибуции, которые ставились только ради этого модуля — их вычищает
# «Удалить модуль» (зависимости iopaint добавляются из его метаданных —
# _module_dep_names). numpy/pillow не трогаются никогда: они нужны самой
# программе; opencv-пакеты вычищаются, только если не стоит rembg
# (у него та же зависимость — принцип rembg «чужое не вычищать», v0.7.12)
_OWN_DISTS = ("iopaint", "torch", "torchvision", "timm", "transformers",
              "tokenizers", "safetensors", "huggingface-hub")
_SHARED_DISTS = ("opencv-python", "opencv-python-headless")


def _module_dep_names() -> list[str]:
    """Прямые зависимости iopaint для удаления: имена без Pillow и opencv.

    Pillow — библиотека программы; opencv-пакеты решаются отдельно
    (_SHARED_DISTS с проверкой rembg), поэтому из динамической части они
    исключены. Статический _OWN_DISTS остаётся запасом на случай, когда
    метаданных уже нет (iopaint удалён).
    """
    skip = ("pillow",) + _SHARED_DISTS
    return [n for n in (_req_name(raw) for raw in _iopaint_requires())
            if n and n not in skip]


def is_installed() -> bool:
    """Установлен ли модуль (все зависимости конвейера на месте)."""
    return all(importlib.util.find_spec(m) is not None
               for m in ("iopaint", "torch", "transformers", "timm"))


def nowm_path(path: str) -> str:
    """Имя файла-результата: ``X.ext`` → ``X_nowm.ext`` рядом с оригиналом.

    Формат сохраняется (результат — непрозрачная картинка, как исходник),
    кроме AVIF → PNG (как в закрашивании v0.8.8). Пустая строка — файл
    обрабатывать не нужно: это уже результат (``X_nowm.jpg``) или GIF
    (анимация не для покадрового inpainting'а).
    """
    stem, ext = os.path.splitext(path)
    if stem.endswith(_NOWM_SUFFIX):
        return ""
    low = ext.lower()
    if low in (".gif", ""):
        return ""
    if low == ".avif":
        return stem + _NOWM_SUFFIX + ".png"
    return stem + _NOWM_SUFFIX + ext


def mask_from_boxes(size, boxes, margin: int = MASK_MARGIN):
    """Маска для LaMa из прямоугольников Florence-2 (numpy, uint8).

    Каждый бокс расширяется на ``margin`` px на сторону (аналог dilate
    маски в WatermarkRemover-AI — надпись редко влезает в бокс впритык),
    обрезается по краям картинки; объединение боксов заливается 255.
    """
    import numpy as np   # лениво: numpy приходит с модулем (torch/iopaint)

    w, h = int(size[0]), int(size[1])
    mask = np.zeros((h, w), dtype=np.uint8)
    for box in boxes or ():
        x1, y1, x2, y2 = (int(round(float(v))) for v in box)
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        x1, y1 = max(x1 - margin, 0), max(y1 - margin, 0)
        x2, y2 = min(x2 + margin, w), min(y2 + margin, h)
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255
    return mask


# ---------- кэши моделей: размер и чистка (свои — только свои) ----------


def _torch_hub_checkpoint_dirs() -> list[str]:
    """Где лежит big-lama.pt: torch.hub.get_dir()/checkpoints (+ запасной путь).

    TORCH_HOME могут переносить кэш — сначала пробуем настоящий, затем
    домашний по умолчанию (~/.cache/torch/hub/checkpoints).
    """
    dirs: list[str] = []
    try:
        import torch
        dirs.append(os.path.join(torch.hub.get_dir(), "checkpoints"))
    except Exception:   # noqa: BLE001 — torch не стоит, обойдёмся домашним
        pass
    home = os.path.expanduser("~")
    dirs.append(os.path.join(home, ".cache", "torch", "hub", "checkpoints"))
    return list(dict.fromkeys(dirs))


def model_cache_globs() -> list[tuple[str, str]]:
    """(папка, маска) своих кэшей: LaMa в torch-hub, Florence-2 в HF-hub."""
    hf_hub = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    patterns: list[tuple[str, str]] = [
        (d, "big-lama*.pt") for d in _torch_hub_checkpoint_dirs()
    ]
    patterns.append((hf_hub, "models--microsoft--Florence-2-*"))
    return patterns


def _path_size(path: str) -> int:
    if os.path.isdir(path):
        return _dir_size(path)
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass   # файл успел исчезнуть — не беда
    return total


def models_size() -> int:
    """Сколько байт занимают скачанные модели (для диалога удаления)."""
    import glob

    total = 0
    for d, pattern in model_cache_globs():
        for p in glob.glob(os.path.join(d, pattern)):
            total += _path_size(p)
    return total


def _clear_model_caches() -> int:
    """Вычистить свои кэши моделей; вернуть, сколько байт освобождено."""
    import glob

    freed = models_size()
    for d, pattern in model_cache_globs():
        for p in glob.glob(os.path.join(d, pattern)):
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass
    return freed


def _installed_dists(names) -> set[str]:
    """Какие из названных pip-дистрибуций реально стоят (по метаданным)."""
    try:
        present = {dist.metadata["Name"].lower()
                   for dist in importlib.metadata.distributions()}
    except Exception:   # noqa: BLE001 — метаданные побились, считаем что нет
        return set()
    return {n for n in names if n.lower() in present}


def _dists_to_remove() -> list[str]:
    """Что uninstall отдаст pip: свои дистрибуции (+opencv, если rembg нет).

    К статическому списку добавляются прямые зависимости iopaint из его
    метаданных (gradio, diffusers, peft, fastapi и прочие — v0.8.12):
    раньше install тянул их, а uninstall оставлял в системе.
    """
    own = tuple(dict.fromkeys((*_OWN_DISTS, *_module_dep_names())))
    dists = [d for d in own if d in _installed_dists(own)]
    try:
        from app.ui import rembg_manager
        rembg_alive = rembg_manager.is_installed()
    except Exception:   # noqa: BLE001 — сосед-модуль не критичен для решения
        rembg_alive = False
    if not rembg_alive:
        dists += [d for d in _SHARED_DISTS if d in _installed_dists(_SHARED_DISTS)]
    return dists


# ---------- общий приём: программа без консоли (pythonw, v0.7.14) ----------


def _ensure_stdio() -> None:
    """Подменить отсутствующие sys.stdout/stderr заглушками.

    Тот же приём, что в rembg_manager (v0.7.14): на Windows программа
    живёт без консоли, sys.stdout/stderr равны None, и библиотеки с
    консольным прогрессом (HF-hub/tqdm) падают на записи. None
    подменяется заглушкой, пишущей в никуда; вызов идемпотентен.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                stub = open(os.devnull, "w", encoding="utf-8")   # noqa: SIM115
            except OSError:
                import io
                stub = io.StringIO()
            setattr(sys, name, stub)


def _disable_hf_progress() -> None:
    """Выключить прогресс-бары huggingface_hub (та же консольная беда)."""
    try:
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()
    except Exception:   # noqa: BLE001 — нет хаба/другая версия: не беда
        pass


def _run_pip(args: list[str]) -> tuple[bool, str]:
    """pip текущего Python без окна терминала; вывод — в память.

    Та же механика, что в rembg_manager (v0.7.12): текущий интерпретатор
    (sys.executable) — пакет попадает ровно в то окружение, где работает
    программа; шелла нет (список аргументов), окна нет (CREATE_NO_WINDOW).
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


# ---------- сигналы фоновых задач ----------


class WatermarkSignals(QObject):
    """Все сигналы задач модуля; объект живёт в GUI-потоке (создаёт вьюер)."""

    install_done = Signal(bool, str)         # ok, хвост вывода pip при ошибке
    uninstall_done = Signal(bool, str, int)  # ok, хвост вывода, освобождено МБ
    file_done = Signal(str, str, bool, str)  # путь, результат, ok, ошибка
    batch_done = Signal(int, int)            # с результатом, с ошибками
    model_prepare = Signal(str)              # модели готовятся (первый раз — качаются)
    model_ready = Signal(str)                # модели готовы — пошла обработка


# ---------- задачи: установка / удаление модуля ----------


class InstallTask(QRunnable):
    """Установка модуля в два pip-шага (v0.8.12).

    Шаг 1 — сам iopaint с ``--no-deps``: его метаданные требуют ровно
    Pillow==9.5.0, у которой нет сборок под Python 3.12/3.13 — обычный
    ``pip install iopaint`` падал на сборке старого исходника
    («KeyError: '__version__'»). Шаг 2 — зависимости iopaint из ЕГО ЖЕ
    метаданных (уже без требования Pillow — библиотека программы стоит и
    не перекладывается) плюс ``transformers``/``timm`` (детектор
    Florence-2). Тяжело (torch качает гигабайты) — поэтому в рабочем
    потоке, интерфейс не замирает (принцип rembg_manager, v0.7.12).
    Повторный запуск после сорванного шага 2 безопасен: шаг 1 увидит
    «уже установлен» и не потратит времени.
    """

    def __init__(self, signals: WatermarkSignals) -> None:
        super().__init__()
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        ok, info = _run_pip(["install", "--disable-pip-version-check",
                             "--no-deps", _MAIN_PACKAGE])
        if not ok:
            self.signals.install_done.emit(False, info)
            return
        deps = _module_requirements()
        if not deps:
            # метаданных нет — ставить вслепую нельзя, модуль остался бы
            # без torch/opencv; честный отказ лучше тихой поломки
            self.signals.install_done.emit(
                False, f"{_MAIN_PACKAGE}: нет зависимостей в метаданных")
            return
        ok, info = _run_pip(["install", "--disable-pip-version-check",
                             *deps, *_SIDE_PACKAGES])
        self.signals.install_done.emit(ok, info)


class UninstallTask(QRunnable):
    """``pip uninstall`` дистрибуций модуля + чистка кэшей моделей.

    Модели вычищаются даже если pip рапортует «not installed»: цель —
    после удаления на диске не остаётся ничего своего (принцип rembg).
    """

    def __init__(self, signals: WatermarkSignals) -> None:
        super().__init__()
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        dists = _dists_to_remove()
        if dists:
            ok, info = _run_pip(["uninstall", "-y", *dists])
        else:
            ok, info = True, ""   # уже ничего не стоит — и хорошо
        freed = _clear_model_caches()
        self.signals.uninstall_done.emit(ok, info, freed // (1024 * 1024))


# ---------- конвейер: детекция Florence-2 + закраска LaMa ----------


def _torch_device() -> str:
    """cuda, если есть; иначе cpu (всё считается локально, без облаков)."""
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:   # noqa: BLE001 — без torch cpu-путь всё равно не дойдёт
        return "cpu"


def _load_inpainter(device: str):
    """LaMa из IOPaint в память; возвращает close(rgb, mask) -> rgb.

    IOPaint принимает RGB [H,W,C] + маску [H,W] (255 = закрасить) и
    возвращает BGR (см. iopaint/model/base.py) — оборачиваем обратно в RGB.
    """
    import torch
    from iopaint.model_manager import ModelManager
    from iopaint.schema import HDStrategy, InpaintRequest

    # CROP-стратегия: у больших картинок обрабатываются только районы
    # вокруг маски — фон вне боксов остаётся пиксель в пиксель
    config = InpaintRequest(
        hd_strategy=HDStrategy.CROP,
        hd_strategy_crop_margin=256,
        hd_strategy_crop_trigger_size=1024,
        hd_strategy_resize_limit=2048,
    )
    manager = ModelManager(name="lama", device=torch.device(device))

    def inpaint(rgb, mask):
        bgr = manager(rgb, mask, config)
        return bgr[:, :, ::-1]

    return inpaint


def _make_detector(model_id: str, device: str):
    """Florence-2 в память; возвращает detect(pil) -> [(x1,y1,x2,y2), …].

    Тот же приём, что в WatermarkRemover-AI: задача
    ``<CAPTION_TO_PHRASE_GROUNDING>`` с фразой «watermark».
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        model_id, trust_remote_code=True, torch_dtype=dtype).to(device).eval()
    prompt = f"{_FLORENCE_TASK} {DETECT_PROMPT}"

    def detect(pil_img):
        inputs = processor(text=prompt, images=pil_img,
                           return_tensors="pt").to(device)
        with torch.inference_mode():
            gen = model.generate(input_ids=inputs["input_ids"],
                                 pixel_values=inputs["pixel_values"],
                                 max_new_tokens=1024, do_sample=False,
                                 num_beams=3)
        text = processor.batch_decode(gen, skip_special_tokens=False)[0]
        answer = processor.post_process_generation(
            text, task=_FLORENCE_TASK,
            image_size=(pil_img.width, pil_img.height))
        return [tuple(int(v) for v in box)
                for box in answer.get(_FLORENCE_TASK, {}).get("bboxes", [])]

    return detect


def _load_pipeline(model_id: str):
    """Обе модели в память: (закраска, детекция). Точка подмены в тестах."""
    device = _torch_device()
    return _load_inpainter(device), _make_detector(model_id, device)


def _save_array(rgb, out_path: str) -> None:
    """Записать результат по расширению (JPEG 92 / WEBP 90 — как в программе)."""
    img = Image.fromarray(rgb)
    ext = os.path.splitext(out_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        img.save(out_path, "JPEG", quality=92)
    elif ext == ".webp":
        img.save(out_path, "WEBP", quality=90)
    else:   # PNG / BMP / TIFF
        img.save(out_path)


class RemoveWatermarkTask(QRunnable):
    """Прогнать пачку файлов через конвейер одной сессией.

    Модели грузятся в память один раз на пачку (повторная загрузка на
    каждый файл растянула бы обработку в разы). Чтение исходников и
    запись результатов — здесь же, в рабочем потоке: на сетевом диске
    GUI не замораживается (принцип v0.7.2). Оригиналы никогда не
    перезаписываются: результат — отдельный файл «*_nowm.ext».
    """

    def __init__(self, jobs: list[tuple[str, str]], model: str,
                 signals: WatermarkSignals) -> None:
        super().__init__()
        self.jobs = jobs            # (исходный путь, путь результата)
        self.model = model
        self.signals = signals

    def run(self) -> None:  # рабочий поток
        self._run_inner()

    def _run_inner(self) -> None:
        _ensure_stdio()          # pythonw: без этого падают HF-прогресс-бары
        _disable_hf_progress()
        self.signals.model_prepare.emit(self.model)
        try:
            inpainter, detect = _load_pipeline(self.model)
        except Exception as exc:   # noqa: BLE001 — модуль сломан/не стоит
            for path, _out in self.jobs:
                self.signals.file_done.emit(path, "", False, str(exc))
            self.signals.batch_done.emit(0, len(self.jobs))
            return
        self.signals.model_ready.emit(self.model)
        ok = fail = 0
        for path, out in self.jobs:
            try:
                with Image.open(path) as im:
                    # EXIF-поворот: фото телефонов иначе уедут «головой вбок»
                    rgb = _exif_rgb(im)
                boxes = detect(Image.fromarray(rgb))
                if not boxes:
                    # водяных знаков не нашлось — писать нечего, это не ошибка
                    self.signals.file_done.emit(path, "", True, "")
                    continue
                mask = mask_from_boxes((rgb.shape[1], rgb.shape[0]), boxes)
                result = inpainter(rgb, mask)
                _save_array(result, out)
                ok += 1
                self.signals.file_done.emit(path, out, True, "")
            except Exception as exc:   # noqa: BLE001 — файл/формат любые
                fail += 1
                self.signals.file_done.emit(path, "", False, str(exc))
        self.signals.batch_done.emit(ok, fail)


def _exif_rgb(im: Image.Image):
    """Декодировать PIL-картинку в RGB-массив, развернув по EXIF."""
    from PIL import ImageOps
    import numpy as np

    return np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
