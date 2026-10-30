"""Оффлайн-тест сохранения отмеченных картинок в выбранном формате.

Проверяет: правила имён (название.ext, название-1.ext, название-2.ext…),
пропуск занятых имён (в т.ч. без учёта регистра), точечные проверки когда
листинг папки недоступен, отказ от перезаписи существующих файлов в момент
записи (чужой файл уцелел), все форматы (WebP/PNG/JPEG/BMP/TIFF),
наложение альфа-канала на белый фон для JPEG и полный конвейер ImageSaver
на локальном HTTP-сервере (без реальной сети).

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_save_formats.py
"""

import http.server
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import image_saver  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def image_bytes(fmt: str, w: int = 320, h: int = 240, color: int = 0x336699) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(color)
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.ReadWrite)
    assert img.save(buf, fmt, 85)
    return bytes(buf.data())


def alpha_image_bytes(w: int = 64, h: int = 64) -> bytes:
    """PNG с прозрачным фоном — для проверки наложения на белый в JPEG."""
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0)   # полностью прозрачный
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.ReadWrite)
    assert img.save(buf, "PNG")
    return bytes(buf.data())


class _Handler(http.server.BaseHTTPRequestHandler):
    files: dict = {}

    def do_GET(self):
        body = self.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        ctype = "image/png" if self.path.endswith(".png") else "image/jpeg"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    tmp = tempfile.mkdtemp(prefix="ih_save_")
    try:
        # 1. очистка имени файла
        check("sanitize: запрещённые символы убраны",
              image_saver.sanitize_base_name('кот: "Мурзик" <2024>?') == "кот Мурзик 2024",
              image_saver.sanitize_base_name('кот: "Мурзик" <2024>?'))
        check("sanitize: пустое имя → пустая строка (заменит вызывающий)",
              image_saver.sanitize_base_name("  ...  ") == "")

        # 2. имена пачки в пустой папке
        names = image_saver.assign_image_names(tmp, "кот", ".webp", 3)
        check("имена пачки: название.webp, название-1.webp, название-2.webp",
              names == ["кот.webp", "кот-1.webp", "кот-2.webp"], str(names))
        names_png = image_saver.assign_image_names(tmp, "кот", ".png", 2)
        check("расширение подставляется: .png",
              names_png == ["кот.png", "кот-1.png"], str(names_png))

        # 3. пропуск занятых имён (есть кот.webp и кот-2.webp)
        used_dir = tempfile.mkdtemp(prefix="ih_save_u_", dir=tmp)
        open(os.path.join(used_dir, "кот.webp"), "wb").close()
        open(os.path.join(used_dir, "кот-2.webp"), "wb").close()
        names2 = image_saver.assign_image_names(used_dir, "кот", ".webp", 4)
        check("занятые имена пропускаются",
              names2 == ["кот-1.webp", "кот-3.webp", "кот-4.webp", "кот-5.webp"], str(names2))

        # 4. регистр не важен (как на дисках Windows)
        case_dir = tempfile.mkdtemp(prefix="ih_save_c_", dir=tmp)
        open(os.path.join(case_dir, "Кот-1.webp"), "wb").close()
        names3 = image_saver.assign_image_names(case_dir, "кот", ".webp", 2)
        check("коллизия без учёта регистра",
              names3 == ["кот.webp", "кот-2.webp"], str(names3))

        # 4b. листинг папки недоступен — точечные проверки кандидатов всё равно
        # находят занятое имя (chmod 333: listdir запрещён, lexists работает)
        probe_dir = tempfile.mkdtemp(prefix="ih_save_p_", dir=tmp)
        open(os.path.join(probe_dir, "кот-1.webp"), "wb").close()
        os.chmod(probe_dir, 0o333)
        try:
            check("листинг недоступной папки → None",
                  image_saver._existing_lower_names(probe_dir) is None)
            names_p = image_saver.assign_image_names(probe_dir, "кот", ".webp", 2)
            check("точечные проверки пропускают занятое имя",
                  names_p == ["кот.webp", "кот-2.webp"], str(names_p))
        finally:
            os.chmod(probe_dir, 0o755)

        # 5. перекодирование PNG-байтов в каждый формат
        for fmt_name in image_saver.SAVE_FORMATS:
            qt_fmt, ext, _quality = image_saver.SAVE_FORMATS[fmt_name]
            out = os.path.join(tmp, f"conv{ext}")
            img = image_saver.decode_image(image_bytes("PNG"))
            w, h = image_saver.save_image(img, out, fmt_name)
            back = QImage(out)
            check(f"{fmt_name}: файл декодируется, размер совпадает",
                  not back.isNull() and (w, h) == (320, 240)
                  and (back.width(), back.height()) == (320, 240), f"{w}×{h}")

        # 5b. альфа-канал → белый фон для JPEG (иначе прозрачность станет чёрной)
        out_jpg = os.path.join(tmp, "alpha.jpg")
        img = image_saver.decode_image(alpha_image_bytes())
        image_saver.save_image(img, out_jpg, "JPEG")
        back = QImage(out_jpg)
        check("JPEG: альфа наложена на белый (формат без альфы)",
              not back.isNull() and not back.hasAlphaChannel())
        if not back.isNull():
            px = back.pixelColor(1, 1)
            check("JPEG: прозрачные пиксели стали белыми",
                  px.red() > 245 and px.green() > 245 and px.blue() > 245,
                  f"rgb({px.red()},{px.green()},{px.blue()})")

        # 6. полный конвейер ImageSaver на локальном HTTP-сервере
        _Handler.files = {
            "/a.png": image_bytes("PNG"),
            "/b.jpg": image_bytes("JPEG", 800, 600, 0x884422),
        }
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"

        save_dir = tempfile.mkdtemp(prefix="ih_save_s_", dir=tmp)
        urls = [base_url + "/a.png", base_url + "/missing.png", base_url + "/b.jpg"]
        names4 = image_saver.assign_image_names(save_dir, "кот", ".webp", 3)

        saver = image_saver.ImageSaver()
        results: list = []
        done: dict = {}
        saver.file_done.connect(lambda i, ok, info: results.append((i, ok, info)))
        saver.finished.connect(lambda ok, fail, folder: done.update(ok=ok, fail=fail))
        saver.start(list(zip(urls, names4)), None, save_dir, "кот", "WebP")

        deadline = time.time() + 30
        while "ok" not in done and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
            app.processEvents()

        check("конвейер: 2 сохранено, 1 ошибка",
              done.get("ok") == 2 and done.get("fail") == 1, str(done))
        saved = sorted(os.listdir(save_dir))
        check("на диске кот.webp и кот-2.webp",
              "кот.webp" in saved and "кот-2.webp" in saved, str(saved))
        check("имя неудавшегося файла не занято на диске",
              "кот-1.webp" not in saved)
        first = QImage(os.path.join(save_dir, "кот.webp"))
        second = QImage(os.path.join(save_dir, "кот-2.webp"))
        check("кот.webp — WebP 320×240",
              not first.isNull() and (first.width(), first.height()) == (320, 240))
        check("кот-2.webp — WebP 800×600",
              not second.isNull() and (second.width(), second.height()) == (800, 600))
        errs = [r for r in results if not r[1]]
        check("ошибка 404 доложена в file_done", len(errs) == 1, str(errs))
        check("после пачки saver не занят", not saver.is_busy())

        # 7. перезапись невозможна и в момент записи: чужой файл появился
        # уже ПОСЛЕ выдачи имён (как будто его создала другая программа)
        race_dir = tempfile.mkdtemp(prefix="ih_save_r_", dir=tmp)
        urls2 = [base_url + "/a.png", base_url + "/b.jpg"]   # оба живые (без 404)
        names5 = image_saver.assign_image_names(race_dir, "кот", ".webp", 2)
        foreign = os.path.join(race_dir, "кот.webp")
        open(foreign, "wb").close()
        saver2 = image_saver.ImageSaver()
        done2: dict = {}
        saver2.finished.connect(lambda ok, fail, f: done2.update(ok=ok, fail=fail))
        saver2.start(list(zip(urls2, names5)), None, race_dir, "кот", "WebP")
        deadline = time.time() + 30
        while "ok" not in done2 and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
            app.processEvents()
        check("гонка записи: 2 сохранено, 0 ошибок",
              done2.get("ok") == 2 and done2.get("fail") == 0, str(done2))
        check("чужой файл не перезаписан (0 байт)", os.path.getsize(foreign) == 0,
              str(os.path.getsize(foreign)))
        saved2 = sorted(os.listdir(race_dir))
        check("новые файлы уехали на кот-1 и кот-2",
              saved2 == ["кот-1.webp", "кот-2.webp", "кот.webp"], str(saved2))
        check("кот-1.webp — 800×600 (второй URL)",
              QImage(os.path.join(race_dir, "кот-1.webp")).height() == 600)
        check("кот-2.webp — 320×240 (первый URL уехал на свободный номер)",
              QImage(os.path.join(race_dir, "кот-2.webp")).height() == 240)
        server.shutdown()
        server.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
