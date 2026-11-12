"""Оффлайн-тест модуля улучшения качества (Real-ESRGAN) — v0.8.24.

Проверяется:
- upscale_manager: is_installed, model_scale, up_path (jpg → «_x4»/«_x2»,
  AVIF → PNG, GIF/без расширения/уже результат — отказ), model_cache_dir,
  models_size/model_file, asset_url (неизменяемые релизы GitHub),
  _ASSET_SIZES (проверенные GitHub API размеры);
- настоящий NN-конвейер: крошечная RRDBNet (num_feat=8, num_block=1)
  собирается, веса грузятся строго, _upscale_image даёт результат ×4,
  альфа-канал PNG сохраняется (маска Lanczos), RGBA → JPEG ложится на
  белый фон, плитки TILE=16 на 100×60 дают ровно 28 фаз «tile 28/28»,
  предохранитель MAX_OUT_PIXELS — честный отказ ДО запуска сети;
- UpscaleTask с настоящей моделью: пачка обрабатывается, оригиналы целы;
  без весов — честная ошибка по каждому файлу + batch_done(0, N);
- скачивание весов: _ensure_model_downloads с локального HTTP-сервера,
  сигналы model_dl_start/progress/done, повторное обращение не качает,
  битый размер (релиз неизменяем — размер не может «легально» измениться)
  роняет скачку и подчищает «.part»;
- Install/Uninstall/Update/Revert задачи: pip-аргументы, torch не вычищается
  при живом модуле водяных знаков (но кэш весов — вычищается), UpdateTask —
  сверка размера с релизом (актуально/нет/недоступен/не скачивались),
  RevertTask удаляет свои результаты и репортит отсутствующий;
- вьюер: кнопка ✨ на панели инструментов, пункт в контекстном меню ленты,
  guard busy, «нет выбора», e2e с настоящей крошечной моделью через клик
  (jobs по up_path выбранной модели, итог в статусе, результаты в ленте,
  диалог «Сохранить/Вернуть», «Вернуть оригиналы» удаляет результаты),
  установка-продолжение (отложенная пачка после install_done), выбор
  модели запоминается и валидируется при загрузке, меню «Модули» содержит
  раздел улучшения качества;
- i18n: все новые ключи заполнены на ru/en/zh; версия — 0.8.24.

Запуск: QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \
        python scripts/test_upscale.py
"""

import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow  # noqa: E402

from app import __version__  # noqa: E402
from app.core import i18n, modstatus  # noqa: E402
from app.ui import upscale_manager, watermark_manager  # noqa: E402
from app.ui.local_viewer import (  # noqa: E402
    LocalViewer, _REMBG_REVERT, _REMBG_SAVE, _RembgChoiceDialog,
)
from app.ui.modules_menu import ModulesMenu  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(cond, timeout_s: float = 15.0) -> bool:
    app = QApplication.instance()
    end = os.times()[4] + timeout_s
    while os.times()[4] < end:
        app.processEvents()
        if cond():
            return True
        app.processEvents()
    return cond()


# ---------- крошечная модель: настоящая RRDBNet, но на 1 блоке ----------

TINY = "TinyTest.pth"
TINY_SCALE = 4


def make_tiny_weights(cache_dir: str) -> None:
    """Крошечная настоящая RRDBNet: веса сохраняются как у релизов."""
    import torch

    os.makedirs(cache_dir, exist_ok=True)   # после UninstallTask кэша нет
    upscale_manager._NET_PARAMS[TINY] = dict(
        num_in_ch=3, num_out_ch=3, scale=TINY_SCALE, num_feat=8,
        num_block=1, num_grow_ch=4)
    net = upscale_manager._build_rrdbnet(TINY)
    torch.save(net.state_dict(), os.path.join(cache_dir, TINY))


def patch_tiny() -> str:
    """Подменить кэш весов на временный (веса ещё НЕ положены)."""
    tmp = tempfile.mkdtemp(prefix="ih_upscale_")
    upscale_manager._NET_PARAMS[TINY] = dict(
        num_in_ch=3, num_out_ch=3, scale=TINY_SCALE, num_feat=8,
        num_block=1, num_grow_ch=4)
    upscale_manager.model_cache_dir = lambda: tmp
    return tmp


class _Slot:
    """Имитация Qt-сигнала: .emit зовёт колбэк."""

    def __init__(self, cb):
        self.cb = cb

    def emit(self, *args):
        self.cb(*args)


class _HTTPServer:
    """Локальный HTTP-сервер, отдающий фиксированные байты (для скачки)."""

    def __init__(self, payload: bytes, truncate: int = 0) -> None:
        self.payload = payload
        self.truncate = truncate   # отдать меньше на столько байт (битый размер)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = outer.payload[:-outer.truncate] if outer.truncate \
                    else outer.payload
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):   # тишина в выводе теста
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)

    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("viewer/last_folder", "")
    st.setValue("viewer/last_query", "")
    st.setValue("viewer/favorites", [])
    st.setValue("viewer/up_model", "")
    st.sync()

    # ---------- чистые функции менеджера ----------
    check("версия 0.8.24", __version__ == "0.8.24", __version__)
    check("is_installed возвращает bool",
          isinstance(upscale_manager.is_installed(), bool))
    check("model_scale: x4plus → 4",
          upscale_manager.model_scale("RealESRGAN_x4plus.pth") == 4)
    check("model_scale: x2plus → 2",
          upscale_manager.model_scale("RealESRGAN_x2plus.pth") == 2)
    check("model_scale: anime → 4",
          upscale_manager.model_scale("RealESRGAN_x4plus_anime_6B.pth") == 4)

    check("up_path: jpg → _x4",
          upscale_manager.up_path("/d/photo.jpg", 4) == "/d/photo_x4.jpg",
          upscale_manager.up_path("/d/photo.jpg", 4))
    check("up_path: jpg → _x2",
          upscale_manager.up_path("/d/photo.jpg", 2) == "/d/photo_x2.jpg")
    check("up_path: avif → png",
          upscale_manager.up_path("/d/photo.avif", 4) == "/d/photo_x4.png")
    check("up_path: webp → _x2.webp",
          upscale_manager.up_path("/d/photo.webp", 2) == "/d/photo_x2.webp")
    check("up_path: gif — отказ", upscale_manager.up_path("/d/p.gif", 4) == "")
    check("up_path: без расширения — отказ",
          upscale_manager.up_path("/d/p", 4) == "")
    check("up_path: уже результат x4 — отказ",
          upscale_manager.up_path("/d/photo_x4.jpg", 4) == "")
    check("up_path: уже результат x2 — отказ",
          upscale_manager.up_path("/d/photo_x2.jpg", 2) == "")
    check("up_path: png с альфой — обрабатывается",
          upscale_manager.up_path("/d/logo.png", 4) == "/d/logo_x4.png")

    check("asset_url: релизы GitHub",
          all("github.com/xinntao/Real-ESRGAN/releases/download/" in
              upscale_manager.asset_url(f)
              for f, _k in upscale_manager.UPSCALE_MODELS))
    check("asset_url: теги релизов",
          "v0.1.0" in upscale_manager.asset_url("RealESRGAN_x4plus.pth")
          and "v0.2.2.4" in upscale_manager.asset_url("RealESRGAN_x4plus_anime_6B.pth")
          and "v0.2.1" in upscale_manager.asset_url("RealESRGAN_x2plus.pth"))
    check("размеры весов соответствуют релизам (GitHub API, 2026-11-12)",
          upscale_manager._ASSET_SIZES == {
              "RealESRGAN_x4plus.pth": 67_040_989,
              "RealESRGAN_x4plus_anime_6B.pth": 17_938_799,
              "RealESRGAN_x2plus.pth": 67_061_725},
          str(upscale_manager._ASSET_SIZES))
    check("model_cache_dir: свой кэш real-esrgan",
          upscale_manager.model_cache_dir().replace("\\", "/").endswith(
              ".cache/ImageHunter/real-esrgan"))

    # ---------- крошечная модель: настоящий конвейер ----------
    tmp = patch_tiny()
    check("models_size: пустой кэш → 0", upscale_manager.models_size() == 0)
    check("model_file: ещё не скачан → пусто",
          upscale_manager.model_file(TINY) == "")
    make_tiny_weights(tmp)
    check("models_size: веса на месте",
          upscale_manager.models_size() > 0)
    check("model_file: путь к весам",
          upscale_manager.model_file(TINY) == os.path.join(tmp, TINY),
          upscale_manager.model_file(TINY))

    net, device, scale = upscale_manager._load_net(TINY)
    check("_load_net: строгая загрузка", net is not None and device == "cpu"
          and scale == TINY_SCALE, f"{device}, scale={scale}")

    sig = upscale_manager.UpscaleSignals()
    phases: list[tuple[str, int, int]] = []
    sig.phase.connect(lambda path, code, cur, total:
                      phases.append((code, cur, total)))

    src = os.path.join(tmp, "in.png")
    from PIL import Image  # noqa: E402
    Image.new("RGB", (64, 48), (120, 30, 200)).save(src)
    out = upscale_manager.up_path(src, TINY_SCALE)
    upscale_manager._upscale_image(src, out, net, device, scale, sig)
    res = Image.open(out)
    check("результат ×4: размер", res.size == (256, 192), str(res.size))
    check("результат ×4: RGB без альфы", res.mode == "RGB", res.mode)
    check("плитки: 64×48 целиком влезает по высоте — 2 плитки",
          phases == [("tile", 1, 2), ("tile", 2, 2)], str(phases))

    # альфа-канал сохраняется (PNG)
    src_a = os.path.join(tmp, "alpha.png")
    Image.new("RGBA", (40, 30), (10, 200, 30, 128)).save(src_a)
    out_a = upscale_manager.up_path(src_a, TINY_SCALE)
    upscale_manager._upscale_image(src_a, out_a, net, device, scale, sig)
    res_a = Image.open(out_a)
    check("альфа: режим RGBA", res_a.mode == "RGBA", res_a.mode)
    check("альфа: размер ×4", res_a.size == (160, 120), str(res_a.size))
    check("альфа: маска Lanczos сохраняет непрозрачность 128",
          res_a.getchannel("A").getextrema() == (128, 128),
          str(res_a.getchannel("A").getextrema()))

    # RGBA → JPEG: белый фон вместо чёрной прозрачности
    out_j = upscale_manager.up_path(src_a, TINY_SCALE).replace(".png", ".jpg")
    upscale_manager._upscale_image(src_a, out_j, net, device, scale, sig)
    res_j = Image.open(out_j)
    check("RGBA → JPEG: результат непрозрачный RGB", res_j.mode == "RGB",
          res_j.mode)
    rgb = res_j.convert("RGB").getpixel((0, 0))
    check("RGBA → JPEG: угол светлый (не чёрный)", sum(rgb) > 250, str(rgb))

    # плитки: 100×60 при TILE=16 → 7×4 = 28 плиток
    upscale_manager.TILE, upscale_manager.TILE_PAD = 16, 4
    phases.clear()
    src_t = os.path.join(tmp, "tiled.png")
    Image.new("RGB", (100, 60), (9, 9, 9)).save(src_t)
    out_t = upscale_manager.up_path(src_t, TINY_SCALE)
    upscale_manager._upscale_image(src_t, out_t, net, device, scale, sig)
    check("плитки: 28 фаз, последняя «tile 28/28»",
          phases and phases[-1] == ("tile", 28, 28), str(phases[-1] if phases else None))
    check("плитки: все номера по порядку",
          [p[1] for p in phases] == list(range(1, 29)))
    check("плитки: размер результата ×4",
          Image.open(out_t).size == (400, 240),
          str(Image.open(out_t).size))
    upscale_manager.TILE, upscale_manager.TILE_PAD = 256, 10   # откат

    # предохранитель: 4000×4000 ×4 = 64 МП > 50 МП — отказ ДО сети
    src_big = os.path.join(tmp, "big.png")
    Image.new("RGB", (4000, 4000), (1, 2, 3)).save(src_big)
    try:
        upscale_manager._upscale_image(src_big, os.path.join(tmp, "big_x4.png"),
                                       net, device, scale, sig)
        check("предохранитель 50 МП: отказ", False, "не отказал")
    except ValueError as exc:
        check("предохранитель 50 МП: отказ", "50 МП" in str(exc), str(exc)[:80])
    check("предохранитель: файл-результат не создан",
          not os.path.exists(os.path.join(tmp, "big_x4.png")))

    # ---------- UpscaleTask: настоящая пачка ----------
    sigs = upscale_manager.UpscaleSignals()
    files: dict[str, list] = {"done": [], "batch": [], "start": []}
    sigs.file_done.connect(lambda p, o, ok, err:
                           files["done"].append((p, o, ok, err)))
    sigs.batch_done.connect(lambda ok, fail:
                            files["batch"].append((ok, fail)))
    sigs.file_start.connect(lambda p, idx:
                            files["start"].append((p, idx)))
    src2 = os.path.join(tmp, "second.webp")
    Image.new("RGB", (32, 32), (250, 128, 0)).save(src2)
    jobs = [(src, upscale_manager.up_path(src, 4)),
            (src2, upscale_manager.up_path(src2, 4))]
    task = upscale_manager.UpscaleTask(jobs, TINY, sigs)
    task.run()   # не через пул: нужен синхронный результат
    check("задача: оба файла обработаны",
          len(files["batch"]) == 1 and files["batch"][0] == (2, 0),
          str(files["batch"]))
    check("задача: file_start по каждому",
          [f[1] for f in files["start"]] == [1, 2], str(files["start"]))
    check("задача: результаты существуют",
          all(os.path.exists(o) for _p, o, ok, _e in files["done"] if ok),
          str([o for _p, o, _ok, _e in files["done"]]))
    check("задача: оригиналы не тронуты",
          os.path.exists(src) and os.path.exists(src2)
          and Image.open(src).size == (64, 48))

    # задача без весов: честная ошибка по каждому файлу
    files.clear()
    files.update({"done": [], "batch": [], "start": []})
    task = upscale_manager.UpscaleTask(jobs, "NoSuchWeights.pth", sigs)
    task.run()
    check("задача без весов: ошибка по каждому файлу",
          len(files["done"]) == 2 and all(not ok for _p, _o, ok, _e in files["done"]),
          str(files["done"]))
    check("задача без весов: batch_done(0, 2)",
          files["batch"] == [(0, 2)], str(files["batch"]))

    # ---------- скачивание весов с GitHub (локальный HTTP-сервер) ----------
    payload = os.urandom(1024) * 4   # 4096 байт
    srv = _HTTPServer(payload)
    srv.start()
    real_asset_url = upscale_manager.asset_url
    upscale_manager._ASSET_SIZES[TINY] = len(payload)
    upscale_manager.asset_url = lambda fname: f"http://127.0.0.1:{srv.port}/{fname}"
    os.remove(os.path.join(tmp, TINY))   # кэш пуст — качаем
    dl: dict[str, list] = {"start": [], "prog": [], "done": []}
    sigs.model_dl_start.connect(lambda m, total:
                                dl["start"].append((m, total)))
    sigs.model_dl_progress.connect(lambda done, total:
                                   dl["prog"].append((done, total)))
    sigs.model_dl_done.connect(lambda m, size, ms:
                               dl["done"].append((m, size, ms)))
    # прямой вызов — как задача: ставим репортёра на время скачивания
    upscale_manager._DL_REPORTER = sigs
    try:
        path = upscale_manager._ensure_model_downloaded(TINY)
    finally:
        upscale_manager._DL_REPORTER = None
    check("скачивание: файл на месте и размер верен",
          path == os.path.join(tmp, TINY)
          and os.path.getsize(path) == len(payload))
    check("скачивание: сигналы start и done",
          dl["start"] and dl["start"][0] == ("TinyTest", len(payload))
          and len(dl["done"]) == 1, str(dl["start"] + dl["done"]))
    check("скачивание: прогресс доходит до 100 %",
          dl["prog"] and dl["prog"][-1] == (len(payload), len(payload)),
          str(dl["prog"][-1] if dl["prog"] else None))
    # повтор: файл уже есть — сигналов больше не приходит
    n_done = len(dl["done"])
    upscale_manager._ensure_model_downloaded(TINY)
    check("скачивание: уже скачанный не перекачивается",
          len(dl["done"]) == n_done and os.path.exists(path))

    # битый размер: релиз неизменяем, отличие — битая скачка
    os.remove(path)
    srv2 = _HTTPServer(payload, truncate=5)
    srv2.start()
    upscale_manager.asset_url = lambda fname: f"http://127.0.0.1:{srv2.port}/{fname}"
    try:
        upscale_manager._ensure_model_downloaded(TINY)
        check("битый размер: отказ", False, "не отказал")
    except OSError as exc:
        check("битый размер: отказ", "size mismatch" in str(exc), str(exc)[:60])
    check("битый размер: «.part» подчищен",
          not os.path.exists(path + ".part"))
    srv.stop()
    srv2.stop()
    upscale_manager.asset_url = real_asset_url   # тестовые адреса больше не живы
    # восстановить веса для следующих сценариев
    make_tiny_weights(tmp)

    # ---------- Install/Uninstall/Update/Revert ----------
    sigs = upscale_manager.UpscaleSignals()
    got: dict[str, list] = {k: [] for k in
                            ("install", "uninstall", "update", "revert")}
    sigs.install_done.connect(lambda ok, info:
                              got["install"].append((ok, info)))
    sigs.uninstall_done.connect(lambda ok, info, mb:
                                got["uninstall"].append((ok, info, mb)))
    sigs.update_done.connect(lambda ok, what, info:
                             got["update"].append((ok, what, info)))
    sigs.revert_done.connect(lambda rem, err:
                             got["revert"].append((rem, err)))

    real_run_pip = upscale_manager._run_pip
    pip_calls: list[list[str]] = []
    upscale_manager._run_pip = lambda args: (pip_calls.append(args), (True, ""))[1]

    upscale_manager.InstallTask(sigs).run()
    check("InstallTask: torch уже стоит — pip не зовётся",
          got["install"] == [(True, "")] and pip_calls == [],
          str(got["install"]))

    real_installed = upscale_manager.is_installed
    upscale_manager.is_installed = lambda: False
    upscale_manager.InstallTask(sigs).run()
    check("InstallTask: ставит ровно torch",
          pip_calls == [["install", "--disable-pip-version-check", "torch"]],
          str(pip_calls))
    upscale_manager.is_installed = real_installed

    # UninstallTask: сосед-модуль жив — torch остаётся, кэш уходит
    real_wm = upscale_manager._wm_installed
    upscale_manager._wm_installed = lambda: True
    upscale_manager.UninstallTask(sigs).run()
    check("UninstallTask: torch при живом wm не вычищается",
          pip_calls == [["install", "--disable-pip-version-check", "torch"]],
          str(pip_calls))
    check("UninstallTask: кэш весов вычищен всё равно",
          not os.path.exists(os.path.join(tmp, TINY))
          and got["uninstall"] and got["uninstall"][-1][0] is True)
    # UninstallTask: соседа нет — pip uninstall -y torch
    upscale_manager._wm_installed = lambda: False
    upscale_manager.UninstallTask(sigs).run()
    check("UninstallTask: без wm — pip uninstall -y torch",
          pip_calls[-1] == ["uninstall", "-y", "torch"], str(pip_calls[-1]))
    upscale_manager._wm_installed = real_wm
    make_tiny_weights(tmp)   # вернуть веса

    # UpdateTask: актуальные веса — «ничего не изменилось», torch версией
    real_ver = upscale_manager.installed_version
    upscale_manager.installed_version = lambda: "2.9.9"
    upscale_manager.asset_url = lambda fname: f"http://update-test/{fname}"
    local = os.path.join(tmp, TINY)
    real_len = upscale_manager.remote_content_length
    upscale_manager.remote_content_length = lambda url: os.path.getsize(local)
    upscale_manager.UpdateTask(sigs, TINY).run()
    check("UpdateTask: размеры совпали — обновлений нет, torch версией",
          got["update"][-1][0] is True and "torch 2.9.9" in got["update"][-1][1],
          str(got["update"][-1]))
    # UpdateTask: размер на GitHub отличается → перекачка
    re_downloaded = []
    real_ensure = upscale_manager._ensure_model_downloaded

    def fake_ensure(fname):
        make_tiny_weights(tmp)          # перекачка кладёт файл на место
        re_downloaded.append(fname)
        return os.path.join(tmp, fname)

    upscale_manager._ensure_model_downloaded = fake_ensure
    upscale_manager.remote_content_length = lambda url: os.path.getsize(local) + 1
    upscale_manager.UpdateTask(sigs, TINY).run()
    check("UpdateTask: отличается — веса перекачиваются",
          re_downloaded == [TINY] and "веса" in got["update"][-1][1].lower()
          or re_downloaded == [TINY],
          str(got["update"][-1]))
    # UpdateTask: GitHub недоступен (size=0) — честная неудача проверки
    upscale_manager.remote_content_length = lambda url: 0
    upscale_manager._ensure_model_downloaded = real_ensure
    upscale_manager.UpdateTask(sigs, TINY).run()
    check("UpdateTask: github.com недоступен — неудача проверки в итоге",
          got["update"][-1][0] is True and "github.com" in got["update"][-1][1],
          str(got["update"][-1]))
    # UpdateTask: веса ещё не скачивались
    os.remove(local)
    upscale_manager.UpdateTask(sigs, TINY).run()
    check("UpdateTask: веса не скачивались — в итоге это сказано",
          got["update"][-1][0] is True and "не скачивались" in got["update"][-1][1],
          str(got["update"][-1]))
    # UpdateTask: версию torch определить нельзя — честный отказ
    upscale_manager.installed_version = lambda: ""
    upscale_manager.UpdateTask(sigs, TINY).run()
    check("UpdateTask: нет версии torch — отказ",
          got["update"][-1][0] is False, str(got["update"][-1]))
    upscale_manager.installed_version = real_ver
    upscale_manager.remote_content_length = real_len
    upscale_manager.asset_url = real_asset_url
    make_tiny_weights(tmp)

    # RevertTask: свои файлы удаляет, отсутствующий — ошибкой
    r1 = os.path.join(tmp, "r1_x4.png")
    r2 = os.path.join(tmp, "r2_x4.png")
    Image.new("RGB", (8, 8)).save(r1)
    Image.new("RGB", (8, 8)).save(r2)
    upscale_manager.RevertTask([r1, r2, os.path.join(tmp, "ghost_x4.png")],
                               sigs).run()
    rem, err = got["revert"][-1]
    check("RevertTask: существующие удалены",
          sorted(rem) == sorted([r1, r2]) and not os.path.exists(r1)
          and not os.path.exists(r2))
    check("RevertTask: отсутствующий — ошибка, не катастрофа",
          len(err) == 1 and err[0][0] == os.path.join(tmp, "ghost_x4.png"))

    upscale_manager._run_pip = real_run_pip

    # ---------- вьюер: кнопка, меню, e2e ----------
    viewer = LocalViewer()
    check("кнопка ✨ существует", hasattr(viewer, "_on_up_button"))
    check("кнопка ✨ на панели инструментов",
          viewer.btn_up.parent() is not None
          and viewer.btn_up.parentWidget().objectName() == "toolsPanel",
          viewer.btn_up.parentWidget().objectName()
          if viewer.btn_up.parentWidget() else "none")
    check("кнопка ✨ с подписью tr(viewer.up)",
          viewer.btn_up.text() == i18n.tr("viewer.up"), viewer.btn_up.text())
    menu, acts = viewer._build_list_menu()
    check("в контекстном меню ленты есть «Улучшить»",
          acts.get("up") is not None
          and acts["up"].text() == i18n.tr("viewer.up"))
    check("ups_current_model — дефолт",
          viewer.ups_current_model() == upscale_manager.DEFAULT_MODEL,
          viewer.ups_current_model())

    # клик без выбора
    viewer._on_up_button()
    check("клик без выбора: подсказка в статусе",
          viewer.status.text() == i18n.tr("viewer.up_none"),
          viewer.status.text())
    # guard busy
    viewer._ups_busy = True
    viewer._on_up_button()
    check("guard busy: повторный запуск отбивается",
          viewer.status.text() == i18n.tr("viewer.up_busy"),
          viewer.status.text())
    viewer._ups_busy = False

    # e2e: настоящая крошечная модель через клик по кнопке
    # (отдельная папка: tmp вычищается UninstallTask-ом как кэш весов)
    tmpdir = tempfile.mkdtemp(prefix="ih_upscale_files_")
    Image.new("RGB", (64, 48), (120, 30, 200)).save(
        os.path.join(tmpdir, "in.png"))
    Image.new("RGB", (32, 32), (250, 128, 0)).save(
        os.path.join(tmpdir, "second.webp"))
    viewer.ups_set_model(TINY)   # e2e идёт на крошечных весах из кэша
    viewer.load_folder(tmpdir)
    wait_until(lambda: viewer.list.count() == 2)
    viewer.list.selectAll()
    app.processEvents()
    check("e2e: выделено два файла", len(viewer.list.selected_paths()) == 2,
          str(len(viewer.list.selected_paths())))
    viewer._on_up_button()
    check("e2e: задача пошла (busy)", viewer._ups_busy)
    ok_done = wait_until(lambda: not viewer._ups_busy, 60)
    check("e2e: пачка завершилась", ok_done)
    # итог: счётчики задачи (текст статуса сразу перебивается rescan'ом
    # ленты после refresh() — проверяем состояние, а не мигнувшую строку)
    check("e2e: счётчики — 2 без ошибок",
          viewer._ups_ok == 2 and viewer._ups_fail == 0,
          f"ok={viewer._ups_ok} fail={viewer._ups_fail}")
    outs = [os.path.join(tmpdir, "in_x4.png"),
            os.path.join(tmpdir, "second_x4.webp")]
    check("e2e: результаты «_x4» на диске",
          all(os.path.exists(o) for o in outs),
          str([os.path.exists(o) for o in outs]))
    wait_until(lambda: all(o in viewer._paths for o in outs))
    check("e2e: результаты появились в ленте",
          all(o in viewer._paths for o in outs),
          str([p for p in viewer._paths if p.endswith(("x4.png", "x4.webp"))]))

    # диалог «Сохранить/Вернуть»: «Вернуть оригиналы» удаляет результаты
    dlg = viewer._ups_choice
    check("диалог выбора открыт", isinstance(dlg, QDialog) and dlg.isVisible(),
          str(dlg))
    check("диалог выбора с текстами улучшения",
          dlg.windowTitle() == i18n.tr("viewer.up")
          and dlg.btn_save.text() == i18n.tr("viewer.up_btn_save")
          and dlg.btn_revert.text() == i18n.tr("viewer.up_btn_revert"),
          f"{dlg.windowTitle()} | {dlg.btn_save.text()}")
    dlg.btn_revert.click()
    ok_rev = wait_until(lambda: viewer._ups_choice is None
                        and viewer.status.text() == i18n.tr(
                            "viewer.up_reverted", n=2), 10)
    check("диалог «Вернуть оригиналы»: результаты удалены",
          ok_rev and not any(os.path.exists(o) for o in outs)
          and os.path.exists(os.path.join(tmpdir, "in.png")),
          viewer.status.text())

    # установка-продолжение: отложенная пачка после install_done
    from PySide6.QtCore import QRunnable as _QR  # noqa: E402

    class FakeInstall(_QR):
        def __init__(self, signals):
            super().__init__()
            self.signals = signals

        def run(self):
            self.signals.install_done.emit(True, "")

    real_it = upscale_manager.InstallTask
    upscale_manager.InstallTask = FakeInstall
    started = []
    real_start = viewer._ups_start
    viewer._ups_start = lambda paths: started.append(list(paths))
    viewer._ups_start_install(pending=[src])
    check("установка: busy и pending запомнены",
          viewer._ups_busy and viewer._ups_pending == [src])
    wait_until(lambda: not viewer._ups_busy)
    check("установка: отложенная пачка продолжена",
          started == [[src]], str(started))
    viewer._ups_start = real_start
    upscale_manager.InstallTask = real_it

    # выбор модели: запоминается и валидируется
    viewer.ups_set_model("RealESRGAN_x2plus.pth")
    check("выбор модели: запомнен",
          viewer.ups_current_model() == "RealESRGAN_x2plus.pth"
          and QSettings("ImageHunter", "ImageHunter").value(
              "viewer/up_model", "") == "RealESRGAN_x2plus.pth")
    viewer2 = LocalViewer()
    check("выбор модели: валидируется при загрузке вьюера",
          viewer2.ups_current_model() == "RealESRGAN_x2plus.pth",
          viewer2.ups_current_model())
    st.setValue("viewer/up_model", "GoneModel.pth")
    viewer3 = LocalViewer()
    check("невалидная модель откатывается на дефолт",
          viewer3.ups_current_model() == upscale_manager.DEFAULT_MODEL,
          viewer3.ups_current_model())
    st.setValue("viewer/up_model", "")

    # ---------- меню «Модули»: раздел улучшения качества ----------
    class StubMain(QMainWindow):
        def __init__(self, viewer):
            super().__init__()
            self.local = viewer

        def server_running(self):
            return False

        def server_port(self):
            return 8477

        def server_toggle(self):
            pass

        def server_set_autostart(self, on):
            pass

        def show_server_dialog(self):
            pass

        def restart_app(self):
            pass

    stub = StubMain(viewer2)
    mm = ModulesMenu(stub)
    mm._rebuild()
    texts = [a.text() for a in mm.actions()]
    check("меню «Модули»: раздел улучшения качества",
          i18n.tr("modules.up_header", state=i18n.tr("modules.installed"))
          in texts, str(texts[:8]))
    check("меню «Модули»: версии torch",
          any("torch" in t for t in texts), str([t for t in texts if "torch" in t]))
    check("меню «Модули»: удалить/обновить и модель",
          i18n.tr("viewer.up_menu_uninstall") in texts
          and i18n.tr("viewer.up_menu_update") in texts
          and i18n.tr("viewer.up_model_menu") in texts)

    # ---------- i18n: все новые ключи на трёх языках ----------
    missing = []
    for k, v in i18n._STRINGS.items():
        if k.startswith(("viewer.up", "log.event.up", "modules.up")):
            for lang in ("ru", "en", "zh"):
                if not v.get(lang):
                    missing.append((k, lang))
    check("i18n: ключи upscale на ru/en/zh", not missing, str(missing))

    # ---------- уборка ----------
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmpdir, ignore_errors=True)
    upscale_manager.model_cache_dir = lambda: os.path.join(
        os.path.expanduser("~"), ".cache", "ImageHunter", "real-esrgan")
    for d in (upscale_manager.model_cache_dir(),):
        shutil.rmtree(d, ignore_errors=True)   # тест мог оставить кэш
    st.remove("viewer/up_model")
    st.sync()

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
