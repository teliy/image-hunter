"""Декодирование изображений с поддержкой AVIF.

PySide6 не включает AVIF-плагин Qt (в imageformats только gif, jpeg, svg,
tiff, webp и т.д.), поэтому Qt файлы AVIF не открывает вовсе. А именно в
AVIF часто приходят картинки с маркетплейсов — AliExpress, например,
отдаёт AVIF даже по ссылкам «.jpg» — и в AVIF хранят фото современные
телефоны.

Здесь один общий загрузчик для миниатюр, полноэкранного просмотра и
сохранения: сначала стандартный QImageReader (быстро, умеет EXIF-поворот),
а если он не справился и данные похожи на AVIF — декодирование через
Pillow + pillow-avif-plugin (ставится вместе с программой, см.
requirements.txt). Определение AVIF — по содержимому (боксы ISO-BMFF
«ftyp avif/avis/av01»), поэтому подхватываются и файлы с чужим
расширением вроде «фото.jpg», внутри которого AVIF.

Все функции потокобезопасны: QImage можно создавать в рабочих потоках,
Pillow декодирует независимые картинки параллельно.
"""

from __future__ import annotations

import io
import os

from PySide6.QtCore import QBuffer, QByteArray, Qt
from PySide6.QtGui import QImage, QImageReader

# --- Pillow + AVIF-кодек: ставится вместе с программой, но отсутствие
# --- не должно ронять приложение — AVIF тогда просто не откроется.
try:
    import pillow_avif  # noqa: F401  регистрирует AVIF-кодек в Pillow
    from PIL import Image as _PilImage
    AVIF_OK = True
except Exception:                                       # pragma: no cover
    AVIF_OK = False

_AVIF_BRANDS = (b"avif", b"avis", b"av01")
_AVIF_EXTS = (".avif", ".avifs")

_warned_no_codec = False


def looks_like_avif(data: bytes) -> bool:
    """Похожи ли байты на AVIF (контейнер ISO-BMFF с брендом avif/avis/av01)."""
    return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _AVIF_BRANDS


def _file_head_is_avif(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return looks_like_avif(f.read(16))
    except OSError:
        return False


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
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QBuffer.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf)
    reader.setAutoTransform(True)
    img = reader.read()
    if not img.isNull():
        return img, ""
    qt_err = reader.errorString() or "неизвестная ошибка"
    if looks_like_avif(data):
        if not AVIF_OK:
            _warn_no_codec_once()
            return QImage(), qt_err
        try:
            return _pil_to_qimage(_PilImage.open(io.BytesIO(data))), ""
        except Exception as exc:                        # noqa: BLE001
            return QImage(), f"AVIF: {exc}"
    return QImage(), qt_err


def load_file(path: str, max_side: int = 0) -> tuple[QImage, str]:
    """Декодировать файл картинки (любой формат Qt + AVIF).

    ``max_side`` — уменьшить до указанной стороны (для миниатюр: Qt
    декодирует со сжатием на лету, Pillow — через thumbnail), 0 — как есть.

    Возвращает ``(QImage, "")`` при успехе или ``(QImage(), причина)``.
    """
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    if max_side > 0:
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            reader.setScaledSize(size.scaled(max_side, max_side, Qt.KeepAspectRatio))
    img = reader.read()
    if not img.isNull():
        return img, ""
    qt_err = reader.errorString() or "неизвестная ошибка"

    ext = os.path.splitext(path)[1].lower()
    suspicious = ext in _AVIF_EXTS
    if not suspicious and AVIF_OK:
        suspicious = _file_head_is_avif(path)   # AVIF под чужим расширением
    if not suspicious:
        return QImage(), qt_err
    if not AVIF_OK:
        _warn_no_codec_once()
        return QImage(), qt_err
    try:
        with open(path, "rb") as f:
            return _pil_to_qimage(_PilImage.open(f), max_side), ""
    except (OSError, ValueError) as exc:
        return QImage(), f"AVIF: {exc}"
    except Exception as exc:                            # noqa: BLE001
        return QImage(), f"AVIF: {exc}"
