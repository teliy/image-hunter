"""Декодирование изображений с поддержкой AVIF.

PySide6 не включает AVIF-плагин Qt (в imageformats только gif, jpeg, svg,
tiff, webp и т.д.), поэтому Qt файлы AVIF не открывает вовсе. А именно в
AVIF часто приходят картинки с маркетплейсов — AliExpress, например,
отдаёт AVIF даже по ссылкам «.jpg» — и в AVIF хранят фото современные
телефоны.

Здесь один общий загрузчик для миниатюр, полноэкранного просмотра и
сохранения. Файл сначала читается целиком ОБЫЧНЫМ питоновским I/O, и уже
из памяти декодируется (QImageReader по QBuffer, при AVIF — Pillow):

* CPython отпускает GIL на read(), поэтому подвисший по сети файл
  (WebDAV-диск Z:, отвалившийся SMB-шара) держит только рабочий поток,
  который его читает, — GUI и остальные потоки живут. Qt-чтение
  (QImageReader по пути) так не умеет: на Windows чтение сетевого файла
  застревает в редиректоре на весь сетевой тайм-аут (~60 с) и процесс
  замирает целиком (v0.7.2);
* файл проходится один раз, а не два-три (size() + read() + проверка
  AVIF по голове) — на сетевом диске это втрое меньше round-trip'ов.

Все функции потокобезопасны: QImage можно создавать в рабочих потоках,
Pillow декодирует независимые картинки параллельно.
"""

from __future__ import annotations

import io
import os

from PySide6.QtCore import QBuffer, QByteArray, Qt
from PySide6.QtGui import QImage, QImageReader

# страховка от чудовищных файлов на сетевых дисках: не тащим в память >1 ГБ
_MAX_FILE_BYTES = 1 << 30

# --- Pillow + AVIF-кодек: ставится вместе с программой, но отсутствие
# --- не должно ронять приложение — AVIF тогда просто не откроется.
try:
    import pillow_avif  # noqa: F401  регистрирует AVIF-кодек в Pillow
    from PIL import Image as _PilImage
    AVIF_OK = True
except Exception:                                       # pragma: no cover
    AVIF_OK = False

_AVIF_BRANDS = (b"avif", b"avis", b"av01")

_warned_no_codec = False


def looks_like_avif(data: bytes) -> bool:
    """Похожи ли байты на AVIF (контейнер ISO-BMFF с брендом avif/avis/av01)."""
    return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _AVIF_BRANDS


def _warn_no_codec_once() -> None:
    """Одно предупреждение в журнал, если AVIF есть, а кодека нет."""
    global _warned_no_codec
    if _warned_no_codec:
        return
    _warned_no_codec = True
    from app.core import applog
    applog.event("log.event.avif_no_codec")


def _pil_to_qimage(im: "_PilImage.Image", max_side: int = 0) -> QImage:
    """PIL.Image → QImage (своё owning-копирование памяти)."""
    if max_side > 0 and max(im.width, im.height) > max_side:
        im.thumbnail((max_side, max_side), _PilImage.LANCZOS)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    raw = im.tobytes("raw", "RGBA")
    img = QImage(raw, im.width, im.height, im.width * 4,
                 QImage.Format.Format_RGBA8888)
    return img.copy()   # отцепить от питоновского буфера bytes


def decode_bytes(data: bytes) -> tuple[QImage, str]:
    """Декодировать байты картинки (любой формат Qt + AVIF).

    Возвращает ``(QImage, "")`` при успехе или ``(QImage(), причина)``
    при неудаче — причина уже готова для журнала.
    """
    return load_bytes(data, 0)


def read_file_bytes(path: str) -> tuple[bytes | None, str]:
    """Прочитать файл целиком обычным питоновским I/O.

    Возвращает ``(байты, "")`` или ``(None, причина)``. Чтение идёт
    системными вызовами CPython, которые отпускают GIL: зависший по сети
    файл блокирует только вызвавший поток — интерфейс и остальные потоки
    продолжают работать. Именно это спасает от 60-секундных зависаний на
    WebDAV/SMB-дисках (v0.7.2, см. докстринг модуля).
    """
    try:
        with open(path, "rb") as f:
            data = f.read(_MAX_FILE_BYTES + 1)
    except OSError as exc:
        return None, str(exc) or "не удалось прочитать файл"
    if not data:
        return None, "файл пуст"
    if len(data) > _MAX_FILE_BYTES:
        return None, "файл больше 1 ГБ — не тяну в память"
    return data, ""


def load_bytes(data: bytes, max_side: int = 0) -> tuple[QImage, str]:
    """Декодировать картинку из памяти (любой формат Qt + AVIF).

    ``max_side`` — уменьшить до указанной стороны (для миниатюр: Qt
    декодирует со сжатием на лету, Pillow — через thumbnail), 0 — как есть.
    """
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QBuffer.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf)
    reader.setAutoTransform(True)
    if max_side > 0:
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            reader.setScaledSize(size.scaled(max_side, max_side, Qt.KeepAspectRatio))
    img = reader.read()
    if not img.isNull():
        return img, ""
    qt_err = reader.errorString() or "неизвестная ошибка"
    if looks_like_avif(data):
        if not AVIF_OK:
            _warn_no_codec_once()
            return QImage(), qt_err
        try:
            return _pil_to_qimage(_PilImage.open(io.BytesIO(data)), max_side), ""
        except Exception as exc:                        # noqa: BLE001
            return QImage(), f"AVIF: {exc}"
    return QImage(), qt_err


def load_file(path: str, max_side: int = 0) -> tuple[QImage, str]:
    """Декодировать файл картинки (любой формат Qt + AVIF).

    Файл читается обычным питоновским I/O (см. read_file_bytes) и
    декодируется из памяти — сетевые подвисания не задевают GUI.

    ``max_side`` — уменьшить до указанной стороны (для миниатюр), 0 — как есть.

    Возвращает ``(QImage, "")`` при успехе или ``(QImage(), причина)``.
    """
    data, err = read_file_bytes(path)
    if data is None:
        return QImage(), err
    return load_bytes(data, max_side)
