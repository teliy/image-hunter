"""Оффлайн-тест модуля удаления водяных знаков (Florence-2 + LaMa, v0.8.11;
двухшаговая установка без пина Pillow — v0.8.12).

Проверяется:
- watermark_manager: is_installed, nowm_path (формат сохраняется, AVIF → PNG,
  GIF и повторная обработка результата отклоняются), mask_from_boxes
  (расширение на margin, склейка координат, обрезка по краям, объединение);
- фильтр требований iopaint: пин Pillow==9.5.0 выбрасывается (у версии нет
  сборок под Python 3.12/3.13 — сборка старого исходника падает с
  «KeyError: '__version__'»), остальное из его же метаданных сохраняется;
- InstallTask ставит модуль в два pip-шага (iopaint --no-deps, затем
  зависимости из метаданных без Pillow + transformers/timm), при отказе
  первого шага второй не запускается, на пустых метаданных — честный
  отказ; сигнал install_done доходит во всех ветках;
- UninstallTask удаляет дистрибуции модуля вместе с прямыми зависимостями
  iopaint из его метаданных (opencv — лишь когда rembg не стоит), вычищает
  свои кэши моделей (big-lama, Florence-2), чужие кэши не трогает,
  рапортует освобождёнными мегабайтами;
- RemoveWatermarkTask без установленного модуля честно репортит ошибку по
  каждому файлу (batch_done(0, N)); со стабами конвейера (_load_pipeline)
  создаёт «имя_nowm.ext»: область маски перекрашена, остальное — оригинал,
  оригинал цел; файл без найденных знаков не даёт файла-результата;
- кнопка 🧽 есть, клик без выбора картинки даёт подсказку в статусе;
- «Убрать водяные знаки» без модуля предлагает установку (стаб вопроса):
  отказ ничего не запускает, согласие ставит pip и продолжает очередь
  (_wm_pending) после установки;
- выбор детектора (base/large) запоминается в QSettings и валидируется;
- контекстное меню ленты содержит «Убрать водяные знаки»;
- пачка через _wm_start: jpg даёт jpg-результат, итог — в статусе;
- _ensure_stdio/_disable_hf_progress: pythonw-сценарий не роняет модуль;
- i18n: все новые ключи заполнены на ru/en/zh; версия — 0.8.12.

Раздел меню «Модули» проверяет scripts/test_modules_menu.py.
Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_watermark.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QRunnable, QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import app  # noqa: E402
from app.core import i18n  # noqa: E402
from app.ui import rembg_manager, watermark_manager  # noqa: E402
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
    "viewer.wm_installing", "viewer.wm_install_ok", "viewer.wm_install_fail",
    "viewer.wm_uninst_q", "viewer.wm_uninstalling", "viewer.wm_uninst_ok",
    "viewer.wm_uninst_fail", "viewer.wm_menu_install",
    "viewer.wm_menu_uninstall", "viewer.wm_model_menu",
    "viewer.wm_model_base", "viewer.wm_model_large", "viewer.wm_prepare",
    "viewer.wm_ready", "log.event.wm_start", "log.event.wm_file_err",
    "log.event.wm_done", "log.event.wm_skip", "log.event.wm_model",
    "log.event.wm_install_start", "log.event.wm_install_done",
    "log.event.wm_install_fail", "log.event.wm_uninstall_start",
    "log.event.wm_uninstall_done", "log.event.wm_uninstall_fail",
    "modules.wm_header",
]


def main() -> int:
    app_inst = QApplication.instance() or QApplication([])
    i18n.set_lang("ru", persist=False)   # детерминированный язык статусов
    st = QSettings("ImageHunter", "ImageHunter")
    st.sync()

    check("версия 0.8.12", app.__version__ == "0.8.12", app.__version__)

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

    # ---------- фильтр требований iopaint: пин Pillow выбрасывается ----------
    real_reqs = watermark_manager._iopaint_requires
    watermark_manager._iopaint_requires = lambda: [
        "Pillow==9.5.0", "torch>=2.0.0", "pydantic>=2.5.2",
        "foo-bar; python_version < '3.10'"]
    reqs = watermark_manager._module_requirements()
    check("требования iopaint: Pillow выброшен, остальные с маркерами",
          reqs == ["torch>=2.0.0", "pydantic>=2.5.2",
                   "foo-bar; python_version < '3.10'"], str(reqs))
    names = watermark_manager._module_dep_names()
    check("имена для удаления: Pillow и opencv не попадают",
          names == ["torch", "pydantic", "foo-bar"], str(names))
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

    # фейковые метаданные iopaint: пин Pillow должен уйти из шага 2
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
              and "torch>=2.0.0" in second and "gradio==4.21.0" in second
              and "transformers" in second and "timm" in second, str(second))
        check("InstallTask: пин Pillow не ставится",
              not any(str(p).lower().startswith("pillow") for p in second),
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
        QThreadPool.globalInstance().start(watermark_manager.UninstallTask(sig))
        wait_until(lambda: bool(results))
        check("UninstallTask: сигнал дошёл", bool(results), str(results))
        args = uninstall_calls[0] if uninstall_calls else []
        check("UninstallTask: pip uninstall -y iopaint",
              args[:2] == ["uninstall", "-y"] and "iopaint" in args, str(args))
        check("UninstallTask: torch вычищается", "torch" in args, str(args))
        check("UninstallTask: кэши моделей удалены",
              not os.path.exists(lama_fake) and not os.path.exists(flo_fake))
        check("UninstallTask: чужие кэши не тронуты",
              os.path.exists(alien_fake))
        check("UninstallTask: освобождено ≥3 МБ",
              bool(results) and results[0][2] >= 3, str(results))
    finally:
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

    # ---------- RemoveWatermarkTask без модуля: честные ошибки ----------
    png = os.path.join(tmpdir, "cat.png")
    from PIL import Image
    # 40×40: «водяной знак» 24..32 с margin 15 не накрывает картинку целиком
    Image.new("RGB", (40, 40), (0, 128, 0)).save(png, "PNG")

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
        # «водяной знак» в правом нижнем углу — по цвету узнаем результат
        return [(24, 24, 31, 31)]

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

    # ---------- вьюер: кнопка, статус, модель, контекстное меню ----------
    viewer = LocalViewer()
    check("кнопка 🧽 существует", hasattr(viewer, "_on_wm_button"))
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
    Image.new("RGB", (40, 40), (0, 128, 0)).save(marked, "JPEG", quality=92)
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
