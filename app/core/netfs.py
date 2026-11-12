"""Сетевые и медленные файловые системы на POSIX (Linux).

Зачем: на Windows сетевые пути распознаёт GetDriveTypeW (v0.7.2), и все
чтения WebDAV/SMB идут через узкий пул из двух потоков. На Linux
детектор возвращал False всегда — davfs2 и другие FUSE-маунты считались
локальными, и чтение миниатюр, просмотр, скан папок и удаление шли через
общие пулы на полной параллельности. davfs2 такой шторм не выдерживает:
слоты запросов кончаются, сервер отвечает «занят», чтения подвисают на
~30 с и падают с Errno 11 (EAGAIN, «Ресурс временно недоступен») —
репорт v0.8.19: маунт cloud.mail.ru через davfs2, все операции
«МЕДЛЕННО (фоном)» по 700–30 000 мс.

Как: /proc/mounts — точный и мгновенный источник fstype; для пути ищем
самый длинный смонтированный префикс, результат кэшируется по пути
(одна операция на файл за сессию, повторные — словарь). Чтение
/proc/mounts стоит десятки микросекунд, так что даже первая проверка
тысячи файлов — незаметная.

Что считается сетевым:
* fstype из явного списка — davfs2, cifs/smbfs, nfs*, sshfs, 9p, afs,
  gfs/ocfs2, ceph, glusterfs, lustre и т. п.;
* fuse.<имя>, в имени которого виден сетевой бэкенд (fuse.davfs2,
  fuse.sshfs, fuse.gvfsd-fuse, fuse.rclone…);
* fuseblk и локальные FUSE-шифрования (gocryptfs, encfs, cryfs, ntfs-3g)
  сетевыми НЕ считаются — это обычные локальные диски.
"""

from __future__ import annotations

import errno
import os
import threading
import time

# fstype, которые всегда сетевые (точное совпадение после lower())
REMOTE_FSTYPES = {
    "davfs", "davfs2", "webdav", "wdfs",
    "cifs", "smb", "smbfs", "smb2", "smb3", "ncpfs",
    "nfs", "nfs4", "nfsd", "sshfs",
    "9p", "afs", "coda", "arla",
    "gfs", "gfs2", "ocfs2", "acfs", "ceph", "glusterfs", "lustre",
}

# признаки сетевого бэкенда внутри "fuse.<имя>"
_REMOTE_FUSE_TAGS = (
    "dav", "ssh", "sftp", "gvfsd", "rclone", "webdav", "ftp", "s3",
    "swift", "gcs", "smb", "cld", "cloud", "onedrive", "gdrive",
    "dropbox", "yandex", "mailru", "afp", "coda",
)

# локальные FUSE-имена — обычные локальные диски, не сеть
_LOCAL_FUSE = {"blk", "gocryptfs", "encfs", "cryfs"}

_CACHE: dict[str, bool] = {}              # realpath(path) → сетевой ли
_CACHE_LOCK = threading.Lock()

# паузы между повторами при EAGAIN: davfs2 уже сам ждал слот, обычно
# хватает одной короткой паузы (0.4 с); три попытки на случай очереди
EAGAIN_TRIES = 3
EAGAIN_PAUSE_S = 0.4


def _proc_mounts_text() -> str:
    """Текст /proc/mounts (подменяется в тестах)."""
    with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _unescape_mount(mp: str) -> str:
    """«\\040» в /proc/mounts — пробел в имени точки монтирования."""
    return mp.replace("\\040", " ").replace("\\011", "\t")


def _under(pn: str, mp: str) -> bool:
    """pn лежит внутри точки монтирования mp (или совпадает с ней)."""
    if mp == "/":
        return True
    return pn == mp or pn.startswith(mp + os.sep)


def _mount_point_from_lines(lines: list[str], pn: str) -> tuple[str, str]:
    """Самый длинный смонтированный префикс пути: (точка, fstype).

    Чистая функция — в тестах подставляются готовые строки /proc/mounts.
    Если ничего не сматчилось — ("/", ""), то есть корень.
    """
    best_mp, best_type = "/", ""
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mp = os.path.normpath(_unescape_mount(parts[1]))
        if not _under(pn, mp):
            continue
        if len(mp) >= len(best_mp):
            best_mp, best_type = mp, parts[2]
    return best_mp, best_type


def fstype_is_remote(fstype: str) -> bool:
    """Сетевой ли fstype (см. докстринг модуля)."""
    fs = (fstype or "").strip().lower()
    if not fs:
        return False
    if fs in REMOTE_FSTYPES:
        return True
    if fs.startswith("fuse.") or fs.startswith("fuseblk."):
        body = fs[fs.find(".") + 1:]
        if body in _LOCAL_FUSE or body.endswith("-3g") or body.endswith("blk"):
            return False
        return any(tag in body for tag in _REMOTE_FUSE_TAGS)
    return False


def is_remote(path: str) -> bool:
    """Сетевой (WebDAV/davfs2, SMB, NFS, FUSE-сеть) ли путь на POSIX.

    Кэшируется по пути: первая проверка читает /proc/mounts, остальные —
    словарь. Перезмонтировали с тем же fstype — кэш не мешает; сменили
    fstype без перезапуска — редкий случай, виноват кэш на сессию (тот же
    компромисс, что у _REMOTE_DRIVE_CACHE на Windows, v0.7.2)."""
    if not path:
        return False
    try:
        key = os.path.realpath(os.path.abspath(path))
    except Exception:                       # noqa: BLE001 — путь странный
        return False
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        lines = _proc_mounts_text().splitlines()
        _mp, fstype = _mount_point_from_lines(lines, key)
        remote = fstype_is_remote(fstype)
    except Exception:                       # noqa: BLE001 — не читается — локальный
        remote = False
    with _CACHE_LOCK:
        _CACHE[key] = remote
    return remote


def clear_cache() -> None:
    """Сбросить кэш (для тестов)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def is_eagain(exc: BaseException) -> bool:
    """EAGAIN/EWOULDBLOCK — davfs2 отдаёт его, когда слоты запросов
    кончились («Ресурс временно недоступен», Errno 11). Повтор через
    паузу обычно проходит: слот к тому времени свободен."""
    if isinstance(exc, BlockingIOError):
        return True
    return getattr(exc, "errno", None) in (errno.EAGAIN, errno.EWOULDBLOCK)


def write_bytes(path: str, data, tries: int = EAGAIN_TRIES) -> None:
    """Записать байты в файл, повторяя при EAGAIN (davfs2).

    Поднимает настоящий OSError с errno и путём — в отличие от
    QImage.save, который глотает системную ошибку и возвращает False
    (v0.8.19: в журнале оставался голый ValueError).
    """
    last: OSError | None = None
    for attempt in range(max(1, tries)):
        try:
            with open(path, "wb") as f:
                f.write(data)
            return
        except OSError as exc:
            last = exc
            if not is_eagain(exc) or attempt == tries - 1:
                raise
            time.sleep(EAGAIN_PAUSE_S)
    raise last if last else OSError(f"не удалось записать {path}")
