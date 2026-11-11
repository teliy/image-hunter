"""Оффлайн-тест удаления фона (rembg) — модуль, кнопка, контекстное меню (v0.7.15).

Проверяется:
- rembg_manager: is_installed, model_cache_dirs, models_size;
- nobg_path: X.ext -> X_nobg.png, повторная обработка результата отклоняется;
- InstallTask вызывает pip c верными аргументами (без окна терминала) и
  сигнал install_done доходит;
- UpdateTask (v0.8.15, обновление модуля): сверка версии rembg с PyPI,
  «обновлений нет» без pip, обновление pip --upgrade rembg[cpu], отказ
  при недоступном pypi/неопределимой версии — честный; вьюер: rembg_update
  стартует задачу, guard busy, итог в статусе, без модуля — не стартует;
- установка через вьюер продолжает отложенную обработку (_rembg_pending);
- UninstallTask удаляет пакет и кэш моделей целиком (~/.rembg, ~/.u2net);
- RevertTask удаляет файлы-результаты, отсутствующий — репортит ошибкой;
- RemoveBgTask: без установленного rembg честно репортит ошибку по каждому
  файлу (batch_done(0, N)), с настоящим rembg (если пакет стоит в окружении)
  создаёт X_nobg.png — в том числе при sys.stdout/stderr = None (pythonw
  на Windows: скачивание модели падало с "'NoneType' object has no
  attribute 'write'" — tqdm в pooch; фикс _ensure_stdio, репорт после 0.7.12);
- скачивание модели видно в интерфейсе (v0.7.15): _stream_model качает
  через requests с сигналами start/progress/done (и подчищает «.part» при
  обрыве), обёртка pooch.retrieve качает своё только при отсутствии файла
  и зовёт оригинал с progressbar=False, хук ставится один раз; e2e: при
  пустом кэше сигналы скачивания приходят, с кэшем — нет;
- выбор после удаления фона (v0.7.15): после пачки открывается немодальный
  диалог с превью; «Сохранить» оставляет файлы, «Вернуть оригиналы»
  удаляет результаты пачки (оригинал не тронут), Esc/крестик — как
  «Сохранить», новая пачка закрывает старый вопрос как «Сохранить»,
  пачка без удачных файлов диалога не открывает;
- _ensure_stdio: None-stdio подменяется заглушками, вызов идемпотентен;
- кнопка 🪄 есть, клик без выбора картинки даёт подсказку в статусе;
- контекстное меню ленты содержит «Удалить фон», подменю «Модель» и пункт
  установки/удаления модуля;
- выбор модели запоминается в QSettings и валидируется при загрузке;
- статусная строка рассказывает про модель: готовится, качается
  (сколько из скольких, проценты), скачана, готова;
- i18n: все новые ключи заполнены на ru/en/zh.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_rembg.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRunnable, QSettings, QThreadPool, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMenu  # noqa: E402

from app.core import i18n  # noqa: E402
from app.ui import rembg_manager  # noqa: E402
from app.ui.local_viewer import (  # noqa: E402
    LocalViewer, _REMBG_REVERT, _checker_pixmap, _fmt_bytes,
)

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
    # v0.8.15: обновление установленного модуля
    "viewer.rembg_menu_update", "viewer.rembg_updating",
    "viewer.rembg_update_done", "viewer.rembg_update_nothing",
    "viewer.rembg_update_fail", "viewer.rembg_update_pypi_fail",
    "viewer.rembg_update_stuck", "viewer.rembg_update_restart",
    "log.event.rembg_update_start", "log.event.rembg_update_done",
    "log.event.rembg_update_fail",
    # v0.7.15: выбор после удаления фона + прогресс скачивания модели
    "viewer.rembg_choice_q", "viewer.rembg_choice_more",
    "viewer.rembg_btn_save", "viewer.rembg_btn_save_tip",
    "viewer.rembg_btn_revert", "viewer.rembg_btn_revert_tip",
    "viewer.rembg_saved", "viewer.rembg_reverting",
    "viewer.rembg_reverted", "viewer.rembg_revert_fail",
    "viewer.rembg_prepare", "viewer.rembg_ready",
    "viewer.rembg_dl_start", "viewer.rembg_dl_prog",
    "viewer.rembg_dl_prog_na", "viewer.rembg_dl_done",
    "log.event.rembg_model_dl", "log.event.rembg_saved",
    "log.event.rembg_revert_start", "log.event.rembg_revert",
    "log.event.rembg_revert_err",
]


class _FakeResp:
    """Заглушка ответа requests: отдаёт куски, может «обрываться» посреди."""

    def __init__(self, chunks, fail_after=None):
        self._chunks = chunks
        self._fail_after = fail_after
        self.headers = {"Content-Length": str(sum(len(c) for c in chunks))}

    def raise_for_status(self):
        pass

    def iter_content(self, _n):
        for i, chunk in enumerate(self._chunks):
            if self._fail_after is not None and i >= self._fail_after:
                raise OSError("сеть отвалилась")
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeRequests:
    """Заглушка модуля requests: get(url, **kw) -> ответ из фабрики."""

    def __init__(self, factory):
        self._factory = factory
        self.calls: list[tuple] = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self._factory(url, **kw)


class _FakeReporter:
    """Ловит доклады _dl_emit: getattr(rep, ev).emit(*a) -> кортеж в список."""

    def __init__(self):
        self.events: list[tuple] = []

    def __getattr__(self, ev):
        outer = self

        class _Sig:
            def emit(_self, *args):
                outer.events.append((ev, *args))

        return _Sig()


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
    # v0.8.18: «убрать фон и водяные знаки перемести на панель ниже» —
    # кнопка живёт в tools_lay, её родитель — QFrame#toolsPanel, а на
    # верхней панели (родитель — сам вьюер) её больше нет
    from PySide6.QtWidgets import QToolButton  # noqa: E402
    check("кнопка 🪄 на панели инструментов (v0.8.18)",
          viewer.btn_rembg.parent() is viewer.tools_panel,
          type(viewer.btn_rembg.parent()).__name__)
    rembg_btns = [b for b in viewer.findChildren(QToolButton)
                  if b.text() == i18n.tr("viewer.rembg")]
    check("🪄 ровно одна — с верхней панели убрана",
          len(rembg_btns) == 1,
          str([b.parent().__class__.__name__ for b in rembg_btns]))
    _tl = viewer.tools_panel.layout()
    check("🪄 стоит после пипетки, в конце инструментов",
          _tl.indexOf(viewer.btn_rembg) > _tl.indexOf(viewer.btn_picker),
          str((_tl.indexOf(viewer.btn_rembg), _tl.indexOf(viewer.btn_picker))))
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
    # (v0.8.2: установка/удаление/модель переехали в меню «Модули» главного
    # окна — их состав проверяет scripts/test_modules_menu.py; в меню ленты
    # осталась только файловая операция «Удалить фон»)
    menu, acts = viewer._build_list_menu()
    texts = [a.text() for a in menu.actions()]
    check("меню: «Удалить фон» в меню",
          i18n.tr("viewer.rembg") in texts, str(texts))
    check("меню: без подменю «Модель»",
          not any(a.menu() for a in menu.actions()), str(texts))
    check("меню: без пунктов установки/удаления модуля",
          i18n.tr("viewer.rembg_menu_install") not in texts
          and i18n.tr("viewer.rembg_menu_uninstall") not in texts, str(texts))
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

    # ---------- UpdateTask: обновление модуля (v0.8.15) ----------
    from PySide6.QtWidgets import QMessageBox  # noqa: E402

    real_ver_r = rembg_manager.installed_version
    real_pypi_r = rembg_manager.pypi_latest
    real_upd_installed_r = rembg_manager.is_installed

    def run_rembg_update():
        sig = rembg_manager.RembgSignals()
        results: list[tuple] = []
        sig.update_done.connect(
            lambda ok, what, info: results.append((ok, what, info)))
        QThreadPool.globalInstance().start(rembg_manager.UpdateTask(sig))
        wait_until(lambda: bool(results))
        return results

    # всё актуально: pip не звался, честное «обновлений нет»
    rembg_manager.installed_version = lambda: "1.0.197"
    rembg_manager.pypi_latest = lambda pkg: "1.0.197"
    calls_u: list[list[str]] = []
    rembg_manager._run_pip = (
        lambda args: (calls_u.append(list(args)), (True, ""))[1])
    try:
        results = run_rembg_update()
        check("UpdateTask: всё актуально — без pip",
              results == [(True, i18n.tr("viewer.rembg_update_nothing",
                                         ver="1.0.197"), "")], str(results))
        check("UpdateTask: всё актуально — pip не звался", calls_u == [],
              str(calls_u))
    finally:
        rembg_manager._run_pip = real_pip

    # вышла новая версия — pip install --upgrade rembg[cpu]; версия после
    # pip сверяется ПО ФАКТУ (v0.8.17) — стаб двигает её вместе с pip
    ver_now_r = ["1.0.197"]

    def rembg_ver():
        return ver_now_r[0]

    def rembg_pip_move(args):
        calls_u.append(list(args))
        ver_now_r[0] = "1.0.200"             # pip обновил
        return True, ""

    rembg_manager.installed_version = rembg_ver
    rembg_manager.pypi_latest = lambda pkg: "1.0.200"
    calls_u = []
    rembg_manager._run_pip = rembg_pip_move
    try:
        results = run_rembg_update()
        check("UpdateTask: pip install --upgrade rembg[cpu]",
              calls_u == [["install", "--disable-pip-version-check",
                           "--upgrade", "rembg[cpu]"]], str(calls_u))
        check("UpdateTask: итог с версиями и подсказкой о перезапуске",
              bool(results) and results[0][0] is True
              and results[0][1] == "1.0.197 → 1.0.200. "
              + i18n.tr("viewer.rembg_update_restart"), str(results))
    finally:
        rembg_manager._run_pip = real_pip

    # репорт v0.8.17: pip отчитался успехом, но версия осталась старой —
    # честная неудача вместо ложного «X → Y»
    ver_now_r[0] = "1.0.197"
    calls_u = []
    rembg_manager._run_pip = (
        lambda args: (calls_u.append(list(args)), (True, ""))[1])
    try:
        results = run_rembg_update()
        check("UpdateTask: pip «успешен», версия не сдвинулась — отказ",
              bool(results) and results[0][0] is False
              and results[0][2] == i18n.tr("viewer.rembg_update_stuck",
                                           ver="1.0.197"), str(results))
    finally:
        rembg_manager._run_pip = real_pip

    # pypi.org недоступен — честный отказ, pip не запускается
    rembg_manager.pypi_latest = lambda pkg: ""
    calls_u = []
    rembg_manager._run_pip = (
        lambda args: (calls_u.append(list(args)), (True, ""))[1])
    try:
        results = run_rembg_update()
        check("UpdateTask: pypi недоступен — отказ",
              results == [(False, "", i18n.tr("viewer.rembg_update_pypi_fail"))],
              str(results))
        check("UpdateTask: при отказе pypi pip не запускается", calls_u == [])
    finally:
        rembg_manager._run_pip = real_pip

    # отказ pip-а доезжает с хвостом вывода
    rembg_manager.pypi_latest = lambda pkg: "1.0.200"
    rembg_manager._run_pip = lambda args: (False, "No space left on device")
    try:
        results = run_rembg_update()
        check("UpdateTask: отказ pip — честная ошибка",
              results == [(False, "", "No space left on device")], str(results))
    finally:
        rembg_manager._run_pip = real_pip

    # версию определить не удалось — отказ без запуска pip
    rembg_manager.installed_version = lambda: ""
    calls_u = []
    rembg_manager._run_pip = (
        lambda args: (calls_u.append(list(args)), (True, ""))[1])
    try:
        results = run_rembg_update()
        check("UpdateTask: версию не определить — отказ",
              bool(results) and results[0][0] is False
              and "rembg" in results[0][2] and calls_u == [], str(results))
    finally:
        rembg_manager._run_pip = real_pip
        rembg_manager.installed_version = real_ver_r
        rembg_manager.pypi_latest = real_pypi_r

    # ---------- обновление через вьюер (v0.8.15) ----------
    rembg_manager.is_installed = lambda: True
    real_upd_task_r = rembg_manager.UpdateTask
    upd_started_r: list[int] = []

    class StubRembgUpd(QRunnable):
        """Стаб задачи обновления: сигнал успеха без сети и pip-а."""

        def __init__(self, signals):
            super().__init__()
            self.signals = signals
            upd_started_r.append(1)

        def run(self):
            self.signals.update_done.emit(
                True,
                "1.0.197 → 1.0.200. " + i18n.tr("viewer.rembg_update_restart"),
                "")

    rembg_manager.UpdateTask = StubRembgUpd
    upd_boxes_r: list[str] = []
    real_info_r = QMessageBox.information
    real_warn_r = QMessageBox.warning
    QMessageBox.information = lambda *a, **k: upd_boxes_r.append("info")
    QMessageBox.warning = lambda *a, **k: upd_boxes_r.append("warn")
    try:
        viewer.rembg_update()
        check("вьюер: обновление стартовало",
              upd_started_r == [1] and viewer._rembg_busy is True)
        wait_until(lambda: not viewer._rembg_busy, timeout_s=10)
        app.processEvents()
        check("вьюер: итог обновления в статусе",
              viewer.status.text() == i18n.tr(
                  "viewer.rembg_update_done",
                  what="1.0.197 → 1.0.200. "
                  + i18n.tr("viewer.rembg_update_restart")),
              viewer.status.text())
        check("вьюер: окно об успехе обновления",
              upd_boxes_r[-1:] == ["info"], str(upd_boxes_r))

        viewer._rembg_busy = True
        viewer.rembg_update()
        check("вьюер: пока busy — второй запуск не нужен",
              viewer._rembg_busy is True and len(upd_started_r) == 1
              and viewer.status.text() == i18n.tr("viewer.rembg_busy"),
              viewer.status.text())
        viewer._rembg_busy = False

        viewer._rembg_signals.update_done.emit(False, "", "pypi недоступен")
        app.processEvents()
        check("вьюер: отказ обновления — статус и предупреждение",
              viewer.status.text() == i18n.tr("viewer.rembg_update_fail",
                                              info="pypi недоступен")
              and upd_boxes_r[-1:] == ["warn"], str(upd_boxes_r))

        rembg_manager.is_installed = lambda: False
        viewer.rembg_update()
        check("вьюер: без модуля обновление не стартует",
              viewer._rembg_busy is False and len(upd_started_r) == 1)
    finally:
        rembg_manager.UpdateTask = real_upd_task_r
        rembg_manager.is_installed = real_upd_installed_r
        QMessageBox.information = real_info_r
        QMessageBox.warning = real_warn_r

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

    # ---------- v0.7.15: _stream_model — скачивание с сигналами ----------
    tgt = os.path.join(tmpdir, "mymodel.onnx")
    fake_req = _FakeRequests(lambda url, **kw: _FakeResp([b"1234", b"5678"]))
    real_requests = rembg_manager.requests
    rep = _FakeReporter()
    rembg_manager.requests = fake_req
    rembg_manager._DL_REPORTER = rep
    try:
        rembg_manager._stream_model("http://localhost/model.onnx", tgt)
    finally:
        rembg_manager.requests = real_requests
        rembg_manager._DL_REPORTER = None
    with open(tgt, "rb") as f:
        got = f.read()
    check("_stream_model: файл собран из кусков", got == b"12345678", repr(got))
    check("_stream_model: .part подчищен", not os.path.exists(tgt + ".part"))
    check("_stream_model: stream=True и свой UA",
          bool(fake_req.calls) and fake_req.calls[0][1].get("stream") is True
          and fake_req.calls[0][1].get("headers", {}).get("User-Agent"),
          str(fake_req.calls))
    kinds = [e[0] for e in rep.events]
    check("_stream_model: start … progress … done",
          kinds[0] == "model_dl_start" and "model_dl_progress" in kinds
          and kinds[-1] == "model_dl_done", str(rep.events))
    check("_stream_model: start знает размер (8 байт)",
          rep.events[0] == ("model_dl_start", "mymodel", 8), str(rep.events[0]))
    check("_stream_model: done — 8 байт и миллисекунды",
          rep.events[-1][:3] == ("model_dl_done", "mymodel", 8)
          and isinstance(rep.events[-1][3], int), str(rep.events[-1]))

    # обрыв сети: исключение наверх, «.part» подчищен, целевого файла нет
    tgt2 = os.path.join(tmpdir, "broken.onnx")
    fake_req2 = _FakeRequests(
        lambda url, **kw: _FakeResp([b"1234", b"5678"], fail_after=1))
    rembg_manager.requests = fake_req2
    raised = False
    try:
        rembg_manager._stream_model("http://localhost/model.onnx", tgt2)
    except OSError:
        raised = True
    finally:
        rembg_manager.requests = real_requests
    check("_stream_model: обрыв сети доходит наверх", raised)
    check("_stream_model: .part подчищен после обрыва",
          not os.path.exists(tgt2 + ".part"))
    check("_stream_model: целевой файл не создан", not os.path.exists(tgt2))

    # ---------- v0.7.15: обёртка pooch.retrieve ----------
    orig_calls: list[tuple] = []

    def fake_orig(url, **kw):
        orig_calls.append((url, kw))
        return os.path.join(kw["path"], kw["fname"])

    stream_calls: list[tuple] = []
    real_stream = rembg_manager._stream_model
    rembg_manager._stream_model = (
        lambda url, target: stream_calls.append((url, target)))
    try:
        wrap = rembg_manager._make_retrieve_wrapper(fake_orig, True)
        out = wrap("http://x/m.onnx", known_hash="md5:1", fname="m.onnx",
                   path=tmpdir)
        check("wrapper: оригинал вернул путь",
              out == os.path.join(tmpdir, "m.onnx"), str(out))
        check("wrapper: файла нет — качаем сами",
              stream_calls == [("http://x/m.onnx", os.path.join(tmpdir, "m.onnx"))],
              str(stream_calls))
        check("wrapper: оригиналу progressbar=False",
              bool(orig_calls) and orig_calls[0][1].get("progressbar") is False,
              str(orig_calls))
        with open(os.path.join(tmpdir, "m.onnx"), "wb") as f:
            f.write(b"x")   # файл появился в кэше
        stream_calls.clear()
        orig_calls.clear()
        wrap("http://x/m.onnx", fname="m.onnx", path=tmpdir)
        check("wrapper: файл в кэше — своё скачивание не зовётся",
              not stream_calls, str(stream_calls))
        orig_calls.clear()
        wrap2 = rembg_manager._make_retrieve_wrapper(fake_orig, False)
        wrap2("http://x/m.onnx", fname="m.onnx", path=tmpdir)
        check("wrapper: без progressbar в сигнатуре — не передаём",
              "progressbar" not in orig_calls[0][1], str(orig_calls))
    finally:
        rembg_manager._stream_model = real_stream

    # ---------- v0.7.15: хук ставится один раз ----------
    try:
        import pooch as _pooch
        have_pooch = True
    except Exception:   # noqa: BLE001 — теста хука без pooch просто нет
        have_pooch = False
    if have_pooch:
        rembg_manager.hook_model_downloads()
        check("hook: перехват установлен",
              getattr(_pooch, "_imagehunter_hook", False))
        wrapped = _pooch.retrieve
        rembg_manager.hook_model_downloads()   # повторный вызов — ничего
        check("hook: повторный вызов не даёт двойную обёртку",
              _pooch.retrieve is wrapped)

    # ---------- v0.7.15: RevertTask ----------
    r1 = os.path.join(tmpdir, "r1_nobg.png")
    r2 = os.path.join(tmpdir, "r2_nobg.png")
    for p, data in ((r1, b"a"), (r2, b"b")):
        with open(p, "wb") as f:
            f.write(data)
    ghost = os.path.join(tmpdir, "ghost_nobg.png")
    sig = rembg_manager.RembgSignals()
    rev: list[tuple] = []
    sig.revert_done.connect(lambda rem, errs: rev.append((rem, errs)))
    QThreadPool.globalInstance().start(
        rembg_manager.RevertTask([r1, r2, ghost], sig))
    wait_until(lambda: bool(rev))
    check("RevertTask: файлы удалены",
          not os.path.exists(r1) and not os.path.exists(r2))
    check("RevertTask: отсутствующий — ошибкой",
          bool(rev) and rev[0][0] == [r1, r2] and len(rev[0][1]) == 1
          and rev[0][1][0][0] == ghost, str(rev))

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
            dl_events: list[tuple] = []
            model_life: list[tuple] = []
            sig.batch_done.connect(lambda ok, fail: batches.append((ok, fail)))
            for evname in ("model_dl_start", "model_dl_progress",
                           "model_dl_done"):
                getattr(sig, evname).connect(
                    lambda *a, e=evname: dl_events.append((e, *a)))
            sig.model_prepare.connect(
                lambda m: model_life.append(("prepare", m)))
            sig.model_ready.connect(lambda m: model_life.append(("ready", m)))
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
        # v0.7.15: пока модель качалась, интерфейсу шли сигналы;
        # сессия готовится до и готова после скачивания
        check("e2e: модель готовится и готова",
              model_life == [("prepare", rembg_manager.DEFAULT_MODEL),
                             ("ready", rembg_manager.DEFAULT_MODEL)],
              str(model_life))
        kinds_e = [e[0] for e in dl_events]
        check("e2e: сигналы скачивания шли (start … done)",
              bool(kinds_e) and kinds_e[0] == "model_dl_start"
              and kinds_e[-1] == "model_dl_done", str(dl_events[:3]))
        model_file = None
        for root, _dirs, files in os.walk(
                os.path.join(os.path.expanduser("~"), ".rembg")):
            if rembg_manager.DEFAULT_MODEL + ".onnx" in files:
                model_file = os.path.join(
                    root, rembg_manager.DEFAULT_MODEL + ".onnx")
                break
        check("e2e: dl_done — размер совпадает с файлом",
              (model_file is not None and dl_events[-1][2]
               == os.path.getsize(model_file)),
              f"{dl_events[-1] if dl_events else None} vs {model_file}")

        # повторный прогон с кэшем: своё скачивание не зовётся — сигналов нет
        out2 = os.path.join(tmpdir, "cat2_nobg.png")
        sig2 = rembg_manager.RembgSignals()
        batches2: list[tuple] = []
        dl2: list[str] = []
        sig2.batch_done.connect(lambda ok, fail: batches2.append((ok, fail)))
        for evname in ("model_dl_start", "model_dl_progress",
                       "model_dl_done"):
            getattr(sig2, evname).connect(
                lambda *a, e=evname: dl2.append(e))
        QThreadPool.globalInstance().start(
            rembg_manager.RemoveBgTask([(png, out2)],
                                       rembg_manager.DEFAULT_MODEL, sig2))
        wait_until(lambda: bool(batches2), timeout_s=120)
        check("кэш: повторная обработка работает",
              batches2 == [(1, 0)] and os.path.isfile(out2), str(batches2))
        check("кэш: без сигналов скачивания", not dl2, str(dl2))

    # ---------- v0.7.15: статусная строка рассказывает про модель ----------
    vsig = viewer._rembg_signals
    vsig.model_prepare.emit("u2netp")
    app.processEvents()
    check("статус: модель готовится",
          viewer.status.text() == i18n.tr("viewer.rembg_prepare", model="u2netp"),
          viewer.status.text())
    vsig.model_dl_start.emit("u2netp", 4849)
    app.processEvents()
    check("статус: скачивание началось",
          viewer.status.text() == i18n.tr("viewer.rembg_dl_start", model="u2netp"),
          viewer.status.text())
    vsig.model_dl_progress.emit(1200, 4849)
    app.processEvents()
    pct = round(1200 * 100 / 4849)
    check("статус: прогресс — модель, байты и проценты",
          "u2netp" in viewer.status.text() and _fmt_bytes(1200) in viewer.status.text()
          and _fmt_bytes(4849) in viewer.status.text() and str(pct) in viewer.status.text(),
          viewer.status.text())
    vsig.model_dl_progress.emit(300, 0)
    app.processEvents()
    check("статус: прогресс без известного размера",
          viewer.status.text() == i18n.tr("viewer.rembg_dl_prog_na", model="u2netp",
                                          done=_fmt_bytes(300)),
          viewer.status.text())
    vsig.model_dl_done.emit("u2netp", 4849, 1500)
    app.processEvents()
    check("статус: модель скачана",
          viewer.status.text() == i18n.tr("viewer.rembg_dl_done", model="u2netp",
                                          size=_fmt_bytes(4849)),
          viewer.status.text())
    vsig.model_ready.emit("u2netp")
    app.processEvents()
    check("статус: модель готова",
          viewer.status.text() == i18n.tr("viewer.rembg_ready", model="u2netp"),
          viewer.status.text())

    # ---------- v0.7.15: выбор «Сохранить результат / Вернуть оригиналы» ----------
    class StubOkTask(QRunnable):
        """Заглушка обработки: каждый файл «успешно», без записи на диск."""

        def __init__(self, jobs, model, signals):
            super().__init__()
            self.jobs, self.signals = jobs, signals

        def run(self):
            for path, out in self.jobs:
                self.signals.file_done.emit(path, out, True, "")
            self.signals.batch_done.emit(len(self.jobs), 0)

    class StubFailTask(QRunnable):
        """Заглушка обработки: все файлы — с ошибкой."""

        def __init__(self, jobs, model, signals):
            super().__init__()
            self.jobs, self.signals = jobs, signals

        def run(self):
            for path, _out in self.jobs:
                self.signals.file_done.emit(path, "", False, "boom")
            self.signals.batch_done.emit(0, len(self.jobs))

    real_remove_task = rembg_manager.RemoveBgTask
    # отдельное входное имя: путь результата derives от него (dove_nobg.png),
    # чтобы не пересекаться с выводом e2e (cat_nobg.png) выше
    dove = os.path.join(tmpdir, "dove.png")
    dimg = QImage(5, 5, QImage.Format.Format_RGB32)
    dimg.fill(QColor(30, 30, 200))
    check("тестовая картинка для выбора создана", dimg.save(dove, "PNG"))
    out_path = os.path.join(tmpdir, "dove_nobg.png")
    try:
        rembg_manager.RemoveBgTask = StubOkTask

        # «Сохранить»: диалог открыт, файл остаётся, статус и журнал в курсе
        viewer._rembg_start([dove])
        wait_until(lambda: viewer._rembg_choice is not None)
        app.processEvents()
        dlg = viewer._rembg_choice
        check("выбор: диалог открыт и видим",
              dlg is not None and dlg.isVisible())
        check("выбор: немодальный — лента живёт",
              dlg.windowModality() == Qt.WindowModality.NonModal,
              str(dlg.windowModality()))
        check("выбор: кнопки Сохранить и Вернуть",
              dlg.btn_save.text() == i18n.tr("viewer.rembg_btn_save")
              and dlg.btn_revert.text() == i18n.tr("viewer.rembg_btn_revert"))
        check("выбор: превью нет — файла результата ещё нет",
              dlg.findChildren(QLabel)
              and len(dlg.findChildren(QLabel)) == 1,
              str(len(dlg.findChildren(QLabel))))
        check("выбор: результаты пачки собраны",
              viewer._rembg_results == [out_path], str(viewer._rembg_results))
        dlg.accept()   # «Сохранить» (accept = 1)
        app.processEvents()
        check("выбор: «Сохранить» — статус",
              viewer.status.text() == i18n.tr("viewer.rembg_saved", n=1),
              viewer.status.text())
        check("выбор: ссылка на диалог сброшена", viewer._rembg_choice is None)
        check("выбор: список результатов обнулён", viewer._rembg_results == [])

        # «Вернуть оригиналы»: результат удаляется, оригинал не тронут
        # (файл-результат — настоящая картинка: по ней строится превью)
        pimg = QImage(6, 6, QImage.Format.Format_ARGB32)
        pimg.fill(QColor(30, 200, 30))
        pimg.save(out_path, "PNG")
        viewer._rembg_start([dove])
        wait_until(lambda: viewer._rembg_choice is not None)
        app.processEvents()
        dlg = viewer._rembg_choice
        check("выбор: превью результата построено (3 метки)",
              len(dlg.findChildren(QLabel)) == 3, str(len(dlg.findChildren(QLabel))))
        dlg.done(_REMBG_REVERT)
        wait_until(lambda: not os.path.exists(out_path))
        # финальный статус приходит сигналом revert_done из рабочего потока
        wait_until(lambda: viewer.status.text()
                   == i18n.tr("viewer.rembg_reverted", n=1))
        app.processEvents()
        check("выбор: «Вернуть» — результат удалён",
              not os.path.exists(out_path))
        check("выбор: «Вернуть» — оригинал на месте", os.path.isfile(dove))
        check("выбор: «Вернуть» — статус",
              viewer.status.text() == i18n.tr("viewer.rembg_reverted", n=1),
              viewer.status.text())

        # Esc/крестик (код 0) — безопасное «Сохранить»
        pimg.save(out_path, "PNG")
        viewer._rembg_start([dove])
        wait_until(lambda: viewer._rembg_choice is not None)
        app.processEvents()
        viewer._rembg_choice.done(0)
        app.processEvents()
        check("выбор: Esc — файл остался", os.path.isfile(out_path))
        check("выбор: Esc — статус «сохранено»",
              viewer.status.text() == i18n.tr("viewer.rembg_saved", n=1),
              viewer.status.text())

        # новая пачка закрывает старый вопрос как «Сохранить»
        viewer._rembg_start([dove])
        wait_until(lambda: viewer._rembg_choice is not None)
        app.processEvents()
        viewer._rembg_start([dove])
        # второй вопрос открывается, когда фоновая пачка дошлёт batch_done
        wait_until(lambda: viewer._rembg_choice is not None)
        app.processEvents()
        check("новая пачка: прежний результат сохранён",
              os.path.isfile(out_path))
        check("новая пачка: вопрос открыт для новой пачки",
              viewer._rembg_choice is not None and viewer._rembg_choice.isVisible())
        viewer._rembg_choice.accept()
        app.processEvents()

        # пачка без удачных файлов диалог не открывает
        rembg_manager.RemoveBgTask = StubFailTask
        viewer._rembg_start([dove])
        wait_until(lambda: not viewer._rembg_busy)
        app.processEvents()
        check("ошибки: диалог выбора не открывается",
              viewer._rembg_choice is None)
        check("ошибки: список результатов пуст", viewer._rembg_results == [])
    finally:
        rembg_manager.RemoveBgTask = real_remove_task
        os.path.exists(out_path) and os.remove(out_path)

    # превью-помощник: настоящая картинка -> pixmap, мусор -> None
    pm = _checker_pixmap(png)
    check("превью: шахматка для настоящей картинки",
          isinstance(pm, QPixmap) and pm.width() == 132 and pm.height() == 132)
    check("превью: нет картинки — нет превью", _checker_pixmap(out_path) is None)

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
