"""Генерация файлов иконки приложения: app/resources/app_icon.png + .ico.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/make_icon.py

Рисует значок кодом из app/ui/app_icon.py (paint_pixmap), сохраняет:
* app_icon.png — 512×512 (для Linux/Qt);
* app_icon.ico  — многоразмерный 16…256 px (для Windows/ярлыков);
* /tmp/icon_preview.png — превью всех размеров для визуальной проверки.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.app_icon import RES_DIR, paint_pixmap  # noqa: E402

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    app = QApplication(sys.argv)
    RES_DIR.mkdir(parents=True, exist_ok=True)

    big = paint_pixmap(512)
    png_path = RES_DIR / "app_icon.png"
    big.save(str(png_path), "PNG")
    print("PNG:", png_path, png_path.stat().st_size, "bytes")

    # файл → Pillow → многоразмерный ICO (честные пиксели каждого размера)
    img = Image.open(png_path)
    ico_path = RES_DIR / "app_icon.ico"
    img.save(str(ico_path), format="ICO",
             sizes=[(s, s) for s in ICO_SIZES])
    print("ICO:", ico_path, ico_path.stat().st_size, "bytes")

    # превью: значки всех размеров на шахматном фоне — глазами проверить читаемость
    sheet = Image.new("RGB", (sum(ICO_SIZES) + 40 * len(ICO_SIZES), 300), "#dddddd")
    x = 20
    for s in ICO_SIZES:
        icon_img = img.resize((s, s), Image.LANCZOS)
        sheet.paste(icon_img, (x, 150 - s // 2))
        x += s + 40
    sheet.save("/tmp/icon_preview.png")
    print("preview: /tmp/icon_preview.png")
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
