"""Оффлайн-тест поддержки AVIF и фонового просмотра (v0.4.0).

Проверяется:
1. AVIF декодируется и из байтов, и из файла (Qt сам AVIF не умеет —
   работает Pillow-кодек через app.core.imgload);
2. AVIF под чужим расширением («фото.jpg» с содержимым AVIF) тоже читается;
3. .avif попадает в списки папок и находит миниатюру;
4. выбор плитки больше не блокирует интерфейс: просмотр грузится в фоне;
5. битые данные дают внятную причину ошибки (без AttributeError
   «QImage has no attribute errorString» — баг журналирования v0.3.5);
6. скачанный AVIF сохраняется в выбранный формат (WebP);
7. новые i18n-ключи есть во всех трёх языках.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_avif.py
"""

import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import applog, i18n, imgload, image_saver  # noqa: E402
from app.ui.local_viewer import (  # noqa: E402
    IMAGE_EXTS, LocalViewer, scan_image_entries,
)

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def make_avif_bytes(w: int = 96, h: int = 72, color=(180, 60, 30)) -> bytes:
    from PIL import Image
    im = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    im.save(buf, format="AVIF")
    return buf.getvalue()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    applog.setup()
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")

    check("Pillow AVIF-кодек доступен", imgload.AVIF_OK)

    tmp = tempfile.mkdtemp(prefix="ih_avif_")
    try:
        avif_bytes = make_avif_bytes()
        path_avif = os.path.join(tmp, "картинка.avif")
        path_fake_jpg = os.path.join(tmp, "фото.jpg")     # AVIF под расширением .jpg
        with open(path_avif, "wb") as f:
            f.write(avif_bytes)
        with open(path_fake_jpg, "wb") as f:
            f.write(avif_bytes)
        img = QImage(24, 24, QImage.Format.Format_RGB32)
        img.fill(0x336699)
        assert img.save(os.path.join(tmp, "обычная.png"))

        # 1. магия AVIF
        check("looks_like_avif распознаёт байты", imgload.looks_like_avif(avif_bytes))
        check("looks_like_avif не путает PNG",
              not imgload.looks_like_avif(b"\x89PNG\r\n\x1a\n0000000"))

        # 2. декодирование из байтов
        img, err = imgload.decode_bytes(avif_bytes)
        check("decode_bytes: AVIF → QImage", not img.isNull() and not err,
              f"{img.width()}×{img.height()} err={err}")
        check("размер совпал", (img.width(), img.height()) == (96, 72))

        # 3. декодирование из файла (по расширению и по содержимому)
        img, err = imgload.load_file(path_avif)
        check("load_file: .avif файл", not img.isNull() and not err, err)
        img, err = imgload.load_file(path_fake_jpg)
        check("load_file: AVIF внутри .jpg (по содержимому)",
              not img.isNull() and not err, err)

        # 4. .avif в списке расширений и в скане папки
        check(".avif/.avifs в IMAGE_EXTS",
              ".avif" in IMAGE_EXTS and ".avifs" in IMAGE_EXTS)
        names = {os.path.basename(p) for p, _s, _m in scan_image_entries(tmp)}
        check("скан папки видит .avif и AVIF-под-.jpg",
              "картинка.avif" in names and "фото.jpg" in names, str(sorted(names)))

        # 5. битые данные: внятная причина, без AttributeError
        try:
            image_saver.decode_image(b"this is definitely not an image")
            check("decode_image: мусор даёт ValueError", False, "исключения не было")
        except ValueError as e:
            msg = str(e)
            check("decode_image: мусор даёт ValueError", True)
            check("причина ошибки — от декодера, а не AttributeError",
                  "errorString" not in msg and "attribute" not in msg.lower(), msg)
        except AttributeError as e:
            check("decode_image: мусор даёт ValueError", False, f"AttributeError: {e}")

        # 6. AVIF-скачивание: декодировать и пересохранить в WebP
        decoded = image_saver.decode_image(avif_bytes)
        out = os.path.join(tmp, "из_авиф.webp")
        w, h = image_saver.save_image(decoded, out, "WebP")
        check("AVIF → WebP сохраняется", os.path.exists(out) and w == 96 and h == 72,
              f"{w}×{h}")
        back = QImage(out)
        check("сохранённый WebP читается обратно", not back.isNull())

        # 7. просмотр папки: AVIF получает миниатюру (фоновая задача)
        viewer = LocalViewer()
        viewer.resize(1280, 800)
        viewer.show()          # offscreen: без показа вьюпорт пуст и миниатюры не ставятся
        app.processEvents()
        viewer.load_folder(tmp)
        app.processEvents()
        rows = {os.path.basename(viewer._paths[r]): r
                for r in range(len(viewer._paths))}
        deadline = time.time() + 15
        while time.time() < deadline:
            app.processEvents()
            if rows["картинка.avif"] in viewer._thumb_done_rows:
                break
            time.sleep(0.03)
        check("миниатюра AVIF готова",
              rows["картинка.avif"] in viewer._thumb_done_rows,
              f"done={sorted(viewer._thumb_done_rows)}")

        # 8. выбор плитки: просмотр грузится ФОНОВО (интерфейс не блокируется)
        viewer.list.setCurrentRow(rows["картинка.avif"])
        check("просмотр ушёл в фон (задача запущена)",
              viewer._view_busy or viewer._pixmap is not None)
        deadline = time.time() + 15
        while time.time() < deadline:
            app.processEvents()
            if viewer._pixmap is not None and not viewer._view_busy:
                break
            time.sleep(0.03)
        check("фоновый просмотр показал картинку", viewer._pixmap is not None)
        check("курсор занятости снят", not viewer._view_busy)
        check("статус показывает размер", "96×72" in viewer.status.text(),
              viewer.status.text())

        # 9. выбор обычного PNG тоже работает
        viewer.list.setCurrentRow(rows["обычная.png"])
        deadline = time.time() + 15
        while time.time() < deadline:
            app.processEvents()
            if not viewer._view_busy and "24×24" in viewer.status.text():
                break
            time.sleep(0.03)
        check("PNG показывается в фоне", "24×24" in viewer.status.text(),
              viewer.status.text())

        # 10. битый файл: в ленте есть, просмотр пишет внятную причину
        bad = os.path.join(tmp, "битый.jpg")
        with open(bad, "wb") as f:
            f.write(b"not an image at all, just text")
        viewer.load_folder(tmp)
        app.processEvents()
        rows = {os.path.basename(viewer._paths[r]): r for r in range(len(viewer._paths))}
        viewer.list.setCurrentRow(rows["битый.jpg"])
        deadline = time.time() + 15
        while time.time() < deadline:
            app.processEvents()
            if not viewer._view_busy:
                break
            time.sleep(0.03)
        check("битый файл: курсор занятости снят", not viewer._view_busy)
        check("битый файл: причина без AttributeError",
              "errorString" not in viewer.view_label.text()
              and viewer.view_label.text() != "", viewer.view_label.text()[:80])

        # 11. i18n: новые ключи есть во всех трёх языках
        for key in ("viewer.loading", "log.event.avif_no_codec",
                    "log.event.search_tabs_restored", "log.event.search_tabs_limit",
                    "ws.tab_new", "ws.tab_new_tip", "ws.tab_duplicate",
                    "ws.tab_close", "ws.tab_close_others", "ws.tab_close_right"):
            langs = i18n._STRINGS.get(key, {})
            check(f"i18n {key}: ru/en/zh",
                  all(langs.get(l) for l in ("ru", "en", "zh")), str(sorted(langs)))
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
