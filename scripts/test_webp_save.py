"""Оффлайн-тест сохранения отмеченных картинок как WebP.

Проверяет: правила имён (название.webp, название-1.webp, название-2.webp…),
пропуск занятых имён (в т.ч. без учёта регистра), перекодирование в WebP
и полный конвейер WebpSaver на локальном HTTP-сервере (без реальной сети).

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_webp_save.py
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

from app.core import webp_saver  # noqa: E402

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

    tmp = tempfile.mkdtemp(prefix="ih_webp_")
    try:
        # 1. очистка имени файла
        check("sanitize: запрещённые символы убраны",
              webp_saver.sanitize_base_name('кот: "Мурзик" <2024>?') == "кот Мурзик 2024",
              webp_saver.sanitize_base_name('кот: "Мурзик" <2024>?'))
        check("sanitize: пустое имя → пустая строка (заменит вызывающий)",
              webp_saver.sanitize_base_name("  ...  ") == "")

        # 2. имена пачки в пустой папке
        names = webp_saver.assign_webp_names(tmp, "кот", 3)
        check("имена пачки: название.webp, название-1.webp, название-2.webp",
              names == ["кот.webp", "кот-1.webp", "кот-2.webp"], str(names))

        # 3. пропуск занятых имён (есть кот.webp и кот-2.webp)
        used_dir = tempfile.mkdtemp(prefix="ih_webp_u_", dir=tmp)
        open(os.path.join(used_dir, "кот.webp"), "wb").close()
        open(os.path.join(used_dir, "кот-2.webp"), "wb").close()
        names2 = webp_saver.assign_webp_names(used_dir, "кот", 4)
        check("занятые имена пропускаются",
              names2 == ["кот-1.webp", "кот-3.webp", "кот-4.webp", "кот-5.webp"], str(names2))

        # 4. регистр не важен (как на дисках Windows)
        case_dir = tempfile.mkdtemp(prefix="ih_webp_c_", dir=tmp)
        open(os.path.join(case_dir, "Кот-1.webp"), "wb").close()
        names3 = webp_saver.assign_webp_names(case_dir, "кот", 2)
        check("коллизия без учёта регистра",
              names3 == ["кот.webp", "кот-2.webp"], str(names3))

        # 5. перекодирование PNG-байтов → файл WebP
        out = os.path.join(tmp, "conv.webp")
        w, h = webp_saver.decode_to_webp(image_bytes("PNG"), out)
        back = QImage(out)
        check("PNG → WebP: файл декодируется, размер совпадает",
              not back.isNull() and (w, h) == (320, 240)
              and (back.width(), back.height()) == (320, 240),
              f"{w}×{h}")

        # 6. полный конвейер WebpSaver на локальном HTTP-сервере
        _Handler.files = {
            "/a.png": image_bytes("PNG"),
            "/b.jpg": image_bytes("JPEG", 800, 600, 0x884422),
        }
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"

        save_dir = tempfile.mkdtemp(prefix="ih_webp_s_", dir=tmp)
        urls = [base + "/a.png", base + "/missing.png", base + "/b.jpg"]
        names4 = webp_saver.assign_webp_names(save_dir, "кот", 3)

        saver = webp_saver.WebpSaver()
        results: list = []
        done: dict = {}
        saver.file_done.connect(lambda i, ok, info: results.append((i, ok, info)))
        saver.finished.connect(lambda ok, fail, folder: done.update(ok=ok, fail=fail))
        saver.start(list(zip(urls, names4)), None, save_dir)

        deadline = time.time() + 30
        while "ok" not in done and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
            app.processEvents()
        server.shutdown()

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
