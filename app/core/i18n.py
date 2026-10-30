"""Мини-i18n: русский, английский и китайский языки без Qt-инструментов перевода.

Строки лежат в одном словаре ``_STRINGS``; ``tr(key, **params)`` возвращает
перевод на текущем языке (с запасным падением на русский). Язык выбирается
в интерфейсе (комбобокс в статус-баре), хранится в QSettings; при смене
языка модуль испускает ``signals.changed`` — все окна перетранслируются
на лету, без перезапуска приложения.

Ключи — точечная нотация «окно.назначение» (viewer.open_folder и т.п.).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QLocale, QSettings, Signal

LANGS = ("ru", "en", "zh")

# название каждого языка пишется на самом языке — стандарт переключателей
LANG_ITEMS = (("ru", "Русский"), ("en", "English"), ("zh", "中文"))

_STRINGS: dict[str, dict[str, str]] = {
    # ---------- главное окно ----------
    "tab.pictures": {
        "ru": "📁 Мои картинки", "en": "📁 My Pictures", "zh": "📁 我的图片"},
    "tab.search": {
        "ru": "🌐 Поиск картинок", "en": "🌐 Image Search", "zh": "🌐 图片搜索"},
    "tab.downloads": {
        "ru": "⬇️ Загрузки", "en": "⬇️ Downloads", "zh": "⬇️ 下载"},
    "main.ready": {
        "ru": "Готово: откройте папку на вкладке «Мои картинки» или найдите картинки во вкладке «Поиск».",
        "en": "Ready: open a folder on the “My Pictures” tab or search for images on the “Search” tab.",
        "zh": "就绪：在“我的图片”标签页打开文件夹，或在“图片搜索”标签页搜索图片。"},
    "main.update": {
        "ru": "Обновить", "en": "Update", "zh": "更新"},
    "main.update_tip": {
        "ru": "Проверить обновления и обновиться прямо из программы (Ctrl+U)",
        "en": "Check for updates and update right from the app (Ctrl+U)",
        "zh": "在程序内检查并安装更新 (Ctrl+U)"},
    "menu.help": {
        "ru": "&Справка", "en": "&Help", "zh": "帮助(&H)"},
    "main.check_updates": {
        "ru": "Проверить обновления…", "en": "Check for updates…", "zh": "检查更新…"},
    "main.about_action": {
        "ru": "О программе", "en": "About", "zh": "关于"},
    "main.upd_check_fail": {
        "ru": "Не удалось проверить обновления.\nПроверьте подключение к интернету.",
        "en": "Could not check for updates.\nCheck your internet connection.",
        "zh": "无法检查更新。\n请检查网络连接。"},
    "main.upd_latest": {
        "ru": "У вас последняя версия — {version}",
        "en": "You have the latest version — {version}",
        "zh": "已是最新版本 — {version}"},
    "main.upd_available": {
        "ru": "Доступна новая версия: {remote} (у вас {current}).\n\nОбновить сейчас? Приложение закроется, в отдельном окне запустится установщик,\nпосле завершения Image Hunter откроется сам.",
        "en": "New version available: {remote} (you have {current}).\n\nUpdate now? The app will close, the installer will run in a separate window,\nand Image Hunter will reopen when it finishes.",
        "zh": "发现新版本：{remote}（当前 {current}）。\n\n现在更新吗？应用程序将关闭，安装程序将在单独的窗口中运行，\n完成后 Image Hunter 会自动重新打开。"},
    "main.upd_running": {
        "ru": "Обновление запущено — приложение закрывается…",
        "en": "Update started — the app is closing…",
        "zh": "更新已启动 — 应用程序正在关闭…"},
    "main.upd_no_installer": {
        "ru": "Рядом с программой не найден установщик (папка installer).\nОбновитесь командой: ImageHunter.bat update",
        "en": "Installer not found next to the app (installer folder).\nUpdate with the command: ImageHunter.bat update",
        "zh": "在程序目录中未找到安装程序（installer 文件夹）。\n请使用命令更新：ImageHunter.bat update"},
    "main.about": {
        "ru": "<b>Image Hunter {version}</b><br>Просмотр локальных изображений, поиск картинок в интернете и массовое скачивание.",
        "en": "<b>Image Hunter {version}</b><br>Browse local images, search for pictures online and download them in bulk.",
        "zh": "<b>Image Hunter {version}</b><br>浏览本地图片、在互联网上搜索图片并批量下载。"},
    "main.lang_tip": {
        "ru": "Язык интерфейса", "en": "Interface language", "zh": "界面语言"},
    "main.lang_changed": {
        "ru": "Язык интерфейса: {name}", "en": "Interface language: {name}", "zh": "界面语言：{name}"},
    "main.upd_checking": {
        "ru": "Проверяю обновления…", "en": "Checking for updates…", "zh": "正在检查更新…"},
    "main.upd_title": {
        "ru": "Обновление", "en": "Update", "zh": "更新"},
    "main.collected": {
        "ru": "Собрано ссылок: {n} — скачивание начато.",
        "en": "Collected {n} links — download started.",
        "zh": "已收集 {n} 个链接 — 下载已开始。"},
    "main.save_name_example": {
        "ru": "название", "en": "name", "zh": "名称"},
    # ---------- сохранение картинок (формат выбирается в веб-поиске) ----------
    "main.save_busy": {
        "ru": "Дождитесь завершения текущего сохранения.",
        "en": "Wait for the current save to finish.",
        "zh": "请等待当前保存完成。"},
    "main.save_no_folder": {
        "ru": "Во вкладке «Мои картинки» не открыта папка.\n\nВыбрать папку для сохранения?",
        "en": "No folder is open on the “My Pictures” tab.\n\nChoose a folder to save to?",
        "zh": "“我的图片”标签页中没有打开文件夹。\n\n选择保存文件夹？"},
    "main.save_pick_title": {
        "ru": "Выбрать папку для сохранения", "en": "Choose a folder to save to", "zh": "选择保存文件夹"},
    "main.save_title": {
        "ru": "Сохранить как {fmt}", "en": "Save as {fmt}", "zh": "另存为 {fmt}"},
    "main.save_name_prompt": {
        "ru": "Имя файлов в папке «{folder}»:\nпервый файл — {base}{ext}, дальше {base}-1{ext}, {base}-2{ext}…",
        "en": "File names in the folder “{folder}”:\nfirst file — {base}{ext}, then {base}-1{ext}, {base}-2{ext}…",
        "zh": "文件夹“{folder}”中的文件名：\n第一个文件 — {base}{ext}，之后为 {base}-1{ext}、{base}-2{ext}…"},
    "main.saving": {
        "ru": "Сохраняю ({fmt}): {done} из {total}…",
        "en": "Saving ({fmt}): {done} of {total}…",
        "zh": "正在保存（{fmt}）：{done} / {total}…"},
    "main.save_err": {
        "ru": "Ошибка сохранения — {info}", "en": "Save error — {info}", "zh": "保存错误 — {info}"},
    "main.save_done": {
        "ru": "Готово: {ok} сохранено{tail} → {folder}",
        "en": "Done: {ok} saved{tail} → {folder}",
        "zh": "完成：已保存 {ok} 个{tail} → {folder}"},
    "main.save_done_tail": {
        "ru": ", ошибок: {fail}", "en": ", {fail} failed", "zh": "，失败 {fail} 个"},
    "main.save_warn": {
        "ru": "Сохранено: {ok}, ошибок: {fail}.\nПодробности — в статусной строке.",
        "en": "Saved: {ok}, failed: {fail}.\nDetails are in the status bar.",
        "zh": "已保存：{ok} 个，失败：{fail} 个。\n详情见状态栏。"},
    # ---------- вкладка «Мои картинки» ----------
    "viewer.open_folder": {
        "ru": "📂 Открыть папку…", "en": "📂 Open Folder…", "zh": "📂 打开文件夹…"},
    "viewer.open_folder_tip": {
        "ru": "Выбрать папку с изображениями (Ctrl+O)",
        "en": "Choose a folder with images (Ctrl+O)",
        "zh": "选择图片文件夹 (Ctrl+O)"},
    "viewer.open_dlg": {
        "ru": "Папка с изображениями", "en": "Folder with images", "zh": "图片文件夹"},
    "viewer.thumbs": {
        "ru": "🖼 Миниатюры", "en": "🖼 Thumbnails", "zh": "🖼 缩略图"},
    "viewer.thumbs_tip": {
        "ru": "Включено: предпросмотр грузится только для видимой части списка —\nсетевой диск не читает все файлы подряд.\nВыключено: миниатюры не загружаются вовсе (для очень медленных дисков).",
        "en": "On: previews load only for the visible part of the list —\nthe network drive is not read file by file.\nOff: no thumbnails at all (for very slow drives).",
        "zh": "开启：仅为列表可见部分加载预览 —\n不会逐个读取网络磁盘上的所有文件。\n关闭：完全不加载缩略图（适用于非常慢的磁盘）。"},
    "viewer.prev_tip": {
        "ru": "Предыдущая (Left)", "en": "Previous (Left)", "zh": "上一张 (Left)"},
    "viewer.next_tip": {
        "ru": "Следующая (Right)", "en": "Next (Right)", "zh": "下一张 (Right)"},
    "viewer.zoom_out_tip": {
        "ru": "Уменьшить", "en": "Zoom out", "zh": "缩小"},
    "viewer.actual_tip": {
        "ru": "Реальный размер", "en": "Actual size", "zh": "实际大小"},
    "viewer.fit_tip": {
        "ru": "Вписать в окно", "en": "Fit to window", "zh": "适应窗口"},
    "viewer.zoom_in_tip": {
        "ru": "Увеличить", "en": "Zoom in", "zh": "放大"},
    "viewer.reveal": {
        "ru": "🗂 Показать в проводнике", "en": "🗂 Show in Explorer", "zh": "🗂 在文件管理器中显示"},
    "viewer.reveal_tip": {
        "ru": "Открыть текущую папку в Проводнике",
        "en": "Open the current folder in the file manager",
        "zh": "在文件管理器中打开当前文件夹"},
    "viewer.search_ph": {
        "ru": "🔍 Поиск по папке и подпапкам…",
        "en": "🔍 Search folder and subfolders…",
        "zh": "🔍 搜索文件夹及子文件夹…"},
    "viewer.search_tip": {
        "ru": "Введите часть имени файла — найдутся все картинки в текущей папке\n"
              "и всех подпапках. Без масок и звёздочек, регистр не важен. Esc — сброс.\n"
              "Потяните мышью за левый или правый край поля, чтобы сделать его шире или уже.",
        "en": "Type part of a file name — all images in the current folder\n"
              "and its subfolders will be found. No masks or stars, case-insensitive. Esc — reset.\n"
              "Drag the left or right edge of the box to make it wider or narrower.",
        "zh": "输入文件名的一部分 — 将找到当前文件夹\n"
              "及所有子文件夹中的图片。无需通配符，不区分大小写。Esc — 重置。\n"
              "拖动输入框的左或右边缘，可以调宽或调窄。"},
    "viewer.dnd_tip": {
        "ru": "Выделите картинки (Ctrl/Shift) и перетащите их мышью в Проводник,\nпочту или другое приложение — передаются оригинальные файлы.",
        "en": "Select images (Ctrl/Shift) and drag them into Explorer,\ne-mail or any other app — the original files are passed on.",
        "zh": "选中图片（Ctrl/Shift）后拖动到文件管理器、\n邮件或其他应用程序 — 传递的是原始文件。"},
    "viewer.pick": {
        "ru": "Выберите диск или папку в дереве слева, либо «Открыть папку…» (Ctrl+O)",
        "en": "Pick a drive or folder in the tree on the left, or use “Open Folder…” (Ctrl+O)",
        "zh": "在左侧树中选择磁盘或文件夹，或使用“打开文件夹…” (Ctrl+O)"},
    "viewer.drives": {
        "ru": "Диски и папки", "en": "Drives and folders", "zh": "磁盘与文件夹"},
    "viewer.refresh_tip": {
        "ru": "Обновить список дисков и папок (например, после подключения флешки)",
        "en": "Refresh the list of drives and folders (e.g. after plugging in a USB stick)",
        "zh": "刷新磁盘和文件夹列表（例如插入 U 盘后）"},
    "viewer.no_images": {
        "ru": "В этой папке нет изображений", "en": "No images in this folder", "zh": "此文件夹中没有图片"},
    "viewer.pick_first": {
        "ru": "Сначала выберите папку в дереве слева или «Открыть папку…»",
        "en": "First pick a folder in the tree on the left or use “Open Folder…”",
        "zh": "请先在左侧树中选择文件夹，或使用“打开文件夹…”"},
    "viewer.searching": {
        "ru": "Поиск «{q}»…", "en": "Searching “{q}”…", "zh": "正在搜索“{q}”…"},
    "viewer.searching_found": {
        "ru": "Поиск «{q}»… найдено: {n}", "en": "Searching “{q}”… found: {n}", "zh": "正在搜索“{q}”… 已找到：{n}"},
    "viewer.search_done": {
        "ru": "Поиск «{q}»: {n} файлов{tail}", "en": "Search “{q}”: {n} files{tail}", "zh": "搜索“{q}”：{n} 个文件{tail}"},
    "viewer.search_trunc": {
        "ru": " (показаны первые 5000)", "en": " (first 5000 shown)", "zh": "（仅显示前 5000 个）"},
    "viewer.cant_open": {
        "ru": "Не удалось открыть:\n{err}", "en": "Could not open:\n{err}", "zh": "无法打开：\n{err}"},
    "viewer.of": {
        "ru": "{i} из {n}", "en": "{i} of {n}", "zh": "第 {i} 张，共 {n} 张"},
    "viewer.home": {
        "ru": "🏠 Домой", "en": "🏠 Home", "zh": "🏠 主目录"},
    "viewer.pictures": {
        "ru": "🖼 Изображения", "en": "🖼 Pictures", "zh": "🖼 图片"},
    "viewer.drive_root": {
        "ru": "Диск /", "en": "Drive /", "zh": "磁盘 /"},
    "viewer.free_space": {
        "ru": "Свободно: {free} из {total}", "en": "Free: {free} of {total}", "zh": "可用：{free} / {total}"},
    "unit.b": {"ru": "Б", "en": "B", "zh": "B"},
    "unit.kb": {"ru": "КБ", "en": "KB", "zh": "KB"},
    "unit.mb": {"ru": "МБ", "en": "MB", "zh": "MB"},
    "unit.gb": {"ru": "ГБ", "en": "GB", "zh": "GB"},
    "unit.tb": {"ru": "ТБ", "en": "TB", "zh": "TB"},
    # ---------- вкладка поиска ----------
    "ws.query_ph": {
        "ru": "Поисковый запрос… (Enter — искать)",
        "en": "Search query… (Enter to search)",
        "zh": "搜索关键词…（回车搜索）"},
    "ws.engine_tip": {
        "ru": "Поисковая система", "en": "Search engine", "zh": "搜索引擎"},
    "ws.find": {
        "ru": "Найти", "en": "Search", "zh": "搜索"},
    "ws.collect": {
        "ru": "📋 Собрать ссылки", "en": "📋 Collect links", "zh": "📋 收集链接"},
    "ws.collect_tip": {
        "ru": "Собрать ссылки на картинки (превью) с текущей страницы выдачи\nи отправить их на вкладку «Загрузки»",
        "en": "Collect image (preview) links from the current results page\nand send them to the “Downloads” tab",
        "zh": "收集当前结果页面上的图片（预览）链接，\n并发送到“下载”标签页"},
    "ws.download_checked": {
        "ru": "⬇ Скачать отмеченные", "en": "⬇ Download checked", "zh": "⬇ 下载已选"},
    "ws.download_checked_tip": {
        "ru": "На плитках выдачи есть оранжевые чекбоксы: отметьте нужные картинки —\nздесь появится счётчик, а по кнопке скачаются большие оригиналы",
        "en": "The results have orange checkboxes: mark the images you need —\na counter appears here and the button downloads the full-size originals",
        "zh": "结果卡片上有橙色复选框：勾选需要的图片 —\n此处会显示计数，点击按钮将下载大尺寸原图"},
    "ws.save": {
        "ru": "💾 Сохранить в папку", "en": "💾 Save to folder", "zh": "💾 保存到文件夹"},
    "ws.save_tip": {
        "ru": "Отмеченные плитки перекодируются в выбранный формат и сохраняются в папку,\nоткрытую во вкладке «Мои картинки»: название{ext}, название-1{ext}…\nИмя спросит при сохранении. Если папка не открыта — предложит выбрать.",
        "en": "Checked tiles are converted to the selected format and saved to the folder\nopen on the “My Pictures” tab: name{ext}, name-1{ext}…\nThe name is asked on save. If no folder is open, you will be asked to pick one.",
        "zh": "勾选的卡片将转换为所选格式，并保存到“我的图片”标签页\n当前打开的文件夹：名称{ext}、名称-1{ext}…\n保存时会询问名称。若未打开文件夹，会提示选择。"},
    "ws.format_tip": {
        "ru": "Формат сохранения отмеченных картинок",
        "en": "Format for saving the checked images",
        "zh": "已选图片的保存格式"},
    "ws.clear": {
        "ru": "✕ Снять отметки", "en": "✕ Clear checks", "zh": "✕ 取消选择"},
    "ws.clear_tip": {
        "ru": "Снять все оранжевые галочки с плиток выдачи одним нажатием",
        "en": "Uncheck all orange checkboxes on the results with one click",
        "zh": "一键取消结果卡片上的所有橙色勾选"},
    "ws.no_checked": {
        "ru": "Нет отмеченных картинок.\n\nОтметьте оранжевыми галочками плитки с нужными картинками "
        "прямо на странице выдачи — на кнопке появится счётчик.",
        "en": "No images are checked.\n\nMark the tiles you need with the orange checkboxes "
        "right on the results page — a counter will appear on the button.",
        "zh": "没有勾选的图片。\n\n请在结果页面上用橙色复选框勾选需要的卡片 — 按钮上会显示计数。"},
    "ws.no_links": {
        "ru": "Ссылки не найдены.\n\nПодсказки:\n• дождитесь полной загрузки выдачи;\n"
        "• прокрутите страницу вниз, чтобы подгрузились миниатюры;\n"
        "• если Яндекс показывает капчу — введите её прямо здесь, во встроенном браузере.",
        "en": "No links found.\n\nTips:\n• wait until the results page fully loads;\n"
        "• scroll down so thumbnails load;\n"
        "• if Yandex shows a captcha — enter it right here, in the built-in browser.",
        "zh": "未找到链接。\n\n提示：\n• 请等待结果页面完全加载；\n"
        "• 向下滚动页面以加载缩略图；\n"
        "• 如果 Yandex 显示验证码 — 请直接在内置浏览器中输入。"},
    # ---------- вкладка «Загрузки» ----------
    "dl.folder": {"ru": "Папка:", "en": "Folder:", "zh": "文件夹："},
    "dl.change": {"ru": "Изменить…", "en": "Change…", "zh": "更改…"},
    "dl.open": {"ru": "Открыть", "en": "Open", "zh": "打开"},
    "dl.open_tip": {
        "ru": "Открыть папку в Проводнике", "en": "Open the folder in the file manager", "zh": "在文件管理器中打开该文件夹"},
    "dl.paste_ph": {
        "ru": "Вставьте прямые ссылки на картинки — по одной в строке…\nСсылки с вкладки «Поиск картинок» попадают сюда автоматически.",
        "en": "Paste direct image links — one per line…\nLinks from the “Image Search” tab arrive here automatically.",
        "zh": "粘贴图片直链 — 每行一个…\n“图片搜索”标签页的链接会自动填入此处。"},
    "dl.download": {
        "ru": "⬇ Скачать ссылки", "en": "⬇ Download links", "zh": "⬇ 下载链接"},
    "dl.stop": {"ru": "■ Остановить", "en": "■ Stop", "zh": "■ 停止"},
    "dl.stop_tip": {
        "ru": "Отменить всё, что ещё не начало скачиваться",
        "en": "Cancel everything that has not started downloading yet",
        "zh": "取消所有尚未开始下载的任务"},
    "dl.h_link": {"ru": "Ссылка", "en": "Link", "zh": "链接"},
    "dl.h_status": {"ru": "Статус", "en": "Status", "zh": "状态"},
    "dl.h_file": {"ru": "Файл / ошибка", "en": "File / error", "zh": "文件 / 错误"},
    "dl.summary_ready": {
        "ru": "Готово: {ok} скачано, {fail} ошибок",
        "en": "Ready: {ok} downloaded, {fail} errors",
        "zh": "就绪：已下载 {ok} 个，失败 {fail} 个"},
    "dl.status_queue": {"ru": "В очереди", "en": "Queued", "zh": "排队中"},
    "dl.status_done": {"ru": "Скачано", "en": "Downloaded", "zh": "已下载"},
    "dl.status_error": {"ru": "Ошибка", "en": "Error", "zh": "错误"},
    "dl.status_cancel": {"ru": "Отменено", "en": "Cancelled", "zh": "已取消"},
    "dl.batch_done": {
        "ru": "Партия завершена: {ok} скачано, {fail} ошибок. Папка: {dir}",
        "en": "Batch finished: {ok} downloaded, {fail} errors. Folder: {dir}",
        "zh": "批次完成：已下载 {ok} 个，失败 {fail} 个。文件夹：{dir}"},
    "dl.summary": {
        "ru": "Всего в списке: {n}  •  скачано: {ok}  •  ошибок: {fail}",
        "en": "Total in list: {n}  •  downloaded: {ok}  •  errors: {fail}",
        "zh": "列表共计：{n}  •  已下载：{ok}  •  失败：{fail}"},
    "dl.paste_first": {
        "ru": "Сначала вставьте ссылки в поле слева.",
        "en": "Paste links into the box on the left first.",
        "zh": "请先将链接粘贴到左侧输入框。"},
    "dl.no_new": {
        "ru": "Новых ссылок нет: они уже скачивались в этой сессии или не являются http(s)-ссылками.",
        "en": "No new links: they were already downloaded in this session or are not http(s) links.",
        "zh": "没有新链接：它们在本会话中已下载过，或不是 http(s) 链接。"},
    "dl.added": {
        "ru": "Добавлено {added} из {total} — остальные уже были в очереди.",
        "en": "Added {added} of {total} — the rest were already queued.",
        "zh": "已添加 {added}/{total} — 其余已在队列中。"},
    "dl.pick_folder": {
        "ru": "Папка для сохранения", "en": "Folder to save to", "zh": "保存文件夹"},
}

# кэш текущего языка: читается на каждый tr() — QSettings трогаем один раз
_current: str | None = None


class _Signals(QObject):
    """Испускается при смене языка — все окна подписываются на перетрансляцию."""

    changed = Signal(str)


signals = _Signals()


def system_lang() -> str:
    """Язык по умолчанию из локали системы: zh* → 中文, ru* → русский, иначе English."""
    code = (QLocale.system().name() or "").split("_")[0].lower()
    if code.startswith("zh"):
        return "zh"
    if code == "ru":
        return "ru"
    return "en"


def current_lang() -> str:
    """Текущий язык: сохранённый в настройках, иначе — из локали системы."""
    global _current
    if _current is None:
        stored = str(QSettings("ImageHunter", "ImageHunter").value("ui/lang", "") or "")
        _current = stored if stored in LANGS else system_lang()
    return _current


def set_lang(code: str, persist: bool = True) -> None:
    """Сменить язык интерфейса: запомнить и перетранслировать все окна."""
    global _current
    if code not in LANGS:
        return
    if persist:
        QSettings("ImageHunter", "ImageHunter").setValue("ui/lang", code)
    if code != current_lang():
        _current = code
        signals.changed.emit(code)
    else:
        _current = code
        signals.changed.emit(code)   # подписчики обновятся и без смены значения


def lang_name(code: str) -> str:
    """«Русский» / «English» / «中文» для указанного кода."""
    for item_code, name in LANG_ITEMS:
        if item_code == code:
            return name
    return code


def tr(key: str, **params) -> str:
    """Перевод ключа на текущий язык (fallback: русский → сам ключ)."""
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(current_lang()) or entry.get("ru") or key
    if params:
        try:
            text = text.format(**params)
        except (KeyError, IndexError, ValueError):
            pass
    return text
