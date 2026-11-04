"""Окно настроек веб-сервера: запуск, порт, токен, QR-код для телефона.

Открывается пунктом «🌐 Панель веб-сервера…» в меню «Модули» главного
окна (v0.8.2; создаётся лениво, при первом клике — сам модуль при этом
ничего не поднимает). Здесь можно:

* запустить и остановить сервер;
* сменить порт и токен, включить «только просмотр» и автостарт;
* скопировать адрес с токеном и отсканировать QR-код телефоном.

QR-код рисуется библиотекой ``qrcode`` — она не входит в зависимости
программы и ставится кнопкой прямо из окна (тот же приём, что у модуля
rembg: pip текущего интерпретатора, без окна терминала). Без неё окно
показывает адрес текстом — QR просто удобство.
"""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt, QBuffer, QByteArray, QThread
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.core.i18n import tr
from app.server.manager import ServerManager, generate_token


class _PipTask(QThread):
    """pip install qrcode в рабочем потоке (окно не замирает)."""

    def __init__(self, parent, on_done):
        super().__init__(parent)
        self._on_done = on_done

    def run(self) -> None:
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", "qrcode"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                                  creationflags=getattr(
                                      subprocess, "CREATE_NO_WINDOW", 0))
            ok = proc.returncode == 0
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        except (OSError, subprocess.SubprocessError) as exc:
            ok, tail = False, [str(exc)]
        self._on_done(ok, " | ".join(tail))


class ServerDialog(QDialog):
    """Настройки и пульт веб-сервера."""

    def __init__(self, manager: ServerManager, parent=None) -> None:
        super().__init__(parent)
        self._mgr = manager
        self._pip: _PipTask | None = None
        self.setWindowTitle(tr("server.title"))
        self.setMinimumWidth(420)
        self.setModal(False)

        root = QVBoxLayout(self)

        # --- пульт: кнопка запуска + статус
        self.btn_toggle = QPushButton()
        self.btn_toggle.setStyleSheet("font-size:15px; padding:9px;")
        self.btn_toggle.clicked.connect(self._toggle)
        root.addWidget(self.btn_toggle)
        self.lbl_state = QLabel()
        self.lbl_state.setWordWrap(True)
        root.addWidget(self.lbl_state)

        # --- адреса + QR
        self.lbl_urls_hint = QLabel(tr("server.urls_lbl"))
        self.lbl_urls_hint.setWordWrap(True)
        root.addWidget(self.lbl_urls_hint)
        self.lbl_urls = QLabel()
        self.lbl_urls.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_urls.setWordWrap(True)
        root.addWidget(self.lbl_urls)
        self.lbl_qr = QLabel()
        self.lbl_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.lbl_qr)
        self.btn_qr = QPushButton(tr("server.qr_install"))
        self.btn_qr.clicked.connect(self._install_qr)
        root.addWidget(self.btn_qr)

        # --- порт
        row_port = QHBoxLayout()
        row_port.addWidget(QLabel(tr("server.port_lbl")))
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(manager.get_port())
        row_port.addWidget(self.spin_port)
        row_port.addStretch(1)
        root.addLayout(row_port)

        # --- токен
        root.addWidget(QLabel(tr("server.token_lbl")))
        row_tok = QHBoxLayout()
        self.ed_token = QLineEdit(manager.get_token())
        self.ed_token.setEchoMode(QLineEdit.EchoMode.Password)
        row_tok.addWidget(self.ed_token)
        btn_eye = QPushButton("👁")
        btn_eye.setFixedWidth(40)
        btn_eye.clicked.connect(self._toggle_echo)
        row_tok.addWidget(btn_eye)
        btn_dice = QPushButton("🎲")
        btn_dice.setFixedWidth(40)
        btn_dice.setToolTip(tr("server.token_gen"))
        btn_dice.clicked.connect(
            lambda: self.ed_token.setText(generate_token()))
        row_tok.addWidget(btn_dice)
        btn_copy = QPushButton("📋")
        btn_copy.setFixedWidth(40)
        btn_copy.setToolTip(tr("server.token_copy"))
        btn_copy.clicked.connect(self._copy_url)
        row_tok.addWidget(btn_copy)
        root.addLayout(row_tok)

        # --- режимы
        self.chk_view = QCheckBox(tr("server.view_only"))
        self.chk_view.setChecked(manager.get_view_only())
        root.addWidget(self.chk_view)
        self.chk_auto = QCheckBox(tr("server.autostart"))
        self.chk_auto.setChecked(manager.get_autostart())
        root.addWidget(self.chk_auto)

        # --- применить
        self.btn_apply = QPushButton(tr("server.apply"))
        self.btn_apply.setStyleSheet("font-size:14px; padding:8px;")
        self.btn_apply.clicked.connect(self._apply)
        root.addWidget(self.btn_apply)

        self.btn_browser = QPushButton(tr("server.open_browser"))
        self.btn_browser.clicked.connect(self._open_browser)
        root.addWidget(self.btn_browser)

        self.lbl_hint = QLabel(tr("server.firewall"))
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#9aa5b5; font-size:12px;")
        root.addWidget(self.lbl_hint)

        manager.state_changed.connect(self._on_state)
        manager.url_changed.connect(self._on_url)
        self._on_state(manager.is_running())
        if manager.is_running():
            urls = manager.urls()
            if urls:
                self._on_url(urls[0])

    # ------------------------------------------------------------- поведение

    def _toggle(self) -> None:
        if self._mgr.is_running():
            self._mgr.stop()
        else:
            self._mgr.start()
        self._refresh_urls()

    def _toggle_echo(self) -> None:
        full = self.ed_token.echoMode() == QLineEdit.EchoMode.Password
        self.ed_token.setEchoMode(
            QLineEdit.EchoMode.Normal if full else QLineEdit.EchoMode.Password)

    def _copy_url(self) -> None:
        from PySide6.QtWidgets import QApplication
        urls = self._mgr.urls()
        QApplication.clipboard().setText(urls[0] if urls else
                                         self._make_url(self.spin_port.value()))

    def _apply(self) -> None:
        """Сохранить настройки; если сервер работал — перезапустить."""
        was_running = self._mgr.is_running()
        self._mgr.set_port(self.spin_port.value())
        self._mgr.set_token(self.ed_token.text().strip() or generate_token())
        self._mgr.set_view_only(self.chk_view.isChecked())
        self._mgr.set_autostart(self.chk_auto.isChecked())
        if was_running:
            self._mgr.restart()
            self._refresh_urls()
        elif self.chk_auto.isChecked():
            self._mgr.start()
            self._refresh_urls()

    def _open_browser(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        urls = self._mgr.urls()
        if urls:
            QDesktopServices.openUrl(QUrl(urls[0]))

    def _install_qr(self) -> None:
        if self._pip is not None and self._pip.isRunning():
            return
        self.btn_qr.setEnabled(False)
        self.btn_qr.setText(tr("server.qr_installing"))
        self._pip = _PipTask(self, self._on_qr_installed)
        self._pip.start()

    def _on_qr_installed(self, ok: bool, tail: str) -> None:
        self.btn_qr.setEnabled(True)
        self.btn_qr.setText(tr("server.qr_install"))
        if ok and self._mgr.has_qr():
            self._refresh_urls()
        else:
            self.lbl_qr.setText(tr("server.qr_fail", tail=tail or "?"))

    # ------------------------------------------------------------- отображение

    def _make_url(self, port: int) -> str:
        from app.server import httpd
        urls = httpd.lan_addresses(port)
        token = self.ed_token.text().strip() or self._mgr.get_token()
        return f"{urls[0]}/?token={token}"

    def _refresh_urls(self) -> None:
        if self._mgr.is_running():
            urls = self._mgr.urls()
            if urls:
                self._on_url(urls[0])
        else:
            self._on_url(self._make_url(self.spin_port.value()))

    def _on_state(self, running: bool) -> None:
        self.btn_toggle.setText(tr("server.stop") if running
                                else tr("server.run"))
        port = self._mgr.port()
        self.lbl_state.setText(
            tr("server.running", port=port) if running
            else tr("server.stopped", port=port))
        self.lbl_state.setStyleSheet(
            "color:#3fb27f;" if running else "color:#9aa5b5;")

    def _on_url(self, url: str) -> None:
        self.lbl_urls.setText(f"<a href='{url}'>{url}</a>")
        self.lbl_urls.setOpenExternalLinks(True)
        self._draw_qr(url)

    def _draw_qr(self, url: str) -> None:
        if not self._mgr.has_qr():
            self.btn_qr.setVisible(True)
            self.lbl_qr.setText(tr("server.qr_none"))
            return
        self.btn_qr.setVisible(False)
        try:
            import qrcode
            from PIL import Image
            im = qrcode.make(url, box_size=6, border=2).convert("RGB")
            buf = QBuffer()
            buf.open(QBuffer.OpenModeFlag.WriteOnly)
            im.save(buf, "PNG")          # type: ignore[union-attr]
            pix = QPixmap()
            pix.loadFromData(bytes(buf.data()), "PNG")
            self.lbl_qr.setPixmap(pix.scaledToWidth(
                220, Qt.TransformationMode.SmoothTransformation))
        except Exception:                  # noqa: BLE001
            self.lbl_qr.setText(tr("server.qr_none"))
