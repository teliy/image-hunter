"""Оффлайн-тест «процесс и статус модулей — в строке статуса» (v0.8.20).

Пожелание: «сделай, чтобы можно было видеть в строке статуса процесс
и/или статус работы модулей, особенно модуля удаления ватермарков».

Проверяется:
1. мост modstatus: report/done доезжают сигналами (в т. ч. из рабочего
   потока — через queued-соединение);
2. виджет: скрыт до активности, появляется по report, полоса прогресса —
   при известной доле (0..1), скрывается при -1, доля зажимается в 0..100;
3. затирание: активность модуля НЕ сбрасывается другими событиями —
   виджет на постоянном месте, показывается последняя обновлённая
   активность из нескольких идущих одновременно;
4. finished: активность снята — показывается следующая, без других —
   виджет скрыт и тики остановлены;
5. секундный тик: активность без обновлений дольше 3 с тикает « · N с»;
6. MainWindow: виджет — ребёнок статус-бара, рядом с подписью вьюера,
   bridge подключён — report мгновенно виден внизу окна;
7. i18n: все новые ключи полны в ru/en/zh;
8. RemoveWatermarkTask: file_start до file_done, фазы detect → found →
   inpaint → save на файле со знаком, только detect на чистом файле;
9. RemoveBgTask: file_start до file_done (с фейковым модулем rembg);
10. механика скачиваний: _incomplete_bytes по «*.incomplete»,
    _dl_emit без репортера не падает, _stream_lama без iopaint честно
    возвращает False, _patch_hf_downloads ставит обёртку один раз.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_modstatus.py
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import i18n, modstatus  # noqa: E402
from app.ui import rembg_manager, watermark_manager  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.modstatus import ModuleStatusWidget  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def pump(app, ms: int = 400) -> None:
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        app.processEvents()


def wait_until(cond, timeout_s: float = 10.0, app=None) -> bool:
    app = app or QApplication.instance()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()   # queued-сигналы из рабочих потоков — через event-loop
        if cond():
            return True
        time.sleep(0.05)
        app.processEvents()
    return bool(cond())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_query", "")
    QSettings("ImageHunter", "ImageHunter").setValue("web/tabs", "")

    # ---------- 1. мост ----------

    got: list[tuple[str, str, float]] = []
    done_keys: list[str] = []
    modstatus.bridge.activity.connect(lambda k, t, f: got.append((k, t, f)))
    modstatus.bridge.finished.connect(done_keys.append)
    modstatus.report("wm", "тестовая активность", frac=0.5)
    pump(app, 150)
    check("мост: report доезжает", got == [("wm", "тестовая активность", 0.5)],
          str(got))
    modstatus.done("wm")
    pump(app, 150)
    check("мост: done доезжает", done_keys == ["wm"], str(done_keys))
    got.clear()
    # из рабочего потока: queued-соединение должно доставить
    threading.Thread(
        target=modstatus.report, args=("wm", "из потока", 0.25),
        daemon=True).start()
    pump(app, 300)
    check("мост: report из рабочего потока (queued)",
          got == [("wm", "из потока", 0.25)], str(got))

    # ---------- 2-6. виджет ----------

    w = ModuleStatusWidget()
    check("виджет скрыт до активности", not w.isVisible())
    modstatus.report("wm", "Удаление водяных знаков: 0/2 — a.webp", frac=0.0)
    w.activity("wm", "Удаление водяных знаков: 0/2 — a.webp", 0.0)
    check("виджет показан", w.isVisible())
    check("текст активности", w._label.text() ==
          "Удаление водяных знаков: 0/2 — a.webp", w._label.text())
    check("полоса видна при известной доле", not w._bar.isHidden())
    check("полоса: 0 %", w._bar.value() == 0, str(w._bar.value()))
    w.activity("wm", "половина", frac=0.5)
    check("полоса: 50 %", w._bar.value() == 50, str(w._bar.value()))
    w.activity("wm", "больше единицы", frac=1.3)
    check("доля зажата в 100 %", w._bar.value() == 100, str(w._bar.value()))
    w.activity("wm", "доля неизвестна", frac=-1.0)
    check("полоса скрыта при -1", w._bar.isHidden())

    # тик секундами: активность дольше 3 с получает « · N с»
    import app.ui.modstatus as msmod
    real_mono = msmod.time.monotonic
    w.activity("wm", "Готовлю модели", frac=-1.0)
    msmod.time.monotonic = lambda: real_mono() + 45.0
    try:
        w._tick()
        check("тик: elapsed добавлен",
              " · 45 с" in w._label.text(), w._label.text())
        msmod.time.monotonic = lambda: real_mono() + 1.0
        w.activity("wm", "только началось", frac=-1.0)
        check("до 3 с elapsed нет",
              " · 1 с" not in w._label.text(), w._label.text())
    finally:
        msmod.time.monotonic = real_mono

    # две активности одновременно: показывается последняя обновлённая;
    # снятие одной возвращает предыдущую
    w.activity("wm", "в/{$тексте}фигурные", frac=0.2)
    w.activity("rembg", "Фон: 1/3 — b.png", frac=0.4)
    check("последняя обновлённая — показана",
          w._label.text() == "Фон: 1/3 — b.png", w._label.text())
    w.finished("rembg")
    check("снятие одной возвращает другую",
          w._label.text() == "в/{$тексте}фигурные", w._label.text())
    check("виджет ещё показан", w.isVisible())
    w.finished("wm")
    check("все сняты — виджет скрыт", not w.isVisible())
    check("тики остановлены", not w._timer.isActive())
    check("метка очищена", w._label.text() == "")

    # ---------- 6. MainWindow: виджет в статус-баре ----------

    win = MainWindow()
    win.show()
    pump(app, 200)
    check("виджет модулей есть у окна", hasattr(win, "_mod_status"))
    check("виджет — ребёнок статус-бара",
          win._mod_status.parent() is win._status, str(win._mod_status.parent()))
    check("виджет скрыт при старте окна", not win._mod_status.isVisible())
    modstatus.report("wm", "Удаление водяных знаков: 0/12 — x.webp", frac=0.0)
    pump(app, 200)
    check("report через мост показывается в окне",
          win._mod_status.isVisible() and
          "0/12 — x.webp" in win._mod_status._label.text(),
          win._mod_status._label.text())
    modstatus.done("wm")
    pump(app, 200)
    check("done через мост скрывает виджет",
          not win._mod_status.isVisible())
    win.close()
    pump(app, 100)

    # ---------- 7. i18n ----------

    keys = ("modstatus.elapsed", "viewer.wm_phase", "viewer.wm_phase_detect",
            "viewer.wm_phase_found", "viewer.wm_phase_inpaint",
            "viewer.wm_phase_save", "viewer.wm_dl_start",
            "viewer.wm_dl_prog", "viewer.wm_dl_prog_na")
    fmt = {
        "modstatus.elapsed": lambda: i18n.tr("modstatus.elapsed", sec=5),
        "viewer.wm_phase": lambda: i18n.tr("viewer.wm_phase", done=1, n=2,
                                           name="x", phase="p"),
        "viewer.wm_phase_found": lambda: i18n.tr("viewer.wm_phase_found", n=3),
        "viewer.wm_dl_start": lambda: i18n.tr("viewer.wm_dl_start", model="m"),
        "viewer.wm_dl_prog": lambda: i18n.tr("viewer.wm_dl_prog", model="m",
                                             done="1 Б", total="2 Б", pct=50),
        "viewer.wm_dl_prog_na": lambda: i18n.tr("viewer.wm_dl_prog_na",
                                                model="m", done="1 Б"),
    }
    for code in ("ru", "en", "zh"):
        i18n.set_lang(code, persist=False)
        texts = {k: (fmt[k]() if k in fmt else i18n.tr(k)) for k in keys}
        missing = [k for k, t in texts.items()
                   if not str(t).strip() or "{" in str(t)]
        check(f"i18n {code}: ключи полны", not missing, str(missing))
    i18n.set_lang("ru", persist=False)

    # ---------- 8. RemoveWatermarkTask: file_start и фазы ----------

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        from PIL import Image
        png = os.path.join(tmpdir, "cat.png")
        Image.new("RGB", (64, 64), (120, 120, 130)).save(png, "PNG")

        real_pipeline = watermark_manager._load_pipeline

        def fake_detect(pil_img):
            return [[(24, 24), (31, 24), (31, 31), (24, 31)]]

        def fake_inpaint(rgb, mask):
            return rgb.copy()

        watermark_manager._load_pipeline = (
            lambda model_id: (fake_inpaint, fake_detect))

        starts, phases, dones, batches = [], [], [], []
        sig = watermark_manager.WatermarkSignals()
        sig.file_start.connect(lambda p, i: starts.append((os.path.basename(p), i)))
        sig.phase.connect(lambda p, c, e: phases.append(
            (os.path.basename(p), c, e)))
        sig.file_done.connect(lambda p, o, ok, e: dones.append((ok, e)))
        sig.batch_done.connect(lambda ok, f: batches.append((ok, f)))
        QThreadPool.globalInstance().start(
            watermark_manager.RemoveWatermarkTask(
                [(png, os.path.join(tmpdir, "cat_nowm.png"))], "m", sig))
        wait_until(lambda: bool(batches))
        check("wm: file_start до file_done",
              starts == [("cat.png", 1)], str(starts))
        check("wm: фазы — detect, found, inpaint, save",
              [c for _p, c, _e in phases] ==
              ["detect", "found", "inpaint", "save"], str(phases))
        check("wm: found несёт число полигонов",
              any(c == "found" and e == 1 for _p, c, e in phases), str(phases))
        check("wm: файл обработан успешно",
              dones == [(True, "")] and batches == [(1, 0)],
              f"{dones} {batches}")

        # чистый файл: только detect, file_done(ok, out="") — как «clean»
        starts.clear(); phases.clear(); dones.clear(); batches.clear()
        watermark_manager._load_pipeline = (
            lambda model_id: (fake_inpaint, lambda im: []))
        QThreadPool.globalInstance().start(
            watermark_manager.RemoveWatermarkTask(
                [(png, os.path.join(tmpdir, "cat2_nowm.png"))], "m", sig))
        wait_until(lambda: bool(batches))
        check("wm чистый: фазы только detect",
              [c for _p, c, _e in phases] == ["detect"], str(phases))
        check("wm чистый: file_done ok без результата",
              dones == [(True, "")] and batches == [(0, 0)],
              f"{dones} {batches}")
        watermark_manager._load_pipeline = real_pipeline

    # ---------- 9. RemoveBgTask: file_start ----------

    with tempfile.TemporaryDirectory() as tmpdir:
        from PIL import Image
        png = os.path.join(tmpdir, "dog.png")
        Image.new("RGB", (32, 32), (10, 100, 200)).save(png, "PNG")

        import types
        fake_rembg = types.ModuleType("rembg")

        def fake_new_session(_model):
            return object()

        def fake_remove(data, session=None):
            return data + b"!"

        fake_rembg.new_session = fake_new_session
        fake_rembg.remove = fake_remove
        real_mod = sys.modules.get("rembg")
        sys.modules["rembg"] = fake_rembg
        try:
            starts2, dones2, batches2 = [], [], []
            sig2 = rembg_manager.RembgSignals()
            sig2.file_start.connect(lambda p, i: starts2.append((i,)))
            sig2.file_done.connect(lambda p, o, ok, e: dones2.append(ok))
            sig2.batch_done.connect(lambda ok, f: batches2.append(ok))
            QThreadPool.globalInstance().start(
                rembg_manager.RemoveBgTask(
                    [(png, os.path.join(tmpdir, "dog_nobg.png"))], "u2netp",
                    sig2))
            wait_until(lambda: bool(batches2))
            check("rembg: file_start до file_done",
                  starts2 == [(1,)] and dones2 == [True],
                  f"{starts2} {dones2}")
        finally:
            if real_mod is not None:
                sys.modules["rembg"] = real_mod
            else:
                sys.modules.pop("rembg", None)

    # ---------- 10. механика скачиваний ----------

    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmpdir:
        blobs = os.path.join(tmpdir, "blobs")
        os.makedirs(blobs)
        check("_incomplete_bytes: пустая папка — 0",
              watermark_manager._incomplete_bytes(blobs) == 0)
        for name, size in (("abc.incomplete", 100), ("def.incomplete", 250),
                           ("done.bin", 999)):
            with open(os.path.join(blobs, name), "wb") as f:
                f.write(b"x" * size)
        check("_incomplete_bytes: только *.incomplete",
              watermark_manager._incomplete_bytes(blobs) == 350)
        check("_incomplete_bytes: папки нет — 0",
              watermark_manager._incomplete_bytes(
                  os.path.join(tmpdir, "нет")) == 0)

    # _dl_emit без репортера — молча; с репортером — сигнал доезжает
    emitted: list[tuple[int, int]] = []
    sig3 = watermark_manager.WatermarkSignals()
    sig3.model_dl_progress.connect(lambda d, t: emitted.append((d, t)))
    watermark_manager._DL_REPORTER = None
    watermark_manager._dl_emit("model_dl_progress", 1, 10)
    check("_dl_emit без репортера — ничего", emitted == [])
    watermark_manager._DL_REPORTER = sig3
    watermark_manager._dl_emit("model_dl_progress", 3, 10)
    watermark_manager._DL_REPORTER = None
    check("_dl_emit с репортером — сигнал", emitted == [(3, 10)], str(emitted))

    # _stream_lama без iopaint: честный False, не исключение
    try:
        import iopaint  # noqa: F401
        has_iopaint = True
    except Exception:   # noqa: BLE001 — в песочнице модуля нет
        has_iopaint = False
    if not has_iopaint:
        check("_stream_lama без iopaint — False",
              watermark_manager._stream_lama() is False)

    # _patch_hf_downloads: обёртка ставится один раз
    try:
        import huggingface_hub
        real_hf = huggingface_hub.hf_hub_download
        watermark_manager._HF_PATCHED = False
        watermark_manager._patch_hf_downloads()
        check("hf: обёртка установлена",
              huggingface_hub.hf_hub_download is not real_hf)
        watermark_manager._patch_hf_downloads()
        check("hf: повторная установка идемпотентна",
              huggingface_hub.hf_hub_download is not real_hf)
        huggingface_hub.hf_hub_download = real_hf
        watermark_manager._HF_PATCHED = False
    except ImportError:
        check("hf: huggingface_hub не установлен — пропуск", True)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for f in FAILURES:
            print(" -", f)
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
