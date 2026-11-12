"""Оффлайн-тесты сетевых ФС на Linux, EAGAIN и прав при удалении (v0.8.19).

Фон: маунт cloud.mail.ru через davfs2 на Linux. Раньше _is_remote_path
считал Linux-пути локальными — узкий сетевой пул (v0.7.2) не включался,
davfs2 получал все параллельные запросы разом: слоты кончались, чтения
провисали ~30 с и падали с «[Errno 11] Ресурс временно недоступен»,
QImage.save на отказе писал голый ValueError без причины, а удаление
сначала ломало права (chmod S_IWRITE = 0o200 — «только запись»).

Проверяется:
* netfs: разбор /proc/mounts (длиннейший префикс, \\040), список сетевых
  fstype (davfs2/cifs/nfs/sshfs + fuse.davfs2/fuse.sshfs/fuse.gvfsd-fuse),
  НЕ-сетевые fuseblk/gocryptfs/ext4, is_eagain;
* imgload.read_file_bytes: EAGAIN ретраится (2 отказа → успех), стойкий
  EAGAIN — честная ошибка, EACCES — без ретраев;
* imgload.write_file_bytes: запись с ретраем по EAGAIN, честный текст ошибки;
* image_saver.save_image: WebP реально пишется и читается обратно;
* local_viewer: _is_remote_path/_drive_has_trash на Linux, _io_pool
  раскладывает сетевые пути в узкий пул, удаление идёт через него;
* _remove_forever на POSIX не ломает права файла и поясняет EACCES;
* i18n: новый ключ viewer.del_denied_hint полон (ru/en/zh).

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_netfs.py
"""

import errno
import os
import stat
import sys
import tempfile
import unittest.mock
from unittest.mock import patch as mock_patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.core import applog, i18n, imgload, netfs
from app.core.i18n import tr
from app.ui import local_viewer as lv

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(cond, timeout_s: float = 8.0) -> bool:
    import time
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
        app.processEvents()
    return bool(cond())


QSettings("ImageHunter", "ImageHunter").clear()
i18n.set_lang("ru", persist=False)
applog.setup()

tmp = tempfile.mkdtemp(prefix="ih_netfs_")

# ---------- 1. netfs: разбор /proc/mounts ----------

MOUNTS = [
    "/dev/sda1 / ext4 rw,relatime 0 0",
    "/dev/sda2 /home ext4 rw 0 0",
    "https://webdav.cloud.mail.ru:443 /home/dima/mailru fuse.davfs2 rw 0 0",
    "//nas/share /mnt/smb cifs rw 0 0",
    "server:/vol /mnt/nas nfs4 rw 0 0",
    "/dev/sdb1 /media/usb fuseblk rw 0 0",
    "tmpfs /run/user/1000 tmpfs rw 0 0",
    "gvfsd-fuse /run/user/1000/gvfs fuse.gvfsd-fuse rw 0 0",
    "sshfs /mnt/remote fuse.sshfs rw 0 0",
    "wdfs-mount /mnt/with\\040space fuse.davfs2 rw 0 0",
]

check("корень → ext4", netfs._mount_point_from_lines(MOUNTS, "/") == ("/", "ext4"))
check("длиннейший префикс: /home/dima → /home/ext4",
      netfs._mount_point_from_lines(MOUNTS, "/home/dima/docs") == ("/home", "ext4"))
check("davfs2-маунт матчится",
      netfs._mount_point_from_lines(MOUNTS, "/home/dima/mailru/Автозапчасти/Taiho/x.webp")
      == ("/home/dima/mailru", "fuse.davfs2"))
check("\\040 разворачивается в пробел",
      netfs._mount_point_from_lines(MOUNTS, "/mnt/with space/f.webp")[0] == "/mnt/with space")
check("неизвестный путь → корень",
      netfs._mount_point_from_lines(MOUNTS, "/opt/x") == ("/", "ext4"))

# ---------- 2. netfs: какие fstype сетевые ----------

for fs in ("davfs2", "cifs", "smbfs", "nfs", "nfs4", "sshfs", "9p", "afs",
           "fuse.davfs2", "fuse.sshfs", "fuse.gvfsd-fuse", "fuse.rclone",
           "fuse.webdavd"):
    check(f"fstype сетевой: {fs}", netfs.fstype_is_remote(fs))
for fs in ("ext4", "xfs", "btrfs", "tmpfs", "overlay", "vfat", "exfat",
           "ntfs", "fuseblk", "fuse.gocryptfs", "fuse.encfs", "ntfs-3g",
           "", "fuse", "proc"):
    check(f"fstype НЕ сетевой: {fs!r}", not netfs.fstype_is_remote(fs))

# ---------- 3. netfs: is_remote по подменённому /proc/mounts ----------

netfs.clear_cache()
with mock_patch.object(netfs, "_proc_mounts_text", lambda: "\n".join(MOUNTS)):
    check("is_remote(davfs2-путь)",
          netfs.is_remote("/home/dima/mailru/Автозапчасти/Taiho/x.webp"))
    check("is_remote(cifs)",
          netfs.is_remote("/mnt/smb/folder/pic.png"))
    check("is_remote(nfs4)", netfs.is_remote("/mnt/nas/a/b.png"))
    check("is_remote(ext4) — False", not netfs.is_remote("/home/dima/Docs/a.png"))
    check("is_remote(usb fuseblk) — False", not netfs.is_remote("/media/usb/a.png"))
    check("is_remote(gvfs)", netfs.is_remote("/run/user/1000/gvfs/smb-share:x/y.png"))
netfs.clear_cache()

# ---------- 4. netfs: is_eagain ----------

check("is_eagain(OSError EAGAIN)", netfs.is_eagain(OSError(errno.EAGAIN, "Ресурс временно недоступен")))
check("is_eagain(EWOULDBLOCK)", netfs.is_eagain(OSError(errno.EWOULDBLOCK, "again")))
check("is_eagain(BlockingIOError)", netfs.is_eagain(BlockingIOError(errno.EAGAIN, "b")))
check("is_eagain(EACCES) — нет", not netfs.is_eagain(OSError(errno.EACCES, "denied")))
check("is_eagain(EIO) — нет", not netfs.is_eagain(OSError(errno.EIO, "io")))
check("is_eagain(ValueError) — нет", not netfs.is_eagain(ValueError("x")))

# ---------- 5. imgload.read_file_bytes: ретраи EAGAIN ----------

src = QImage(60, 40, QImage.Format.Format_RGB32)
src.fill(0xFF3050A0)
png_path = os.path.join(tmp, "pic.png")
src.save(png_path, "PNG")
real_open = open


def flaky_open(times, exc, modes=("rb", "wb")):
    """open, первые ``times`` раз бросающий exc (на выбранных режимах)."""
    def _open(p, mode="r", **kw):
        if mode in modes and _open.calls[0] < times:
            _open.calls[0] += 1
            raise exc
        return real_open(p, mode, **kw)
    _open.calls = [0]
    return _open


with mock_patch("builtins.open", flaky_open(2, BlockingIOError(errno.EAGAIN, "Ресурс временно недоступен"))):
    data, err = imgload.read_file_bytes(png_path)
check("EAGAIN×2 → ретрай успешен", data is not None and err == "",
      err or f"{len(data or b'')} байт")

with mock_patch("builtins.open", flaky_open(10, BlockingIOError(errno.EAGAIN, "Ресурс временно недоступен"))):
    data, err = imgload.read_file_bytes(png_path)
check("стойкий EAGAIN → честная ошибка", data is None and "Ресурс" in err, err)

with mock_patch("builtins.open", flaky_open(10, PermissionError(errno.EACCES, "Отказано в доступе"))):
    data, err = imgload.read_file_bytes(png_path)
check("EACCES — без ретраев", data is None and "Отказано" in err, err)

img, err = imgload.load_file(png_path)
check("load_file жив после рефакторинга чтения", not img.isNull() and not err, err)

# ---------- 6. imgload.write_file_bytes ----------

out1 = os.path.join(tmp, "out1.bin")
ok, err = imgload.write_file_bytes(out1, b"payload-123")
check("write_file_bytes: пишет", ok and not err and open(out1, "rb").read() == b"payload-123", err)

out2 = os.path.join(tmp, "out2.bin")
ok, err = imgload.write_file_bytes(out2, b"x")
check("write_file_bytes: перезаписывает пустым→не путём", ok and not err, err)

with mock_patch("builtins.open", flaky_open(2, BlockingIOError(errno.EAGAIN, "Ресурс временно недоступен"))):
    ok, err = imgload.write_file_bytes(out2, b"after-eagain")
check("write_file_bytes: EAGAIN×2 → ретрай", ok and open(out2, "rb").read() == b"after-eagain", err)

with mock_patch("builtins.open", flaky_open(10, BlockingIOError(errno.EAGAIN, "Ресурс временно недоступен"))):
    ok, err = imgload.write_file_bytes(out2, b"never")
check("write_file_bytes: стойкий EAGAIN → ошибка", not ok and "Ресурс" in err, err)

# ---------- 7. image_saver.save_image: WebP через память ----------

from app.core.image_saver import save_image

webp_path = os.path.join(tmp, "saved.webp")
w, h = save_image(src, webp_path, "WebP")
back = QImage(webp_path)
check("save_image(WebP) пишет и читается обратно",
      w == 60 and h == 40 and not back.isNull() and back.size() == src.size(),
      f"{w}x{h}")

if os.geteuid() != 0:   # под root тесты прав бессмысленны
    ro_dir = os.path.join(tmp, "ro")
    os.mkdir(ro_dir, 0o755)
    ro_path = os.path.join(ro_dir, "x.webp")
    os.chmod(ro_dir, 0o555)
    try:
        try:
            save_image(src, ro_path, "WebP")
            check("save_image в папку без прав: отказ ожидаемым исключением", False, "не отказал")
        except ValueError as exc:
            check("save_image: причина отказа в тексте",
                  "WebP" in str(exc) and ("Отказано" in str(exc) or "Permission" in str(exc) or "Errno" in str(exc)),
                  str(exc)[:120])
    finally:
        os.chmod(ro_dir, 0o755)

# ---------- 8. local_viewer: Linux-ветки детекторов ----------

with mock_patch.object(netfs, "is_remote", lambda p: True):
    check("_is_remote_path видит сетевой путь", lv._is_remote_path("/x/a.png"))
    check("_drive_has_trash(сетевой) — корзины нет", lv._drive_has_trash("/x/a.png") is False)
with mock_patch.object(netfs, "is_remote", lambda p: False):
    check("_is_remote_path локальный — False", not lv._is_remote_path("/x/a.png"))
    check("_drive_has_trash(локальный Linux) — есть", lv._drive_has_trash("/x/a.png") is True)
check("_is_remote_path(пусто) — False", not lv._is_remote_path(""))
check("_drive_has_trash(пусто) — неизвестно", lv._drive_has_trash("") is None)

# ---------- 9. _io_pool: раскладка по пулам ----------

w = lv.LocalViewer()
with mock_patch.object(lv, "_is_remote_path", lambda p: True):
    check("_io_pool(сетевой) → узкий пул", w._io_pool("/x/a.png") is w._net_pool)
with mock_patch.object(lv, "_is_remote_path", lambda p: False):
    check("_io_pool(локальный) → общий пул",
          w._io_pool("/x/a.png") is __import__("PySide6.QtCore", fromlist=["QThreadPool"]).QThreadPool.globalInstance())
with mock_patch.object(lv, "_is_remote_path",
                       lambda p: p.endswith(".webp")):
    check("_io_pool(список, один сетевой) → узкий пул",
          w._io_pool("/l/a.png", "/l/b.webp") is w._net_pool)

# ---------- 10. удаление через сетевой пул end-to-end ----------

del_dir = tempfile.mkdtemp(prefix="ih_netfs_del_")
paths = []
for i in range(2):
    p = os.path.join(del_dir, f"n{i}.png")
    QImage(10, 10, QImage.Format.Format_RGB32).save(p, "PNG")
    paths.append(p)

with mock_patch.object(lv, "_is_remote_path", lambda p: True):
    w.load_folder(del_dir, entries=[(p, 10, 0.0) for p in paths])
    wait_until(lambda: w.list.count() == 2)
    w.list.selectAll()
    w._delete_perm = True
    w._start_delete(list(w._paths), phase=2)
    ok = wait_until(lambda: w.list.count() == 0
                    and not any(os.path.exists(p) for p in paths), 8.0)
check("удаление сетевых путей идёт через узкий пул и удаляет", ok,
      f"строк: {w.list.count()}")

# ---------- 11. _remove_forever на POSIX не ломает права ----------

if os.geteuid() != 0:
    ro2 = os.path.join(tmp, "ro2")
    os.mkdir(ro2, 0o755)
    stuck = os.path.join(ro2, "stuck.webp")
    open(stuck, "wb").write(b"keep me")
    os.chmod(stuck, 0o644)
    os.chmod(ro2, 0o555)          # каталог без записи: unlink → EACCES
    try:
        ok, err = lv._remove_forever(stuck)
        mode = stat.S_IMODE(os.stat(stuck).st_mode)
        check("неудаляемый файл: честный отказ", not ok and bool(err), err[:120])
        check("неудаляемый файл: подсказка про права в тексте",
              "нет прав" in err, err[:160])
        check("неудаляемый файл: права НЕ сломаны (0o644)", mode == 0o644, oct(mode))
    finally:
        os.chmod(ro2, 0o755)
        os.remove(stuck)

    ro3 = os.path.join(tmp, "ro3")
    os.mkdir(ro3, 0o755)
    f400 = os.path.join(ro3, "r400.webp")
    open(f400, "wb").write(b"x")
    os.chmod(f400, 0o400)         # только чтение владельцу
    ok, err = lv._remove_forever(f400)
    check("read-only файл удаляется (владельцу добавляется запись)",
          ok and not err and not os.path.exists(f400), err)

# read-only файл в обычной папке — как было на Windows, удаляется и на Linux
f444 = os.path.join(tmp, "r444.webp")
open(f444, "wb").write(b"x")
os.chmod(f444, 0o444)
ok, err = lv._remove_forever(f444)
check("0o444 удаляется", ok and not os.path.exists(f444), err)

# ---------- 12. i18n ----------

row = i18n._STRINGS.get("viewer.del_denied_hint", {})
check("i18n viewer.del_denied_hint (ru/en/zh)",
      all(row.get(l) for l in ("ru", "en", "zh")), str(sorted(row)))
for key in ("viewer.del_missing", "viewer.del_failed", "viewer.delete_busy"):
    row = i18n._STRINGS.get(key, {})
    check(f"i18n {key} (ru/en/zh)", all(row.get(l) for l in ("ru", "en", "zh")),
          str(sorted(row)))

print()
if FAILURES:
    print(f"ПРОВАЛЕНО: {len(FAILURES)} — " + "; ".join(FAILURES))
    os._exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
os._exit(0)
