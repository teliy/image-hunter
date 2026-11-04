"""Внутреннее API веб-сервера Image Hunter — файловая часть без интерфейса.

Здесь нет ни Qt-виджетов, ни HTTP: класс :class:`Api` — чистые операции над
файловой системой, которыми пользуются и HTTP-обработчики, и тесты. Так
сервер повторяет поведение программы и не может с ней разойтись:

* миниатюры кладутся в тот же дисковый кэш, что и у «Моих картинок»
  (ключ — SHA-1 от «нормализованный путь + размер + mtime»), а при
  размере 160 px переиспользуют готовые миниатюры программы;
* переименование — те же правила, что и по F2 в программе: чистка имени
  (пробелы по краям, точки на конце), запрет пустых имён и символов
  ``\\ / : * ? " < > |``, отказ перезаписывать существующий файл,
  разрешено переименование «только регистр»;
* удаление — в корзину (средствами Qt, как в программе) или окончательно
  со снятием «только чтения»; режим «только просмотр» запрещает всё,
  что меняет файлы;
* поиск по имени — однопроходный ``os.scandir`` (как в программе), с
  опциями «вглубь подпапок» и «игнорировать дефис», с пределом результатов;
* удаление фона — тот же формат результата «X_nobg.png», тот же перехват
  скачивания модели; работа идёт фоновым заданием с опросом статуса.

Всё потокобезопасно: ThreadingHTTPServer зовёт методы из разных потоков.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import logging
import os
import secrets
import stat as stat_mod
import sys
import threading

from PIL import Image, ImageOps

try:                                   # AVIF-кодек ставится вместе с программой
    import pillow_avif  # noqa: F401
except Exception:                      # noqa: BLE001 — AVIF просто не откроется
    pass

# ровно тот же список, что в «Моих картинках» (app/ui/local_viewer.py)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".avif", ".avifs"}

THUMB_SIZE_DEFAULT = 320          # размер миниатюры для телефона (px, большая сторона)
SEARCH_MAX = 2000                 # предел результатов поиска (дальше — флаг truncated)
_LOG_RING_MAX = 400               # строк журнала в кольцевом буфере
_TRASH_CACHE: dict[str, bool] = {}  # корень диска -> есть ли корзина (как в программе)


# ---------------------------------------------------------------- журнал

class LogRing(logging.Handler):
    """Кольцевой буфер последних строк журнала — для /api/log.

    Подключается к корневому журналу на время работы сервера: и события
    самой программы, и события сервера видны с телефона. Формат строки —
    «ЧЧ:ММ:СС [УРОВЕНЬ] текст», как во вкладке «Журнал».
    """

    def __init__(self, limit: int = _LOG_RING_MAX) -> None:
        super().__init__()
        self._limit = limit
        self._items: list[str] = []
        self._lock = threading.Lock()
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:                      # noqa: BLE001 — формат не должен падать
            return
        with self._lock:
            self._items.append(line)
            if len(self._items) > self._limit:
                del self._items[: len(self._items) - self._limit]

    def tail(self, n: int = 100) -> list[str]:
        with self._lock:
            return list(self._items[-max(1, min(n, self._limit)):])


def _clean_rename_name(raw: str) -> str:
    """Те же правила, что в редакторе имени программы: пробелы по краям и
    точки на конце убираются — Windows такие имена не создаёт."""
    return (raw or "").strip().rstrip(". ")


def _name_is_allowed(name: str) -> bool:
    """Имя допустимо: непустое, не «.»/«..», без запрещённых в Windows
    символов и управляющих. Один список с программой — предсказуемо везде."""
    if not name or name in (".", ".."):
        return False
    return not any(c in name for c in '<>:"/\\|?*') and all(ord(c) >= 32 for c in name)


def _thumb_cache_dir() -> str:
    """Тот же кэш миниатюр, что у программы: %LOCALAPPDATA%\\ImageHunter\\thumbs
    (Linux: ~/.cache/ImageHunter/thumbs). Пустая строка — кэш недоступен."""
    import tempfile
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        d = os.path.join(base, "ImageHunter", "thumbs")
    else:
        xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache")
        d = os.path.join(xdg, "ImageHunter", "thumbs")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return ""


def _thumb_key(path: str, size: int, mtime: float) -> str:
    """Ключ кэша — тот же алгоритм, что в программе (normcase + размер + mtime)."""
    try:
        norm = os.path.normcase(os.path.abspath(path))
    except OSError:
        norm = path
    raw = f"{norm}|{size}|{mtime:.0f}".encode("utf-8", "surrogateescape")
    return hashlib.sha1(raw).hexdigest()


# ---------------------------------------------------------------- API


class Api:
    """Внутреннее API: всё, что умеет программа, — как вызовы.

    Параметры конструктора:

    * ``version`` — версия программы (для /api/ping);
    * ``view_only`` — только просмотр: rename/delete/rembg запрещены;
    * ``restrict_roots`` — список корней (папок/дисков); пустой или None —
      доступно всё, как в самой программе;
    * ``favorites`` — избранные папки (в GUI-режиме их подставляет менеджер
      из настроек программы);
    * ``ring`` — свой обработчик журнала; по умолчанию создаётся свой.
    """

    def __init__(self, *, version: str = "", view_only: bool = False,
                 restrict_roots: list[str] | None = None,
                 favorites: list[str] | None = None,
                 ring: LogRing | None = None) -> None:
        self.version = version
        self.view_only = bool(view_only)
        self.restrict_roots = [os.path.normcase(os.path.abspath(r))
                               for r in (restrict_roots or []) if r]
        self.favorites = list(favorites or [])
        self.ring = ring or LogRing()
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._job_seq = 0

    # ------------------------------------------------------------- проверки

    def _check_path(self, path: str) -> str:
        """Нормализовать путь и проверить ограничение корней.

        Возвращает нормализованный путь; ValueError — путь не разрешён.
        """
        if not path:
            raise ValueError("пустой путь")
        norm = os.path.normpath(os.path.abspath(path))
        if self.restrict_roots:
            nc = os.path.normcase(norm)
            for root in self.restrict_roots:
                rc = os.path.normcase(root)
                if nc == rc or nc.startswith(rc.rstrip(os.sep) + os.sep):
                    return norm
            raise ValueError("путь вне разрешённых корней")
        return norm

    def _require_write(self) -> None:
        if self.view_only:
            raise PermissionError("сервер в режиме «только просмотр»")

    # ------------------------------------------------------------- информация

    def ping(self) -> dict:
        return {
            "app": "Image Hunter",
            "version": self.version,
            "host": os.uname().nodename if hasattr(os, "uname") else
                    (os.environ.get("COMPUTERNAME") or ""),
            "platform": sys.platform,
            "view_only": self.view_only,
            # куда открыть интерфейс при старте: первый разрешённый корень
            # (в режиме ограничения) — иначе телефон упрётся в отказ по «/»
            "root": self.restrict_roots[0] if self.restrict_roots else "",
        }

    # ------------------------------------------------------------- диски

    def drives(self) -> list[dict]:
        """Диски машины + избранные папки (как секция дерева «Диски и папки»)."""
        out: list[dict] = []
        for fav in self.favorites:
            if not os.path.isdir(fav):
                continue
            try:
                self._check_path(fav)
            except ValueError:
                continue          # вне разрешённых корней — с телефона не видна
            out.append({"path": fav, "label": os.path.basename(fav) or fav,
                        "kind": "favorite", "free": 0, "total": 0})
        for path, label, kind in self._enum_drives():
            try:
                self._check_path(path)
            except ValueError:
                continue          # диск целиком вне корней — не предлагаем
            out.append({"path": path, "label": label, "kind": kind,
                        "free": _free_bytes(path), "total": 0})
        return out

    def _enum_drives(self) -> list[tuple[str, str, str]]:
        if sys.platform == "win32":
            try:
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            except Exception:                  # noqa: BLE001
                bitmask = 0
            out = []
            for i in range(26):
                if not (bitmask >> i) & 1:
                    continue
                letter = f"{chr(ord('A') + i)}:\\"
                kind = "drive"
                try:
                    rtype = ctypes.windll.kernel32.GetDriveTypeW(letter)
                    if rtype == 4:
                        kind = "remote"
                    elif rtype in (2, 5):     # съёмный / CD
                        kind = "removable"
                    buf = ctypes.create_unicode_buffer(261)
                    if ctypes.windll.kernel32.GetVolumeInformationW(
                            letter, buf, 261, None, None, None, None, 0):
                        label = f"{buf.value or ''} ({letter[0]}:)"
                    else:
                        label = f"💾 {letter[0]}:"
                except Exception:              # noqa: BLE001
                    label = f"💾 {letter[0]}:"
                out.append((letter, label, kind))
            return out
        # POSIX: смонтированные реальные файловые системы
        out: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        entries: list[tuple[str, str]] = []
        try:
            with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        entries.append((parts[1], parts[0]))
        except OSError:
            entries = [("/", "")]
        skip = ("/dev", "/proc", "/sys", "/run", "/boot", "/snap", "/tmpfs")
        for mnt, dev in entries:
            if mnt in seen or not os.path.isdir(mnt):
                continue
            if any(mnt == s or mnt.startswith(s + "/") for s in skip) and mnt != "/":
                continue
            if dev.startswith(("/dev/loop", "tmpfs", "cgroup", "proc", "sysfs",
                               "devpts", "mqueue", "shm", "overlay")):
                continue
            seen.add(mnt)
            label = os.path.basename(mnt.rstrip("/")) or mnt
            kind = "remote" if (dev.startswith("//") or ":/" in dev) else "drive"
            out.append((mnt, f"💾 {label}", kind))
            if len(out) >= 24:
                break
        if not out:
            out.append(("/", "💾 /", "drive"))
        return out

    # ------------------------------------------------------------- папки и поиск

    def list_folder(self, path: str) -> dict:
        """Содержимое папки: подпапки + картинки (как лента «Моих картинок»)."""
        path = self._check_path(path)
        if not os.path.isdir(path):
            raise FileNotFoundError(path)
        folders: list[dict] = []
        files: list[dict] = []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith("."):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            folders.append({"name": name,
                                            "path": os.path.join(path, name)})
                        elif (os.path.splitext(name)[1].lower() in IMAGE_EXTS
                              and entry.is_file(follow_symlinks=False)):
                            st = entry.stat(follow_symlinks=False)
                            files.append({
                                "name": name, "path": os.path.join(path, name),
                                "size": st.st_size, "mtime": int(st.st_mtime),
                            })
                    except OSError:
                        continue        # файл успел исчезнуть — не беда
        except OSError as exc:
            raise FileNotFoundError(str(exc) or path) from exc
        folders.sort(key=lambda d: d["name"].lower())
        files.sort(key=lambda d: d["name"].lower())
        return {"path": path, "folders": folders, "files": files,
                "parent": os.path.dirname(path) if path != os.path.dirname(path) else ""}

    def search(self, path: str, query: str, deep: bool = False,
               ignore_dash: bool = False) -> dict:
        """Поиск картинок по имени: от ``path`` (deep — и вглубь подпапок).

        Однопроходный обход как в программе; предел SEARCH_MAX, дальше
        ``truncated: true``. ``ignore_dash`` — как чекбокс программы:
        дефисы в имени файла и запросе не учитываются.
        """
        base = self._check_path(path)
        if not os.path.isdir(base):
            raise FileNotFoundError(base)
        q = (query or "").strip().lower()
        if ignore_dash:
            q = q.replace("-", "")
        needle = q or ""
        found: list[dict] = []
        truncated = False
        for root, dirs, files in _walk(base, deep):
            for name in files:
                if os.path.splitext(name)[1].lower() not in IMAGE_EXTS:
                    continue
                hay = name.lower()
                if ignore_dash:
                    hay = hay.replace("-", "")
                if needle and needle not in hay:
                    continue
                full = os.path.join(root, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                found.append({"name": name, "path": full,
                              "size": st.st_size, "mtime": int(st.st_mtime),
                              "folder": root})
                if len(found) >= SEARCH_MAX:
                    truncated = True
                    break
            if truncated:
                break
        found.sort(key=lambda d: d["name"].lower())
        return {"path": base, "query": query, "files": found, "truncated": truncated}

    # ------------------------------------------------------------- картинки

    def image_bytes(self, path: str) -> tuple[bytes, str, int]:
        """Полный файл картинки: (байты, content-type, mtime)."""
        path = self._check_path(path)
        data, ctype = _read_image(path)
        try:
            mtime = int(os.stat(path).st_mtime)
        except OSError:
            mtime = 0
        return data, ctype, mtime

    def thumbnail(self, path: str, size: int = THUMB_SIZE_DEFAULT) -> tuple[bytes, int]:
        """Миниатюра PNG: из дискового кэша программы или декодированием.

        ``size`` — большая сторона в пикселях. Ключ кэша тот же, что у
        программы; при ``size <= 160`` сначала пробуется готовая миниатюра
        программы (файл ``<ключ>.png``), чтобы не декодировать файл заново.
        Возвращает (байты PNG, mtime файла).
        """
        path = self._check_path(path)
        size = max(32, min(int(size or THUMB_SIZE_DEFAULT), 1024))
        try:
            st = os.stat(path)
        except OSError as exc:
            raise FileNotFoundError(path) from exc
        key = _thumb_key(path, st.st_size, st.st_mtime)
        cache_dir = _thumb_cache_dir()
        own_path = os.path.join(cache_dir, f"{key}-{size}.png") if cache_dir else ""
        if own_path and size <= 160:
            prog_path = os.path.join(cache_dir, f"{key}.png")   # кэш программы
            if os.path.isfile(prog_path):
                try:
                    return _read_file(prog_path), int(st.st_mtime)
                except OSError:
                    pass
        if own_path and os.path.isfile(own_path):
            try:
                return _read_file(own_path), int(st.st_mtime)
            except OSError:
                pass
        data, _ctype = _read_image(path)
        try:
            with Image.open(io.BytesIO(data)) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((size, size), Image.LANCZOS)
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA" if (im.mode in ("P", "LA")
                                               or "transparency" in im.info) else "RGB")
                out = io.BytesIO()
                im.save(out, "PNG")
        except Exception as exc:               # noqa: BLE001 — битая/не-картинка
            raise ValueError(f"не удалось декодировать картинку: {exc}") from exc
        png = out.getvalue()
        if own_path:
            _atomic_write(own_path, png)
        return png, int(st.st_mtime)

    # ------------------------------------------------------------- изменения

    def rename(self, path: str, new_name: str) -> dict:
        """Переименовать файл — по правилам программы (см. модульный докстринг)."""
        self._require_write()
        path = self._check_path(path)
        new_name = _clean_rename_name(new_name)
        if not _name_is_allowed(new_name):
            raise ValueError("недопустимое имя")
        folder = os.path.dirname(path)
        target = os.path.join(folder, new_name)
        case_only = (os.path.normcase(os.path.abspath(target))
                     == os.path.normcase(os.path.abspath(path)))
        if not case_only and os.path.lexists(target):
            raise FileExistsError("файл с таким именем уже существует")
        try:
            os.rename(path, target)
        except OSError as exc:
            raise OSError(str(exc)) from exc
        return {"ok": True, "old": path, "new": target}

    def delete(self, paths: list[str], permanent: bool = False) -> dict:
        """Удалить файлы: в корзину (по умолчанию) или окончательно."""
        self._require_write()
        results: list[dict] = []
        for raw in paths or []:
            try:
                path = self._check_path(raw)
            except ValueError as exc:
                results.append({"path": raw, "ok": False, "error": str(exc)})
                continue
            if permanent:
                ok, err = _remove_forever(path)
            else:
                ok, err = _trash_file(path)
            results.append({"path": path, "ok": ok, "error": err})
        return {"results": results}

    # ------------------------------------------------------------- rembg

    def rembg_installed(self) -> bool:
        try:
            from app.ui import rembg_manager   # лениво: модуль сам по себе лёгкий
            return rembg_manager.is_installed()
        except Exception:                      # noqa: BLE001
            return False

    def rembg_start(self, paths: list[str], model: str = "") -> dict:
        """Запустить удаление фона пачки файлов фоновым заданием.

        Возвращает ``{"id": …, "total": n}``; статус — :meth:`rembg_status`.
        Результаты — «X_nobg.png» рядом с оригиналами, как в программе.
        """
        self._require_write()
        if not self.rembg_installed():
            raise RuntimeError("модуль rembg не установлен — установите его в программе")
        jobs: list[tuple[str, str]] = []
        from app.ui import rembg_manager
        for raw in paths or []:
            try:
                path = self._check_path(raw)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            out = rembg_manager.nobg_path(path)
            if out:
                jobs.append((path, out))
        if not jobs:
            raise ValueError("нет файлов для обработки (или это уже результаты *_nobg)")
        model = model or "u2netp"
        with self._lock:
            self._job_seq += 1
            job_id = f"j{self._job_seq}-{secrets.token_hex(3)}"
            job = {"id": job_id, "state": "running", "done": 0, "total": len(jobs),
                   "current": os.path.basename(jobs[0][0]), "ok": 0, "fail": 0,
                   "errors": [], "model": model}
            self._jobs[job_id] = job
        th = threading.Thread(target=self._rembg_run, args=(job, jobs, model),
                              daemon=True, name=f"rembg-{job_id}")
        th.start()
        return {"id": job_id, "total": len(jobs)}

    def _rembg_run(self, job: dict, jobs: list[tuple[str, str]], model: str) -> None:
        from app.ui import rembg_manager
        rembg_manager._ensure_stdio()
        rembg_manager.hook_model_downloads()
        try:
            from rembg import remove, new_session
        except Exception as exc:               # noqa: BLE001
            job.update(state="error", error=str(exc))
            return
        try:
            session = new_session(model)
        except Exception as exc:               # noqa: BLE001 — скачивание модели и пр.
            job.update(state="error", error=str(exc))
            return
        for path, out in jobs:
            job["current"] = os.path.basename(path)
            try:
                with open(path, "rb") as f:
                    data = f.read()
                result = remove(data, session=session)
                with open(out, "wb") as f:
                    f.write(result)
                job["ok"] += 1
            except Exception as exc:           # noqa: BLE001
                job["fail"] += 1
                job["errors"].append({"path": path, "error": str(exc)})
            job["done"] += 1
        job["state"] = "done"

    def rembg_status(self, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return {k: v for k, v in job.items()}

    def rembg_models(self) -> list[str]:
        try:
            from app.ui import rembg_manager
            return [m[0] for m in rembg_manager.REMBG_MODELS]
        except Exception:                      # noqa: BLE001
            return ["u2netp"]

    # ------------------------------------------------------------- журнал

    def log_tail(self, n: int = 100) -> dict:
        return {"lines": self.ring.tail(n)}


# ---------------------------------------------------------------- помощники


def _walk(base: str, deep: bool):
    """Обход папки: без deep — только верхний уровень; с deep — вглубь.

    os.walk идёт сверху вниз; папки, начинающиеся с точки, пропускаются.
    """
    if not deep:
        try:
            with os.scandir(base) as it:
                names_files = [e.name for e in it if e.is_file(follow_symlinks=False)]
        except OSError:
            names_files = []
        yield base, [], names_files
        return
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        yield root, dirs, files


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _atomic_write(target: str, data: bytes) -> None:
    tmp = f"{target}.{os.getpid()}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    ".avif": "image/avif", ".avifs": "image/avif",
}


def content_type_for(path: str) -> str:
    return _CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def _read_image(path: str) -> tuple[bytes, str]:
    """Прочитать файл картинки обычным I/O (GIL отпускается — сеть не блокирует
    остальные потоки) и вернуть (байты, content-type)."""
    size = os.path.getsize(path)
    if size > (1 << 30):
        raise ValueError("файл больше 1 ГБ")
    data = _read_file(path)
    if not data:
        raise ValueError("файл пуст")
    return data, content_type_for(path)


def _free_bytes(path: str) -> int:
    try:
        if sys.platform == "win32":
            free = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path), None, None, ctypes.byref(free))
            return free.value
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize
    except Exception:                          # noqa: BLE001
        return 0


def _remove_forever(path: str) -> tuple[bool, str]:
    """Окончательное удаление (как в программе: сначала снять read-only)."""
    try:
        if not os.path.isfile(path):
            return False, "файл не найден"
        try:
            os.chmod(path, stat_mod.S_IWRITE)
        except OSError:
            pass
        os.remove(path)
        return True, ""
    except OSError as exc:
        return False, str(exc)


def _drive_has_trash(path: str) -> bool | None:
    """Есть ли на диске корзина (Windows; None — неизвестно). Копия логики
    программы: сетевые диски корзины не имеют — сразу окончательное удаление."""
    if sys.platform != "win32" or not path:
        return None
    try:
        root = os.path.splitdrive(path)[0]
        if len(root) < 2:
            return None
        cached = _TRASH_CACHE.get(root)
        if cached is not None:
            return cached

        class _RBInfo(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong),
                        ("i64Size", ctypes.c_int64),
                        ("i64NumItems", ctypes.c_int64)]

        info = _RBInfo()
        info.cbSize = ctypes.sizeof(info)
        hr = ctypes.windll.shell32.SHQueryRecycleBinW(root + "\\", ctypes.byref(info))
        _TRASH_CACHE[root] = (hr == 0)
        return _TRASH_CACHE[root]
    except Exception:                          # noqa: BLE001
        return None


def _trash_file(path: str) -> tuple[bool, str]:
    """Корзина. Внутри запущенной программы — QFile.moveToTrash (как там);
    если Qt недоступен или на диске нет корзины — честный отказ."""
    try:
        if not os.path.isfile(path):
            return False, "файл не найден"
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QFile
        if _drive_has_trash(path) is False and sys.platform == "win32":
            return False, "на этом диске нет корзины — используйте окончательное удаление"
        res = QFile.moveToTrash(path)
        ok = bool(res[0]) if isinstance(res, tuple) else bool(res)
        return ok, "" if ok else "не удалось переместить в корзину"
    except ImportError:
        return False, "корзина недоступна (нет Qt) — используйте окончательное удаление"
    except Exception as exc:                   # noqa: BLE001
        return False, str(exc)
