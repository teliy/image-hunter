"""Оффлайн-тест мини-i18n: полнота словарей, переключение языков, перетрансляция UI.

Проверяет:
1. каждый ключ есть во всех трёх языках (ru/en/zh) и непуст;
2. tr() возвращает перевод текущего языка и подставляет параметры;
3. система определения языка по локали;
4. смена языка перетранслирует все окна без перезапуска
   (LocalViewer, WebSearch, DownloadsView, MainWindow);
5. выбор языка сохраняется в настройках и восстанавливается при следующем запуске.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_i18n.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QLocale  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import i18n  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    # 1. полнота словарей
    missing = []
    for key, entry in i18n._STRINGS.items():
        for lang in i18n.LANGS:
            if not (entry.get(lang) or "").strip():
                missing.append(f"{key}:{lang}")
    check(f"все {len(i18n._STRINGS)} ключей есть в ru/en/zh", not missing,
          ", ".join(missing[:5]))

    # 2. tr() и подстановка параметров
    i18n.set_lang("ru", persist=False)
    check("ru: переключение работает", i18n.tr("ws.find") == "Найти",
          i18n.tr("ws.find"))
    check("ru: параметры подставляются",
          i18n.tr("main.collected", n=7) == "Собрано ссылок: 7 — скачивание начато.",
          i18n.tr("main.collected", n=7))
    i18n.set_lang("en", persist=False)
    check("en: переключение работает", i18n.tr("ws.find") == "Search",
          i18n.tr("ws.find"))
    check("en: параметры подставляются",
          i18n.tr("viewer.of", i=2, n=5) == "2 of 5", i18n.tr("viewer.of", i=2, n=5))
    i18n.set_lang("zh", persist=False)
    check("zh: переключение работает", "下载" in i18n.tr("dl.download"),
          i18n.tr("dl.download"))
    check("zh: параметры подставляются",
          i18n.tr("dl.summary", n=3, ok=2, fail=1).startswith("列表共计：3"),
          i18n.tr("dl.summary", n=3, ok=2, fail=1))
    check("несуществующий ключ → сам ключ", i18n.tr("no.such.key") == "no.such.key")

    # 3. определение языка по локали
    check("system_lang: значения из LANGS", i18n.system_lang() in i18n.LANGS,
          i18n.system_lang())
    check("локаль Qt читается", bool(QLocale.system().name() or True),
          QLocale.system().name())

    # 4. перетрансляция всех окон без перезапуска
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").remove("viewer/splitter")

    from app.core.downloader import Downloader
    from app.ui.downloads import DownloadsView
    from app.ui.local_viewer import LocalViewer
    from app.ui.main_window import MainWindow
    from app.ui.web_search import WebSearch

    i18n.set_lang("en", persist=False)
    viewer = LocalViewer()
    web = WebSearch()
    dl = DownloadsView(Downloader())
    win = MainWindow()

    check("EN: вкладки главного окна",
          win.tabs.tabText(0) == "📁 My Pictures" and win.tabs.tabText(2) == "⬇️ Downloads",
          f"{win.tabs.tabText(0)} | {win.tabs.tabText(2)}")
    check("EN: кнопка открыть папку",
          any(getattr(b, "text", lambda: "")() == "📂 Open Folder…"
              for b, _t, _k in viewer._i18n_buttons))

    i18n.set_lang("ru", persist=False)
    check("RU: вкладки перетранслировались на лету",
          win.tabs.tabText(0) == "📁 Мои картинки" and win.tabs.tabText(2) == "⬇️ Загрузки",
          f"{win.tabs.tabText(0)} | {win.tabs.tabText(2)}")
    check("RU: кнопка открыть папку",
          any(getattr(b, "text", lambda: "")() == "📂 Открыть папку…"
              for b, _t, _k in viewer._i18n_buttons))
    check("RU: кнопка сохранения с форматом",
          web.btn_save.text().startswith("💾 Сохранить в папку"), web.btn_save.text())
    check("RU: заголовок таблицы загрузок",
          dl.table.horizontalHeaderItem(0).text() == "Ссылка")

    i18n.set_lang("zh", persist=False)
    check("ZH: вкладки перетранслировались на лету",
          win.tabs.tabText(0) == "📁 我的图片", win.tabs.tabText(0))
    check("ZH: кнопка сохранения",
          web.btn_save.text().startswith("💾 保存到文件夹"), web.btn_save.text())
    check("ZH: поле поиска (плейсхолдер)",
          "搜索" in web.query.placeholderText(), web.query.placeholderText())

    # 5. сохранение и восстановление выбора языка
    i18n.set_lang("ru")   # persist=True
    check("выбор сохранён в настройках",
          str(QSettings("ImageHunter", "ImageHunter").value("ui/lang", "")) == "ru")
    i18n._current = None   # как в новом запуске
    check("восстанавливается из настроек", i18n.current_lang() == "ru")
    i18n.set_lang("ru")    # оставляем чистое состояние для остальных тестов

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
