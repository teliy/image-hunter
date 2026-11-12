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
принцип, что при удалении: «numpy/Pillow бережены»). Туда же не попадает
``gradio`` (v0.8.13) — веб-морда iopaint, конвейер её не импортирует, а
её пин ``numpy~=1.0`` не выполняется на Python 3.13+: у numpy 1.x нет
готовых сборок, pip собирал исходник и падал (репорт: «при установке
модуля такая ошибка», хвост pip про numpy). Вместе с зависимостями
ставятся ``transformers`` и ``timm`` (детектор Florence-2) и шимы для
новых Python (v0.8.13): ``standard-imghdr`` — iopaint импортирует
``imghdr``, удалённый из стандартной библиотеки в Python 3.13, и
``setuptools`` — pinned diffusers импортирует ``distutils.util``, живущий
только через setuptools. torch — самый тяжёлый гость, счёт на гигабайты.
Модели скачиваются при первом запуске: LaMa (~200 МБ) — в кэш torch-hub
(iopaint считает модель доступной только по файлу на диске, поэтому
``LaMa.download()`` вызывается до ``ModelManager``), Florence-2
(base ~500 МБ / large ~1,6 ГБ) — в кэш Hugging Face. «Удалить модуль»
вычищает и пакеты, и кэши моделей — но только СВОИ: big-lama.pt и
Florence-2; кэши других моделей (и общие библиотеки numpy/pillow, нужные
программе и rembg, и шимы окружения) не трогаются.

Детекция с v0.8.14 — две задачи Florence-2 вместо одной (репорт:
«Знаки не удалил. Получилась какая-то ерунда.» — tiled-знак «НАТАР»
на каталоге запчастей стал кашей на весь кадр). Первичной стала
``<OCR_WITH_REGION>``: точные ПОВЁРНУТЫЕ четырёхугольники надписей с
фильтром по медианной насыщенности HSV — серый полупрозрачный знак
остаётся, цветной текст этикетки товара не закрашивается. Знак без
текста (логотип) ловит резервная ``<CAPTION_TO_PHRASE_GROUNDING>`` с
фразой «watermark» — только если OCR не нашёл ничего. Живой замер
(Florence-2-base, картинка пользователя): grounding отдавал 3–4
гигантских бокса на 18–100% кадра → маска 100% → LaMa «достроил» весь
кадр; OCR двух проходов (оригинал + авто-контраст) нашёл 46 квадов
знака (медианная насыщенность 0–25) против четырёх надписей этикетки
(~180), 13 бледных экземпляров видны только на усиленной копии.
Предохранители: боксы-гиганты (больше четверти кадра) отбрасываются,
а если итоговая маска накрыла больше половины кадра — файл честно
помечается ошибкой, картинка не портится.

Здесь только механика; все надписи (i18n) и журнальные события — в
local_viewer, который этими задачами распоряжается. Тяжёлые зависимости
импортируются лениво: пока модуль не установлен, файл безопасно
импортируется в любом процессе (принцип rembg_manager, v0.7.12).

Обновление установленного модуля — UpdateTask (v0.8.15, пожелание: «Если
разработчики florence и lama обновят версию, imagehunter этого не узнает?
Нужно добавить возможность обновлять установленные модули»). Пакеты
(iopaint, transformers, timm) сверяются с PyPI, модели — с их первоисточниками:
ревизия Florence-2 в кэше Hugging Face — с актуальной на хабе, big-lama —
размером файла с релизом. Обновляются теми же безопасными механизмами,
что и установка; проверка моделей не фатальна — пакеты обновляются,
неудача докладывается в итоге.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.core.i18n import tr
from app.core.updates import is_newer, pypi_latest
from PySide6.QtCore import QObject, QRunnable, Signal

# фраза для Florence-2: что искать на картинке (как в WatermarkRemover-AI)
DETECT_PROMPT = "watermark"
_FLORENCE_TASK = "<CAPTION_TO_PHRASE_GROUNDING>"
_OCR_TASK = "<OCR_WITH_REGION>"        # повёрнутые четырёхугольники надписей

# предохранители детекции (v0.8.14, живой замер — репорт «Знаки не
# удалил. Получилась какая-то ерунда», tiled-знак «НАТАР» на 1024x683):
# * бокс больше четверти кадра — не знак, а галлюцинация grounding'а на
#   tiled-знаках (живые мусорные боксы: 100%, 39%, 28%, 18% кадра;
#   настоящий экземпляр знака — 1–10%);
# * медианная насыщенность HSV внутри OCR-квада: серый полупрозрачный
#   знак даёт 0–25, цветной текст этикетки товара ~180 — порог между
#   ними десятикратный, квад выше порога не закрашивается;
# * маска, накрывшая больше 60% кадра (на репорте было 100%), — это не
#   «удаление знака», а уничтожение картинки: файл помечается ошибкой,
#   оригинал не трогается.
_GIANT_FRAC = 0.25
_OCR_MAX_SAT = 60.0
_MAX_MASK_COVER = 0.6

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
# из его же метаданных, уже без требования Pillow и gradio
# (_module_requirements)
_MAIN_PACKAGE = "iopaint"
_SIDE_PACKAGES = ("transformers", "timm")
# весь конвейер для строки версий в меню «Модули» (v0.8.17) и сверки с PyPI
PIPELINE_PACKAGES = (_MAIN_PACKAGE, *_SIDE_PACKAGES)

# шимы окружения для новых Python (v0.8.13): стандартная библиотека
# похудела, а pinned-зависимости iopaint про это не знают —
# * standard-imghdr: iopaint/helper.py делает «import imghdr», которого
#   в Python 3.13+ больше нет (модуль 300 строк, формат файлов);
# * setuptools: pinned diffusers импортирует «distutils.util» — с 3.12
#   distutils живёт только через setuptools.
# При удалении НЕ вычищаются (как numpy/Pillow — общее достояние:
# setuptools нужен половине экосистемы, imghdr-шим на 3.12 и так
# затеняется настоящим модулем из стандартной библиотеки)
_ENV_SHIMS = ("standard-imghdr", "setuptools")

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


# что НЕ ставится из зависимостей iopaint: pillow — библиотека самой
# программы (v0.8.12); gradio — веб-морда iopaint (v0.8.13), наш конвейер
# её не импортирует (в iopaint 1.6.0 gradio трогает только web_config.py),
# а её пин «numpy~=1.0» не выполняется на Python 3.13+ — у numpy 1.x нет
# готовых сборок, pip лезет собирать исходник и валит установку (репорт:
# «при установке модуля такая ошибка»); заодно с numpy 1.x часто тянулась
# и старая opencv, которой тоже нет сборок под 3.13
_INSTALL_SKIP = ("pillow", "gradio")


def _module_requirements() -> list[str]:
    """Зависимости iopaint для pip: его же список без Pillow и gradio.

    Pillow (v0.8.12) — библиотека программы, стоит и не перекладывается.
    gradio (v0.8.13) — веб-морда iopaint, конвейеру не нужна; её пин
    «numpy~=1.0» на Python 3.13+ собирал numpy из исходников и валил
    установку (репорт: «при установке модуля такая ошибка»). Всё
    остальное — как сказал сам iopaint (маркеры окружения сохраняются,
    pip сам их оценит).
    """
    return [raw.strip() for raw in _iopaint_requires()
            if _req_name(raw) and _req_name(raw) not in _INSTALL_SKIP]


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
    исключены. gradio остаётся в списке удаления, хотя на установку не
    идёт (v0.8.13): старые установки могли его притащить — pip честно
    пропустит отсутствующий («Skipping … not installed»). Шимы окружения
    (_ENV_SHIMS) тоже не вычищаются — общее достояние. Статический
    _OWN_DISTS остаётся запасом на случай, когда метаданных уже нет
    (iopaint удалён).
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


def sel_result_path(path: str) -> str:
    """Имя файла-результата убирания ПО ВЫДЕЛЕНИЮ (v0.8.22).

    Пожелание: «сделай возможность удалять ватермарки из выделения на
    картинке». База та же, что у ``nowm_path`` — ``X.ext`` →
    ``X_nowm.ext`` (AVIF → PNG; GIF/без расширения — не обрабатывать),
    но у выделения есть сценарий, которого у пачки нет: пользователь
    чистит остатки знака на УЖЕ готовом результате — значит, входом
    бывает ``X_nowm.ext``, и отказывать нельзя. Поэтому: вход ``X_nowm.*``
    не отбраковывается, а результат получает следующее свободное имя
    ``X_nowm-1.ext``, ``X_nowm-2.ext``… (проверка прямо перед стартом
    задачи, приём _free_crop_name v0.8.7 — чужие файлы не затираются).
    """
    stem, ext = os.path.splitext(path)
    low = ext.lower()
    if low in (".gif", ""):
        return ""
    base = stem if stem.endswith(_NOWM_SUFFIX) else stem + _NOWM_SUFFIX
    out_ext = ".png" if low == ".avif" else ext
    # вход — уже «_nowm»: имя результата обязано отличаться от входного
    # файла (он и есть base+ext), поэтому нумерация начинается с −1
    n = 1 if base == stem else 0
    candidate = f"{base}{out_ext}" if n == 0 else f"{base}-{n}{out_ext}"
    while os.path.lexists(candidate):
        n += 1
        candidate = f"{base}-{n}{out_ext}"
    return candidate


def _poly_area(poly) -> float:
    """Площадь полигона (формула шнурования); точки — пары (x, y)."""
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _boxes_to_polys(boxes, w: int, h: int) -> list[list[tuple[float, float]]]:
    """Прямоугольники (x1, y1, x2, y2) → полигоны из 4 углов.

    Перевёрнутые координаты чинятся, всё обрезается по краям картинки.
    """
    polys = []
    for box in boxes or ():
        x1, y1, x2, y2 = (float(v) for v in box)
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        x1, x2 = max(x1, 0.0), min(x2, float(w))
        y1, y2 = max(y1, 0.0), min(y2, float(h))
        polys.append([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
    return polys


def _giant_polys(polys, w: int, h: int) -> list[list[tuple[float, float]]]:
    """Полигон больше _GIANT_FRAC кадра — не знак, а галлюцинация (v0.8.14).

    Живой замер: grounding на tiled-знаке отдавал боксы на 100%, 39% и
    28% кадра — каждый из них накрыл бы товар целиком.
    """
    frame = float(w * h)
    return [p for p in polys if 0.0 < _poly_area(p) / frame <= _GIANT_FRAC]


def _ocr_polys(hsv, data, w: int, h: int) -> list[list[tuple[float, float]]]:
    """Квады <OCR_WITH_REGION> → полигоны знаков; цветной текст отсекается.

    Квад — повёрнутый четырёхугольник надписи [x1, y1, … x4, y4].
    Фильтр насыщенности (v0.8.14): в прямоугольнике квада считается
    МЕДИАННАЯ насыщенность HSV — у серого полупрозрачного знака она
    0–25 даже поверх цветной коробки, у текста этикетки товара ~180;
    квады выше _OCR_MAX_SAT — не знак и не закрашиваются.
    """
    import numpy as np

    polys = []
    for q in (data or {}).get("quad_boxes", []):
        poly = [(min(max(float(q[i]), 0.0), float(w)),
                 min(max(float(q[i + 1]), 0.0), float(h)))
                for i in range(0, len(q) - 1, 2)]
        if len(poly) < 3:
            continue
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        x1, y1 = int(min(xs)), int(min(ys))
        x2, y2 = int(max(xs)), int(max(ys))
        region = hsv[max(y1, 0):max(y2, 0), max(x1, 0):max(x2, 0), 1]
        if region.size == 0:
            continue
        if float(np.median(region)) > _OCR_MAX_SAT:
            continue   # цветная надпись (этикетка товара) — не трогаем
        polys.append(poly)
    return _giant_polys(polys, w, h)


def mask_from_polys(size, polys, margin: int = MASK_MARGIN):
    """Маска для LaMa из полигонов детекции (numpy, uint8).

    Полигоны заливаются 255 (PIL polygon — точные повёрнутые квадры
    OCR вместо обрамляющих прямоугольников), затем маска расширяется
    на ``margin`` px фильтром максимума (аналог dilate в
    WatermarkRemover-AI — надпись редко влезает в рамку впритык);
    для прямоугольников результат совпадает с прежним раздуванием
    каждого бокса, для повёрнутых квадров — заметно точнее.
    """
    import numpy as np   # лениво: numpy приходит с модулем (torch/iopaint)

    w, h = int(size[0]), int(size[1])
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)
    for poly in polys or ():
        pts = [(min(max(float(x), 0.0), float(w)),
                min(max(float(y), 0.0), float(h))) for x, y in poly]
        if len(pts) >= 3:
            draw.polygon(pts, fill=255)
    if margin > 0 and polys:
        img = img.filter(ImageFilter.MaxFilter(2 * int(margin) + 1))
    return np.asarray(img, dtype=np.uint8)


def mask_from_boxes(size, boxes, margin: int = MASK_MARGIN):
    """Маска для LaMa из прямоугольников (numpy, uint8) — прежняя геометрия.

    Каждый бокс расширяется на ``margin`` px на сторону, обрезается по
    краям картинки; объединение боксов заливается 255. Отдельная от
    полигонов реализация держит точную прежнюю геометрию (срез numpy
    не включает правый/нижний край — живые тесты на неё опираются);
    в конвейере v0.8.14 прямоугольники grounding'а приходят сюда через
    _boxes_to_polys → mask_from_polys, а эта функция остаётся для
    совместимости и тестов.
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


# ---------- обновление модуля: проверка пакетов и моделей (v0.8.15) ----------

# API Hugging Face: актуальная ревизия (commit) репозитория модели
HF_API_URL = "https://huggingface.co/api/models/{repo}"
# запасной адрес big-lama — настоящий берётся из установленного iopaint
# (_lama_url); константа совпадает с его дефолтом (iopaint/model/lama.py)
LAMA_MODEL_URL = ("https://github.com/Sanster/models/releases/download/"
                  "add_big_lama/big-lama.pt")


def installed_version(name: str) -> str:
    """Версия установленной pip-дистрибуции; "" — нет пакета/метаданных."""
    try:
        return importlib.metadata.version(name)
    except Exception:   # noqa: BLE001 — PackageNotFoundError и битые метаданные
        return ""


def florence_revision(repo: str) -> str:
    """Ревизия (commit) Florence-2 в локальном кэше HF; "" — не качалась.

    Публичная обёртка _florence_cached_sha для меню «Модули» (v0.8.17):
    строка «Модели» показывает, какая ревизия выбранного детектора
    скачана — у модели версии нет, ревизия и есть её версия.
    """
    return _florence_cached_sha(repo)


def lama_size() -> int:
    """Размер скачанного big-lama.pt в байтах; 0 — модель не скачана.

    Для строки «Модели» в меню «Модули» (v0.8.17): у модели версии нет —
    о её состоянии говорит сам факт скачивания и размер файла.
    """
    path = lama_file()
    return os.path.getsize(path) if path else 0


def _hf_hub_cache() -> str:
    """Кэш Hugging Face с учётом HF_HUB_CACHE/HF_HOME (как у самого hf-hub)."""
    hub = os.environ.get("HF_HUB_CACHE")
    if not hub:
        home = os.environ.get("HF_HOME")
        hub = (os.path.join(home, "hub") if home
               else os.path.join(os.path.expanduser("~"),
                                 ".cache", "huggingface", "hub"))
    return hub


def _florence_cached_sha(repo: str) -> str:
    """Ревизия (commit) Florence-2 в локальном кэше HF; "" — не качалась.

    hf-hub пишет актуальную скачанную ревизию в refs/main кэша модели —
    сверка с хабом отвечает на вопрос «вышла ли новая версия».
    """
    ref = os.path.join(_hf_hub_cache(), "models--" + repo.replace("/", "--"),
                       "refs", "main")
    try:
        with open(ref, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def hf_latest_sha(repo: str) -> str:
    """Актуальная ревизия (commit) модели на Hugging Face; "" — нет связи."""
    try:
        req = urllib.request.Request(
            HF_API_URL.format(repo=repo), headers={"User-Agent": "ImageHunter"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read(1 << 20).decode("utf-8", "replace"))
        return str(data.get("sha") or "")
    except (OSError, ValueError):
        return ""


def lama_file() -> str:
    """Путь к скачанному big-lama.pt; "" — модель ещё не скачивалась."""
    import glob

    for d, pattern in model_cache_globs():
        if "big-lama" not in pattern:
            continue
        for p in sorted(glob.glob(os.path.join(d, pattern))):
            if os.path.isfile(p):
                return p
    return ""


def _lama_url() -> str:
    """Настоящий адрес big-lama из установленного iopaint (у него и md5)."""
    try:
        from iopaint.model.lama import LAMA_MODEL_URL as url
        return url
    except Exception:   # noqa: BLE001 — iopaint не импортируется, берём дефолт
        return LAMA_MODEL_URL


def remote_content_length(url: str) -> int:
    """Размер файла по HEAD-запросу; 0 — узнать не удалось."""
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "ImageHunter"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except (OSError, ValueError):
        return 0


def _brief(exc: Exception) -> str:
    """Короткая причина из исключения — для строки итога обновления."""
    text = (str(exc).strip().splitlines() or [""])[0]
    return text[:160] if text else type(exc).__name__


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
    update_done = Signal(bool, str, str)     # ok, что изменилось ("" — ничего), ошибка
    file_done = Signal(str, str, bool, str)  # путь, результат, ok, ошибка
    batch_done = Signal(int, int)            # с результатом, с ошибками
    model_prepare = Signal(str)              # модели готовятся (первый раз — качаются)
    model_ready = Signal(str)                # модели готовы — пошла обработка
    # процесс в строке статуса (v0.8.20, пожелание: «видеть в строке
    # статуса процесс и/или статус работы модулей, особенно модуля
    # удаления ватермарков»)
    file_start = Signal(str, int)            # путь, номер файла в пачке (с 1)
    phase = Signal(str, str, int)            # путь, код фазы, счётчик (или -1)
    model_dl_start = Signal(str, int)        # модель, всего байт (0 — неизвестно)
    model_dl_progress = Signal(int, int)     # скачано байт, всего байт


# активная задача с объектом сигналов: скачивания моделей докладывают ей
# (тот же приём, что в rembg_manager — пачка ставит репортера на время
# работы, глубоко лежащий код дергает _dl_emit, не зная про сигналы)
_DL_REPORTER: "WatermarkSignals | None" = None


def _dl_emit(ev: str, *args) -> None:
    """Доложить о ходе работы активной задаче (если она есть)."""
    rep = _DL_REPORTER
    if rep is None:
        return
    try:
        getattr(rep, ev).emit(*args)
    except RuntimeError:
        pass   # объект сигналов уже удалён — не беда


# ---------- задачи: установка / удаление модуля ----------


class InstallTask(QRunnable):
    """Установка модуля в два pip-шага (v0.8.12, список шага 2 — v0.8.13).

    Шаг 1 — сам iopaint с ``--no-deps``: его метаданные требуют ровно
    Pillow==9.5.0, у которой нет сборок под Python 3.12/3.13 — обычный
    ``pip install iopaint`` падал на сборке старого исходника
    («KeyError: '__version__'»). Шаг 2 — зависимости iopaint из ЕГО ЖЕ
    метаданных (без Pillow — библиотека программы, и без gradio —
    веб-моды, чей пин «numpy~=1.0» на Python 3.13+ валил установку
    сборкой numpy из исходников) плюс ``transformers``/``timm`` (детектор
    Florence-2) и шимы окружения для новых Python (_ENV_SHIMS). Тяжело
    (torch качает гигабайты) — поэтому в рабочем потоке, интерфейс не
    замирает (принцип rembg_manager, v0.7.12). Повторный запуск после
    сорванного шага 2 безопасен: шаг 1 увидит «уже установлен» и не
    потратит времени.
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
                             *deps, *_SIDE_PACKAGES, *_ENV_SHIMS])
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


class UpdateTask(QRunnable):
    """Проверить и обновить установленный модуль (v0.8.15).

    Пожелание: «Если разработчики florence и lama обновят версию,
    imagehunter этого не узнает? Нужно добавить возможность обновлять
    установленные модули».

    * **Пакеты** (iopaint, transformers, timm) сверяются с PyPI; что
      новее — обновляется тем же безопасным конвейером, что и установка:
      iopaint с ``--no-deps`` (его пин Pillow==9.5.0 не выполняется на
      новых Python — v0.8.12), затем зависимости из УЖЕ обновлённых
      метаданных без Pillow/gradio + transformers/timm + шимы окружения
      (v0.8.13). ``--upgrade`` с дефолтной стратегией pip only-if-needed
      двигает только пакеты модуля и то, что не удовлетворяет новым
      требованиям, — numpy/Pillow самой программы не трогаются. Успех
      pip не принимается на веру (v0.8.17): каждая цель сверяется по
      факту, застрявшая — одиночным ``pip install --upgrade``, а итог
      называет версии, которые реально стоят.
    * **Florence-2**: ревизия в кэше HF (refs/main) сверяется с API хаба;
      отличается — ``snapshot_download`` докачивает только изменившиеся
      файлы (модель у hf-hub попадает в кэш та же, что грузит
      from_pretrained).
    * **big-lama**: размер локального файла сверяется с релизом; отличается —
      файл перекачивается штатным ``LaMa.download()`` (он же проверит md5).

    Пакеты, версию которых сверить не удалось (pypi.org недоступен) —
    честный отказ: обновлять вслепую нельзя. Недоступность проверки
    МОДЕЛЕЙ не фатальна: пакеты обновляются, а неудача докладывается
    в итоге — модуль остаётся рабочим.
    """

    def __init__(self, signals: WatermarkSignals, model: str) -> None:
        super().__init__()
        self.signals = signals
        self.model = model          # выбранный детектор (каким пользуются)

    def run(self) -> None:  # рабочий поток
        changes: list[str] = []     # что обновилось — для итога
        fails: list[str] = []       # что проверить/обновить не удалось
        pkgs_touched = False        # pip что-то двигал — нужен перезапуск
        names = (_MAIN_PACKAGE, *_SIDE_PACKAGES)
        installed = {n: installed_version(n) for n in names}
        unknown = [n for n, v in installed.items() if not v]
        if unknown:
            self.signals.update_done.emit(
                False, "",
                f"{unknown[0]}: не удалось определить установленную версию")
            return
        latest = {n: pypi_latest(n) for n in names}
        dead = [n for n, v in latest.items() if not v]
        if dead:
            self.signals.update_done.emit(
                False, "", tr("viewer.wm_update_pypi_fail", name=dead[0]))
            return
        newer = [n for n in names if is_newer(latest[n], installed[n])]
        if newer:
            ok, info = _run_pip(["install", "--disable-pip-version-check",
                                 "--no-deps", "--upgrade", _MAIN_PACKAGE])
            if ok:
                deps = _module_requirements()   # метаданные УЖЕ новых iopaint
                if not deps:
                    # как в InstallTask (v0.8.12): вслепую нельзя —
                    # модуль остался бы без torch/opencv
                    ok, info = False, f"{_MAIN_PACKAGE}: нет зависимостей в метаданных"
                else:
                    ok, info = _run_pip([
                        "install", "--disable-pip-version-check", "--upgrade",
                        *deps, *_SIDE_PACKAGES, *_ENV_SHIMS])
            if not ok:
                self.signals.update_done.emit(False, "", info)
                return
            # pip отчитался успехом, но это ещё не значит, что каждая цель
            # сдвинулась (репорт v0.8.17: диалог обещал «transformers
            # 4.48.3 → 5.22.2», после перезапуска версия была прежней).
            # В общей команде резолвер мог откатить пакет под чужое
            # требование, «only-if-needed» — оставить уже-удовлетворённый,
            # а самая свежая версия могла не подойти этому Python. Сверяем
            # каждую цель ПО ФАКТУ; застрявшую обновляем одиночным pip —
            # без соседей резолверу не с кем откатываться; не сдвинулась
            # и там — честная неудача вместо ложного «обновилось».
            for n in newer:
                ver = installed_version(n)
                if is_newer(latest[n], ver):
                    ok, info = _run_pip(["install",
                                         "--disable-pip-version-check",
                                         "--upgrade", n])
                    ver = installed_version(n)
                if ver and not is_newer(latest[n], ver):
                    changes.append(f"{n} {installed[n]} → {ver}")
                    pkgs_touched = True
                else:
                    fails.append(tr("viewer.wm_update_stuck", name=n,
                                    ver=ver or installed[n]))
        # Florence-2 выбранного детектора: ревизия кэша против хаба
        short = self.model.split("/")[-1]
        remote = hf_latest_sha(self.model)
        if remote:
            cached = _florence_cached_sha(self.model)
            if cached and cached != remote:
                try:
                    _ensure_stdio()            # pythonw: HF-прогресс-бары
                    _disable_hf_progress()
                    from huggingface_hub import snapshot_download
                    snapshot_download(self.model)   # только изменённые файлы
                    changes.append(tr("viewer.wm_update_model", model=short))
                except Exception as exc:   # noqa: BLE001 — сеть/диск любые
                    fails.append(tr("viewer.wm_update_model_fail", model=short,
                                    info=_brief(exc)))
        else:
            fails.append(tr("viewer.wm_update_model_fail", model=short,
                            info="huggingface.co"))
        # big-lama: размер локального файла против релиза
        local = lama_file()
        if local:
            size = remote_content_length(_lama_url())
            if size <= 0:
                fails.append(tr("viewer.wm_update_lama_fail", info="github.com"))
            elif size != os.path.getsize(local):
                try:
                    os.remove(local)
                    from iopaint.model.lama import LaMa
                    LaMa.download()            # скачает свежий и проверит md5
                    changes.append(tr("viewer.wm_update_lama"))
                except Exception as exc:   # noqa: BLE001 — сеть/диск любые
                    fails.append(tr("viewer.wm_update_lama_fail",
                                    info=_brief(exc)))
        if changes or fails:
            what = ", ".join(changes + fails)
            if pkgs_touched:
                # пакеты обновились — в этой сессии могли остаться старые
                # модули в памяти (импортируются лениво, но однажды
                # импортированный не перечитывается)
                what += ". " + tr("viewer.wm_update_restart")
        else:
            what = tr("viewer.wm_update_nothing", pkgs=", ".join(
                f"{n} {installed[n]}" for n in names))
        self.signals.update_done.emit(True, what, "")


# ---------- конвейер: детекция Florence-2 + закраска LaMa ----------


def _torch_device() -> str:
    """cuda, если есть; иначе cpu (всё считается локально, без облаков)."""
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:   # noqa: BLE001 — без torch cpu-путь всё равно не дойдёт
        return "cpu"


def _md5_of(path: str) -> str:
    """MD5 файла потоково (модели — сотни мегабайт)."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _stream_lama() -> bool:
    """Скачать big-lama сами, с докладом прогресса; True — успех.

    Штатный ``LaMa.download()`` качает через torch.hub с прогрессом в
    консоли, которой у pythonw-версии нет: пользователь сидит в тишине,
    пока идут ~200 МБ. Здесь свой потоковый download (тот же приём, что
    у rembg — v0.7.15): каждые ~0,3 с сигнал model_dl_progress доезжает
    до статус-бара. Файл пишется в «.part» и переименовывается только
    после проверки MD5 (он же — критерий успеха); при любой неудаче
    «.part» подчищается и возвращается False — вызывающий код отдаёт
    скачивание штатному ``LaMa.download()`` (он и путь, и md5 знает
    сам, наша цель — только прогресс). Точка расчёта пути и md5 —
    метаданные установленного iopaint (тот же адрес, что у него).
    """
    try:
        from iopaint.helper import get_cache_path_by_url
        from iopaint.model.lama import LAMA_MODEL_MD5, LAMA_MODEL_URL
        target = get_cache_path_by_url(LAMA_MODEL_URL)
    except Exception:                       # noqa: BLE001 — iopaint не стоит: не наша забота
        return False
    if os.path.exists(target):
        return True                         # уже скачан (гонки не страшны)
    import requests   # лениво: нужен только на этом пути

    tmp = target + ".part"
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        total = remote_content_length(LAMA_MODEL_URL)
        _dl_emit("model_dl_start", "big-lama", total)
        with requests.get(LAMA_MODEL_URL, stream=True, timeout=(10, 120),
                          headers={"User-Agent": "ImageHunter"}) as r:
            r.raise_for_status()
            if total <= 0:
                total = int(r.headers.get("Content-Length") or 0)
                if total:
                    _dl_emit("model_dl_start", "big-lama", total)
            done, last = 0, 0.0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(65536):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if total > 0 and now - last >= 0.3:   # не заваливаем GUI-очередь
                        last = now
                        _dl_emit("model_dl_progress", done, total)
        if total > 0:
            _dl_emit("model_dl_progress", done, total)   # финальные 100 %
        if LAMA_MODEL_MD5 and _md5_of(tmp) != LAMA_MODEL_MD5:
            os.remove(tmp)
            return False                        # битая скачка — штатный путь перепроверит
        os.replace(tmp, target)
        return True
    except Exception:                           # noqa: BLE001 — сеть/диск любые
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def _ensure_lama_downloaded() -> None:
    """big-lama.pt должен лежать на диске ДО ModelManager (v0.8.13).

    iopaint считает модель доступной только по файлу в кэше torch-hub
    (scan_models → LaMa.is_downloaded): без скачивания ModelManager
    встречает «lama» как неизвестную модель — «Unsupported model: lama.
    Available models: ['cv2']» — и все файлы падали бы с этой ошибкой на
    первом же запуске. Качаем сами с прогрессом в статус-бар (v0.8.20);
    не вышло — штатный ``LaMa.download()`` (он же проверит md5). Уже
    скачанный не перекачивается.
    """
    from iopaint.model.lama import LaMa

    if not LaMa.is_downloaded():
        if not _stream_lama():
            LaMa.download()


# ---------- прогресс скачивания Florence-2 (HF) в статус-бар (v0.8.20) ----------

# файлы меньше этого размера (config.json, токенизаторы) — без прогресса:
# они качаются за мгновение, а HEAD-запрос на каждый дороже самих файлов
_HF_BIG_BYTES = 10 * (1 << 20)
_HF_PATCHED = False


def _incomplete_bytes(blobs_dir: str) -> int:
    """Сколько байт лежит в недокачанных «*.incomplete» кэша hf-hub.

    hf-hub качает во временный файл «<etag>.incomplete» в blobs/ модели
    и переименовывает по завершении — размер недокачанного и есть честный
    прогресс. Папки нет (кэш пуст/другое место) — 0.
    """
    try:
        total = 0
        for name in os.listdir(blobs_dir):
            if name.endswith(".incomplete"):
                try:
                    total += os.path.getsize(os.path.join(blobs_dir, name))
                except OSError:
                    pass   # файл успел исчезнуть/переименоваться — не беда
        return total
    except OSError:
        return 0


def _watch_hf_blob(repo_id: str, filename: str, stop: threading.Event) -> None:
    """Watchdog скачивания: размер *.incomplete → сигналы прогресса.

    Сам hf-hub-качальник трогать нельзя (кэш blobs/snapshots/refs — его
    семантика), поэтому следим со стороны: раз в 0,3 с считаем размер
    недокачанных файлов blobs/ выбранного репозитория и докладываем.
    Тотал — из HEAD-запроса (метаданные файла на хабе); для мелких файлов
    (< _HF_BIG_BYTES) прогресса нет — они мгновенные. Работает с любой
    версией hf-hub: не зависит от tqdm_class/прогресс-баров хаба.
    """
    try:
        from huggingface_hub import get_hf_file_metadata, hf_hub_url
        url = hf_hub_url(repo_id, filename)
        total = int(get_hf_file_metadata(url).size or 0)
    except Exception:                       # noqa: BLE001 — сеть/версия хаба любые
        total = 0
    if total and total < _HF_BIG_BYTES:
        return                              # мелочь — молча
    short = repo_id.split("/")[-1]
    _dl_emit("model_dl_start", short, total)
    if not total:
        return                              # без тотала тикать нечестно
    blobs = os.path.join(_hf_hub_cache(),
                         "models--" + repo_id.replace("/", "--"), "blobs")
    last = -1
    while not stop.wait(0.3):
        done = _incomplete_bytes(blobs)
        if done and done != last:
            last = done
            _dl_emit("model_dl_progress", min(done, total), total)


def _patch_hf_downloads() -> None:
    """Обернуть hf_hub_download: доклад о прогрессе во время пачки.

    Florence-2 грузится через transformers → hf_hub_download; тот при
    первом запуске качает ~0,5 ГБ (base) — раньше молча. Обёртка ставится
    ОДИН раз за жизнь процесса и ДО импорта transformers: тот делает
    «from huggingface_hub import hf_hub_download» при импорте, и должен
    увидеть обёртку. Обёртка лишь запускает watchdog на время качания;
    без активной пачки (репортера нет) — прямой проход, поведение не
    меняется. Приём тот же, что у pooch в rembg_manager (v0.7.15).
    """
    global _HF_PATCHED
    if _HF_PATCHED:
        return
    try:
        import huggingface_hub
        orig = huggingface_hub.hf_hub_download
    except Exception:                       # noqa: BLE001 — перехватывать нечего
        return

    def patched(repo_id, filename, *args, **kwargs):
        rep = _DL_REPORTER
        if rep is None:
            return orig(repo_id, filename, *args, **kwargs)
        stop = threading.Event()
        watch = threading.Thread(target=_watch_hf_blob,
                                 args=(repo_id, filename, stop), daemon=True)
        watch.start()
        try:
            return orig(repo_id, filename, *args, **kwargs)
        finally:
            stop.set()
            watch.join(timeout=2.0)

    huggingface_hub.hf_hub_download = patched
    _HF_PATCHED = True


def _load_inpainter(device: str):
    """LaMa из IOPaint в память; возвращает close(rgb, mask) -> rgb.

    IOPaint принимает RGB [H,W,C] + маску [H,W] (255 = закрасить) и
    возвращает BGR (см. iopaint/model/base.py) — оборачиваем обратно в RGB.
    """
    import torch
    from iopaint.model_manager import ModelManager
    from iopaint.schema import HDStrategy, InpaintRequest

    _ensure_lama_downloaded()

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


def _ocr_passes(pil_img, ask):
    """Квадры OCR с оригинала И с контраст-усиленной копии (v0.8.14).

    Знак полупрозрачный: самые бледные экземпляры (по краям кадра, поверх
    яркого фона) OCR на оригинале не видит — живой замер на репорте
    «Знаки не удалил…»: 35 квадов с оригинала против 46 с копии после
    ``ImageOps.autocontrast(cutoff=1)``, 13 экземпляров найдены только
    на усиленной. Пропущенные экземпляры опасны вдвойне: их пиксели
    остаются в картинке, и LaMa использует их как контекст — достраивает
    призраки знака внутри закрашенных дыр. Сатурационный фильтр (_ocr_polys)
    считается по ТЕЙ ЖЕ копии, что подана в OCR: серый знак остаётся
    серым при любом контрасте, цветная этикетка — цветной.
    """
    import numpy as np

    polys = []
    for im in (pil_img, ImageOps.autocontrast(pil_img, cutoff=1)):
        hsv = np.asarray(im.convert("HSV"))
        polys += _ocr_polys(hsv, ask(im).get(_OCR_TASK, {}),
                            im.width, im.height)
    return polys


def _merge_detection(ocr: list, grounding: list) -> list:
    """Что закрашивать: полигоны OCR, а без текста — grounding (v0.8.14).

    Объединять нельзя: на tiled-знаке grounding отдаёт мусорные
    гигантские боксы рядом с честными квадрами OCR, и маска снова
    накрывает кадр. OCR нашёл надписи — ему и верим; не нашёл — знак,
    возможно, логотип без текста, тогда и подключается grounding.
    """
    return ocr or grounding


def _make_detector(model_id: str, device: str):
    """Florence-2 в память; возвращает detect(pil) -> [полигон, …].

    Перед импортом transformers включается доклад о скачивании
    (_patch_hf_downloads, v0.8.20): первая загрузка модели — сотни
    МБ, без этого они шли молча.

    Полигон — список точек [(x, y), …]: OCR отдаёт повёрнутые
    четырёхугольники надписей, grounding — прямоугольники. Сначала
    ``<OCR_WITH_REGION>`` в два прохода (_ocr_passes): по оригиналу и по
    контраст-усиленной копии — бледные экземпляры знака иначе ускользают,
    а их пиксели уводят LaMa в призраки; каждый квад
    проходит фильтр насыщенности (_ocr_polys): он вырезает именно
    надписи знака и щадит цветной текст этикетки; пусто —
    ``<CAPTION_TO_PHRASE_GROUNDING>`` «watermark» (знак-лого, как в
    WatermarkRemover-AI), с отбраковкой боксов-гигантов (_giant_polys).
    Живой замер Florence-2-base на репорте «Знаки не удалил. Получилась
    какая-то ерунда» (tiled-знак «НАТАР»): grounding возвращал 3–4
    бокса на 18–100% кадра и маска из них накрывала всю картинку;
    OCR двух проходов нашёл 46 квадов (33 + 13 бледных только на
    усиленной копии), 4 квада этикетки отсечены насыщенностью (~180
    против 0–25 у знака).
    """
    import numpy as np
    import torch

    _patch_hf_downloads()   # ДО импорта transformers: тот свяжет обёртку при импорте
    from transformers import AutoModelForCausalLM, AutoProcessor

    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        model_id, trust_remote_code=True, torch_dtype=dtype).to(device).eval()

    def _ask(pil_img, prompt: str):
        inputs = processor(text=prompt, images=pil_img,
                           return_tensors="pt").to(device)
        with torch.inference_mode():
            gen = model.generate(input_ids=inputs["input_ids"],
                                 pixel_values=inputs["pixel_values"],
                                 max_new_tokens=1024, do_sample=False,
                                 num_beams=3)
        text = processor.batch_decode(gen, skip_special_tokens=False)[0]
        return processor.post_process_generation(
            text, task=prompt.strip(),
            image_size=(pil_img.width, pil_img.height))

    def detect(pil_img):
        w, h = pil_img.width, pil_img.height
        ocr = _ocr_passes(pil_img, lambda im: _ask(im, _OCR_TASK))
        grounding = []
        if not ocr:   # текста не нашлось — пробуем найти знак-логотип
            answer = _ask(pil_img, f"{_FLORENCE_TASK} {DETECT_PROMPT}")
            boxes = answer.get(_FLORENCE_TASK, {}).get("bboxes", [])
            grounding = _giant_polys(_boxes_to_polys(boxes, w, h), w, h)
        return _merge_detection(ocr, grounding)

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

    v0.8.22 — убирание ПО ВЫДЕЛЕНИЮ: ``sel`` — прямоугольник (x, y, w, h)
    в координатах картинки, нарисованный рамкой режима обрезки. Детекция
    Florence-2 не нужна и НЕ ГРУЗИТСЯ (в память идёт только LaMa —
    секунды экономии и полгигабайта RAM), маска — ровно выделение, без
    расширения: человек нарисовал рамку сам, расширять её — закрасить
    больше, чем он выбрал (WYSIWYG). Покрытие по-прежнему проверяется:
    выделение на весь кадр — не «удаление знака», а уничтожение картинки.
    """

    def __init__(self, jobs: list[tuple[str, str]], model: str,
                 signals: WatermarkSignals,
                 sel: tuple[int, int, int, int] | None = None) -> None:
        super().__init__()
        self.jobs = jobs            # (исходный путь, путь результата)
        self.model = model
        self.signals = signals
        self.sel = sel              # (x, y, w, h) выделения — None: автодетекция

    def run(self) -> None:  # рабочий поток
        # на время пачки скачивания моделей докладывают её сигналам
        # (v0.8.20: процесс в строке статуса) — тот же приём, что у rembg
        global _DL_REPORTER
        _DL_REPORTER = self.signals
        try:
            self._run_inner()
        finally:
            _DL_REPORTER = None

    def _run_inner(self) -> None:
        _ensure_stdio()          # pythonw: без этого падают HF-прогресс-бары
        _disable_hf_progress()   # свои прогресс-сигналы; консольных нет у pythonw
        by_sel = self.sel is not None
        self.signals.model_prepare.emit(self.model)
        try:
            if by_sel:
                # Florence-2 не грузится — рисует человек, а не детектор
                inpainter = _load_inpainter(_torch_device())
                detect = None
            else:
                inpainter, detect = _load_pipeline(self.model)
        except Exception as exc:   # noqa: BLE001 — модуль сломан/не стоит
            for path, _out in self.jobs:
                self.signals.file_done.emit(path, "", False, str(exc))
            self.signals.batch_done.emit(0, len(self.jobs))
            return
        self.signals.model_ready.emit(self.model)
        ok = fail = 0
        for idx, (path, out) in enumerate(self.jobs, 1):
            # начало файла + фазы внутри него — в строку статуса (v0.8.20):
            # детекция и закраска больших картинок идут секунды, без фаз
            # прогресс замирал на «N/M» до завершения файла
            self.signals.file_start.emit(path, idx)
            try:
                with Image.open(path) as im:
                    # EXIF-поворот: фото телефонов иначе уедут «головой вбок»
                    # (тот же разворот, что у показа вьюера — QImageReader
                    # setAutoTransform — выделение совпадает с показом)
                    rgb = _exif_rgb(im)
                if by_sel:
                    # маска ровно выделение (v0.8.22): (x, y, w, h) →
                    # срез numpy не включает правый/нижний край — пиксели
                    # рамки x..x+w-1 / y..y+h-1, ровно то, что нарисовано
                    x, y, w, h = self.sel
                    mask = mask_from_boxes(
                        (rgb.shape[1], rgb.shape[0]),
                        [(x, y, x + w, y + h)], margin=0)
                    if mask.max() == 0:   # выделение ≥1×1 — защита на всякий случай
                        self.signals.file_done.emit(path, "", True, "")
                        continue
                else:
                    self.signals.phase.emit(path, "detect", -1)
                    polys = detect(Image.fromarray(rgb))
                    mask = mask_from_polys((rgb.shape[1], rgb.shape[0]), polys)
                    if mask.max() == 0:
                        # водяных знаков не нашлось — писать нечего, это не ошибка
                        self.signals.file_done.emit(path, "", True, "")
                        continue
                    self.signals.phase.emit(path, "found", len(polys))
                cover = float((mask > 0).mean())
                if cover > _MAX_MASK_COVER:
                    # маска-гигант не «удаляет знак», а уничтожает картинку
                    # (репорт v0.8.14: маска на 100% кадра → каша) — честный
                    # отказ лучше испорченного файла; у выделения свой текст:
                    # тут рисовал человек, детектор ни при чём (v0.8.22)
                    fail += 1
                    self.signals.file_done.emit(
                        path, "", False,
                        tr("log.event.wm_sel_cover" if by_sel
                           else "log.event.wm_cover",
                           pct=round(cover * 100)))
                    continue
                self.signals.phase.emit(path, "inpaint", -1)
                result = inpainter(rgb, mask)
                self.signals.phase.emit(path, "save", -1)
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
