"""Запуск веб-сервера отдельным процессом: ``python -m app.server``.

Основной сценарий модуля — сервер внутри запущенной программы (кнопка
«🌐»). Отдельный процесс нужен для/headless-случаев: папка с фото на
машине без интерфейса, отладка, скрипты. В headless-режиме нет GUI, но
API то же самое: папки, миниатюры (общий кэш), поиск, переименование,
удаление, журнал. Удаление фона работает, если rembg установлен в это
же окружение.

Примеры::

    python -m app.server --port 8477 --token мой-токен
    python -m app.server --view-only --lifetime 3600
    python -m app.server --restrict C:\\Users\\me\\Pictures

Параметры:

* ``--port N``      — порт (по умолчанию 8477; 0 — случайный свободный);
* ``--host ADDR``   — интерфейс (по умолчанию 0.0.0.0 — все);
* ``--token T``     — токен (по умолчанию сгенерировать и напечатать);
* ``--view-only``   — запретить удалённые изменения;
* ``--restrict P``  — разрешить только пути внутри папки P (можно несколько раз);
* ``--lifetime N``  — выйти через N секунд (для тестов);
* ``--quiet``       — не печатать адреса (только ошибки).
"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.server",
        description="Веб-сервер Image Hunter (модуль удалённого доступа)")
    parser.add_argument("--port", type=int, default=8477)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--token", default="")
    parser.add_argument("--view-only", action="store_true")
    parser.add_argument("--restrict", action="append", default=[])
    parser.add_argument("--lifetime", type=int, default=0,
                        help="выйти через N секунд")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    from app.server.api import Api
    from app.server.httpd import IHServer, lan_addresses
    from app.server.manager import generate_token

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("urllib3", "requests", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    token = args.token or generate_token()
    api = Api(version=_version(), view_only=args.view_only,
              restrict_roots=args.restrict or None)
    srv = IHServer(api, token, host=args.host, port=args.port)
    try:
        port = srv.start()
    except OSError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"Image Hunter web server v{api.version}")
        print(f"режим: {'только просмотр' if args.view_only else 'полный доступ'}")
        if args.restrict:
            print("корни: " + ", ".join(args.restrict))
        for u in lan_addresses(port):
            print(f"  {u}/?token={token}")
        print("Ctrl+C — остановить")

    if not args.quiet:
        api.ring.tail(1)   # кольцевой буфер и так собирает журнал
    try:
        import time
        deadline = time.monotonic() + (args.lifetime if args.lifetime > 0
                                       else 10 ** 12)
        while time.monotonic() < deadline:
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    return 0


def _version() -> str:
    try:
        from app import __version__
        return __version__
    except Exception:                          # noqa: BLE001
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
