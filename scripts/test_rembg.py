"""Оффлайн-тест удаления фона (rembg) — модуль, кнопка, контекстное меню (v0.7.12).

Проверяется:
- rembg_manager: is_installed, model_cache_dirs, models_size;
- nobg_path: X.ext -> X_nobg.png, повторная обработка результата отклоняется;
- InstallTask вызывает pip c верными аргументами (без окна терминала) и
  сигнал install_done доходит;
- установка через вьюер продолжает отложенную обработку (_rembg_pending);
- UninstallTask удаляет пакет и кэш моделей целиком (~/.rembg, ~/.u2net);
- RemoveBgTask: без установленного rembg честно репортит ошибку по каждому
  файлу (batch_done(0, N)), с настоящим rembg (если пакет стоит в окружении)
  создаёт X_nobg.png — в том числе при sys.stdout/stderr = None (pythonw
  на Windows: скачивание модели падало с "'NoneType' object has no
  attribute 'write'" — tqdm в pooch; фикс _ensure_stdio, репорт после 0.7.12);
- _ensure_stdio: None-stdio подменяется заглушками, вызов идемпотентен;
- кнопка 🪄 есть, клик без выбора картинки даёт подсказку в статусе;
- контекстное меню ленты содержит «Удалить фон», подменю «Модель» и пункт
  установки/удаления модуля;
- выбор модели запоминается в QSettings и валидируется при загрузке;
- i18n: все новые ключи заполнены на ru/en/zh.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_rembg.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRunnable, QSettings, QThreadPool  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from app.core import i18n  # noqa: E402
from app.ui import rembg_manager  # noqa: E402
from app.ui.local_viewer import LocalViewer  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(cond, timeout_s: float = 10.0) -> bool:
    app = QApplication.instance()
    end = os.times()[4] + timeout_s
    while os.times()[4] < end:
        app.processEvents()
        if cond():
            return True
        app.processEvents()
    return cond()


REMBG_KEYS = [
    "viewer.rembg", "viewer.rembg_tip", "viewer.rembg_none",
    "viewer.rembg_busy", "viewer.rembg_already", "viewer.rembg_progress",
    "viewer.rembg_done", "viewer.rembg_done_fail", "viewer.rembg_inst_q",
    "viewer.rembg_installing", "viewer.rembg_install_ok",
    "viewer.rembg_install_fail", "viewer.rembg_uninst_q",
    "viewer.rembg_uninstalling", "viewer.rembg_uninst_ok",
    "viewer.rembg_uninst_fail", "viewer.rembg_menu_install",
    "viewer.rembg_menu_uninstall", "viewer.rembg_model_menu",
    "viewer.rembg_model_u2netp", "viewer.rembg_model_u2net",
    "viewer.rembg_model_isnet", "log.event.rembg_start",
    "log.event.rembg_file_err", "log.event.rembg_done",
    "log.event.rembg_skip", "log.event.rembg_model",
    "log.event.rembg_install_start", "log.event.rembg_install_done",
    "log.event.rembg_install_fail", "log.event.rembg_uninstall_start",
    "log.event.rembg_uninstall_done", "log.event.rembg_uninstall_fail",
]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)

    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("viewer/last_folder", "")
    st.setValue("viewer/last_query", "")
    st.setValue("viewer/favorites", [])
    st.setValue("viewer/rembg_model", "")
    st.sync()

    # ---------- чистые функции менеджера ----------
    check("is_installed возвращает bool",
          isinstance(rembg_manager.is_installed(), bool))

    check("nobg_path: jpg -> png",
          rembg_manager.nobg_path("/d/photo.jpg") == "/d/photo_nobg.png",
          rembg_manager.nobg_path("/d/photo.jpg"))
    check("nobg_path: результат уже помечен — отказ",
          rembg_manager.nobg_path("/d/photo_nobg.png") == "")
    check("nobg_path: без расширения",
          rembg_manager.nobg_path("/d/photo") == "/d/photo_nobg.png")

    check("model_cache_dirs: .rembg и .u2net",
          [os.path.basename(d) for d in rembg_manager.model_cache_dirs()]
          == [".rembg", ".u2net"],
          str(rembg_manager.model_cache_dirs()))
    # тесту нужен пустой кэш: от скачанных ранее прогонами/вручную моделей
    # (е2е ниже сам скачает модель заново — часть сценария None-stdio)
    for d in rembg_manager.model_cache_dirs():
        shutil.rmtree(d, ignore_errors=True)
    check("models_size: пусто = 0", rembg_manager.models_size() == 0)

    # ---------- вьюер: кнопка и начальное состояние ----------
    viewer = LocalViewer()
    check("кнопка 🪄 существует", hasattr(viewer, "_on_rembg_button"))
    check("модель по умолчанию",
          viewer._rembg_model == rembg_manager.DEFAULT_MODEL, viewer._rembg_model)
    check("не занят на старте", viewer._rembg_busy is False)

    viewer._on_rembg_button()
    app.processEvents()
    check("клик без картинки — подсказка в статусе",
          viewer.status.text() == i18n.tr("viewer.rembg_none"), viewer.status.text())

    viewer._on_rembg_model("u2net")
    st.sync()
    check("выбор модели сохранён",
          st.value("viewer/rembg_model", "", type=str) == "u2net")
    viewer2 = LocalViewer()
    check("модель восстанавливается в новом вьюере", viewer2._rembg_model == "u2net")
    # мусорная модель в настройках откатывается на дефолт
    st.setValue("viewer/rembg_model", "no-such-model")
    viewer3 = LocalViewer()
    check("мусорная модель -> дефолт",
          viewer3._rembg_model == rembg_manager.DEFAULT_MODEL, viewer3._rembg_model)
    st.setValue("viewer/rembg_model", "")

    # ---------- контекстное меню ----------
    menu, acts = viewer._build_list_menu()
    texts = [a.text() for a in menu.actions()]
    check("меню: «Удалить фон» в меню",
          i18n.tr("viewer.rembg") in texts, str(texts))
    check("меню: подменю «Модель»",
          i18n.tr("viewer.rembg_model_menu") in texts)
    model_menu = next((a.menu() for a in menu.actions()
                       if a.menu()
                       and a.text() == i18n.tr("viewer.rembg_model_menu")), None)
    got_models = [a.text() for a in model_menu.actions()] if model_menu else []
    check("меню: три модели",
          len(got_models) == len(rembg_manager.REMBG_MODELS), str(got_models))
    if rembg_manager.is_installed():
        check("меню: пункт удаления модуля",
              "uninst" in acts and "inst" not in acts, str(list(acts)))
    else:
        check("меню: пункт установки модуля",
              "inst" in acts and "uninst" not in acts, str(list(acts)))
    menu.close()

    # ---------- InstallTask: аргументы pip и доставка сигнала ----------
    calls: list[list[str]] = []
    real_pip = rembg_manager._run_pip

    def fake_pip(args):
        calls.append(list(args))
        return True, ""

    rembg_manager._run_pip = fake_pip
    try:
        sig = rembg_manager.RembgSignals()
        results: list[tuple] = []
        sig.install_done.connect(lambda ok, info: results.append((ok, info)))
        QThreadPool.globalInstance().start(rembg_manager.InstallTask(sig))
        wait_until(lambda: bool(results))
        check("InstallTask: сигнал дошёл",
              bool(results) and results[0][0] is True)
        check("InstallTask: pip install rembg[cpu]",
              bool(calls) and calls[0][:2] == ["install", "--disable-pip-version-check"]
              and "rembg[cpu]" in calls[0], str(calls))
    finally:
        rembg_manager._run_pip = real_pip

    # ---------- установка через вьюер: очередь продолжается ----------
    tmpdir = tempfile.mkdtemp(prefix="ih_rembg_")
    png = os.path.join(tmpdir, "cat.png")
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(QColor(200, 30, 30))
    check("тестовая картинка создана", img.save(png, "PNG"))

    calls.clear()

    def fake_pip2(args):
        calls.append(list(args))
        return True, ""

    rembg_manager._run_pip = fake_pip2
    real_task = rembg_manager.RemoveBgTask

    class StubTask(QRunnable):
        """Заглушка обработки: установка не должна тянуть настоящую модель."""

        def __init__(self, jobs, model, signals):
            super().__init__()
            self.jobs, self.signals = jobs, signals

        def run(self):
            self.signals.batch_done.emit(0, len(self.jobs))

    rembg_manager.RemoveBgTask = StubTask
    try:
        viewer._rembg_start_install(pending=[png])
        # после установки вьюер должен сам продолжить обработку очереди
        wait_until(lambda: not viewer._rembg_busy, timeout_s=10)
        app.processEvents()
        check("установка запустила pip", len(calls) == 1, str(calls))
        check("очередь обработана после установки",
              viewer._rembg_pending is None or viewer._rembg_pending == [],
              str(viewer._rembg_pending))
        st.sync()
    finally:
        rembg_manager._run_pip = real_pip
        rembg_manager.RemoveBgTask = real_task

    # ---------- _ensure_stdio: pythonw-сценарий (None-stdio) ----------
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = None
    sys.stderr = None
    try:
        rembg_manager._ensure_stdio()
        st_ok = sys.stdout is not None and sys.stderr is not None
        rembg_manager._ensure_stdio()   # повторный вызов не должен ничего ломать
        idem_ok = sys.stdout is not None and sys.stderr is not None
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
    check("_ensure_stdio: None-stdout подменён заглушкой", st_ok)
    check("_ensure_stdio: повторный вызов идемпотентен", idem_ok)

    # ---------- RemoveBgTask: ошибка без модуля / e2e с модулем ----------
    if not rembg_manager.is_installed():
        fake_png = os.path.join(tmpdir, "x.png")
        with open(fake_png, "wb") as f:
            f.write(b"png")
        sig = rembg_manager.RembgSignals()
        per_file: list[tuple] = []
        batches: list[tuple] = []
        sig.file_done.connect(lambda p, o, ok, e: per_file.append((p, ok, e)))
        sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
        QThreadPool.globalInstance().start(
            rembg_manager.RemoveBgTask([(fake_png, fake_png + ".out")],
                                       "u2netp", sig))
        wait_until(lambda: bool(batches))
        check("RemoveBgTask без модуля: ошибка репортится",
              len(per_file) == 1 and per_file[0][1] is False, str(per_file))
        check("RemoveBgTask без модуля: batch_done(0, 1)",
              batches == [(0, 1)], str(batches))
    else:
        # настоящий rembg, ровно сценарий пользователя (репорт после 0.7.12):
        # моделей нет (кэш вычищен — как после установки) и программа
        # запущена без консоли (pythonw): sys.stdout/sys.stderr равны None.
        # Раньше скачивание модели падало с "'NoneType' object has no
        # attribute 'write'" (tqdm в pooch пишет в stderr) — удаление
        # фона не работало вовсе. Теперь _ensure_stdio чинит stdio, модель
        # скачивается и обработка доходит до файла-результата.
        shutil.rmtree(os.path.join(os.path.expanduser("~"), ".rembg"),
                      ignore_errors=True)
        shutil.rmtree(os.path.join(os.path.expanduser("~"), ".u2net"),
                      ignore_errors=True)
        saved_out, saved_err = sys.stdout, sys.stderr
        sys.stdout = None
        sys.stderr = None
        try:
            sig = rembg_manager.RembgSignals()
            batches: list[tuple] = []
            sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
            out = os.path.join(tmpdir, "cat_nobg.png")
            QThreadPool.globalInstance().start(
                rembg_manager.RemoveBgTask([(png, out)],
                                           rembg_manager.DEFAULT_MODEL, sig))
            out_ok = wait_until(lambda: os.path.isfile(out), timeout_s=300)
            wait_until(lambda: bool(batches))
            batch = list(batches)
            cache_ok = os.path.isdir(
                os.path.join(os.path.expanduser("~"), ".rembg"))
        finally:
            sys.stdout, sys.stderr = saved_out, saved_err
        check("None-stdio e2e: файл-результат создан (модель скачалась)",
              out_ok, out)
        check("None-stdio e2e: batch_done(1, 0)", batch == [(1, 0)], str(batch))
        check("None-stdio e2e: кэш моделей создан", cache_ok)

    # ---------- UninstallTask: чистит пакет и модели ----------
    calls.clear()

    def fake_pip3(args):
        calls.append(list(args))
        return True, ""

    rembg_manager._run_pip = fake_pip3
    try:
        # фейковый кэш моделей в домашней папке
        home = os.path.expanduser("~")
        d1 = os.path.join(home, ".rembg", "u2netp")
        os.makedirs(d1, exist_ok=True)
        with open(os.path.join(d1, "model.onnx"), "wb") as f:
            f.write(b"x" * 2048)
        sig = rembg_manager.RembgSignals()
        unres: list[tuple] = []
        sig.uninstall_done.connect(lambda ok, info, mb: unres.append((ok, mb)))
        QThreadPool.globalInstance().start(rembg_manager.UninstallTask(sig))
        wait_until(lambda: bool(unres))
        check("UninstallTask: pip uninstall rembg+onnxruntime",
              bool(calls) and calls[0] == ["uninstall", "-y", "rembg", "onnxruntime"],
              str(calls))
        check("UninstallTask: кэш моделей вычищен",
              not os.path.isdir(os.path.join(home, ".rembg")))
        check("UninstallTask: сигнал с МБ",
              bool(unres) and unres[0][0] is True, str(unres))
    finally:
        rembg_manager._run_pip = real_pip
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------- i18n: ключи на трёх языках ----------
    QThreadPool.globalInstance().waitForDone(60000)   # фоновые задачи дочитали — только потом выходим
    for key in REMBG_KEYS:
        vals = i18n._STRINGS.get(key, {})
        check(f"i18n {key}",
              all(str(vals.get(lang, "")).strip() for lang in ("ru", "en", "zh")),
              str(vals))

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
