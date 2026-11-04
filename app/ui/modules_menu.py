"""Меню «Модули» в строке меню: настройки, установка и удаление модулей.

Единое место управления подключаемыми модулями — слева от «Справки»
(v0.8.2). Внутри два раздела:

* **Удаление фона (rembg)** — установка/удаление пакета и выбор модели;
  сами действия делегированы вьюеру «Моих картинок» (:class:`app.ui.
  local_viewer.LocalViewer`): он владеет фоновыми задачами pip, guard-ом
  от двойного запуска и всей репортёрикой в статус/журнал с v0.7.12;
* **Веб-сервер (доступ с телефона)** — панель управления (порт, токен,
  QR-код, «только просмотр»), запуск/остановка и автостарт с программой;
  менеджер создаётся лениво, как и раньше: пока модуль не тронули,
  ``app.server`` не импортируется и ничего не слушает (v0.8.0).

Меню собирается заново при каждом открывании (``aboutToShow``): состав,
галочки и заголовки-состояния всегда соответствуют действительности —
модуль могли установить или удалить с прошлого раза, сервер могли
перезапустить из его панели. Заодно это даёт бесплатную перетрансляцию
при смене языка.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMenu

from app.core import applog
from app.core.i18n import tr
from app.ui import rembg_manager


class ModulesMenu(QMenu):
    """Меню «Модули»: один экземпляр создаёт MainWindow."""

    def __init__(self, main) -> None:
        super().__init__(tr("menu.modules"), main)
        self._main = main          # MainWindow: сервер и вьюер живут там
        self.aboutToShow.connect(self._rebuild)
        self._rebuild()

    def retranslate(self) -> None:
        """Заголовок меню; пункты пересоберутся с новым языком при открытии."""
        self.setTitle(tr("menu.modules"))

    # ------------------------------------------------------------- сборка

    def _rebuild(self) -> None:
        """Собрать пункты заново: состояние модулей могли поменять."""
        self.clear()
        self._add_rembg_section()
        self.addSeparator()
        self._add_server_section()

    def _add_rembg_section(self) -> None:
        """Раздел удаления фона: состояние, установка/удаление, модель."""
        viewer = self._main.local
        installed = rembg_manager.is_installed()
        head = self.addAction(tr("modules.rembg_header", state=tr(
            "modules.installed" if installed else "modules.not_installed")))
        head.setEnabled(False)   # заголовок-состояние, не команда
        busy = viewer.rembg_is_busy()
        if installed:
            act = self.addAction(tr("viewer.rembg_menu_uninstall"))
            act.triggered.connect(viewer.rembg_uninstall)
        else:
            act = self.addAction(tr("viewer.rembg_menu_install"))
            act.triggered.connect(viewer.rembg_install)
        act.setEnabled(not busy)   # pip уже идёт — второго запуска не будет
        # выбор модели: запоминается, размер/качество на любой вкус (v0.7.12)
        # Подменю с явным C++-родителем: обёртка от addMenu(строка) в части
        # версий PySide6 теряется сборщику мусора вместе с C++-объектом
        # (воспроизведено на 6.8–6.11, приём из local_viewer, v0.7.16)
        m_model = QMenu(self)
        m_model.setTitle(tr("modules.model_menu"))
        self.addMenu(m_model)
        for model_id, key in rembg_manager.REMBG_MODELS:
            a = m_model.addAction(tr(key))
            a.setCheckable(True)
            a.setChecked(model_id == viewer.rembg_current_model())
            a.triggered.connect(lambda _=False, mid=model_id:
                                viewer.rembg_set_model(mid))

    def _add_server_section(self) -> None:
        """Раздел веб-сервера: панель, запуск/остановка, автостарт.

        Ни один пункт не импортирует ``app.server`` сам по себе: менеджер
        создаётся только при реальном действии (v0.8.0 — ленивость).
        Поэтому порт для заголовка читается из настроек напрямую, а его
        значение по умолчанию (DEFAULT_PORT из app.server.manager)
        продублировано сознательно — импорт нарушил бы ленивость."""
        running = self._main.server_running()
        if running:
            head = self.addAction("🌐 " + tr("server.running",
                                             port=self._main.server_port()))
        else:
            port = QSettings("ImageHunter", "ImageHunter").value(
                "server/port", 8477, type=int)
            head = self.addAction("🌐 " + tr("server.stopped", port=port))
        head.setEnabled(False)
        act_toggle = self.addAction(
            tr("server.stop" if running else "server.run"))
        act_toggle.triggered.connect(self._main.server_toggle)
        act_auto = self.addAction(tr("server.autostart"))
        act_auto.setCheckable(True)
        act_auto.setChecked(QSettings("ImageHunter", "ImageHunter").value(
            "server/autostart", False, type=bool))
        act_auto.toggled.connect(self._main.server_set_autostart)
        act_panel = self.addAction(tr("modules.panel"))
        act_panel.triggered.connect(self._main.show_server_dialog)
