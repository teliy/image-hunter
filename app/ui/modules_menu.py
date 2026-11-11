"""Меню «Модули» в строке меню: настройки, установка и удаление модулей.

Единое место управления подключаемыми модулями — слева от «Справки»
(v0.8.2). Внутри два раздела:

* **Удаление фона (rembg)** — установка/удаление пакета и выбор модели;
  сами действия делегированы вьюеру «Моих картинок» (:class:`app.ui.
  local_viewer.LocalViewer`): он владеет фоновыми задачами pip, guard-ом
  от двойного запуска и всей репортёрикой в статус/журнал с v0.7.12;
* **Водяные знаки (Florence-2 + LaMa/IOPaint)** — установка/удаление
  модуля и выбор детектора; делегировано вьюеру тем же способом (v0.8.11);
* **Веб-сервер (доступ с телефона)** — панель управления (порт, токен,
  QR-код, «только просмотр»), запуск/остановка и автостарт с программой;
  менеджер создаётся лениво, как и раньше: пока модуль не тронули,
  ``app.server`` не импортируется и ничего не слушает (v0.8.0).

У установленных модулей под заголовком-состоянием — недоступные строки
со справкой о версиях (v0.8.17): пакет rembg; для водяных знаков — весь
конвейер (iopaint, transformers, timm) и модели (ревизия Florence-2 в
кэше HF, размер big-lama) — ровно то, что «Обновить модуль» сверяет с
PyPI/Hugging Face (v0.8.15).

Внизу — «Перезагрузить Image Hunter» (v0.8.17): новый экземпляр
подхватывает обновлённые версии модулей (подсказка после «Обновить»,
v0.8.15, больше не требует закрывать программу руками). Пока pip
ставит/обновляет модуль, пункт запрещён — перезагрузка оборвала бы
установку.

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
from app.ui import rembg_manager, watermark_manager


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
        self._add_watermark_section()
        self.addSeparator()
        self._add_server_section()
        self._add_restart_section()

    def _add_info_line(self, text: str) -> None:
        """Недоступная строка-справка (заголовки-состояния, версии).

        Впредь и заголовки разделов — через этот помощник."""
        act = self.addAction(text)
        act.setEnabled(False)   # справка, не команда

    def _add_rembg_section(self) -> None:
        """Раздел удаления фона: состояние, версии, установка/удаление, модель."""
        viewer = self._main.local
        installed = rembg_manager.is_installed()
        self._add_info_line(tr("modules.rembg_header", state=tr(
            "modules.installed" if installed else "modules.not_installed")))
        busy = viewer.rembg_is_busy()
        if installed:
            # версии установленного модуля (v0.8.17) — пакет rembg
            self._add_info_line(tr("modules.versions", list="rembg " + (
                rembg_manager.installed_version()
                or tr("modules.version_unknown"))))
            act = self.addAction(tr("viewer.rembg_menu_uninstall"))
            act.triggered.connect(viewer.rembg_uninstall)
            # обновление установленного модуля: PyPI против локальной версии
            # (v0.8.15); пока pip/обработка идут — второго запуска не будет
            upd = self.addAction(tr("viewer.rembg_menu_update"))
            upd.triggered.connect(viewer.rembg_update)
            upd.setEnabled(not busy)
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

    def _add_watermark_section(self) -> None:
        """Раздел водяных знаков: состояние, версии, установка/удаление, детектор."""
        viewer = self._main.local
        installed = watermark_manager.is_installed()
        self._add_info_line(tr("modules.wm_header", state=tr(
            "modules.installed" if installed else "modules.not_installed")))
        busy = viewer.wm_is_busy()
        if installed:
            # версии конвейера (v0.8.17): пакеты + модели (ревизия
            # Florence-2 в кэше HF, размер big-lama) — то, с чем сверяется
            # «Обновить модуль» (v0.8.15)
            pkgs = ", ".join(
                f"{n} {watermark_manager.installed_version(n) or tr('modules.version_unknown')}"
                for n in watermark_manager.PIPELINE_PACKAGES)
            self._add_info_line(tr("modules.versions", list=pkgs))
            self._add_info_line(tr("modules.models",
                                   list=self._wm_models_line(viewer)))
            act = self.addAction(tr("viewer.wm_menu_uninstall"))
            act.triggered.connect(viewer.wm_uninstall)
            # обновление установленного модуля: PyPI/Hugging Face против
            # локальных версий (v0.8.15); пока pip/обработка идут — запрет
            upd = self.addAction(tr("viewer.wm_menu_update"))
            upd.triggered.connect(viewer.wm_update)
            upd.setEnabled(not busy)
        else:
            act = self.addAction(tr("viewer.wm_menu_install"))
            act.triggered.connect(viewer.wm_install)
        act.setEnabled(not busy)   # pip уже идёт — второго запуска не будет
        # выбор детектора: base — резвый, large — точнее (v0.8.11);
        # подменю с явным C++-родителем — приём из _add_rembg_section
        m_model = QMenu(self)
        m_model.setTitle(tr("viewer.wm_model_menu"))
        self.addMenu(m_model)
        for model_id, key in watermark_manager.FLORENCE_MODELS:
            a = m_model.addAction(tr(key))
            a.setCheckable(True)
            a.setChecked(model_id == viewer.wm_current_model())
            a.triggered.connect(lambda _=False, mid=model_id:
                                viewer.wm_set_model(mid))

    def _wm_models_line(self, viewer) -> str:
        """Состояние моделей конвейера для строки «Модели» (v0.8.17).

        Florence-2: у модели версии нет — её версия это ревизия (commit)
        в кэше HF, короткий хвост sha; не скачана — так и написано (модель
        докачается при первом удалении знаков). big-lama: размер файла;
        скачивается при установке (v0.8.13), но файл могли удалить руками.
        """
        repo = viewer.wm_current_model()
        short = repo.split("/")[-1]
        sha = watermark_manager.florence_revision(repo)
        florence = (f"{short} rev {sha[:7]}" if sha else
                    f"{short} {tr('modules.model_not_downloaded')}")
        size = watermark_manager.lama_size()
        lama = (tr("modules.size_mb", mb=size >> 20) if size
                else f"big-lama {tr('modules.model_not_downloaded')}")
        return f"{florence}, {lama}"

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

    def _add_restart_section(self) -> None:
        """«Перезагрузить Image Hunter» внизу меню (v0.8.17).

        Новый экземпляр стартует с задержкой (updates.start_restart), этот
        закрывается — после перезагрузки программа подхватывает
        обновлённые версии модулей (подсказка после «Обновить модуль»,
        v0.8.15). Пока pip ставит/обновляет модуль, пункт запрещён:
        перезагрузка оборвала бы установку.
        """
        self.addSeparator()
        act = self.addAction(tr("modules.restart"))
        act.triggered.connect(self._main.restart_app)
        viewer = self._main.local
        act.setEnabled(not (viewer.rembg_is_busy() or viewer.wm_is_busy()))
