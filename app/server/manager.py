"""Менеджер веб-сервера: жизнь модуля из интерфейса программы.

Менеджер — единственное место, где модуль касается настроек программы и
её журнала: он читает/пишет QSettings, подставляет избранные папки из
дерева «Диски и папки», подключает кольцевой буфер журнала и поднимает
сам HTTP-сервер (:class:`app.server.httpd.IHServer`) в фоновом потоке.
Интерфейсу он даёт сигналы:

* ``state_changed(bool)`` — сервер запущен/остановлен (меню «Модули»,
  панель);
* ``url_changed(str)``    — главный адрес с токеном (для окна настроек).

Настройки (QSettings «ImageHunter»):

* ``server/port``      — порт (по умолчанию 8477);
* ``server/token``     — токен доступа (генерируется один раз);
* ``server/view_only`` — «только просмотр» (по умолчанию выключен —
  удалённо доступны все действия программы);
* ``server/autostart`` — поднимать сервер вместе с программой
  (по умолчанию нет).

Запуск/остановка идемпотентны и потокобезопасны: вызывать можно откуда
угодно (кнопка, автостарт, закрытие окна).
"""

from __future__ import annotations

import logging
import secrets
import socket

from PySide6.QtCore import QObject, QSettings, Signal

from app.core import applog
from app.core.i18n import tr
from app.server import api as api_mod
from app.server import httpd
from app.server.api import LogRing

ORG, APP = "ImageHunter", "ImageHunter"
DEFAULT_PORT = 8477


def generate_token() -> str:
    """Токен доступа: 16 байт энтропии, URL-безопасный (~22 символа)."""
    return secrets.token_urlsafe(16)


class ServerManager(QObject):
    """Запуск/остановка сервера + настройки. Один экземпляр на программу."""

    state_changed = Signal(bool)          # сервер работает / остановлен
    url_changed = Signal(str)             # главный адрес с токеном

    def __init__(self) -> None:
        super().__init__()
        self._srv: httpd.IHServer | None = None
        self._ring: LogRing | None = None
        self.api: api_mod.Api | None = None

    # ------------------------------------------------------------- настройки

    @staticmethod
    def _settings() -> QSettings:
        return QSettings(ORG, APP)

    def get_port(self) -> int:
        try:
            return int(self._settings().value("server/port", DEFAULT_PORT))
        except (TypeError, ValueError):
            return DEFAULT_PORT

    def set_port(self, port: int) -> None:
        self._settings().setValue("server/port", int(port))

    def get_token(self) -> str:
        token = self._settings().value("server/token", "")
        if not token:
            token = generate_token()
            self._settings().setValue("server/token", token)
        return str(token)

    def set_token(self, token: str) -> None:
        self._settings().setValue("server/token", token)

    def get_view_only(self) -> bool:
        return self._settings().value("server/view_only", False, type=bool)

    def set_view_only(self, value: bool) -> None:
        self._settings().setValue("server/view_only", bool(value))

    def get_autostart(self) -> bool:
        return self._settings().value("server/autostart", False, type=bool)

    def set_autostart(self, value: bool) -> None:
        self._settings().setValue("server/autostart", bool(value))

    # ------------------------------------------------------------- жизнь

    def is_running(self) -> bool:
        return self._srv is not None and self._srv.running

    def start(self) -> bool:
        """Поднять сервер. True — работает (или уже работал)."""
        if self.is_running():
            return True
        token = self.get_token()
        favorites = self._read_favorites()
        self.api = api_mod.Api(
            version=self._version(), view_only=self.get_view_only(),
            favorites=favorites, ring=LogRing())
        self._ring = self.api.ring
        logging.getLogger().addHandler(self._ring)
        srv = httpd.IHServer(self.api, token, host="0.0.0.0",
                             port=self.get_port())
        try:
            port = srv.start()
        except OSError as exc:
            logging.getLogger().removeHandler(self._ring)
            self._ring = None
            self.api = None
            applog.error(f"🌐 {exc}")
            return False
        self._srv = srv
        applog.event("log.event.server_start", port=port,
                     mode=tr("server.mode_ro" if self.get_view_only()
                             else "server.mode_rw"))
        self.state_changed.emit(True)
        urls = httpd.lan_addresses(port)
        if urls:
            self.url_changed.emit(f"{urls[0]}/?token={token}")
        return True

    def stop(self) -> None:
        if self._ring is not None:
            try:
                logging.getLogger().removeHandler(self._ring)
            except Exception:                  # noqa: BLE001
                pass
            self._ring = None
        srv = self._srv
        self._srv = None
        if srv is not None:
            srv.stop()
            applog.event("log.event.server_stop", port=srv.port)
        self.state_changed.emit(False)

    def restart(self) -> bool:
        """Перезапуск с новыми настройками (порт/режим)."""
        self.stop()
        return self.start()

    def _read_favorites(self) -> list[str]:
        """Избранные папки дерева — из настроек программы (ключ viewer/favorites)."""
        try:
            raw = self._settings().value("viewer/favorites", [])
            if isinstance(raw, str):
                raw = [raw] if raw else []
            return [str(p) for p in raw if p and str(p).strip()]
        except Exception:                      # noqa: BLE001
            return []

    @staticmethod
    def _version() -> str:
        try:
            from app import __version__
            return __version__
        except Exception:                      # noqa: BLE001
            return ""

    # ------------------------------------------------------------- адреса

    def urls(self) -> list[str]:
        """Адреса сервера в сети (все интерфейсы), каждый — с токеном."""
        if self._srv is None:
            return []
        token = self.get_token()
        return [f"{u}/?token={token}" for u in httpd.lan_addresses(self._srv.port)]

    def port(self) -> int:
        return self._srv.port if self._srv is not None else self.get_port()

    def has_qr(self) -> bool:
        """Доступна ли библиотека qrcode (для окна настроек)."""
        try:
            import qrcode  # noqa: F401
            return True
        except Exception:                      # noqa: BLE001
            return False
