"""Сетевые и медленные файловые системы на POSIX (Linux).

Зачем: на Windows сетевые пути распознаёт GetDriveTypeW (v0.7.2), и все
чтения WebDAV/SMB идут через узкий пул из двух потоков. На Linux
детектор возвращал False всегда — davfs2 и другие FUSE-маунты считались
локальными, и чтение миниатюр, просмотр, скан папок и удаление шли через
общие пулы на полной параллельности. davfs2 такой шторм не выдерживает:
слоты запросов кончаются, сервер отвечает «занят», чтения подвисают на
~30 с и падают с Errno 11 (EAGAIN, «Ресурс временно недоступен») —
репорт v0.8.19: маунт cloud.mail.ru через davfs2, все операции
«МЕДЛЕННО (фоном)» по 700–30 000 мс. Другая сторона того же репорта —
зависание «при обращении к сети»: на подвисшем WebDAV битые/обрезанные
данные — норма, а их конкурентный Qt-декод клинил процесс (вторая часть
v0.8.19, замок в imgload).

Как: /proc/self/mounts — точный и мгновенный источник fstype; его
генерирует само ядро, чтение не подвисает даже когда сами монтирования
мёртвые (в отличие от stat() по их файлам, поэтому realpath тут НЕ
используется — только строковая абсолютизация). Для пути ищем самый
длинный (самый конкретный) смонтированный префикс; таблица перечитывается
не чаще раза в 2 с (перемонтировали — через 2 с видно), вердикт по
конкретному пути кэшируется на сессию.

Что считается сетевым:
* fstype из явного списка — davfs2, cifs/smbfs, nfs*, sshfs, 9p, drvfs
  (WSL), общие папки виртуалок (vboxsf, vmhgfs, prl_fs), gfs/ocfs2,
  ceph, glusterfs, beegfs, lustre, curlftpfs, mtpfs и т. п.;
* fuse.<имя>, в имени которого виден сетевой бэкенд (fuse.davfs2,
  fuse.sshfs, fuse.gvfsd-fuse, fuse.rclone, fuse.yandex.disk,
  fuse.s3fs…); для незнакомых fuse.* — эвристика по фрагментам имени
  демона;
* пути GVFS — Nautilus (GNOME) монтирует WebDAV/SFTP/SMB под
  /run/user/<uid>/gvfs/, иногда под типом, которого нет в списках;
  чужой uid — не наш маунт, не считается.

Сугубо локальные слои сетью НЕ считаются, даже если в имени спрятан
«сетевой» фрагмент: fuseblk/ntfs-3g — обычный диск через FUSE, gocryptfs,
encfs, cryfs — шифрование, а unionfs прячет в имени «nfs», mergerfs,
overlayfs, appimage, squashfuse — сборки/сидиобразы.
"""

from __future__ import annotations

import errno
import os
import re
import threading
import time

# fstype, которые всегда сетевые (точное совпадение после lower())
REMOTE_FSTYPES = {
    "davfs", "davfs2", "webdav", "wdfs",
    "cifs", "smb", "smbfs", "smb2", "smb3", "ncpfs",
    "nfs", "nfs4", "nfsd", "sshfs",
    "9p", "drvfs",                    # WSL2 /mnt/… и WSL1 — чтения медленные
    "afs", "openafs", "coda", "arla",
    "gfs", "gfs2", "ocfs2", "acfs",
    "ceph", "cephfs", "glusterfs", "glusterfs-fuse", "beegfs", "lustre",
    "vboxsf", "vmhgfs", "prl_fs",     # общие папки виртуальных машин
    "curlftpfs", "obexfs", "obexftpfs", "mtpfs",
}

# признаки сетевого бэкенда внутри "fuse.<имя>"
_REMOTE_FUSE_TAGS = (
    "dav", "ssh", "sftp", "smb", "cifs", "nfs", "ftp", "webdav", "rclone",
    "gvfs", "kio", "cloud", "nextcloud", "owncloud", "gdrive", "onedrive",
    "dropbox", "s3", "swift", "gcs", "mega", "yandex", "mailru", "afp",
    "obex", "mtp", "ceph", "cld", "coda",
)

# локальные FUSE-имена — обычные локальные диски, не сеть. Проверяются ДО
# эвристики по тегам: в имени unionfs прячется «nfs», и без явного
# исключения локальный слой считался бы сетью
_LOCAL_FUSE = {
    "blk", "gocryptfs", "encfs", "cryfs",
    "unionfs", "mergerfs", "overlayfs", "appimage", "borgfs", "cramfs",
    "squashfuse", "archivemount", "ext4", "zfs", "ecryptfs",
}

# пути GVFS (GNOME: Nautilus монтирует WebDAV/SFTP/SMB сюда)
_GVFS_PREFIX = "/run/user/{uid}/gvfs"

# /proc/self/mounts перечитывается не чаще раза в 2 с: перемонтировали —
# через 2 с видно, а таблица у ядра читается мгновенно в любом случае
MOUNTS_TTL_S = 2.0

_CACHE: dict[str, bool] = {}              # abspath(path) → сетевой ли
_CACHE_LOCK = threading.Lock()

# паузы между повторами при EAGAIN: davfs2 уже сам ждал слот, обычно
# хватает одной короткой паузы (0.4 с); три попытки на случай очереди
EAGAIN_TRIES = 3
EAGAIN_PAUSE_S = 0.4

_OCT_ESCAPE_RE = re.compile(r"\\([0-7]{3})")


def _proc_mounts_text() -> str:
    """Текст /proc/self/mounts (подменяется в тестах)."""
    with open("/proc/self/mounts", "r", encoding="utf-8", errors="replace") as f:
        return f.read()


_mounts_cache: list[tuple[str, str]] = []
_mounts_at: float = -1e18


def mounts_table() -> list[tuple[str, str]]:
    """[(точка монтирования, fstype)] с коротким кэшем; длинные точки первыми.

    Порядок важен: поиск префикса идёт сверху вниз, первый матч — самый
    конкретный маунт (например /run/user/1000/gvfs перекрывает /run/user/1000).
    """
    global _mounts_cache, _mounts_at
    now = time.monotonic()
    if _mounts_cache and now - _mounts_at < MOUNTS_TTL_S:
        return _mounts_cache
    try:
        parsed = parse_mounts(_proc_mounts_text())
    except Exception:                       # noqa: BLE001 — /proc всегда есть, но вдруг
        parsed = []
    _mounts_cache, _mounts_at = parsed, now
    return parsed


def parse_mounts(text: str) -> list[tuple[str, str]]:
    """[(точка монтирования, fstype)] из содержимого /proc/self/mounts.

    Пробелы и прочие спецсимволы в точке монтирования ядро экранирует
    восьмеричными последовательностями («\\040» — пробел, «\\011» — таб) —
    раскрываем обратно. Чистая функция — в тестах подставляются готовые
    строки; если ничего не сматчилось — таблица пуста.
    """
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[1].startswith("/"):
            continue
        mnt = _OCT_ESCAPE_RE.sub(
            lambda m: chr(int(m.group(1), 8)), parts[1])
        out.append((mnt, parts[2].strip().lower()))
    out.sort(key=lambda t: len(t[0]), reverse=True)
    return out


def _unescape_mount(mp: str) -> str:
    """Экранирование ядра («\\040» и соседние восьмеричные) → обычные символы."""
    return _OCT_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 8)), mp)


def _under(pn: str, mp: str) -> bool:
    """pn лежит внутри точки монтирования mp (или совпадает с ней)."""
    if mp == "/":
        return True
    return pn == mp or pn.startswith(mp + os.sep)


def _mount_point_from_lines(lines: list[str], pn: str) -> tuple[str, str]:
    """Самый длинный смонтированный префикс пути: (точка, fstype).

    Классический разбор строк /proc/mounts — им пользуются тесты и
    is_remote; если ничего не сматчилось — ("/", ""), то есть корень.
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
    if fs in _LOCAL_FUSE:
        return False
    if fs in REMOTE_FSTYPES:
        return True
    if fs.startswith("fuse.") or fs.startswith("fuseblk."):
        body = fs[fs.find(".") + 1:]
        if body in _LOCAL_FUSE or body.endswith("-3g") or body.endswith("blk"):
            return False
        return any(tag in body for tag in _REMOTE_FUSE_TAGS)
    return False


def linux_is_remote(path: str, mounts: "list[tuple[str, str]] | None" = None) -> bool:
    """Сетевой ли путь на POSIX: fstype самого конкретного маунта + GVFS.

    ``mounts`` — готовая таблица parse_mounts (для тестов); без неё
    читается /proc/self/mounts с коротким кэшем. Пути GVFS под СВОИМ
    uid — всегда сеть (Nautilus монтирует WebDAV/SFTP/SMB туда, иногда
    под типом, которого нет в списках); чужой uid — не наш маунт.
    os.path.abspath — только строковая операция: realpath здесь опасен,
    lstat по мёртвому маунту может подвиснуть на десятки секунд.
    """
    if mounts is None:
        mounts = mounts_table()
    try:
        p = os.path.abspath(path)
    except Exception:                       # noqa: BLE001 — путь странный — локальный
        return False
    gvfs = _GVFS_PREFIX.format(uid=os.getuid())
    if p == gvfs or p.startswith(gvfs + "/"):
        return True
    for mnt, fst in mounts:                 # самый длинный префикс первым
        if p == mnt or p.startswith(mnt + "/"):
            return fstype_is_remote(fst)
    return False


def is_remote(path: str) -> bool:
    """Сетевой (WebDAV/davfs2, SMB, NFS, FUSE-сеть) ли путь на POSIX.

    Вердикт по пути кэшируется на сессию: первая проверка читает
    /proc/self/mounts, остальные — словарь. Перезмонтировали с тем же
    fstype — кэш не мешает; сменили fstype без перезапуска — редкий
    случай, виноват кэш на сессию (тот же компромисс, что у
    _REMOTE_DRIVE_CACHE на Windows, v0.7.2)."""
    if not path:
        return False
    try:
        key = os.path.abspath(path)   # без realpath: lstat мёртвого маунта подвисает
    except Exception:                       # noqa: BLE001 — путь странный
        return False
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        remote = linux_is_remote(key)
    except Exception:                       # noqa: BLE001 — не читается — локальный
        remote = False
    with _CACHE_LOCK:
        _CACHE[key] = remote
    return remote


def clear_cache() -> None:
    """Сбросить кэши (для тестов)."""
    global _mounts_cache, _mounts_at
    with _CACHE_LOCK:
        _CACHE.clear()
    _mounts_cache, _mounts_at = [], -1e18


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
