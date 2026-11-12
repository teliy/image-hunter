"""Оффлайн-тест модуля удаления водяных знаков (Florence-2 + LaMa, v0.8.11;
двухшаговая установка без пина Pillow — v0.8.12; без gradio, с шимами для
новых Python и скачиванием big-lama до ModelManager — v0.8.13; двухзадачная
детекция OCR+grounding с фильтрами и предохранителем покрытия — v0.8.14;
обновление установленного модуля: PyPI/Hugging Face/релиз big-lama — v0.8.15;
убирание по выделению без детекции — v0.8.22).

Проверяется:
- watermark_manager: is_installed, nowm_path (формат сохраняется, AVIF → PNG,
  GIF и повторная обработка результата отклоняются), mask_from_boxes
  (расширение на margin, склейка координат, обрезка по краям, объединение),
  mask_from_polys (поворотные квадры OCR, расширение фильтром максимума);
  v0.8.14: _poly_area, _giant_polys (боксы-гиганты с репорта «Знаки не
  удалил. Получилась какая-то ерунда» отбрасываются), _ocr_polys (медианная
  насыщенность HSV: серый знак отделяется от цветной этикетки),
  _merge_detection (OCR выигрывает, grounding — лишь без текста),
  предохранитель покрытия маски (маска на 70% кадра — честная ошибка
  вместо испорченной картинки, на 55% — результат)
- фильтр требований iopaint: пины Pillow==9.5.0 и gradio==4.21.0
  выбрасываются (у Pillow нет сборок под Python 3.12/3.13 — сборка старого
  исходника падает с «KeyError: '__version__'»; пин gradio «numpy~=1.0» не
  выполняется на Python 3.13+ — pip собирал numpy из исходников и валил
  установку), остальное из его же метаданных сохраняется;
- InstallTask ставит модуль в два pip-шага (iopaint --no-deps, затем
  зависимости из метаданных без Pillow/gradio + transformers/timm + шимы
  standard-imghdr/setuptools для новых Python: imghdr удалён из stdlib в
  3.13, distutils живёт только через setuptools), при отказе первого шага
  второй не запускается, на пустых метаданных — честный отказ; сигнал
  install_done доходит во всех ветках;
- _ensure_lama_downloaded: модель качается до ModelManager (без файла на
  диске iopaint не считает «lama» доступной — «Unsupported model: lama»),
  уже скачанный файл не перекачивается;
- UninstallTask удаляет дистрибуции модуля вместе с прямыми зависимостями
  iopaint из его метаданных (opencv — лишь когда rembg не стоит), вычищает
  свои кэши моделей (big-lama, Florence-2), чужие кэши не трогает,
  рапортует освобождёнными мегабайтами;
- RemoveWatermarkTask без установленного модуля честно репортит ошибку по
  каждому файлу (batch_done(0, N)); со стабами конвейера (_load_pipeline)
  создаёт «имя_nowm.ext»: область маски перекрашена, остальное — оригинал,
  оригинал цел; файл без найденных знаков не даёт файла-результата;
- v0.8.22, убирание по выделению: sel_result_path (свежий «X.ext» →
  «X_nowm.ext», занятые имена → «-1»/«-2», вход уже «_nowm» → номер с −1,
  AVIF → PNG, GIF/без расширения — отказ); RemoveWatermarkTask с sel —
  детекция НЕ грузится (_load_pipeline не вызывается), маска ровно
  выделение без расширения, фазы без detect/found, предохранитель
  покрытия со своим текстом (wm_sel_cover); вьюер: кнопка «🧽 Убрать в
  выделении» на панели инструментов между «Закрасить» и «К следующему»,
  видна только в режиме обрезки, рамка рисуется честной доставкой мыши,
  клик стартует задачу с sel, результат открывается после пересканирования
  с режимом обрезки на нём, чистка результата даёт «-1», без модуля —
  вопрос установки (отказ ничего не делает, согласие ставит pip и
  продолжает выделение из _on_wm_install_done);
- кнопка 🧽 есть, клик без выбора картинки даёт подсказку в статусе;
- «Убрать водяные знаки» без модуля предлагает установку (стаб вопроса):
  отказ ничего не запускает, согласие ставит pip и продолжает очередь
  (_wm_pending) после установки;
- выбор детектора (base/large) запоминается в QSettings и валидируется;
- контекстное меню ленты содержит «Убрать водяные знаки»;
- пачка через _wm_start: jpg даёт jpg-результат, итог — в статусе;
- _ensure_stdio/_disable_hf_progress: pythonw-сценарий не роняет модуль;
- v0.8.15, обновление модуля: pypi_latest/hf_latest_sha (JSON из сети,
  честная пустота при отказе), _florence_cached_sha (refs/main кэша HF),
  lama_file/_lama_url/remote_content_length, is_newer; UpdateTask —
  «обновлений нет» без pip, обновление пакетов двумя pip-шагами с
  --upgrade (свежие метаданные, без Pillow/gradio, с шимами), отказ
  pypi/шага 1/пустых метаданных — честный отказ, обновление Florence-2
  (snapshot_download) и big-lama (LaMa.download) по отличию ревизий,
  неудача проверки моделей не фатальна, подсказка о перезапуске;
  вьюер: wm_update стартует задачу с выбранным детектором, guard busy,
  итог в статусе, без модуля — не стартует;
- i18n: все новые ключи заполнены на ru/en/zh; версия — 0.8.25.

Раздел меню «Модули» проверяет scripts/test_modules_menu.py.
Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_watermark.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (QEvent, QPointF, QRect, QRunnable, QSettings,  # noqa: E402
                            Qt, QThreadPool)
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import app  # noqa: E402
from app.core import i18n  # noqa: E402
from app.ui import rembg_manager, upscale_manager, watermark_manager  # noqa: E402
from app.ui.local_viewer import LocalViewer  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(cond, timeout_s: float = 10.0) -> bool:
    app_inst = QApplication.instance()
    end = os.times()[4] + timeout_s
    while os.times()[4] < end:
        app_inst.processEvents()
        if cond():
            return True
        app_inst.processEvents()
    return cond()


WM_KEYS = [
    "viewer.wm", "viewer.wm_tip", "viewer.wm_none", "viewer.wm_busy",
    "viewer.wm_already", "viewer.wm_progress", "viewer.wm_done",
    "viewer.wm_clean", "viewer.wm_done_fail", "viewer.wm_inst_q",
    "viewer.wm_sel", "viewer.wm_sel_tip",
    "viewer.wm_installing", "viewer.wm_install_ok", "viewer.wm_install_fail",
    "viewer.wm_uninst_q", "viewer.wm_uninstalling", "viewer.wm_uninst_ok",
    "viewer.wm_uninst_fail", "viewer.wm_menu_install",
    "viewer.wm_menu_uninstall", "viewer.wm_menu_update",
    "viewer.wm_updating", "viewer.wm_update_done", "viewer.wm_update_fail",
    "viewer.wm_update_nothing", "viewer.wm_update_model",
    "viewer.wm_update_lama", "viewer.wm_update_model_fail",
    "viewer.wm_update_lama_fail", "viewer.wm_update_pypi_fail",
    "viewer.wm_update_stuck", "viewer.wm_update_restart",
    "viewer.wm_model_menu",
    "viewer.wm_model_base", "viewer.wm_model_large", "viewer.wm_prepare",
    "viewer.wm_ready", "log.event.wm_start", "log.event.wm_file_err",
    "log.event.wm_cover", "log.event.wm_sel_cover", "log.event.wm_done",
    "log.event.wm_skip", "log.event.wm_sel_start", "log.event.wm_model",
    "log.event.wm_install_start", "log.event.wm_install_done",
    "log.event.wm_install_fail", "log.event.wm_uninstall_start",
    "log.event.wm_uninstall_done", "log.event.wm_uninstall_fail",
    "log.event.wm_update_start", "log.event.wm_update_done",
    "log.event.wm_update_fail",
    "modules.wm_header",
]


def main() -> int:
    app_inst = QApplication.instance() or QApplication([])
    i18n.set_lang("ru", persist=False)   # детерминированный язык статусов
    st = QSettings("ImageHunter", "ImageHunter")
    st.sync()

    check("версия 0.8.25", app.__version__ == "0.8.25", app.__version__)

    # ---------- менеджер: чистые функции ----------
    check("is_installed() — булево", isinstance(watermark_manager.is_installed(), bool))
    check("модель по умолчанию в списке",
          watermark_manager.DEFAULT_MODEL in {m for m, _k in watermark_manager.FLORENCE_MODELS})
    cases = {"cat.jpg": "cat_nowm.jpg", "cat.jpeg": "cat_nowm.jpeg",
             "cat.png": "cat_nowm.png", "cat.webp": "cat_nowm.webp",
             "cat.bmp": "cat_nowm.bmp", "cat.tiff": "cat_nowm.tiff",
             "cat.avif": "cat_nowm.png"}
    for src, want in cases.items():
        got = watermark_manager.nowm_path(src)
        check(f"nowm_path {src} → {want}", got == want, got)
    for bad in ("cat_nowm.jpg", "cat.gif", "cat"):
        got = watermark_manager.nowm_path(bad)
        check(f"nowm_path {bad!r} → отказ", got == "", repr(got))

    # ---------- sel_result_path: имя результата убирания по выделению (v0.8.22) ----------
    sel_cases = {"cat.jpg": "cat_nowm.jpg", "cat.png": "cat_nowm.png",
                 "cat.webp": "cat_nowm.webp", "cat.avif": "cat_nowm.png"}
    for src, want in sel_cases.items():
        got = watermark_manager.sel_result_path(src)
        check(f"sel_result_path {src} → {want}", got == want, got)
    for bad in ("cat.gif", "cat"):
        got = watermark_manager.sel_result_path(bad)
        check(f"sel_result_path {bad!r} → отказ", got == "", repr(got))
    # вход уже «_nowm» — не отбраковывается: это чистка остатков на
    # готовом результате, имя уедет в следующий свободный номер
    got = watermark_manager.sel_result_path("cat_nowm.webp")
    check("sel_result_path «cat_nowm.webp» → «cat_nowm-1.webp»",
          got == "cat_nowm-1.webp", got)

    # ---------- mask_from_boxes: геометрия маски ----------
    mask = watermark_manager.mask_from_boxes((10, 10), [])
    check("маска без боксов пуста", mask.max() == 0)
    mask = watermark_manager.mask_from_boxes((100, 80), [(20, 10, 40, 30)], margin=0)
    check("маска: внутри бокса 255",
          mask[10, 20] == 255 and mask[29, 39] == 255)
    check("маска: снаружи 0",
          mask[9, 20] == 0 and mask[10, 19] == 0 and mask[30, 40] == 0)
    mask = watermark_manager.mask_from_boxes((100, 80), [(20, 10, 40, 30)], margin=5)
    check("маска: margin расширяет бокс",
          mask[5, 15] == 255 and mask[34, 44] == 255 and mask[4, 15] == 0)
    mask = watermark_manager.mask_from_boxes((100, 80), [(40, 30, 20, 10)], margin=0)
    check("маска: перевёрнутые координаты чинятся",
          mask[10, 20] == 255 and mask[29, 39] == 255 and mask[9, 20] == 0)
    mask = watermark_manager.mask_from_boxes((50, 50), [(45, 45, 60, 60)], margin=10)
    check("маска: обрезка по краям картинки",
          mask[49, 49] == 255 and mask.shape == (50, 50))
    mask = watermark_manager.mask_from_boxes(
        (100, 100), [(10, 10, 20, 20), (15, 15, 30, 30)], margin=0)
    check("маска: объединение боксов",
          mask[12, 12] == 255 and mask[25, 25] == 255 and mask[9, 12] == 0)

    # ---------- mask_from_polys: полигоны детекции v0.8.14 ----------
    mask = watermark_manager.mask_from_polys((10, 10), [])
    check("полигоны: без полигонов маска пуста", mask.max() == 0)
    # повернутый квад вокруг центра: уголки бокса чистые, центр — закрашен
    quad = [(10, 20), (20, 10), (30, 20), (20, 30)]
    mask = watermark_manager.mask_from_polys((40, 40), [quad], margin=0)
    check("полигоны: ромб закрашен внутри", mask[20, 20] == 255)
    check("полигоны: угол обрамляющего бокса не тронут",
          mask[10, 10] == 0 and mask[30, 30] == 0)
    mask = watermark_manager.mask_from_polys((40, 40), [quad], margin=4)
    check("полигоны: фильтр максимума расширяет маску",
          mask[20, 34] == 255 and mask[34, 20] == 255)
    # точки вне кадра обрезаются, вырожденные полигоны игнорируются
    mask = watermark_manager.mask_from_polys(
        (40, 40), [[(-5, 0), (10, -5), (10, 10), (-5, 10)],
                   [(30, 30), (30, 30), (30, 30)]], margin=0)
    check("полигоны: обрезка по кадру и вырожденные",
          mask[0, 0] == 255 and mask[5, 5] == 255 and mask[39, 39] == 0)

    # ---------- _poly_area и _giant_polys: боксы-гиганты с репорта ----------
    check("площадь: прямоугольник 10x20",
          watermark_manager._poly_area([(0, 0), (10, 0), (10, 20), (0, 20)]) == 200.0)
    check("площадь: вырожденный полигон нулевая",
          watermark_manager._poly_area([(10, 10), (50, 10), (90, 10)]) == 0.0)
    frame = (1000, 1000)
    box = lambda a, b: [(a, a), (b, a), (b, b), (a, b)]
    giants = watermark_manager._giant_polys(
        [box(0, 1000), box(0, 625), box(0, 530), box(250, 687), box(0, 450)],
        *frame)
    # живые мусорные боксы с репорта: 100%, 39%, 28% кадра — отброшены;
    # 19% (наш реальный случай grounding'а) и 20% — остались
    check("гиганты: боксы >25% кадра отброшены",
          len(giants) == 2 and
          watermark_manager._poly_area(giants[0]) == (687.0 - 250.0) ** 2 and
          watermark_manager._poly_area(giants[1]) == 450.0 ** 2,
          str(len(giants)))
    check("гиганты: вырожденный полигон не выживает",
          watermark_manager._giant_polys(
              [[(10, 10), (50, 10), (90, 10)]], 100, 100) == [])

    # ---------- _ocr_polys: фильтр насыщенности отделяет знак от этикетки ----------
    import numpy as np

    hsv = np.zeros((100, 100, 3), dtype=np.uint8)   # всё серое (насыщенность 0)
    hsv[60:80, 60:80, 1] = 200      # цветная надпись этикетки (насыщенность ~180)
    data = {"quad_boxes": [
        [10.0, 10.0, 30.0, 10.0, 30.0, 30.0, 10.0, 30.0],   # серый знак — остаётся
        [60.0, 60.0, 80.0, 60.0, 80.0, 80.0, 60.0, 80.0],   # цветная этикетка — вон
        [0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0],   # гигант — вон
        [-10.0, 40.0, 20.0, 40.0, 20.0, 55.0, -10.0, 55.0],  # частично вне кадра
    ]}
    polys = watermark_manager._ocr_polys(hsv, data, 100, 100)
    check("ocr-полигоны: знак остался, этикетка и гигант отсечены",
          len(polys) == 2 and
          watermark_manager._poly_area(polys[0]) == 400.0 and
          polys[1][0] == (0.0, 40.0),
          str(len(polys)))
    check("ocr-полигоны: пустой ответ — пустой список",
          watermark_manager._ocr_polys(hsv, {}, 100, 100) == [])

    # ---------- _merge_detection: OCR выигрывает, grounding — резерв ----------
    check("слияние: OCR есть — grounding игнорируется",
          watermark_manager._merge_detection([["ocr"]], [["g"]]) == [["ocr"]])
    check("слияние: OCR пуст — работает grounding",
          watermark_manager._merge_detection([], [["g"]]) == [["g"]])
    check("слияние: пусто везде — пусто",
          watermark_manager._merge_detection([], []) == [])

    # ---------- _ocr_passes: оригинал + авто-контраст (v0.8.14) ----------
    from PIL import Image as _Img

    gray_img = _Img.new("RGB", (60, 60), (200, 200, 200))
    quad_a = [5.0, 5.0, 25.0, 5.0, 25.0, 25.0, 5.0, 25.0]
    quad_b = [35.0, 35.0, 55.0, 35.0, 55.0, 55.0, 35.0, 55.0]
    poly_a = [(5.0, 5.0), (25.0, 5.0), (25.0, 25.0), (5.0, 25.0)]
    poly_b = [(35.0, 35.0), (55.0, 35.0), (55.0, 55.0), (35.0, 55.0)]
    calls = []

    def fake_ask(im):
        # первый вызов (оригинал) видит один знак, второй (авто-контраст
        # бледной копии) — другой: объединение должно собрать оба
        calls.append(im)
        return {"<OCR_WITH_REGION>":
                {"quad_boxes": [quad_a if len(calls) == 1 else quad_b]}}

    passed = watermark_manager._ocr_passes(gray_img, fake_ask)
    check("проходы OCR: два вызова — оригинал и усиленная копия",
          len(calls) == 2)
    check("проходы OCR: объединение квадов двух проходов",
          len(passed) == 2 and passed[0] == poly_a and passed[1] == poly_b,
          str(len(passed)))
    # гигант из любого прохода отбрасывается
    calls.clear()

    def giant_ask(im):
        calls.append(im)
        return {"<OCR_WITH_REGION>": {"quad_boxes": [
            [0.0, 0.0, 60.0, 0.0, 60.0, 60.0, 0.0, 60.0]]}}

    watermark_manager._ocr_passes(gray_img, giant_ask)
    check("проходы OCR: гигант не выживает ни в одном проходе",
          len(calls) == 2)

    # ---------- фильтр требований iopaint: пины Pillow и gradio выбрасываются ----------
    real_reqs = watermark_manager._iopaint_requires
    watermark_manager._iopaint_requires = lambda: [
        "Pillow==9.5.0", "torch>=2.0.0", "gradio==4.21.0",
        "pydantic>=2.5.2", "foo-bar; python_version < '3.10'"]
    reqs = watermark_manager._module_requirements()
    check("требования iopaint: Pillow и gradio выброшены, остальные с маркерами",
          reqs == ["torch>=2.0.0", "pydantic>=2.5.2",
                   "foo-bar; python_version < '3.10'"], str(reqs))
    names = watermark_manager._module_dep_names()
    check("имена для удаления: Pillow/opencv нет, gradio остаётся",
          names == ["torch", "gradio", "pydantic", "foo-bar"], str(names))
    watermark_manager._iopaint_requires = lambda: []
    check("требования iopaint: пустые метаданные — пустой список",
          watermark_manager._module_requirements() == []
          and watermark_manager._module_dep_names() == [])
    watermark_manager._iopaint_requires = real_reqs

    # ---------- InstallTask: два pip-шага и доставка сигнала ----------
    calls: list[list[str]] = []
    real_pip = watermark_manager._run_pip

    def fake_pip(args):
        calls.append(list(args))
        return True, ""

    # фейковые метаданные iopaint: пины Pillow и gradio должны уйти из шага 2
    watermark_manager._iopaint_requires = lambda: [
        "Pillow==9.5.0", "torch>=2.0.0", "gradio==4.21.0"]
    watermark_manager._run_pip = fake_pip
    try:
        sig = watermark_manager.WatermarkSignals()
        results: list[tuple] = []
        sig.install_done.connect(lambda ok, info: results.append((ok, info)))
        QThreadPool.globalInstance().start(watermark_manager.InstallTask(sig))
        wait_until(lambda: bool(results))
        check("InstallTask: сигнал дошёл",
              bool(results) and results[0][0] is True)
        check("InstallTask: ровно два pip-вызова", len(calls) == 2, str(calls))
        first = calls[0] if calls else []
        second = calls[1] if len(calls) > 1 else []
        check("InstallTask: шаг 1 — iopaint без зависимостей",
              first == ["install", "--disable-pip-version-check",
                        "--no-deps", "iopaint"], str(first))
        check("InstallTask: шаг 2 — зависимости iopaint и Florence-2",
              second[:2] == ["install", "--disable-pip-version-check"]
              and "torch>=2.0.0" in second
              and "transformers" in second and "timm" in second, str(second))
        check("InstallTask: пин Pillow не ставится",
              not any(str(p).lower().startswith("pillow") for p in second),
              str(second))
        check("InstallTask: gradio не ставится, шимы окружения ставятся",
              "gradio==4.21.0" not in second
              and "standard-imghdr" in second and "setuptools" in second,
              str(second))
    finally:
        watermark_manager._run_pip = real_pip
        watermark_manager._iopaint_requires = real_reqs

    # отказ первого шага: второй не запускается
    fail_calls: list[list[str]] = []

    def failing_pip(args):
        fail_calls.append(list(args))
        return False, "No space left on device"

    watermark_manager._iopaint_requires = lambda: ["torch>=2.0.0"]
    watermark_manager._run_pip = failing_pip
    try:
        sig = watermark_manager.WatermarkSignals()
        results = []
        sig.install_done.connect(lambda ok, info: results.append((ok, info)))
        QThreadPool.globalInstance().start(watermark_manager.InstallTask(sig))
        wait_until(lambda: bool(results))
        check("InstallTask: ошибка доезжает с хвостом вывода",
              bool(results) and results[0] == (False, "No space left on device"),
              str(results))
        check("InstallTask: при отказе шага 1 второй шаг не запускается",
              len(fail_calls) == 1, str(fail_calls))
    finally:
        watermark_manager._run_pip = real_pip
        watermark_manager._iopaint_requires = real_reqs

    # пустые метаданные после установки — честный отказ, а не тихая поломка
    watermark_manager._iopaint_requires = lambda: []
    watermark_manager._run_pip = fake_pip
    calls.clear()
    try:
        sig = watermark_manager.WatermarkSignals()
        results = []
        sig.install_done.connect(lambda ok, info: results.append((ok, info)))
        QThreadPool.globalInstance().start(watermark_manager.InstallTask(sig))
        wait_until(lambda: bool(results))
        check("InstallTask: пустые метаданные — честный отказ",
              bool(results) and results[0][0] is False
              and "iopaint" in str(results[0][1]), str(results))
        check("InstallTask: на пустых метаданных вызов один",
              len(calls) == 1, str(calls))
    finally:
        watermark_manager._run_pip = real_pip
        watermark_manager._iopaint_requires = real_reqs

    # ---------- _ensure_lama_downloaded: big-lama качается ДО ModelManager ----------
    # iopaint считает модель доступной только по файлу на диске: без скачивания
    # ModelManager встречает «lama» как неизвестную («Unsupported model: lama.
    # Available models: ['cv2']»). Проверяем на стабе iopaint.model.lama.
    import types
    fake_lama = types.ModuleType("iopaint.model.lama")
    state = {"on_disk": False, "downloads": 0}

    class _FakeLaMa:
        @staticmethod
        def is_downloaded():
            return state["on_disk"]

        @staticmethod
        def download():
            state["downloads"] += 1
            state["on_disk"] = True

    fake_lama.LaMa = _FakeLaMa
    saved_lama_mod = sys.modules.get("iopaint.model.lama")
    sys.modules["iopaint.model.lama"] = fake_lama
    try:
        watermark_manager._ensure_lama_downloaded()
        check("LaMa: без файла на диске модель качаем",
              state["downloads"] == 1, str(state))
        watermark_manager._ensure_lama_downloaded()
        check("LaMa: скачанный файл не перекачивается",
              state["downloads"] == 1, str(state))
    finally:
        if saved_lama_mod is not None:
            sys.modules["iopaint.model.lama"] = saved_lama_mod
        else:
            sys.modules.pop("iopaint.model.lama", None)

    # ---------- UninstallTask: только свои дистрибуции + свои кэши ----------
    real_dists_fn = watermark_manager._installed_dists
    real_globs = watermark_manager.model_cache_globs
    tmpdir = tempfile.mkdtemp(prefix="ih_wm_")
    # свои кэши моделей в пуст tmpdir: big-lama.pt и Florence-2 в HF-стиле
    torch_dir = os.path.join(tmpdir, "torch", "checkpoints")
    hf_dir = os.path.join(tmpdir, "hf", "hub")
    os.makedirs(torch_dir, exist_ok=True)
    os.makedirs(hf_dir, exist_ok=True)
    lama_fake = os.path.join(torch_dir, "big-lama.pt")
    flo_fake = os.path.join(hf_dir, "models--microsoft--Florence-2-base")
    os.makedirs(flo_fake, exist_ok=True)
    with open(lama_fake, "wb") as f:
        f.write(b"x" * (3 * 1024 * 1024))
    with open(os.path.join(flo_fake, "model.safetensors"), "wb") as f:
        f.write(b"y" * (2 * 1024 * 1024))
    alien_fake = os.path.join(torch_dir, "some-other-model.pt")
    with open(alien_fake, "wb") as f:
        f.write(b"z" * (1024 * 1024))
    watermark_manager.model_cache_globs = lambda: [
        (torch_dir, "big-lama*.pt"), (hf_dir, "models--microsoft--Florence-2-*")]

    watermark_manager._installed_dists = (
        lambda names: {"iopaint", "torch", "opencv-python"} & set(names))
    uninstall_calls: list[list[str]] = []
    watermark_manager._run_pip = (
        lambda args: (uninstall_calls.append(list(args)), (True, ""))[1])
    try:
        sig = watermark_manager.WatermarkSignals()
        results = []
        sig.uninstall_done.connect(
            lambda ok, info, mb: results.append((ok, info, mb)))
        # v0.8.24: torch — общее достояние с модулем улучшения качества.
        # Сосед жив → torch остаётся в системе, уходит только своё;
        # соседа нет (или torch не стоит вовсе) → torch вычищается.
        real_ups_installed = upscale_manager.is_installed
        upscale_manager.is_installed = lambda: True
        QThreadPool.globalInstance().start(watermark_manager.UninstallTask(sig))
        wait_until(lambda: bool(results))
        args = uninstall_calls[0] if uninstall_calls else []
        check("UninstallTask: pip uninstall -y iopaint",
              args[:2] == ["uninstall", "-y"] and "iopaint" in args, str(args))
        check("UninstallTask: torch остаётся при живом модуле улучшения",
              "torch" not in args, str(args))
        check("UninstallTask: кэши моделей удалены",
              not os.path.exists(lama_fake) and not os.path.exists(flo_fake))
        check("UninstallTask: освобождено ≥3 МБ (первый прогон)",
              bool(results) and results[0][2] >= 3, str(results))
        # соседа нет — torch больше ничей, вычищается (кэши уже пусты,
        # поэтому счёт «освобождено» дальше не проверяется)
        results.clear()
        uninstall_calls.clear()
        upscale_manager.is_installed = lambda: False
        QThreadPool.globalInstance().start(watermark_manager.UninstallTask(sig))
        wait_until(lambda: bool(results))
        args = uninstall_calls[0] if uninstall_calls else []
        check("UninstallTask: torch вычищается без модуля улучшения",
              "torch" in args, str(args))
        check("UninstallTask: чужие кэши не тронуты",
              os.path.exists(alien_fake))
    finally:
        upscale_manager.is_installed = real_ups_installed
        watermark_manager._installed_dists = real_dists_fn
        watermark_manager.model_cache_globs = real_globs
        watermark_manager._run_pip = real_pip

    # opencv вычищается только когда rembg не стоит
    real_rembg_installed = rembg_manager.is_installed
    watermark_manager._installed_dists = (
        lambda names: {"iopaint", "opencv-python"} & set(names))
    try:
        rembg_manager.is_installed = lambda: True
        dists = watermark_manager._dists_to_remove()
        check("UninstallTask: при живом rembg opencv остаётся",
              "opencv-python" not in dists and "iopaint" in dists, str(dists))
        rembg_manager.is_installed = lambda: False
        dists = watermark_manager._dists_to_remove()
        check("UninstallTask: без rembg opencv уходит вместе с модулем",
              "opencv-python" in dists, str(dists))
    finally:
        rembg_manager.is_installed = real_rembg_installed
        watermark_manager._installed_dists = real_dists_fn

    # прямые зависимости iopaint из его метаданных вычищаются вместе с модулем
    watermark_manager._iopaint_requires = lambda: [
        "gradio==4.21.0", "diffusers==0.27.2", "Pillow==9.5.0", "opencv-python"]
    watermark_manager._installed_dists = (
        lambda names: {"gradio", "diffusers"} & set(names))
    try:
        dists = watermark_manager._dists_to_remove()
        check("UninstallTask: зависимости iopaint уходят, Pillow/opencv — нет",
              "gradio" in dists and "diffusers" in dists
              and "pillow" not in dists and "opencv-python" not in dists,
              str(dists))
    finally:
        watermark_manager._iopaint_requires = real_reqs
        watermark_manager._installed_dists = real_dists_fn

    # ---------- обновление модуля: сеть и кэши (v0.8.15) ----------
    import urllib.request as _ur
    from app.core import updates as _updates

    class _FakeResp:
        """Ответ urlopen: JSON-тело и заголовки (для pypi/hf/HEAD)."""

        def __init__(self, payload, length="12345"):
            self._payload = payload
            self.headers = {"Content-Length": length}

        def read(self, _n):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    real_urlopen = _ur.urlopen

    def _net_fail(req, timeout=0):
        raise OSError("no network")

    _ur.urlopen = lambda req, timeout=0: _FakeResp(b'{"info": {"version": "9.9.9"}}')
    try:
        check("pypi_latest: версия из JSON",
              _updates.pypi_latest("iopaint") == "9.9.9",
              _updates.pypi_latest("iopaint"))
    finally:
        _ur.urlopen = real_urlopen
    _ur.urlopen = _net_fail
    try:
        check("pypi_latest: нет сети — честная пустота",
              _updates.pypi_latest("iopaint") == "")
        check("hf_latest_sha: нет сети — честная пустота",
              watermark_manager.hf_latest_sha("microsoft/Florence-2-base") == "")
        check("remote_content_length: нет сети — 0",
              watermark_manager.remote_content_length("http://x/y") == 0)
    finally:
        _ur.urlopen = real_urlopen
    _ur.urlopen = lambda req, timeout=0: _FakeResp(b'{"sha": "cafe1234"}')
    try:
        check("hf_latest_sha: ревизия из API хаба",
              watermark_manager.hf_latest_sha("microsoft/Florence-2-base")
              == "cafe1234")
        check("remote_content_length: размер из HEAD",
              watermark_manager.remote_content_length("http://x/lama.pt")
              == 12345)
    finally:
        _ur.urlopen = real_urlopen

    check("installed_version: несуществующий пакет — пусто",
          watermark_manager.installed_version("ih-no-such-pkg-xyz") == "")
    check("is_newer: 1.7.0 новее 1.6.0, равные — нет",
          _updates.is_newer("1.7.0", "1.6.0")
          and not _updates.is_newer("1.6.0", "1.6.0"))

    # кэш HF: ревизия скачанной модели читается из refs/main
    real_hf_cache = watermark_manager._hf_hub_cache
    hf_cache = os.path.join(tmpdir, "hfhub")
    os.makedirs(os.path.join(hf_cache, "models--microsoft--Florence-2-base",
                             "refs"), exist_ok=True)
    with open(os.path.join(hf_cache, "models--microsoft--Florence-2-base",
                           "refs", "main"), "w", encoding="utf-8") as f:
        f.write("deadbeef\n")
    watermark_manager._hf_hub_cache = lambda: hf_cache
    try:
        check("кэш HF: ревизия из refs/main",
              watermark_manager._florence_cached_sha(
                  "microsoft/Florence-2-base") == "deadbeef")
        check("кэш HF: модели нет — пусто",
              watermark_manager._florence_cached_sha("microsoft/Nope") == "")
    finally:
        watermark_manager._hf_hub_cache = real_hf_cache

    # big-lama: файл ищется в кэше torch-hub, адрес — из iopaint или дефолт
    real_globs_upd = watermark_manager.model_cache_globs
    torch_dir_u = os.path.join(tmpdir, "torch_upd")
    os.makedirs(torch_dir_u, exist_ok=True)
    lama_u = os.path.join(torch_dir_u, "big-lama.pt")
    with open(lama_u, "wb") as f:
        f.write(b"L" * 1234)
    watermark_manager.model_cache_globs = lambda: [(torch_dir_u, "big-lama*.pt")]
    try:
        check("big-lama: файл найден в кэше",
              watermark_manager.lama_file() == lama_u,
              watermark_manager.lama_file())
    finally:
        watermark_manager.model_cache_globs = real_globs_upd
    check("big-lama: кэша нет — пусто", watermark_manager.lama_file() == "")
    check("_lama_url: без iopaint — запасной адрес с big-lama.pt",
          "big-lama.pt" in watermark_manager._lama_url(),
          watermark_manager._lama_url())

    # ---------- UpdateTask: проверка и обновление модуля ----------
    real_pip_upd = watermark_manager._run_pip
    real_ver = watermark_manager.installed_version
    real_pypi = watermark_manager.pypi_latest
    real_reqs_upd = watermark_manager._iopaint_requires
    real_hfsha = watermark_manager.hf_latest_sha
    real_cached = watermark_manager._florence_cached_sha
    real_lama_file = watermark_manager.lama_file
    real_lama_url = watermark_manager._lama_url
    real_head = watermark_manager.remote_content_length

    def upd_pip_calls():
        calls: list[list[str]] = []
        watermark_manager._run_pip = (
            lambda args: (calls.append(list(args)), (True, ""))[1])
        return calls

    def run_update(model="microsoft/Florence-2-base"):
        sig = watermark_manager.WatermarkSignals()
        results: list[tuple] = []
        sig.update_done.connect(
            lambda ok, what, info: results.append((ok, what, info)))
        QThreadPool.globalInstance().start(
            watermark_manager.UpdateTask(sig, model))
        wait_until(lambda: bool(results))
        return results

    ver_equal = {"iopaint": "1.6.0", "transformers": "4.48.3", "timm": "1.0.15"}
    # всё актуально: ни pip, ни перекачек — честное «обновлений нет»
    pip_calls = upd_pip_calls()
    watermark_manager.installed_version = lambda n: ver_equal[n]
    watermark_manager.pypi_latest = lambda n: ver_equal[n]
    watermark_manager.hf_latest_sha = lambda repo: "cafe"
    watermark_manager._florence_cached_sha = lambda repo: "cafe"
    watermark_manager.lama_file = lambda: ""
    try:
        results = run_update()
        check("UpdateTask: всё актуально — без pip",
              results == [(True, i18n.tr("viewer.wm_update_nothing", pkgs=
                          "iopaint 1.6.0, transformers 4.48.3, timm 1.0.15"), "")],
              str(results))
        check("UpdateTask: всё актуально — pip не звался", pip_calls == [],
              str(pip_calls))
    finally:
        watermark_manager._run_pip = real_pip_upd

    # пакеты обновились: два pip-шага с --upgrade, новые метаданные, шимы;
    # версии после pip сверяются ПО ФАКТУ (v0.8.17) — стаб двигает ровно
    # то, что двигает настоящий pip: шаг 1 — iopaint, шаг 2 — остальные
    ver_old = {"iopaint": "1.6.0", "transformers": "4.48.3", "timm": "1.0.15"}
    ver_new = {"iopaint": "1.7.0", "transformers": "4.49.0", "timm": "1.0.15"}
    pip_calls: list[list[str]] = []
    ver_now = dict(ver_old)

    def upd_pip_move(args):
        pip_calls.append(list(args))
        ver_now.update(ver_new if "--no-deps" not in args
                       else {"iopaint": ver_new["iopaint"]})
        return True, ""

    watermark_manager._run_pip = upd_pip_move
    watermark_manager.installed_version = lambda n: ver_now.get(n, "")
    watermark_manager.pypi_latest = lambda n: ver_new[n]
    watermark_manager._iopaint_requires = lambda: [
        "Pillow==9.5.0", "torch>=2.0.0", "gradio==4.21.0"]
    try:
        results = run_update()
        ok, what, info = results[0] if results else (None, "", "")
        check("UpdateTask: пакеты — сигнал успеха",
              bool(results) and ok is True and info == "", str(results))
        check("UpdateTask: iopaint 1.6.0 → 1.7.0 в итоге",
              "iopaint 1.6.0 → 1.7.0" in what, what)
        check("UpdateTask: transformers 4.48.3 → 4.49.0 в итоге",
              "transformers 4.48.3 → 4.49.0" in what, what)
        check("UpdateTask: подсказка о перезапуске в итоге",
              i18n.tr("viewer.wm_update_restart") in what, what)
        check("UpdateTask: ровно два pip-вызова", len(pip_calls) == 2,
              str(pip_calls))
        first = pip_calls[0] if pip_calls else []
        second = pip_calls[1] if len(pip_calls) > 1 else []
        check("UpdateTask: шаг 1 — iopaint --no-deps --upgrade",
              first == ["install", "--disable-pip-version-check",
                        "--no-deps", "--upgrade", "iopaint"], str(first))
        check("UpdateTask: шаг 2 — --upgrade, свежие зависимости и Florence-2",
              second[:3] == ["install", "--disable-pip-version-check",
                             "--upgrade"]
              and "torch>=2.0.0" in second and "transformers" in second
              and "timm" in second, str(second))
        check("UpdateTask: Pillow и gradio не ставятся, шимы ставятся",
              not any(str(p).lower().startswith("pillow") for p in second)
              and "gradio==4.21.0" not in second
              and "standard-imghdr" in second and "setuptools" in second,
              str(second))
    finally:
        watermark_manager._run_pip = real_pip_upd

    # репорт v0.8.17: общий шаг 2 «успешен», но transformers не сдвинулся —
    # сверяем по факту и спасаем одиночным pip; в итоге РЕАЛЬНАЯ версия
    pip_calls = []
    ver_now = dict(ver_old)

    def upd_pip_skip(args):
        pip_calls.append(list(args))
        if "--no-deps" in args:               # шаг 1: только iopaint
            ver_now["iopaint"] = ver_new["iopaint"]
        elif args[1:] == ["--disable-pip-version-check",
                          "--upgrade", "transformers"]:
            ver_now["transformers"] = "4.50.0"  # одиночный pip спас
        return True, ""

    watermark_manager._run_pip = upd_pip_skip
    watermark_manager.installed_version = lambda n: ver_now.get(n, "")
    watermark_manager.pypi_latest = lambda n: ver_new[n]
    watermark_manager.hf_latest_sha = lambda repo: "cafe"
    watermark_manager._florence_cached_sha = lambda repo: "cafe"
    watermark_manager.lama_file = lambda: ""
    try:
        results = run_update()
        ok, what, info = results[0] if results else (None, "", "")
        check("UpdateTask: застрявший пакет — одиночный pip зван",
              len(pip_calls) == 3 and pip_calls[2] == ["install",
                                                       "--disable-pip-version-check",
                                                       "--upgrade",
                                                       "transformers"],
              str(pip_calls))
        check("UpdateTask: спасённый — в итоге РЕАЛЬНАЯ версия",
              bool(results) and ok is True
              and "transformers 4.48.3 → 4.50.0" in what
              and "4.49.0" not in what, what)
        check("UpdateTask: спасённый — подсказка о перезапуске",
              i18n.tr("viewer.wm_update_restart") in what, what)
    finally:
        watermark_manager._run_pip = real_pip_upd

    # одиночный pip тоже не сдвинул — честная неудача вместо ложного «→»
    pip_calls = []
    ver_now = dict(ver_old)

    def upd_pip_stuck(args):
        pip_calls.append(list(args))
        if "--no-deps" in args:
            ver_now["iopaint"] = ver_new["iopaint"]
        return True, ""                          # transformers не двигается

    watermark_manager._run_pip = upd_pip_stuck
    watermark_manager.installed_version = lambda n: ver_now.get(n, "")
    watermark_manager.pypi_latest = lambda n: ver_new[n]
    watermark_manager.hf_latest_sha = lambda repo: "cafe"
    watermark_manager._florence_cached_sha = lambda repo: "cafe"
    watermark_manager.lama_file = lambda: ""
    try:
        results = run_update()
        ok, what, info = results[0] if results else (None, "", "")
        check("UpdateTask: безнадёжный — одиночная попытка, честная пометка",
              bool(results) and ok is True
              and i18n.tr("viewer.wm_update_stuck", name="transformers",
                          ver="4.48.3") in what
              and "transformers 4.48.3 →" not in what, what)
        check("UpdateTask: безнадёжный — сдвинувшийся сосед в итоге",
              "iopaint 1.6.0 → 1.7.0" in what, what)
        check("UpdateTask: безнадёжный — подсказка есть (сосед сдвинулся)",
              i18n.tr("viewer.wm_update_restart") in what, what)
    finally:
        watermark_manager._run_pip = real_pip_upd

    # не сдвинулось НИЧЕГО: подсказки о перезапуске нет — пакеты те же
    pip_calls = []
    ver_now = dict(ver_old)

    def upd_pip_dead(args):
        pip_calls.append(list(args))
        return True, ""

    watermark_manager._run_pip = upd_pip_dead
    watermark_manager.installed_version = lambda n: ver_now.get(n, "")
    watermark_manager.pypi_latest = lambda n: ver_new[n]
    watermark_manager.hf_latest_sha = lambda repo: "cafe"
    watermark_manager._florence_cached_sha = lambda repo: "cafe"
    watermark_manager.lama_file = lambda: ""
    try:
        results = run_update()
        ok, what, info = results[0] if results else (None, "", "")
        check("UpdateTask: всё застряло — обе честные пометки",
              bool(results) and ok is True
              and i18n.tr("viewer.wm_update_stuck", name="iopaint",
                          ver="1.6.0") in what
              and i18n.tr("viewer.wm_update_stuck", name="transformers",
                          ver="4.48.3") in what, what)
        check("UpdateTask: всё застряло — попытки в одиночку по каждой",
              len(pip_calls) == 4 and pip_calls[2][-1] == "iopaint"
              and pip_calls[3][-1] == "transformers", str(pip_calls))
        check("UpdateTask: всё застряло — подсказки о перезапуске нет",
              i18n.tr("viewer.wm_update_restart") not in what, what)
    finally:
        watermark_manager._run_pip = real_pip_upd

    # pypi.org недоступен — честный отказ, обновлять вслепую нельзя
    pip_calls = upd_pip_calls()
    watermark_manager.installed_version = lambda n: ver_equal[n]
    watermark_manager.pypi_latest = lambda n: ""
    try:
        results = run_update()
        check("UpdateTask: pypi недоступен — отказ с именем пакета",
              results == [(False, "", i18n.tr("viewer.wm_update_pypi_fail",
                                              name="iopaint"))], str(results))
        check("UpdateTask: при отказе pypi pip не запускается",
              pip_calls == [], str(pip_calls))
    finally:
        watermark_manager._run_pip = real_pip_upd

    # отказ шага 1: второй не запускается, ошибка доезжает
    pip_calls = upd_pip_calls()
    watermark_manager._run_pip = (
        lambda args: (pip_calls.append(list(args)),
                      (False, "No space left on device"))[1])
    watermark_manager.pypi_latest = lambda n: ver_new[n]
    try:
        results = run_update()
        check("UpdateTask: отказ шага 1 — честная ошибка",
              results == [(False, "", "No space left on device")], str(results))
        check("UpdateTask: при отказе шага 1 второй не запускается",
              len(pip_calls) == 1, str(pip_calls))
    finally:
        watermark_manager._run_pip = real_pip_upd

    # пустые метаданные обновлённого iopaint — честный отказ
    pip_calls = upd_pip_calls()
    watermark_manager._iopaint_requires = lambda: []
    try:
        results = run_update()
        check("UpdateTask: пустые метаданные — честный отказ",
              bool(results) and results[0][0] is False
              and "iopaint" in results[0][2], str(results))
        check("UpdateTask: на пустых метаданных вызов один",
              len(pip_calls) == 1, str(pip_calls))
    finally:
        watermark_manager._run_pip = real_pip_upd

    # модуль не установлен/метаданных нет — отказ без запуска pip
    watermark_manager.installed_version = lambda n: ""
    watermark_manager.pypi_latest = lambda n: ver_new[n]
    try:
        results = run_update()
        check("UpdateTask: без пакета — отказ, версию не определить",
              bool(results) and results[0][0] is False
              and "iopaint" in results[0][2], str(results))
    finally:
        watermark_manager._run_pip = real_pip_upd

    # Florence-2: ревизия кэша отличается — snapshot_download свежего
    fake_hub = types.ModuleType("huggingface_hub")
    hub_calls: list[str] = []
    fake_hub.snapshot_download = lambda repo: hub_calls.append(repo)
    saved_hub = sys.modules.get("huggingface_hub")
    sys.modules["huggingface_hub"] = fake_hub
    pip_calls = upd_pip_calls()
    watermark_manager.installed_version = lambda n: ver_equal[n]
    watermark_manager.pypi_latest = lambda n: ver_equal[n]
    watermark_manager.hf_latest_sha = lambda repo: "bbb2222"
    watermark_manager._florence_cached_sha = lambda repo: "aaa1111"
    watermark_manager.lama_file = lambda: ""
    try:
        results = run_update()
        check("UpdateTask: Florence-2 — snapshot_download свежей ревизии",
              bool(results) and hub_calls == ["microsoft/Florence-2-base"],
              str(hub_calls))
        check("UpdateTask: Florence-2 — обновление в итоге",
              bool(results) and i18n.tr("viewer.wm_update_model",
                                        model="Florence-2-base") in results[0][1],
              results[0][1] if results else "")
        check("UpdateTask: Florence-2 — pip не звался", pip_calls == [])
    finally:
        watermark_manager._run_pip = real_pip_upd
        if saved_hub is not None:
            sys.modules["huggingface_hub"] = saved_hub
        else:
            sys.modules.pop("huggingface_hub", None)

    # huggingface.co недоступен: пакеты не тронуты, отказ — не фатален
    watermark_manager.hf_latest_sha = lambda repo: ""
    try:
        results = run_update()
        check("UpdateTask: HF недоступен — итог с пометкой, успех",
              bool(results) and results[0][0] is True
              and i18n.tr("viewer.wm_update_model_fail",
                          model="Florence-2-base",
                          info="huggingface.co") in results[0][1],
              str(results))
    finally:
        watermark_manager._run_pip = real_pip_upd

    # snapshot_download упал: неудача докладывается, модуль остался цел
    fake_hub = types.ModuleType("huggingface_hub")

    def _hub_boom(repo):
        raise RuntimeError("boom: disk full")

    fake_hub.snapshot_download = _hub_boom
    sys.modules["huggingface_hub"] = fake_hub
    watermark_manager.hf_latest_sha = lambda repo: "bbb2222"
    watermark_manager._florence_cached_sha = lambda repo: "aaa1111"
    try:
        results = run_update()
        check("UpdateTask: сбой snapshot_download — честная пометка",
              bool(results) and results[0][0] is True
              and "boom: disk full" in results[0][1], str(results))
    finally:
        watermark_manager._run_pip = real_pip_upd
        if saved_hub is not None:
            sys.modules["huggingface_hub"] = saved_hub
        else:
            sys.modules.pop("huggingface_hub", None)

    # big-lama: размер релиза отличается — перекачка штатным LaMa.download()
    fake_lama_upd = types.ModuleType("iopaint.model.lama")
    lama_state = {"downloads": 0}

    class _FakeLaMaUpd:
        @staticmethod
        def download():
            lama_state["downloads"] += 1

    fake_lama_upd.LaMa = _FakeLaMaUpd
    fake_lama_upd.LAMA_MODEL_URL = "http://example.com/big-lama.pt"
    saved_lama_upd = sys.modules.get("iopaint.model.lama")
    sys.modules["iopaint.model.lama"] = fake_lama_upd
    watermark_manager.lama_file = lambda: lama_u
    watermark_manager._lama_url = lambda: "http://example.com/big-lama.pt"
    watermark_manager.hf_latest_sha = lambda repo: "cafe"
    watermark_manager._florence_cached_sha = lambda repo: "cafe"
    try:
        pip_calls = upd_pip_calls()
        watermark_manager.remote_content_length = lambda url: 2000
        try:
            results = run_update()
            check("UpdateTask: big-lama — файл удалён и перекачан",
                  not os.path.exists(lama_u) and lama_state["downloads"] == 1,
                  str(lama_state))
            check("UpdateTask: big-lama — обновление в итоге",
                  bool(results)
                  and i18n.tr("viewer.wm_update_lama") in results[0][1],
                  results[0][1] if results else "")
        finally:
            watermark_manager._run_pip = real_pip_upd
        # размер совпал — модель актуальна, файл на месте
        with open(lama_u, "wb") as f:
            f.write(b"L" * 2000)
        pip_calls = upd_pip_calls()
        watermark_manager.remote_content_length = lambda url: 2000
        try:
            results = run_update()
            check("UpdateTask: big-lama актуален — файл и качание не тронуты",
                  os.path.exists(lama_u) and lama_state["downloads"] == 1
                  and pip_calls == []
                  and i18n.tr("viewer.wm_update_nothing", pkgs=
                              "iopaint 1.6.0, transformers 4.48.3, timm 1.0.15")
                  == results[0][1], str(results))
        finally:
            watermark_manager._run_pip = real_pip_upd
        # размер узнать не удалось — пометка в итоге, файл не тронут
        watermark_manager.remote_content_length = lambda url: 0
        try:
            results = run_update()
            check("UpdateTask: big-lama недоступен — пометка, файл цел",
                  os.path.exists(lama_u) and lama_state["downloads"] == 1
                  and i18n.tr("viewer.wm_update_lama_fail",
                              info="github.com") in results[0][1],
                  results[0][1] if results else "")
        finally:
            watermark_manager._run_pip = real_pip_upd
    finally:
        if saved_lama_upd is not None:
            sys.modules["iopaint.model.lama"] = saved_lama_upd
        else:
            sys.modules.pop("iopaint.model.lama", None)

    # восстановить всё, что подменял блок обновления
    watermark_manager.installed_version = real_ver
    watermark_manager.pypi_latest = real_pypi
    watermark_manager._iopaint_requires = real_reqs_upd
    watermark_manager.hf_latest_sha = real_hfsha
    watermark_manager._florence_cached_sha = real_cached
    watermark_manager.lama_file = real_lama_file
    watermark_manager._lama_url = real_lama_url
    watermark_manager.remote_content_length = real_head

    # ---------- RemoveWatermarkTask без модуля: честные ошибки ----------
    png = os.path.join(tmpdir, "cat.png")
    from PIL import Image
    # 50×50: «водяной знак» стаба 24..31 с margin 15 даёт 58% кадра —
    # меньше предохранителя покрытия (60%), иначе честная ошибка вместо результата
    Image.new("RGB", (50, 50), (0, 128, 0)).save(png, "PNG")

    sig = watermark_manager.WatermarkSignals()
    files: list[tuple] = []
    batches: list[tuple] = []
    sig.file_done.connect(
        lambda p, out, ok, err: files.append((p, out, ok, err)))
    sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
    prepares: list[str] = []
    sig.model_prepare.connect(lambda m: prepares.append(m))
    QThreadPool.globalInstance().start(
        watermark_manager.RemoveWatermarkTask([(png, png + "_x")], "m", sig))
    wait_until(lambda: bool(batches))
    check("без модуля: batch_done(0, 1)",
          batches == [(0, 1)], str(batches))
    check("без модуля: file_done с ошибкой",
          bool(files) and files[0][2] is False and files[0][1] == "",
          str(files))
    check("без модуля: модель сначала «готовится»",
          prepares == ["m"], str(prepares))

    # ---------- RemoveWatermarkTask со стабами конвейера: файлы ----------
    real_pipeline = watermark_manager._load_pipeline

    def fake_detect(pil_img):
        # «водяной знак» в правом нижнем углу — по цвету узнаем результат;
        # с v0.8.14 детекция отдаёт ПОЛИГОНЫ (список точек), не боксы
        return [[(24, 24), (31, 24), (31, 31), (24, 31)]]

    def fake_inpaint(rgb, mask):
        rgb = rgb.copy()
        rgb[mask > 0] = (255, 0, 0)   # закрашенная область — красная
        return rgb

    watermark_manager._load_pipeline = (
        lambda model_id: (fake_inpaint, fake_detect))
    sig = watermark_manager.WatermarkSignals()
    files, batches, readies = [], [], []
    sig.file_done.connect(
        lambda p, out, ok, err: files.append((p, out, ok, err)))
    sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
    sig.model_ready.connect(lambda m: readies.append(m))
    QThreadPool.globalInstance().start(
        watermark_manager.RemoveWatermarkTask(
            [(png, os.path.join(tmpdir, "cat_nowm.png"))], "m", sig))
    wait_until(lambda: bool(batches))
    check("со стабом: batch_done(1, 0)", batches == [(1, 0)], str(batches))
    check("со стабом: модели готовы", readies == ["m"], str(readies))
    out_path = os.path.join(tmpdir, "cat_nowm.png")
    check("со стабом: файл-результат создан", os.path.exists(out_path))
    if os.path.exists(out_path):
        src = Image.open(png).convert("RGB")
        dst = Image.open(out_path).convert("RGB")
        check("со стабом: маска перекрашена в красный",
              dst.getpixel((25, 25)) == (255, 0, 0))
        check("со стабом: остальное — оригинал",
              dst.getpixel((0, 0)) == src.getpixel((0, 0)))
        check("со стабом: оригинал цел",
              src.getpixel((25, 25)) == (0, 128, 0))

    # ---------- предохранитель покрытия маски (v0.8.14) ----------
    # маска 70% кадра: rect (0,0,99,54) + margin 15 → 70 строк из 100 —
    # честная ошибка, файл-результат НЕ создаётся
    big = os.path.join(tmpdir, "big.png")
    Image.new("RGB", (100, 100), (0, 128, 0)).save(big, "PNG")
    big_rect = [[(0.0, 0.0), (99.0, 0.0), (99.0, 54.0), (0.0, 54.0)]]
    watermark_manager._load_pipeline = (
        lambda model_id: (fake_inpaint, lambda img: big_rect))
    sig = watermark_manager.WatermarkSignals()
    files, batches = [], []
    sig.file_done.connect(
        lambda p, out, ok, err: files.append((p, out, ok, err)))
    sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
    QThreadPool.globalInstance().start(
        watermark_manager.RemoveWatermarkTask(
            [(big, os.path.join(tmpdir, "big_nowm.png"))], "m", sig))
    wait_until(lambda: bool(batches))
    check("покрытие 70%: ошибка, файла-результата нет",
          batches == [(0, 1)] and bool(files) and files[0][2] is False
          and files[0][1] == "" and "70" in files[0][3], str(files))
    check("покрытие 70%: текст ошибки — ключ wm_cover",
          bool(files) and files[0][3] == i18n.tr("log.event.wm_cover", pct=70),
          files[0][3] if files else "")

    # маска 55% кадра: rect (0,0,99,39) + margin 15 → 55 строк из 100 — результат
    ok_rect = [[(0.0, 0.0), (99.0, 0.0), (99.0, 39.0), (0.0, 39.0)]]
    watermark_manager._load_pipeline = (
        lambda model_id: (fake_inpaint, lambda img: ok_rect))
    sig = watermark_manager.WatermarkSignals()
    files, batches = [], []
    sig.file_done.connect(
        lambda p, out, ok, err: files.append((p, out, ok, err)))
    sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
    QThreadPool.globalInstance().start(
        watermark_manager.RemoveWatermarkTask(
            [(big, os.path.join(tmpdir, "ok_nowm.png"))], "m", sig))
    wait_until(lambda: bool(batches))
    check("покрытие 55%: результат создан",
          batches == [(1, 0)]
          and os.path.exists(os.path.join(tmpdir, "ok_nowm.png")),
          str(batches))

    # файл без найденных знаков: не даёт результата, не считается ошибкой
    watermark_manager._load_pipeline = (
        lambda model_id: (fake_inpaint, lambda img: []))
    clean_png = os.path.join(tmpdir, "clean.png")
    Image.new("RGB", (6, 6), (10, 20, 30)).save(clean_png, "PNG")
    sig = watermark_manager.WatermarkSignals()
    files, batches = [], []
    sig.file_done.connect(
        lambda p, out, ok, err: files.append((p, out, ok, err)))
    sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
    QThreadPool.globalInstance().start(
        watermark_manager.RemoveWatermarkTask(
            [(clean_png, os.path.join(tmpdir, "clean_nowm.png"))], "m", sig))
    wait_until(lambda: bool(batches))
    check("чистый файл: ok без результата",
          files == [(clean_png, "", True, "")], str(files))
    check("чистый файл: файла-результата нет",
          not os.path.exists(os.path.join(tmpdir, "clean_nowm.png")))
    check("чистый файл: batch_done(0, 0)", batches == [(0, 0)], str(batches))
    watermark_manager._load_pipeline = real_pipeline

    # ---------- убирание по выделению: RemoveWatermarkTask с sel (v0.8.22) ----------
    # пожелание: «сделай возможность удалять ватермарки из выделения на
    # картинке». Sel-поток грузит ТОЛЬКО LaMa (_load_inpainter) —
    # _load_pipeline не вызывается вовсе; маска — ровно выделение.
    real_inpainter = watermark_manager._load_inpainter
    pipeline_touched: list[str] = []

    def boom_pipeline(model_id):
        # если sel-поток сунется за детекцией — это увидит проверка ниже
        pipeline_touched.append(model_id)
        return (fake_inpaint, fake_detect)

    sel_masks: list = []

    def sel_inpaint(rgb, mask):
        sel_masks.append(mask.copy())
        return fake_inpaint(rgb, mask)

    watermark_manager._load_pipeline = boom_pipeline
    watermark_manager._load_inpainter = lambda device: sel_inpaint
    sel_png = os.path.join(tmpdir, "selphoto.png")
    Image.new("RGB", (60, 45), (0, 128, 0)).save(sel_png, "PNG")
    sig = watermark_manager.WatermarkSignals()
    files, batches, phases, starts = [], [], [], []
    sig.file_done.connect(
        lambda p, out, ok, err: files.append((p, out, ok, err)))
    sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
    sig.phase.connect(lambda p, code, extra: phases.append(code))
    sig.file_start.connect(lambda p, idx: starts.append((p, idx)))
    QThreadPool.globalInstance().start(
        watermark_manager.RemoveWatermarkTask(
            [(sel_png, os.path.join(tmpdir, "selphoto_nowm.png"))], "m", sig,
            sel=(10, 8, 24, 12)))
    wait_until(lambda: bool(batches))
    check("sel: batch_done(1, 0)", batches == [(1, 0)], str(batches))
    check("sel: детекция не вызывалась (_load_pipeline не трогали)",
          not pipeline_touched, str(pipeline_touched))
    check("sel: file_start до фаз", bool(starts) and starts[0][1] == 1,
          str(starts))
    check("sel: фазы без детекции/поиска — сразу закраска и сохранение",
          phases == ["inpaint", "save"], str(phases))
    m = sel_masks[0]
    check("sel: маска ровно выделение — внутри 255",
          bool((m[8:20, 10:34] == 255).all()), str(m.shape))
    check("sel: маска ровно выделение — рамка чистая (без расширения)",
          m[7, 10] == 0 and m[20, 10] == 0 and m[8, 9] == 0 and m[8, 34] == 0,
          f"{m[7, 10]} {m[20, 10]} {m[8, 9]} {m[8, 34]}")
    out_sel = os.path.join(tmpdir, "selphoto_nowm.png")
    check("sel: файл-результат создан", os.path.exists(out_sel))
    if os.path.exists(out_sel):
        dst = Image.open(out_sel).convert("RGB")
        check("sel: внутри выделения — закраска", dst.getpixel((20, 12)) == (255, 0, 0))
        check("sel: снаружи — оригинал", dst.getpixel((2, 2)) == (0, 128, 0))
        check("sel: оригинал цел",
              Image.open(sel_png).convert("RGB").getpixel((20, 12)) == (0, 128, 0))

    # sel_result_path по диску: занятые имена не затираются
    open(os.path.join(tmpdir, "busy_nowm.png"), "wb").close()
    got = watermark_manager.sel_result_path(os.path.join(tmpdir, "busy.png"))
    check("sel_result_path: имя занято → «busy_nowm-1.png»",
          got == os.path.join(tmpdir, "busy_nowm-1.png"), got)
    open(os.path.join(tmpdir, "busy_nowm-1.png"), "wb").close()
    got = watermark_manager.sel_result_path(os.path.join(tmpdir, "busy.png"))
    check("sel_result_path: заняты оба → «busy_nowm-2.png»",
          got == os.path.join(tmpdir, "busy_nowm-2.png"), got)

    # предохранитель покрытия и для выделения: весь кадр — честный отказ
    sel_big = os.path.join(tmpdir, "selbig.png")
    Image.new("RGB", (100, 100), (0, 128, 0)).save(sel_big, "PNG")
    sig = watermark_manager.WatermarkSignals()
    files, batches = [], []
    sig.file_done.connect(
        lambda p, out, ok, err: files.append((p, out, ok, err)))
    sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
    QThreadPool.globalInstance().start(
        watermark_manager.RemoveWatermarkTask(
            [(sel_big, os.path.join(tmpdir, "selbig_nowm.png"))], "m", sig,
            sel=(0, 0, 100, 100)))
    wait_until(lambda: bool(batches))
    check("sel: покрытие 100% — честный отказ",
          batches == [(0, 1)] and bool(files) and files[0][2] is False,
          str(files))
    check("sel: текст отказа — свой ключ wm_sel_cover (без детектора)",
          bool(files) and files[0][3] == i18n.tr("log.event.wm_sel_cover", pct=100),
          files[0][3] if files else "")
    check("sel: файла-результата нет",
          not os.path.exists(os.path.join(tmpdir, "selbig_nowm.png")))
    watermark_manager._load_pipeline = real_pipeline
    watermark_manager._load_inpainter = real_inpainter

    # ---------- вьюер: кнопка, статус, модель, контекстное меню ----------
    # чужая сохранённая папка (персистентный QSettings от других наборов
    # тестов) не должна восстанавливаться: её фоновый скан перебивает
    # статус пачки («Читаю папку…» → путь) и роняет проверку итога
    st.remove("viewer/last_folder")
    viewer = LocalViewer()
    check("кнопка 🧽 существует", hasattr(viewer, "_on_wm_button"))
    # v0.8.20: «убрать фон и водяные знаки перемести на панель ниже» —
    # обе кнопки переехали на панель инструментов (tools_panel)
    from PySide6.QtWidgets import QToolButton  # noqa: E402
    check("кнопка 🧽 на панели инструментов (v0.8.20)",
          viewer.btn_wm.parent() is viewer.tools_panel,
          type(viewer.btn_wm.parent()).__name__)
    wm_btns = [b for b in viewer.findChildren(QToolButton)
               if b.text() == i18n.tr("viewer.wm")]
    check("🧽 ровно одна — с верхней панели убрана",
          len(wm_btns) == 1,
          str([b.parent().__class__.__name__ for b in wm_btns]))
    _tl = viewer.tools_panel.layout()
    check("🧽 рядом с 🪄, в конце инструментов",
          _tl.indexOf(viewer.btn_wm) > _tl.indexOf(viewer.btn_rembg)
          > _tl.indexOf(viewer.btn_picker),
          str((_tl.indexOf(viewer.btn_wm), _tl.indexOf(viewer.btn_rembg))))
    check("модель по умолчанию",
          viewer._wm_model == watermark_manager.DEFAULT_MODEL,
          viewer._wm_model)
    check("не занят на старте", viewer._wm_busy is False)

    viewer._on_wm_button()
    app_inst.processEvents()
    check("клик без картинки — подсказка в статусе",
          viewer.status.text() == i18n.tr("viewer.wm_none"), viewer.status.text())

    viewer._on_wm_model("microsoft/Florence-2-large")
    st.sync()
    check("выбор детектора запомнился", viewer._wm_model ==
          "microsoft/Florence-2-large")
    viewer2 = LocalViewer()
    check("детектор восстанавливается в новом вьюере",
          viewer2._wm_model == "microsoft/Florence-2-large")
    st.setValue(watermark_manager.MODEL_KEY, "no-such-model")
    viewer3 = LocalViewer()
    check("мусорный детектор → дефолт",
          viewer3._wm_model == watermark_manager.DEFAULT_MODEL,
          viewer3._wm_model)
    st.setValue(watermark_manager.MODEL_KEY, "")

    menu, acts = viewer._build_list_menu()
    texts = [a.text() for a in menu.actions()]
    check("меню: «Убрать водяные знаки» в меню",
          i18n.tr("viewer.wm") in texts, str(texts))
    check("меню: есть действие wm", "wm" in acts)
    menu.close()

    # ---------- установка «на ходу»: отказ и согласие ----------
    viewer._wm_targets = lambda: [png]   # у вьюера нет папки — подставим цель

    # отказ: ничего не запускается (в песочнице модуля нет — вопрос покажется)
    real_question = QMessageBox.question
    QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.No
    try:
        viewer._on_wm_button()
        app_inst.processEvents()
        check("отказ установки: ничего не запущено",
              viewer._wm_busy is False and viewer._wm_pending is None)
    finally:
        QMessageBox.question = real_question

    # согласие: pip стартует, очередь продолжается после установки
    wm_calls: list[list[str]] = []

    def fake_pip3(args):
        wm_calls.append(list(args))
        return True, ""

    class StubWmTask(QRunnable):
        """Заглушка обработки: установка не должна тянуть настоящие модели."""

        def __init__(self, jobs, model, signals):
            super().__init__()
            self.jobs, self.signals = jobs, signals

        def run(self):
            self.signals.batch_done.emit(0, len(self.jobs))

    real_task = watermark_manager.RemoveWatermarkTask
    watermark_manager._run_pip = fake_pip3
    # метаданные iopaint фейковые: в песочнице пакета нет, а установка
    # должна пройти оба шага до конца
    watermark_manager._iopaint_requires = lambda: ["torch>=2.0.0"]
    watermark_manager.RemoveWatermarkTask = StubWmTask
    QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
    try:
        viewer._on_wm_button()
        wait_until(lambda: not viewer._wm_busy, timeout_s=10)
        app_inst.processEvents()
        check("согласие: pip запущен в два шага", len(wm_calls) == 2,
              str(wm_calls))
        check("согласие: очередь обработана после установки",
              viewer._wm_pending is None or viewer._wm_pending == [],
              str(viewer._wm_pending))
        want = (i18n.tr("viewer.wm_done", ok=0)
                + i18n.tr("viewer.wm_done_fail", fail=1))
        check("согласие: очередь честно доложила итог",
              viewer.status.text() == want, viewer.status.text())
        st.sync()
    finally:
        QMessageBox.question = real_question
        watermark_manager._run_pip = real_pip
        watermark_manager._iopaint_requires = real_reqs
        watermark_manager.RemoveWatermarkTask = real_task

    # ---------- пачка через _wm_start со стабом: статус и результат ----------
    marked = os.path.join(tmpdir, "marked.jpg")
    Image.new("RGB", (50, 50), (0, 128, 0)).save(marked, "JPEG", quality=92)
    watermark_manager._load_pipeline = (
        lambda model_id: (fake_inpaint, fake_detect))
    try:
        viewer._wm_start([marked])
        wait_until(lambda: not viewer._wm_busy, timeout_s=10)
        check("пачка: jpg даёт jpg-результат",
              os.path.exists(os.path.join(tmpdir, "marked_nowm.jpg")))
        # итог ловим поллингом: статус пишет обработчик сигнала задачи,
        # единичный флейк песочницы не должен ронять проверку
        check("пачка: итог в статусе",
              wait_until(lambda: viewer.status.text()
                         == i18n.tr("viewer.wm_done", ok=1), timeout_s=10),
              viewer.status.text())
    finally:
        watermark_manager._load_pipeline = real_pipeline

    # ---------- убирание по выделению в вьюере (v0.8.22) ----------
    # кнопка живёт в режиме обрезки: «🪣 Закрасить» → «🧽 Убрать в выделении»
    # → «✂▶ К следующему»
    viewer.resize(1000, 720)
    viewer.show()
    app_inst.processEvents()
    check("вьюер-sel: кнопка на панели инструментов",
          viewer.btn_wm_sel.parent() is viewer.tools_panel,
          type(viewer.btn_wm_sel.parent()).__name__)
    check("вьюер-sel: между «Закрасить» и «К следующему»",
          _tl.indexOf(viewer.btn_wm_sel) > _tl.indexOf(viewer.btn_fill)
          and _tl.indexOf(viewer.btn_wm_sel) < _tl.indexOf(viewer.btn_crop_next),
          str(_tl.indexOf(viewer.btn_wm_sel)))
    check("вьюер-sel: текст и подсказка по i18n",
          viewer.btn_wm_sel.text() == i18n.tr("viewer.wm_sel")
          and i18n.tr("viewer.wm_sel_tip") in viewer.btn_wm_sel.toolTip(),
          viewer.btn_wm_sel.text())
    check("вьюер-sel: скрыта вне режима обрезки",
          not viewer.btn_wm_sel.isVisible(), str(viewer.btn_wm_sel.isVisible()))

    sel_folder = tempfile.mkdtemp(prefix="ih_wm_sel_")
    sel_src = os.path.join(sel_folder, "selphoto.png")
    Image.new("RGB", (60, 45), (0, 128, 0)).save(sel_src, "PNG")
    viewer.load_folder(sel_folder)
    check("вьюер-sel: папка открыта, картинка показана",
          wait_until(lambda: viewer.list.count() == 1
                     and viewer._pixmap is not None and viewer.btn_crop.isEnabled(),
                     timeout_s=15))
    viewer.list.setCurrentRow(0)
    check("вьюер-sel: плитка открыта в просмотре",
          wait_until(lambda: viewer._paths
                     and viewer._paths[viewer.list.currentRow()] == sel_src,
                     timeout_s=10))

    viewer.set_crop_mode(True)
    check("вьюер-sel: в режиме «Убрать в выделении» видна и погашена",
          viewer.btn_wm_sel.isVisible() and not viewer.btn_wm_sel.isEnabled())
    check("вьюер-sel: «Сохранить»/«К следующему» по-прежнему рядом",
          viewer.btn_crop_save.isVisible() and viewer.btn_crop_next.isVisible())

    # выделение честной доставкой событий мыши: (10, 8) → (33, 19) = 24×12
    def sel_drag(view, a, b):
        r = view.pixmap_rect()
        iw = max(1, view._crop_img.width())
        ih = max(1, view._crop_img.height())

        def wpt(ix, iy):
            return QPointF(r.x() + ix * r.width() / iw,
                           r.y() + iy * r.height() / ih)

        pa, pb = wpt(*a), wpt(*b)
        view.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, pa,
                                         Qt.MouseButton.LeftButton,
                                         Qt.MouseButton.LeftButton, Qt.NoModifier))
        view.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, pb,
                                        Qt.NoButton, Qt.MouseButton.LeftButton,
                                        Qt.NoModifier))
        view.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease,
                                           pb, Qt.MouseButton.LeftButton,
                                           Qt.NoButton, Qt.NoModifier))

    sel_drag(viewer.view_label, (10, 8), (33, 19))
    check("вьюер-sel: рамка 24×12 в координатах картинки",
          viewer.view_label.selection() == QRect(10, 8, 24, 12),
          str(viewer.view_label.selection()))
    check("вьюер-sel: с выделением кнопка включилась",
          viewer.btn_wm_sel.isEnabled())

    captured: dict = {}

    class StubSelTask(QRunnable):
        """Стаб sel-задачи: рисует файл-результат и докладывает успех."""

        def __init__(self, jobs, model, signals, sel=None):
            super().__init__()
            self.jobs, self.sel = jobs, sel
            self.signals = signals
            captured["jobs"], captured["sel"] = jobs, sel
            captured["signals"] = signals

        def run(self):
            Image.new("RGB", (60, 45), (255, 0, 0)).save(self.jobs[0][1], "PNG")
            self.signals.file_done.emit(self.jobs[0][0], self.jobs[0][1],
                                        True, "")
            self.signals.batch_done.emit(1, 0)

    real_task_sel = watermark_manager.RemoveWatermarkTask
    real_installed_sel = watermark_manager.is_installed
    watermark_manager.RemoveWatermarkTask = StubSelTask
    watermark_manager.is_installed = lambda: True
    try:
        viewer.btn_wm_sel.click()
        # busy выставляется в обработчике кнопки синхронно: проверяем ДО
        # processEvents, который может доставить уже готовые сигналы
        # пачки и снять busy раньше проверки (флейм на загруженной машине)
        check("вьюер-sel: busy на время работы", viewer._wm_busy is True)
        app_inst.processEvents()
        check("вьюер-sel: клик стартовал задачу с выделением",
              captured.get("sel") == (10, 8, 24, 12), str(captured.get("sel")))
        check("вьюер-sel: работа — один файл «имя_nowm.ext»",
              captured.get("jobs") == [(sel_src, os.path.join(sel_folder,
                                                             "selphoto_nowm.png"))],
              str(captured.get("jobs")))
        wait_until(lambda: not viewer._wm_busy, timeout_s=10)
        check("вьюер-sel: флаг открытия потреблён (итог прошёл через batch_done)",
              viewer._wm_sel_open == "", viewer._wm_sel_open)
        check("вьюер-sel: результат появляется в ленте",
              wait_until(lambda: viewer.list.count() == 2, timeout_s=15))
        # результат открывается в просмотре, режим обрезки встаёт на него —
        # остатки знака можно чистить той же рамкой без перекликивания
        check("вьюер-sel: результат открыт и режим на месте",
              wait_until(lambda: viewer._paths
                         and 0 <= viewer.list.currentRow() < len(viewer._paths)
                         and viewer._paths[viewer.list.currentRow()].endswith(
                             "selphoto_nowm.png")
                         and viewer._crop_mode and viewer._pixmap is not None,
                         timeout_s=15),
              f"row={viewer.list.currentRow()} crop={viewer._crop_mode}")

        # итеративная чистка: выделение на УЖЕ готовом «_nowm»-результате —
        # имя уезжает в следующий свободный номер, ничего не затирается
        sel_drag(viewer.view_label, (40, 30), (59, 44))
        captured.clear()
        viewer.btn_wm_sel.click()
        app_inst.processEvents()
        check("вьюер-sel: чистка результата → «selphoto_nowm-1.png»",
              captured.get("jobs")
              == [(os.path.join(sel_folder, "selphoto_nowm.png"),
                   os.path.join(sel_folder, "selphoto_nowm-1.png"))],
              str(captured.get("jobs")))
        wait_until(lambda: not viewer._wm_busy, timeout_s=10)
        check("вьюер-sel: второй результат в ленте",
              wait_until(lambda: viewer.list.count() == 3, timeout_s=15))
        # дождаться, пока второй результат открылся и режим встал на него:
        # дальше рисуется новое выделение на УЖЕ показанном результате
        check("вьюер-sel: второй результат открыт, режим на нём",
              wait_until(lambda: viewer._paths
                         and 0 <= viewer.list.currentRow() < len(viewer._paths)
                         and viewer._paths[viewer.list.currentRow()].endswith(
                             "selphoto_nowm-1.png")
                         and viewer._pixmap is not None and viewer._crop_mode,
                         timeout_s=15),
              f"row={viewer.list.currentRow()} crop={viewer._crop_mode}")
    finally:
        watermark_manager.RemoveWatermarkTask = real_task_sel
        watermark_manager.is_installed = real_installed_sel

    # ---------- «Убрать в выделении» без модуля: отказ и согласие ----------
    viewer.set_crop_mode(True)   # идемпотентно: режим уже на результате
    sel_drag(viewer.view_label, (5, 5), (20, 15))
    captured.clear()
    inst_calls: list[int] = []

    def fake_installed_once():
        # #1 — клик-отказ, #2 — клик-согласие (пока модуля нет),
        # #3 — продолжение из _on_wm_install_done (модуль «установился»)
        inst_calls.append(1)
        return len(inst_calls) > 2

    pip_calls: list[list[str]] = []

    def fake_pip_sel(args):
        pip_calls.append(list(args))
        return True, ""

    real_installed2 = watermark_manager.is_installed
    real_pip_sel = watermark_manager._run_pip
    real_reqs_sel = watermark_manager._iopaint_requires
    real_task3 = watermark_manager.RemoveWatermarkTask
    watermark_manager.is_installed = fake_installed_once
    watermark_manager._run_pip = fake_pip_sel
    watermark_manager._iopaint_requires = lambda: ["torch>=2.0.0"]
    watermark_manager.RemoveWatermarkTask = StubSelTask   # после установки sel продолжится стабом
    real_question = QMessageBox.question
    QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.No
    try:
        viewer.btn_wm_sel.click()
        app_inst.processEvents()
        check("вьюер-sel: отказ установки — ничего не стартовало",
              viewer._wm_busy is False and not viewer._wm_sel_pending
              and not pip_calls and not captured,
              f"busy={viewer._wm_busy} pip={len(pip_calls)}")

        QMessageBox.question = (lambda *a, **kw: QMessageBox.StandardButton.Yes)
        viewer.btn_wm_sel.click()
        app_inst.processEvents()
        # pip идёт в рабочем потоке — дождаться первых вызовов поллингом
        check("вьюер-sel: согласие — pip стартовал",
              wait_until(lambda: bool(pip_calls), timeout_s=10),
              f"pip={len(pip_calls)} busy={viewer._wm_busy}")
        wait_until(lambda: not viewer._wm_busy, timeout_s=15)
        app_inst.processEvents()
        check("вьюер-sel: после установки выделение обработано",
              bool(captured) and captured.get("sel") == (5, 5, 16, 11),
              str(captured.get("sel")))
        check("вьюер-sel: флаг ожидания снят", viewer._wm_sel_pending is False)
        st.sync()
    finally:
        QMessageBox.question = real_question
        watermark_manager.is_installed = real_installed2
        watermark_manager._run_pip = real_pip_sel
        watermark_manager._iopaint_requires = real_reqs_sel
        watermark_manager.RemoveWatermarkTask = real_task3

    # клик без выделения — молчаливый выход (кнопка и так погашена)
    viewer.view_label._crop_sel = None
    viewer.view_label.crop_selection_changed.emit()
    app_inst.processEvents()
    check("вьюер-sel: без выделения кнопка погашена и клик ничего не делает",
          not viewer.btn_wm_sel.isEnabled() and viewer._wm_busy is False)
    viewer.set_crop_mode(False)

    # ---------- обновление модуля из вьюера (v0.8.15) ----------
    real_upd_installed = watermark_manager.is_installed
    watermark_manager.is_installed = lambda: True
    real_upd_task = watermark_manager.UpdateTask
    upd_started: list[str] = []

    class StubUpdTask(QRunnable):
        """Стаб задачи обновления: сигнал успеха без сети и pip-а."""

        def __init__(self, signals, model):
            super().__init__()
            self.signals, self.model = signals, model
            upd_started.append(model)

        def run(self):
            self.signals.update_done.emit(
                True,
                "iopaint 1.6.0 → 1.7.0. " + i18n.tr("viewer.wm_update_restart"),
                "")

    watermark_manager.UpdateTask = StubUpdTask
    upd_boxes: list[str] = []
    real_info_wm = QMessageBox.information
    real_warn_wm = QMessageBox.warning
    QMessageBox.information = lambda *a, **k: upd_boxes.append("info")
    QMessageBox.warning = lambda *a, **k: upd_boxes.append("warn")
    try:
        viewer.wm_update()
        check("вьюер: обновление стартовало с выбранным детектором",
              upd_started == [viewer._wm_model] and viewer._wm_busy is True,
              str(upd_started))
        wait_until(lambda: not viewer._wm_busy, timeout_s=10)
        app_inst.processEvents()
        want_upd = i18n.tr(
            "viewer.wm_update_done",
            what="iopaint 1.6.0 → 1.7.0. " + i18n.tr("viewer.wm_update_restart"))
        check("вьюер: итог обновления в статусе",
              viewer.status.text() == want_upd, viewer.status.text())
        check("вьюер: окно об успехе обновления",
              upd_boxes[-1:] == ["info"], str(upd_boxes))

        viewer._wm_busy = True
        viewer.wm_update()
        check("вьюер: пока busy — второй запуск не нужен",
              viewer._wm_busy is True and len(upd_started) == 1
              and viewer.status.text() == i18n.tr("viewer.wm_busy"),
              viewer.status.text())
        viewer._wm_busy = False

        # отказ: честная ошибка в статусе и окно-предупреждение
        viewer._wm_signals.update_done.emit(False, "", "pypi недоступен")
        app_inst.processEvents()
        check("вьюер: отказ обновления — статус и предупреждение",
              viewer.status.text() == i18n.tr("viewer.wm_update_fail",
                                              info="pypi недоступен")
              and upd_boxes[-1:] == ["warn"], str(upd_boxes))

        # модуль не установлен — обновление не запускается вовсе
        watermark_manager.is_installed = lambda: False
        viewer.wm_update()
        check("вьюер: без модуля обновление не стартует",
              viewer._wm_busy is False and len(upd_started) == 1)
    finally:
        watermark_manager.UpdateTask = real_upd_task
        watermark_manager.is_installed = real_upd_installed
        QMessageBox.information = real_info_wm
        QMessageBox.warning = real_warn_wm

    # ---------- _ensure_stdio: pythonw-сценарий (None-stdio) ----------
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = None
    sys.stderr = None
    try:
        watermark_manager._ensure_stdio()
        st_ok = sys.stdout is not None and sys.stderr is not None
        watermark_manager._ensure_stdio()   # повторный вызов идемпотентен
        idem_ok = sys.stdout is not None and sys.stderr is not None
        # HF-прогресс-бары: без huggingface_hub не должен падать
        watermark_manager._disable_hf_progress()
        hf_ok = True
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
    check("_ensure_stdio: None-stdout подменён заглушкой", st_ok)
    check("_ensure_stdio: повторный вызов идемпотентен", idem_ok)
    check("_disable_hf_progress: без huggingface_hub не падает", hf_ok)

    # ---------- i18n: все ключи на трёх языках ----------
    missing = []
    for key in WM_KEYS:
        for lang in i18n.LANGS:
            if not i18n._STRINGS.get(key, {}).get(lang):
                missing.append(f"{key}:{lang}")
    check("i18n: все ключи wm заполнены на ru/en/zh", not missing,
          ", ".join(missing))

    st.sync()
    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
