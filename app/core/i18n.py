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
    "tab.log": {
        "ru": "📜 Журнал", "en": "📜 Log", "zh": "📜 日志"},
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
        "ru": "Доступна новая версия: {remote} (у вас {current}).\n\nОбновить сейчас? Приложение закроется, обновление пройдёт в фоне без единого окна,\nпосле завершения Image Hunter откроется сам.",
        "en": "New version available: {remote} (you have {current}).\n\nUpdate now? The app will close, the update runs in the background with no windows at all,\nand Image Hunter reopens when it finishes.",
        "zh": "发现新版本：{remote}（当前 {current}）。\n\n现在更新吗？应用程序将关闭，更新将在后台完全无窗口地运行，\n完成后 Image Hunter 会自动重新打开。"},
    "main.upd_running": {
        "ru": "Обновление выполняется в фоне — без единого окна терминала.\n\nПриложение сейчас закроется и запустится само через 1–2 минуты.\nЕсли обновление не удастся, появится обычный диалог с ошибкой и путём к журналу (%TEMP%\\ImageHunter_update.log).",
        "en": "The update runs in the background — with no terminal windows at all.\n\nThe app will close now and relaunch by itself in 1–2 minutes.\nIf the update fails, a normal dialog with the error and the log path (%TEMP%\\ImageHunter_update.log) will appear.",
        "zh": "更新将在后台运行 — 全程不显示任何终端窗口。\n\n应用程序现在将关闭，并在 1–2 分钟后自动重新启动。\n如果更新失败，将弹出普通对话框，显示错误信息和日志路径（%TEMP%\\ImageHunter_update.log）。"},
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
    "viewer.checker_tip": {
        "ru": "Размер клеток фона-«шахматки»: под прозрачными картинками (PNG, GIF,\n"
              "WebP…) рисуются белые и серые квадраты — так видно, где картинка\n"
              "прозрачна. Тяните ползунок, чтобы укрупнить или измельчить клетки.",
        "en": "Checkerboard cell size: behind transparent images (PNG, GIF, WebP…)\n"
              "white and gray squares are drawn — so you can see where the image\n"
              "is transparent. Drag the slider for larger or smaller squares.",
        "zh": "棋盘格底纹的方格大小：透明图片（PNG、GIF、WebP…）下方会绘制\n"
              "白色与灰色方格，便于看清图片的透明区域。拖动滑块可放大或缩小方格。"},
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
        "ru": "Выделите картинки (Ctrl/Shift) и перетащите их мышью в Проводник,\n"
              "почту или другое приложение — передаются оригинальные файлы.\n"
              "Если тянуть не получается: Ctrl+C (или правый клик → «Копировать\n"
              "выделенные файлы»), затем вставьте их там, где нужно (Ctrl+V).\n"
              "Двойной клик по имени файла — переименовать его, по самой\n"
              "картинке — открыть в системном просмотрщике.",
        "en": "Select images (Ctrl/Shift) and drag them into Explorer,\n"
              "e-mail or any other app — the original files are passed on.\n"
              "If dragging does not work: Ctrl+C (or right-click → “Copy\n"
              "selected files”), then paste them where needed (Ctrl+V).\n"
              "Double-click a file's name to rename it; double-click the\n"
              "picture itself to open it in the system viewer.",
        "zh": "选中图片（Ctrl/Shift）后拖动到文件管理器、\n"
              "邮件或其他应用程序 — 传递的是原始文件。\n"
              "如果无法拖动：Ctrl+C（或右键 →“复制所选文件”），\n"
              "然后在需要的地方粘贴 (Ctrl+V)。\n"
              "双击文件名可重命名；双击图片本身\n"
              "将在系统查看器中打开。"},
    "viewer.tree_drop_tip": {
        "ru": "Перетащите выделенные в ленте файлы на папку или диск — они\n"
              "перенесутся туда (файл над свёрнутой папкой сам её раскроет).",
        "en": "Drop files selected in the strip onto a folder or drive —\n"
              "they will be moved there (holding a file over a collapsed\n"
              "folder expands it).",
        "zh": "将缩略图条中选中的文件拖到文件夹或磁盘上即可移动；\n"
              "悬停在折叠的文件夹上会自动展开。"},
    "viewer.ctx_open": {
        "ru": "Открыть", "en": "Open", "zh": "打开"},
    "viewer.ctx_copy": {
        "ru": "Копировать выделенные файлы", "en": "Copy selected files", "zh": "复制所选文件"},
    "viewer.ctx_copy_tip": {
        "ru": "Файлы лягут в буфер обмена как обычные скопированные файлы —\n"
              "можно вставить в Проводник или браузер (Ctrl+V)",
        "en": "The files go to the clipboard as normal copied files —\n"
              "paste them into Explorer or a browser (Ctrl+V)",
        "zh": "文件将以常规复制方式放入剪贴板 —\n可粘贴到文件管理器或浏览器 (Ctrl+V)"},
    "viewer.ctx_rename": {
        "ru": "✏️ Переименовать", "en": "✏️ Rename", "zh": "✏️ 重命名"},
    "viewer.ctx_rename_tip": {
        "ru": "F2 или двойной клик по имени файла — переименовать, не выходя\n"
              "из программы. Двойной клик по самой картинке по-прежнему\n"
              "открывает её в системном просмотрщике.",
        "en": "F2 or double-click the file's name to rename it without leaving\n"
              "ImageHunter. Double-clicking the picture itself still opens\n"
              "it in the system viewer.",
        "zh": "按 F2 或双击文件名即可重命名，无需离开程序。\n双击图片本身仍会在系统查看器中打开。"},
    "viewer.rename_nothing": {
        "ru": "Нечего переименовывать — выберите картинку в ленте",
        "en": "Nothing to rename — pick an image in the strip first",
        "zh": "没有可重命名的内容 — 请先在缩略图条中选择图片"},
    "viewer.rename_busy": {
        "ru": "Предыдущее переименование ещё не завершилось — секунду",
        "en": "The previous rename has not finished yet — one moment",
        "zh": "上一次重命名尚未完成 — 请稍候"},
    "viewer.rename_progress": {
        "ru": "Переименовываю «{name}»…", "en": "Renaming “{name}”…", "zh": "正在重命名“{name}”…"},
    "viewer.rename_invalid": {
        "ru": "Такое имя файла не подходит: пустое, с точкой или пробелом на конце\n"
              "либо с символами \\ / : * ? \" < > |",
        "en": "This file name will not work: empty, ending with a dot or space,\n"
              "or containing \\ / : * ? \" < > |",
        "zh": "该文件名不可用：为空、以点或空格结尾，\n或包含 \\ / : * ? \" < > | 字符"},
    "viewer.rename_done": {
        "ru": "Переименовано: {old} → {new}",
        "en": "Renamed: {old} → {new}",
        "zh": "已重命名：{old} → {new}"},
    "viewer.rename_err": {
        "ru": "Не удалось переименовать «{name}»: {err}",
        "en": "Could not rename “{name}”: {err}",
        "zh": "无法重命名“{name}”：{err}"},
    "viewer.ctx_delete": {
        "ru": "🗑 Удалить", "en": "🗑 Delete", "zh": "🗑 删除"},
    "viewer.ctx_delete_tip": {
        "ru": "Delete — переместить выделенные файлы в корзину.\n"
              "На дисках без корзины (сетевые, часть съёмных)\n"
              "программа предложит удалить их окончательно.",
        "en": "Delete — move the selected files to the Recycle Bin.\n"
              "On drives without a Recycle Bin (network, some removable)\n"
              "ImageHunter offers to delete them permanently.",
        "zh": "Delete — 将所选文件移入回收站。\n"
              "在没有回收站的磁盘上（网络磁盘、部分移动设备），\n"
              "程序会建议永久删除。"},
    "viewer.del_title": {
        "ru": "Удаление файлов", "en": "Delete files", "zh": "删除文件"},
    "viewer.del_confirm": {
        "ru": "Переместить в корзину выбранные файлы ({n} шт.)?\n\n"
              "Их можно будет восстановить из корзины Проводника.\n"
              "Если на диске нет корзины, программа предложит\n"
              "удалить их окончательно.",
        "en": "Move the selected files ({n}) to the Recycle Bin?\n\n"
              "You can restore them from Explorer's Recycle Bin.\n"
              "If the drive has no Recycle Bin, ImageHunter will offer\n"
              "to delete them permanently.",
        "zh": "将所选文件（{n} 个）移入回收站？\n\n"
              "之后可以在资源管理器的回收站中还原。\n"
              "如果磁盘没有回收站，程序会建议永久删除。"},
    "viewer.del_nothing": {
        "ru": "Нечего удалять — выделите картинки в ленте",
        "en": "Nothing to delete — select images in the strip first",
        "zh": "没有可删除的内容 — 请先在缩略图条中选择图片"},
    "viewer.delete_busy": {
        "ru": "Удаляю файлы…", "en": "Deleting files…", "zh": "正在删除文件…"},
    "viewer.folder_reading": {
        "ru": "Читаю папку…", "en": "Reading folder…", "zh": "正在读取文件夹…"},
    "viewer.del_done": {
        "ru": "Удалено в корзину: {n}", "en": "Moved to Recycle Bin: {n}", "zh": "已移入回收站：{n}"},
    "viewer.del_done_err": {
        "ru": "Удалено: {n}, не удалось: {m} (причины в журнале)",
        "en": "Deleted: {n}, failed: {m} (reasons in the Log)",
        "zh": "已删除：{n}，失败：{m}（原因见日志）"},
    "viewer.del_missing": {
        "ru": "файл не найден", "en": "file not found", "zh": "未找到文件"},
    "viewer.del_failed": {
        "ru": "не удалось переместить в корзину (проверьте права доступа или наличие корзины на диске)",
        "en": "could not move to the Recycle Bin (check permissions or whether the drive has one)",
        "zh": "无法移入回收站（请检查权限或该磁盘是否有回收站）"},
    "viewer.del_denied_hint": {
        "ru": "нет прав доступа: папка смонтирована от другого пользователя "
              "(davfs2 — uid/gid и file_mode в davfs2.conf/fstab)?",
        "en": "permission denied: the folder is mounted by another user "
              "(davfs2 — check uid/gid and file_mode in davfs2.conf/fstab)?",
        "zh": "没有访问权限：文件夹由其他用户挂载（davfs2 — 请检查 davfs2.conf/fstab 中的 uid/gid 与 file_mode）"},
    "viewer.del_perm_title": {
        "ru": "На диске нет корзины", "en": "No Recycle Bin on this drive",
        "zh": "磁盘没有回收站"},
    "viewer.del_perm_confirm": {
        "ru": "На диске с выбранными файлами нет корзины.\n"
              "Удалить их ({n} шт.) НАВСЕГДА, без возможности восстановления?",
        "en": "The drive holding the selected files has no Recycle Bin.\n"
              "Delete them ({n}) PERMANENTLY? This cannot be undone.",
        "zh": "所选文件所在的磁盘没有回收站。\n"
              "永久删除这 {n} 个文件？此操作无法撤销。"},
    "viewer.del_perm_ask_title": {
        "ru": "Не удалось переместить в корзину",
        "en": "Could not move to the Recycle Bin",
        "zh": "无法移入回收站"},
    "viewer.del_perm_ask": {
        "ru": "Не удалось переместить в корзину {n} шт. —\n"
              "на этом диске нет корзины или файл занят.\n\n"
              "Удалить их окончательно, без возможности восстановления?",
        "en": "Could not move {n} file(s) to the Recycle Bin —\n"
              "the drive has no Recycle Bin or a file is in use.\n\n"
              "Delete them permanently? This cannot be undone.",
        "zh": "有 {n} 个文件无法移入回收站 —\n"
              "该磁盘没有回收站，或文件被占用。\n\n"
              "是否永久删除？此操作无法撤销。"},
    "viewer.del_done_perm": {
        "ru": "Удалено окончательно: {n}", "en": "Deleted permanently: {n}",
        "zh": "已永久删除：{n}"},
    "viewer.del_done_mixed": {
        "ru": "Удалено: {n} (в корзину {t}, окончательно {p})",
        "en": "Deleted: {n} ({t} to Recycle Bin, {p} permanently)",
        "zh": "已删除：{n}（回收站 {t}，永久 {p}）"},
    "viewer.copy_nothing": {
        "ru": "Ничего не выделено — копировать нечего",
        "en": "Nothing is selected — nothing to copy",
        "zh": "未选择任何内容 — 没有可复制的"},
    "viewer.move_busy": {
        "ru": "Предыдущее перемещение ещё идёт — секунду",
        "en": "The previous move is still in progress — one moment",
        "zh": "上一个移动操作仍在进行 — 请稍候"},
    "viewer.move_nothing": {
        "ru": "Нечего перемещать", "en": "Nothing to move", "zh": "没有可移动的文件"},
    "viewer.move_same_folder": {
        "ru": "Файлы уже лежат в этой папке — переносить нечего",
        "en": "The files are already in this folder — nothing to move",
        "zh": "文件已在此文件夹中 — 无需移动"},
    "viewer.moving": {
        "ru": "Переношу {n} файлов → {target}…",
        "en": "Moving {n} files → {target}…",
        "zh": "正在移动 {n} 个文件 → {target}…"},
    "viewer.move_done": {
        "ru": "Перемещено: {n} → {target}",
        "en": "Moved: {n} → {target}",
        "zh": "已移动：{n} 个 → {target}"},
    "viewer.move_done_err": {
        "ru": "Перемещено: {n}, с ошибками: {m} (подробности в Журнале)",
        "en": "Moved: {n}, failed: {m} (details in the Log)",
        "zh": "已移动：{n} 个，失败：{m} 个（详见日志）"},
    "viewer.move_none": {
        "ru": "Переносить нечего — файлы уже в целевой папке",
        "en": "Nothing moved — the files are already there",
        "zh": "无需移动 — 文件已在目标文件夹中"},
    "viewer.copied_status": {
        "ru": "Скопировано: {n} — вставьте в Проводник или браузер (Ctrl+V)",
        "en": "Copied: {n} — paste into Explorer or a browser (Ctrl+V)",
        "zh": "已复制：{n} — 可粘贴到文件管理器或浏览器 (Ctrl+V)"},
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
    "viewer.fav_add": {
        "ru": "⭐ В избранное", "en": "⭐ Add to favorites", "zh": "⭐ 加入收藏夹"},
    "viewer.fav_remove": {
        "ru": "Убрать из избранного", "en": "Remove from favorites", "zh": "从收藏夹移除"},
    "viewer.fav_add_tip": {
        "ru": "Добавить текущую папку в избранное — она будет первой\n"
              "в дереве «Диски и папки» при каждом запуске",
        "en": "Add the current folder to favorites — it will stay on top\n"
              "of the “Drives and folders” tree across launches",
        "zh": "将当前文件夹加入收藏夹——每次启动时它都会\n固定在“磁盘与文件夹”树的顶部"},
    "viewer.fav_remove_tip": {
        "ru": "Убрать текущую папку из избранного",
        "en": "Remove the current folder from favorites",
        "zh": "从收藏夹移除当前文件夹"},
    # ---------- удаление фона (rembg, v0.7.12) ----------
    "viewer.rembg": {
        "ru": "🪄 Удалить фон", "en": "🪄 Remove Background", "zh": "🪄 删除背景"},
    "viewer.rembg_tip": {
        "ru": "Удалить фон у картинки (модуль rembg, всё считается локально).\n"
              "Результат — «имя_nobg.png» рядом с оригиналом; после обработки\n"
              "можно сохранить его или вернуть оригиналы. При первом запуске\n"
              "скачается выбранная модель.",
        "en": "Remove the image background (rembg module, fully local).\n"
              "The result is “name_nobg.png” next to the original; afterwards\n"
              "you can keep it or revert to the originals. The first run\n"
              "downloads the selected model.",
        "zh": "删除图片背景（rembg 模块，完全本地）。\n"
              "结果为原图旁的“名称_nobg.png”；处理后可保留结果或恢复原图。\n"
              "首次运行会下载所选模型。"},
    "viewer.rembg_none": {
        "ru": "Сначала выберите картинку в ленте",
        "en": "Select an image in the strip first",
        "zh": "请先在缩略图栏中选择图片"},
    "viewer.rembg_busy": {
        "ru": "Идёт удаление фона — подождите",
        "en": "Background removal is already running — please wait",
        "zh": "正在删除背景，请稍候"},
    "viewer.rembg_already": {
        "ru": "Это уже картинка без фона",
        "en": "This is already a no-background image",
        "zh": "这已经是无背景图片"},
    "viewer.rembg_progress": {
        "ru": "Удаление фона: {done}/{n} — {name}…",
        "en": "Removing background: {done}/{n} — {name}…",
        "zh": "删除背景：{done}/{n} — {name}…"},
    "viewer.rembg_done": {
        "ru": "Фон удалён: {ok}", "en": "Background removed: {ok}", "zh": "背景已删除：{ok}"},
    "viewer.rembg_done_fail": {
        "ru": ", с ошибками: {fail}", "en": ", {fail} failed", "zh": "，失败：{fail}"},
    "viewer.rembg_inst_q": {
        "ru": "Модуль удаления фона (rembg) не установлен.\n\n"
              "Установить сейчас? Пакет с ONNX Runtime — порядка 100–200 МБ,\n"
              "всё работает локально, без облака. Модель (~5–170 МБ в зависимости\n"
              "от выбранной) скачается при первом удалении фона.",
        "en": "The background removal module (rembg) is not installed.\n\n"
              "Install it now? The package with ONNX Runtime is about 100–200 MB;\n"
              "everything runs locally, no cloud. The model (~5–170 MB depending\n"
              "on the chosen one) is downloaded on first use.",
        "zh": "删除背景模块（rembg）尚未安装。\n\n"
              "现在安装吗？含 ONNX Runtime 的包约 100–200 MB，\n"
              "完全本地运行，无需云端。模型（视所选约 5–170 MB）\n"
              "会在首次删除背景时下载。"},
    "viewer.rembg_installing": {
        "ru": "Устанавливаю модуль удаления фона (rembg)…",
        "en": "Installing the background removal module (rembg)…",
        "zh": "正在安装删除背景模块（rembg）…"},
    "viewer.rembg_install_ok": {
        "ru": "Модуль установлен — нажмите «Удалить фон» ещё раз",
        "en": "Module installed — click “Remove Background” again",
        "zh": "模块已安装——请再次点击“删除背景”"},
    "viewer.rembg_install_fail": {
        "ru": "Не удалось установить rembg: {info}",
        "en": "Failed to install rembg: {info}",
        "zh": "安装 rembg 失败：{info}"},
    "viewer.rembg_uninst_q": {
        "ru": "Удалить модуль rembg и скачанные модели ({mb})?\n"
              "Из программы и с диска будет вычищено всё целиком.",
        "en": "Remove the rembg module and the downloaded models ({mb})?\n"
              "Everything will be cleaned from the program and disk.",
        "zh": "删除 rembg 模块及已下载的模型（{mb}）？\n程序和磁盘上的内容将被完全清除。"},
    "viewer.rembg_uninstalling": {
        "ru": "Удаляю модуль rembg и модели…",
        "en": "Removing the rembg module and models…",
        "zh": "正在删除 rembg 模块和模型…"},
    "viewer.rembg_uninst_ok": {
        "ru": "Модуль rembg и модели удалены (освобождено {mb})",
        "en": "rembg module and models removed ({mb} freed)",
        "zh": "rembg 模块和模型已删除（释放 {mb}）"},
    "viewer.rembg_uninst_fail": {
        "ru": "Не удалось удалить модуль: {info}",
        "en": "Failed to remove the module: {info}",
        "zh": "删除模块失败：{info}"},
    "viewer.rembg_menu_install": {
        "ru": "Установить модуль удаления фона (rembg)…",
        "en": "Install the background removal module (rembg)…",
        "zh": "安装删除背景模块（rembg）…"},
    "viewer.rembg_menu_uninstall": {
        "ru": "Удалить модуль rembg и модели…",
        "en": "Uninstall the rembg module and models…",
        "zh": "卸载 rembg 模块和模型…"},
    "viewer.rembg_model_menu": {
        "ru": "Модель", "en": "Model", "zh": "模型"},
    "viewer.rembg_model_u2netp": {
        "ru": "u2netp — быстрая (~5 МБ)",
        "en": "u2netp — fast (~5 MB)",
        "zh": "u2netp — 快速（约 5 MB）"},
    "viewer.rembg_model_u2net": {
        "ru": "u2net — качественнее (~176 МБ)",
        "en": "u2net — better quality (~176 MB)",
        "zh": "u2net — 更高质量（约 176 MB）"},
    "viewer.rembg_model_isnet": {
        "ru": "isnet-general-use — самые чистые края (~170 МБ)",
        "en": "isnet-general-use — cleanest edges (~170 MB)",
        "zh": "isnet-general-use — 边缘最干净（约 170 MB）"},
    "log.event.rembg_start": {
        "ru": "🪄 Удаление фона: файлов {n}, модель {model}",
        "en": "🪄 Background removal: {n} file(s), model {model}",
        "zh": "🪄 删除背景：{n} 个文件，模型 {model}"},
    "log.event.rembg_file_err": {
        "ru": "🪄 Не удалось убрать фон: {name} — {err}",
        "en": "🪄 Failed to remove background: {name} — {err}",
        "zh": "🪄 删除背景失败：{name} — {err}"},
    "log.event.rembg_done": {
        "ru": "🪄 Удаление фона завершено: {ok}, ошибок {fail} — {ms} мс{extra}",
        "en": "🪄 Background removal finished: {ok} done, {fail} failed — {ms} ms{extra}",
        "zh": "🪄 删除背景完成：{ok} 个成功，{fail} 个失败 — {ms} 毫秒{extra}"},
    "log.event.rembg_skip": {
        "ru": "🪄 Пропущено файлов: {n} — это уже результаты без фона",
        "en": "🪄 Skipped {n} file(s) — already no-background results",
        "zh": "🪄 已跳过 {n} 个文件——它们已经是无背景结果"},
    "log.event.rembg_model": {
        "ru": "🪄 Выбрана модель: {model}",
        "en": "🪄 Model selected: {model}",
        "zh": "🪄 已选择模型：{model}"},
    "log.event.rembg_install_start": {
        "ru": "🪄 Устанавливаю модуль rembg (pip install rembg[cpu])…",
        "en": "🪄 Installing the rembg module (pip install rembg[cpu])…",
        "zh": "🪄 正在安装 rembg 模块（pip install rembg[cpu]）…"},
    "log.event.rembg_install_done": {
        "ru": "🪄 Модуль rembg установлен",
        "en": "🪄 rembg module installed",
        "zh": "🪄 rembg 模块已安装"},
    "log.event.rembg_install_fail": {
        "ru": "🪄 Ошибка установки rembg: {info}",
        "en": "🪄 rembg installation error: {info}",
        "zh": "🪄 rembg 安装错误：{info}"},
    "log.event.rembg_uninstall_start": {
        "ru": "🪄 Удаляю модуль rembg и модели…",
        "en": "🪄 Removing the rembg module and models…",
        "zh": "🪄 正在删除 rembg 模块和模型…"},
    "log.event.rembg_uninstall_done": {
        "ru": "🪄 Модуль rembg удалён, освобождено {mb} МБ",
        "en": "🪄 rembg module removed, {mb} MB freed",
        "zh": "🪄 rembg 模块已删除，释放 {mb} MB"},
    "log.event.rembg_uninstall_fail": {
        "ru": "🪄 Ошибка удаления модуля: {info}",
        "en": "🪄 Module removal error: {info}",
        "zh": "🪄 模块删除错误：{info}"},
    "viewer.rembg_menu_update": {
        "ru": "Обновить модуль rembg…",
        "en": "Update the rembg module…",
        "zh": "更新 rembg 模块…"},
    "viewer.rembg_updating": {
        "ru": "Обновляю модуль rembg: сверяю версию с PyPI…",
        "en": "Updating the rembg module: checking the version on PyPI…",
        "zh": "正在更新 rembg 模块：正在与 PyPI 核对版本…"},
    "viewer.rembg_update_done": {
        "ru": "Модуль rembg: {what}",
        "en": "rembg module: {what}",
        "zh": "rembg 模块：{what}"},
    "viewer.rembg_update_nothing": {
        "ru": "обновлений нет — rembg {ver} актуален",
        "en": "nothing to update — rembg {ver} is up to date",
        "zh": "无需更新——rembg {ver} 已是最新"},
    "viewer.rembg_update_fail": {
        "ru": "Не удалось обновить модуль rembg: {info}",
        "en": "Failed to update the rembg module: {info}",
        "zh": "更新 rembg 模块失败：{info}"},
    "viewer.rembg_update_pypi_fail": {
        "ru": "pypi.org недоступен — версию rembg сверить не удалось",
        "en": "pypi.org is unreachable — cannot check the rembg version",
        "zh": "pypi.org 不可用——无法核对 rembg 的版本"},
    "viewer.rembg_update_stuck": {
        # репорт v0.8.17: pip отчитался успехом, но пакет остался старым —
        # честная неудача вместо ложного «X → Y»
        "ru": "rembg: остался на {ver} — обновить не удалось",
        "en": "rembg: still on {ver} — the update did not take",
        "zh": "rembg：仍为 {ver}——更新未生效"},
    "viewer.rembg_update_restart": {
        "ru": "перезапустите Image Hunter — меню «Модули» → «Перезагрузить Image Hunter»",
        "en": "restart Image Hunter — menu “Modules” → “Restart Image Hunter”",
        "zh": "请重启 Image Hunter — 菜单“模块”→“重启 Image Hunter”"},
    "log.event.rembg_update_start": {
        "ru": "🪄 Обновляю модуль rembg: сверяю версию с PyPI…",
        "en": "🪄 Updating the rembg module: checking the version on PyPI…",
        "zh": "🪄 正在更新 rembg 模块：正在与 PyPI 核对版本…"},
    "log.event.rembg_update_done": {
        "ru": "🪄 Модуль rembg: {what}",
        "en": "🪄 rembg module: {what}",
        "zh": "🪄 rembg 模块：{what}"},
    "log.event.rembg_update_fail": {
        "ru": "🪄 Ошибка обновления модуля rembg: {info}",
        "en": "🪄 rembg module update error: {info}",
        "zh": "🪄 rembg 模块更新错误：{info}"},
    # ---------- выбор после удаления фона + прогресс модели (v0.7.15) ----------
    "viewer.rembg_choice_q": {
        "ru": "Готово без фона: {n}.\n"
              "Файлы «*_nobg.png» лежат рядом с оригиналами — пока это окно\n"
              "открыто, ленту можно щёлкать и рассматривать результаты.\n\n"
              "Сохранить результат или вернуть оригиналы?",
        "en": "Done without background: {n}.\n"
              "The “*_nobg.png” files sit next to the originals — while this\n"
              "window is open you can click the strip and inspect them.\n\n"
              "Keep the result or revert to the originals?",
        "zh": "已去除背景：{n} 个。\n"
              "“*_nobg.png”文件保存在原图旁——当前窗口打开时仍可点击\n"
              "缩略图栏查看结果。\n\n"
              "保留结果还是恢复原图？"},
    "viewer.rembg_choice_more": {
        "ru": "…и ещё {n}", "en": "…and {n} more", "zh": "…等 {n} 个"},
    "viewer.rembg_btn_save": {
        "ru": "💾 Сохранить результат", "en": "💾 Keep Result", "zh": "💾 保留结果"},
    "viewer.rembg_btn_save_tip": {
        "ru": "Файлы «*_nobg.png» останутся рядом с оригиналами",
        "en": "The “*_nobg.png” files stay next to the originals",
        "zh": "“*_nobg.png”文件将保留在原图旁"},
    "viewer.rembg_btn_revert": {
        "ru": "↩ Вернуть оригиналы", "en": "↩ Revert to Originals", "zh": "↩ 恢复原图"},
    "viewer.rembg_btn_revert_tip": {
        "ru": "Удалить результаты этой пачки — оригиналы не менялись",
        "en": "Remove this batch's results — originals were not touched",
        "zh": "删除本批结果——原图未被改动"},
    "viewer.rembg_saved": {
        "ru": "Результат сохранён: {n}", "en": "Result kept: {n}", "zh": "已保留结果：{n}"},
    "viewer.rembg_reverting": {
        "ru": "Возвращаю оригиналы…", "en": "Restoring the originals…", "zh": "正在恢复原图…"},
    "viewer.rembg_reverted": {
        "ru": "Оригиналы возвращены: {n}", "en": "Originals restored: {n}", "zh": "已恢复原图：{n}"},
    "viewer.rembg_revert_fail": {
        "ru": "Оригиналы возвращены: {ok}, не удалось удалить: {fail}",
        "en": "Originals restored: {ok}, failed to remove: {fail}",
        "zh": "已恢复原图：{ok}，删除失败：{fail}"},
    "viewer.rembg_prepare": {
        "ru": "Готовится модель {model}…",
        "en": "Preparing the {model} model…",
        "zh": "正在准备模型 {model}…"},
    "viewer.rembg_ready": {
        "ru": "Модель {model} готова",
        "en": "The {model} model is ready",
        "zh": "模型 {model} 已就绪"},
    "viewer.rembg_dl_start": {
        "ru": "Скачивается модель {model}…",
        "en": "Downloading the {model} model…",
        "zh": "正在下载模型 {model}…"},
    "viewer.rembg_dl_prog": {
        "ru": "Скачивается модель {model}: {done} из {total} ({pct} %)",
        "en": "Downloading the {model} model: {done} of {total} ({pct} %)",
        "zh": "正在下载模型 {model}：{done}/{total}（{pct} %）"},
    "viewer.rembg_dl_prog_na": {
        "ru": "Скачивается модель {model}: {done}",
        "en": "Downloading the {model} model: {done}",
        "zh": "正在下载模型 {model}：{done}"},
    "viewer.rembg_dl_done": {
        "ru": "Модель {model} скачана ({size})",
        "en": "The {model} model is downloaded ({size})",
        "zh": "模型 {model} 下载完成（{size}）"},
    "log.event.rembg_model_dl": {
        "ru": "🪄 Модель {model} скачана: {size}, {ms} мс",
        "en": "🪄 The {model} model downloaded: {size}, {ms} ms",
        "zh": "🪄 模型 {model} 已下载：{size}，{ms} 毫秒"},
    "log.event.rembg_saved": {
        "ru": "🪄 Результат сохранён: {n}",
        "en": "🪄 Result kept: {n}",
        "zh": "🪄 已保留结果：{n}"},
    "log.event.rembg_revert_start": {
        "ru": "🪄 Возвращаю оригиналы: удаляю результаты ({n})",
        "en": "🪄 Restoring originals: removing the results ({n})",
        "zh": "🪄 正在恢复原图：删除结果（{n}）"},
    "log.event.rembg_revert": {
        "ru": "🪄 Оригиналы возвращены: удалено файлов {n}, ошибок {fail}",
        "en": "🪄 Originals restored: {n} file(s) removed, {fail} failed",
        "zh": "🪄 已恢复原图：删除 {n} 个文件，{fail} 个失败"},
    "log.event.rembg_revert_err": {
        "ru": "🪄 Не удалось удалить результат: {name} — {err}",
        "en": "🪄 Failed to remove the result: {name} — {err}",
        "zh": "🪄 删除结果失败：{name} — {err}"},
    # ---------- улучшение качества (Real-ESRGAN, v0.8.24) ----------
    "viewer.up": {
        "ru": "✨ Улучшить", "en": "✨ Upscale", "zh": "✨ 增强"},
    "viewer.up_tip": {
        "ru": "Улучшить качество и увеличить разрешение картинки\n"
              "(модуль Real-ESRGAN, веса качаются с GitHub, всё локально).\n"
              "Результат — «имя_x4.ext»/«имя_x2.ext» рядом с оригиналом;\n"
              "после обработки можно сохранить его или вернуть оригиналы.\n"
              "При первом улучшении скачаются веса выбранной модели.",
        "en": "Improve quality and enlarge the image resolution\n"
              "(Real-ESRGAN module, weights are downloaded from GitHub,\n"
              "fully local). The result is “name_x4.ext”/“name_x2.ext” next\n"
              "to the original; afterwards you can keep it or revert to the\n"
              "originals. The first run downloads the selected weights.",
        "zh": "提升画质并放大图片分辨率（Real-ESRGAN 模块，权重从 GitHub\n"
              "下载，完全本地）。结果为原图旁的“名称_x4.ext”/“名称_x2.ext”；\n"
              "处理后可保留结果或恢复原图。首次增强会下载所选权重。"},
    "viewer.up_none": {
        "ru": "Сначала выберите картинку в ленте",
        "en": "Select an image in the strip first",
        "zh": "请先在缩略图栏中选择图片"},
    "viewer.up_already": {
        "ru": "Улучшать нечего: GIF, файлы без расширения или уже результаты",
        "en": "Nothing to upscale: GIFs, extensionless files or existing results",
        "zh": "无可增强项：GIF、无扩展名文件或已是结果"},
    "viewer.up_busy": {
        "ru": "Идёт улучшение качества — подождите",
        "en": "Upscaling is already running — please wait",
        "zh": "正在增强画质，请稍候"},
    "viewer.up_progress": {
        "ru": "Улучшение: {done}/{n} — {name}…",
        "en": "Upscaling: {done}/{n} — {name}…",
        "zh": "增强画质：{done}/{n} — {name}…"},
    "viewer.up_phase": {
        "ru": "Улучшение: {done}/{n} — {name}: {phase}",
        "en": "Upscaling: {done}/{n} — {name}: {phase}",
        "zh": "增强画质：{done}/{n} — {name}：{phase}"},
    "viewer.up_phase_tile": {
        "ru": "плитка {cur}/{total}",
        "en": "tile {cur}/{total}",
        "zh": "分块 {cur}/{total}"},
    "viewer.up_done": {
        "ru": "Улучшено: {ok}", "en": "Upscaled: {ok}", "zh": "已增强：{ok}"},
    "viewer.up_done_fail": {
        "ru": ", с ошибками: {fail}", "en": ", {fail} failed", "zh": "，失败：{fail}"},
    "viewer.up_inst_q": {
        "ru": "Модуль улучшения качества (Real-ESRGAN) не установлен.\n\n"
              "Установить сейчас? Скачается torch — порядка 200 МБ (CPU)\n"
              "до пары гигабайт, всё работает локально, без облака. Веса\n"
              "модели (~17–64 МБ в зависимости от выбранной) скачаются\n"
              "с GitHub при первом улучшении.",
        "en": "The upscaling module (Real-ESRGAN) is not installed.\n\n"
              "Install it now? torch will be downloaded — from ~200 MB (CPU)\n"
              "up to a couple of GB; everything runs locally, no cloud. The\n"
              "model weights (~17–64 MB depending on the chosen one) are\n"
              "downloaded from GitHub on first use.",
        "zh": "画质增强模块（Real-ESRGAN）尚未安装。\n\n"
              "现在安装吗？将下载 torch——约 200 MB（CPU）到数 GB，\n"
              "完全本地运行，无需云端。模型权重（约 17–64 MB，视所选）\n"
              "会在首次增强时从 GitHub 下载。"},
    "viewer.up_installing": {
        "ru": "Устанавливаю модуль улучшения качества (torch)…",
        "en": "Installing the upscaling module (torch)…",
        "zh": "正在安装画质增强模块（torch）…"},
    "viewer.up_install_ok": {
        "ru": "Модуль установлен — нажмите «Улучшить» ещё раз",
        "en": "Module installed — click “Upscale” again",
        "zh": "模块已安装——请再次点击“增强”"},
    "viewer.up_install_fail": {
        "ru": "Не удалось установить модуль улучшения качества: {info}",
        "en": "Failed to install the upscaling module: {info}",
        "zh": "安装画质增强模块失败：{info}"},
    "viewer.up_uninst_q": {
        "ru": "Удалить модуль улучшения качества и скачанные веса ({mb})?\n"
              "Из программы и с диска будет вычищено всё целиком. torch,\n"
              "нужный модулю водяных знаков, останется.",
        "en": "Remove the upscaling module and the downloaded weights ({mb})?\n"
              "Everything will be cleaned from the program and disk. torch\n"
              "needed by the watermark module stays.",
        "zh": "删除画质增强模块及已下载的权重（{mb}）？\n程序和磁盘上的内容将被完全清除。\n水印模块所需的 torch 将保留。"},
    "viewer.up_uninstalling": {
        "ru": "Удаляю модуль улучшения качества и веса…",
        "en": "Removing the upscaling module and weights…",
        "zh": "正在删除画质增强模块和权重…"},
    "viewer.up_uninst_ok": {
        "ru": "Модуль улучшения качества и веса удалены (освобождено {mb})",
        "en": "Upscaling module and weights removed ({mb} freed)",
        "zh": "画质增强模块和权重已删除（释放 {mb}）"},
    "viewer.up_uninst_fail": {
        "ru": "Не удалось удалить модуль: {info}",
        "en": "Failed to remove the module: {info}",
        "zh": "删除模块失败：{info}"},
    "viewer.up_menu_install": {
        "ru": "Установить модуль улучшения качества (Real-ESRGAN)…",
        "en": "Install the upscaling module (Real-ESRGAN)…",
        "zh": "安装画质增强模块（Real-ESRGAN）…"},
    "viewer.up_menu_uninstall": {
        "ru": "Удалить модуль улучшения качества и веса…",
        "en": "Uninstall the upscaling module and weights…",
        "zh": "卸载画质增强模块和权重…"},
    "viewer.up_menu_update": {
        "ru": "Обновить модуль улучшения качества",
        "en": "Update the upscaling module",
        "zh": "更新画质增强模块"},
    "viewer.up_updating": {
        "ru": "Обновляю модуль улучшения качества: сверяю веса с GitHub…",
        "en": "Updating the upscaling module: checking the weights on GitHub…",
        "zh": "正在更新画质增强模块：正在与 GitHub 核对权重…"},
    "viewer.up_update_done": {
        "ru": "Модуль улучшения качества: {what}",
        "en": "Upscaling module: {what}",
        "zh": "画质增强模块：{what}"},
    "viewer.up_update_fail": {
        "ru": "Ошибка обновления модуля улучшения качества: {info}",
        "en": "Upscaling module update error: {info}",
        "zh": "画质增强模块更新错误：{info}"},
    "viewer.up_update_nothing": {
        "ru": "веса {model} актуальны (размер совпадает с релизом); torch {ver} — не перекладывается",
        "en": "the {model} weights are current (size matches the release); torch {ver} is left as is",
        "zh": "权重 {model} 最新（大小与发布版一致）；torch {ver} 保持不变"},
    "viewer.up_update_weights": {
        "ru": "веса {model} перекачаны с GitHub; torch {ver}",
        "en": "the {model} weights were re-downloaded from GitHub; torch {ver}",
        "zh": "权重 {model} 已从 GitHub 重新下载；torch {ver}"},
    "viewer.up_update_dl_fail": {
        "ru": "не удалось проверить {model} на github.com; torch {ver}",
        "en": "could not check {model} on github.com; torch {ver}",
        "zh": "无法在 github.com 上检查 {model}；torch {ver}"},
    "viewer.up_update_no_dl": {
        "ru": "веса {model} ещё не скачивались (скачаются при первом улучшении); torch {ver}",
        "en": "the {model} weights were not downloaded yet (they download on first use); torch {ver}",
        "zh": "权重 {model} 尚未下载（首次增强时下载）；torch {ver}"},
    "viewer.up_model_menu": {
        "ru": "Модель", "en": "Model", "zh": "模型"},
    "viewer.up_model_x4plus": {
        "ru": "RealESRGAN x4plus — универсальная ×4 (~64 МБ)",
        "en": "RealESRGAN x4plus — universal ×4 (~64 MB)",
        "zh": "RealESRGAN x4plus — 通用 ×4（约 64 MB）"},
    "viewer.up_model_anime": {
        "ru": "RealESRGAN x4 anime 6B — для аниме и рисованной графики ×4 (~17 МБ)",
        "en": "RealESRGAN x4 anime 6B — for anime and drawn art ×4 (~17 MB)",
        "zh": "RealESRGAN x4 anime 6B — 动漫与手绘插画 ×4（约 17 MB）"},
    "viewer.up_model_x2plus": {
        "ru": "RealESRGAN x2plus — умеренная ×2, безопаснее для фото (~64 МБ)",
        "en": "RealESRGAN x2plus — moderate ×2, safer for photos (~64 MB)",
        "zh": "RealESRGAN x2plus — 适度 ×2，对照片更稳妥（约 64 MB）"},
    "viewer.up_prepare": {
        "ru": "Готовлю веса модели {model}",
        "en": "Preparing the {model} weights",
        "zh": "正在准备 {model} 权重"},
    "viewer.up_ready": {
        "ru": "Модель {model} готова",
        "en": "The {model} model is ready",
        "zh": "模型 {model} 已就绪"},
    "viewer.up_dl_start": {
        "ru": "Скачиваются веса {model}…",
        "en": "Downloading the {model} weights…",
        "zh": "正在下载 {model} 权重…"},
    "viewer.up_dl_prog": {
        "ru": "Скачиваются веса {model}: {done} из {total} ({pct} %)",
        "en": "Downloading the {model} weights: {done} of {total} ({pct} %)",
        "zh": "正在下载 {model} 权重：{done}/{total}（{pct}%）"},
    "viewer.up_dl_prog_na": {
        "ru": "Скачиваются веса {model}: {done}…",
        "en": "Downloading the {model} weights: {done}…",
        "zh": "正在下载 {model} 权重：{done}…"},
    "viewer.up_dl_done": {
        "ru": "Веса {model} скачаны ({size})",
        "en": "The {model} weights downloaded ({size})",
        "zh": "{model} 权重已下载（{size}）"},
    "viewer.up_choice_q": {
        "ru": "Готово улучшений: {n}.\n"
              "Файлы «*_x4.ext»/«*_x2.ext» лежат рядом с оригиналами — пока\n"
              "это окно открыто, ленту можно щёлкать и рассматривать\n"
              "результаты.\n\n"
              "Сохранить результат или вернуть оригиналы?",
        "en": "Upscales done: {n}.\n"
              "The “*_x4.ext”/“*_x2.ext” files sit next to the originals —\n"
              "while this window is open you can click the strip and inspect\n"
              "them.\n\n"
              "Keep the result or revert to the originals?",
        "zh": "已增强：{n} 个。\n"
              "“*_x4.ext”/“*_x2.ext”文件保存在原图旁——当前窗口打开时仍可\n"
              "点击缩略图栏查看结果。\n\n"
              "保留结果还是恢复原图？"},
    "viewer.up_choice_more": {
        "ru": "(ещё {n})", "en": "(plus {n} more)", "zh": "（另有 {n} 个）"},
    "viewer.up_btn_revert": {
        "ru": "Вернуть оригиналы", "en": "Revert to originals", "zh": "恢复原图"},
    "viewer.up_btn_revert_tip": {
        "ru": "Удалить файлы-результаты этой пачки; оригиналы не тронуты",
        "en": "Delete the result files of this batch; originals are untouched",
        "zh": "删除本批的结果文件；原图不受影响"},
    "viewer.up_btn_save": {
        "ru": "Сохранить", "en": "Keep", "zh": "保留"},
    "viewer.up_btn_save_tip": {
        "ru": "Оставить файлы-результаты на диске",
        "en": "Keep the result files on disk",
        "zh": "将结果文件保留在磁盘上"},
    "viewer.up_reverting": {
        "ru": "Возвращаю оригиналы — убираю результаты улучшения…",
        "en": "Restoring originals — removing the upscale results…",
        "zh": "正在恢复原图——删除增强结果…"},
    "viewer.up_saved": {
        "ru": "Результат улучшения сохранён: {n}",
        "en": "Upscale results kept: {n}",
        "zh": "已保留增强结果：{n}"},
    "viewer.up_revert_fail": {
        "ru": "Вернуть оригиналы не удалось: удалено {ok}, ошибок {fail}",
        "en": "Failed to revert: {ok} removed, {fail} failed",
        "zh": "恢复失败：已删除 {ok} 个，{fail} 个失败"},
    "viewer.up_reverted": {
        "ru": "Оригиналы возвращены: удалено результатов {n}",
        "en": "Originals restored: {n} result file(s) removed",
        "zh": "已恢复原图：删除 {n} 个结果文件"},
    "modules.up_header": {
        "ru": "Улучшение качества (Real-ESRGAN): {state}",
        "en": "Upscaling (Real-ESRGAN): {state}",
        "zh": "画质增强（Real-ESRGAN）：{state}"},
    "log.event.up_start": {
        "ru": "✨ Улучшение качества: файлов {n}, модель {model}",
        "en": "✨ Upscaling: {n} file(s), model {model}",
        "zh": "✨ 画质增强：{n} 个文件，模型 {model}"},
    "log.event.up_file_err": {
        "ru": "✨ Не удалось улучшить: {name} — {err}",
        "en": "✨ Failed to upscale: {name} — {err}",
        "zh": "✨ 增强失败：{name} — {err}"},
    "log.event.up_tile": {
        "ru": "✨ {name}: плитка {cur}/{total}",
        "en": "✨ {name}: tile {cur}/{total}",
        "zh": "✨ {name}：分块 {cur}/{total}"},
    "log.event.up_done": {
        "ru": "✨ Улучшение завершено: {ok}, ошибок {fail} — {ms} мс{extra}",
        "en": "✨ Upscaling finished: {ok} done, {fail} failed — {ms} ms{extra}",
        "zh": "✨ 画质增强完成：{ok} 个成功，{fail} 个失败 — {ms} 毫秒{extra}"},
    "log.event.up_skip": {
        "ru": "✨ Пропущено файлов: {n} — GIF/без расширения или уже результат",
        "en": "✨ Skipped {n} file(s) — GIFs, extensionless files or existing results",
        "zh": "✨ 已跳过 {n} 个文件——GIF/无扩展名或已是结果"},
    "log.event.up_model": {
        "ru": "✨ Выбрана модель: {model}",
        "en": "✨ Model selected: {model}",
        "zh": "✨ 已选择模型：{model}"},
    "log.event.up_model_dl": {
        "ru": "✨ Веса {model} скачаны: {size}, {ms} мс",
        "en": "✨ The {model} weights downloaded: {size}, {ms} ms",
        "zh": "✨ {model} 权重已下载：{size}，{ms} 毫秒"},
    "log.event.up_install_start": {
        "ru": "✨ Устанавливаю модуль улучшения качества (pip install torch)…",
        "en": "✨ Installing the upscaling module (pip install torch)…",
        "zh": "✨ 正在安装画质增强模块（pip install torch）…"},
    "log.event.up_install_done": {
        "ru": "✨ Модуль улучшения качества установлен",
        "en": "✨ The upscaling module installed",
        "zh": "✨ 画质增强模块已安装"},
    "log.event.up_install_fail": {
        "ru": "✨ Ошибка установки модуля улучшения качества: {info}",
        "en": "✨ Upscaling module install error: {info}",
        "zh": "✨ 画质增强模块安装错误：{info}"},
    "log.event.up_uninstall_start": {
        "ru": "✨ Удаляю модуль улучшения качества и скачанные веса…",
        "en": "✨ Removing the upscaling module and downloaded weights…",
        "zh": "✨ 正在删除画质增强模块和已下载的权重…"},
    "log.event.up_uninstall_done": {
        "ru": "✨ Модуль улучшения качества удалён (освобождено {mb})",
        "en": "✨ Upscaling module removed ({mb} freed)",
        "zh": "✨ 画质增强模块已删除（释放 {mb}）"},
    "log.event.up_uninstall_fail": {
        "ru": "✨ Ошибка удаления модуля улучшения качества: {info}",
        "en": "✨ Upscaling module removal error: {info}",
        "zh": "✨ 画质增强模块删除错误：{info}"},
    "log.event.up_update_start": {
        "ru": "✨ Обновляю модуль улучшения качества: сверяю веса с GitHub…",
        "en": "✨ Updating the upscaling module: checking the weights on GitHub…",
        "zh": "✨ 正在更新画质增强模块：正在与 GitHub 核对权重…"},
    "log.event.up_update_done": {
        "ru": "✨ Модуль улучшения качества: {what}",
        "en": "✨ Upscaling module: {what}",
        "zh": "✨ 画质增强模块：{what}"},
    "log.event.up_update_fail": {
        "ru": "✨ Ошибка обновления модуля улучшения качества: {info}",
        "en": "✨ Upscaling module update error: {info}",
        "zh": "✨ 画质增强模块更新错误：{info}"},
    "log.event.up_saved": {
        "ru": "✨ Результат улучшения сохранён: {n}",
        "en": "✨ Upscale results kept: {n}",
        "zh": "✨ 已保留增强结果：{n}"},
    "log.event.up_revert_start": {
        "ru": "✨ Возвращаю оригиналы: удаляю результаты ({n})",
        "en": "✨ Restoring originals: removing the results ({n})",
        "zh": "✨ 正在恢复原图：删除结果（{n}）"},
    "log.event.up_revert": {
        "ru": "✨ Оригиналы возвращены: удалено файлов {n}, ошибок {fail}",
        "en": "✨ Originals restored: {n} file(s) removed, {fail} failed",
        "zh": "✨ 已恢复原图：删除 {n} 个文件，{fail} 个失败"},
    "log.event.up_revert_err": {
        "ru": "✨ Не удалось удалить результат: {name} — {err}",
        "en": "✨ Failed to remove the result: {name} — {err}",
        "zh": "✨ 删除结果失败：{name} — {err}"},
    # ---------- удаление водяных знаков (Florence-2 + LaMa/IOPaint, v0.8.11) ----------
    "viewer.wm": {
        "ru": "🧽 Убрать водяные знаки", "en": "🧽 Remove Watermarks", "zh": "🧽 去除水印"},
    "viewer.wm_tip": {
        "ru": "Убрать водяные знаки у картинки (модуль Florence-2 + LaMa, всё локально).\n"
              "Результат — «имя_nowm.ext» рядом с оригиналом. При первом запуске\n"
              "скачаются модели (~0,7 ГБ для base).",
        "en": "Remove watermarks from the image (Florence-2 + LaMa module, fully local).\n"
              "The result is “name_nowm.ext” next to the original. The first run\n"
              "downloads the models (~0.7 GB for base).",
        "zh": "去除图片水印（Florence-2 + LaMa 模块，完全本地）。\n"
              "结果为原图旁的“名称_nowm.ext”。首次运行会下载模型（base 约 0.7 GB）。"},
    "viewer.wm_none": {
        "ru": "Сначала выберите картинку в ленте",
        "en": "Select an image in the strip first",
        "zh": "请先在缩略图栏中选择图片"},
    "viewer.wm_sel": {
        "ru": "🧽 Убрать в выделении", "en": "🧽 Erase Selection", "zh": "🧽 清除选区水印"},
    "viewer.wm_sel_tip": {
        "ru": "Убрать водяные знаки в выделенной области (v0.8.22): LaMa закрасит ровно её,\n"
              "без автопоиска — Florence-2 не грузится. Результат — отдельный файл\n"
              "«имя_nowm.ext» рядом с оригиналом; повторная чистка результата —\n"
              "«имя_nowm-1.ext», «-2»… Оригиналы никогда не перезаписываются.",
        "en": "Erase watermarks inside the selection (v0.8.22): LaMa fills exactly that area,\n"
              "no auto-detection — Florence-2 is not loaded. The result is a separate file\n"
              "“name_nowm.ext” next to the original; re-cleaning the result yields\n"
              "“name_nowm-1.ext”, “-2”… Originals are never overwritten.",
        "zh": "去除选区内的水印（v0.8.22）：LaMa 只填充所选区域——无需自动检测，不加载 Florence-2。\n"
             "结果为原图旁的单独文件“名称_nowm.ext”；对结果再次清除会得到\n"
             "“名称_nowm-1.ext”“-2”……原图永远不会被覆盖。"},
    "viewer.wm_tiled": {
        "ru": "🧽 Все повторы", "en": "🧽 All repeats", "zh": "🧽 所有重复"},
    "viewer.wm_tiled_tip": {
        "ru": "Убрать плиточный знак ВО ВСЕХ местах (v0.8.28): выделите ОДИН\n"
              "экземпляр — остальные найдутся по решётке и закрасятся разом,\n"
              "включая экземпляры на пёстрых фонах, где автопоиск слеп.\n"
              "Если решётка не собралась, закрашивается ровно выделение.\n"
              "Результат — отдельный файл «имя_nowm.ext» рядом с оригиналом.",
        "en": "Erase a tiled watermark EVERYWHERE (v0.8.28): select ONE instance —\n"
              "the others are found on the lattice and erased in one pass,\n"
              "including instances on busy backgrounds where auto-detection\n"
              "is blind. If no lattice emerges, exactly the selection is filled.\n"
              "The result is a separate file “name_nowm.ext” next to the original.",
        "zh": "一次性去除平铺水印的所有实例（v0.8.28）：框选一个实例——其余的会\n"
             "按网格找到并一次擦除，包括自动检测失效的复杂背景上的实例。\n"
             "若未能构建网格，则只填充所选区域。结果为原图旁的单独文件\n"
             "“名称_nowm.ext”。"},
    "viewer.wm_busy": {
        "ru": "Идёт удаление водяных знаков — подождите",
        "en": "Watermark removal is already running — please wait",
        "zh": "正在去除水印，请稍候"},
    "viewer.wm_already": {
        "ru": "Эти файлы — уже результаты *_nowm (или GIF)",
        "en": "These files are already *_nowm results (or GIF)",
        "zh": "这些文件已是 *_nowm 结果（或 GIF）"},
    "viewer.wm_progress": {
        "ru": "Удаление водяных знаков: {done}/{n} — {name}…",
        "en": "Removing watermarks: {done}/{n} — {name}…",
        "zh": "去除水印：{done}/{n} — {name}…"},
    "viewer.wm_done": {
        "ru": "Водяные знаки убраны: {ok}",
        "en": "Watermarks removed: {ok}",
        "zh": "水印已去除：{ok}"},
    "viewer.wm_clean": {
        "ru": "; чистых: {clean}", "en": "; clean: {clean}", "zh": "；无水印：{clean}"},
    "viewer.wm_done_fail": {
        "ru": "; ошибок: {fail}", "en": "; failed: {fail}", "zh": "；失败：{fail}"},
    "viewer.wm_inst_q": {
        "ru": "Модуль удаления водяных знаков (Florence-2 + LaMa) не установлен.\n\n"
              "Установить сейчас? Скачается iopaint, transformers и timm\n"
              "(вместе с PyTorch — гигабайты), модели подгрузятся при первом\n"
              "запуске (LaMa ~0,2 ГБ, Florence-2-base ~0,5 ГБ). Всё локально.",
        "en": "The watermark removal module (Florence-2 + LaMa) is not installed.\n\n"
              "Install it now? This downloads iopaint, transformers and timm\n"
              "(PyTorch included — gigabytes); the models are fetched on first\n"
              "use (LaMa ~0.2 GB, Florence-2-base ~0.5 GB). Everything runs locally.",
        "zh": "未安装水印去除模块（Florence-2 + LaMa）。\n\n"
              "现在安装吗？将下载 iopaint、transformers、timm（含 PyTorch，数 GB），\n"
              "模型在首次使用时下载（LaMa 约 0.2 GB，Florence-2-base 约 0.5 GB）。全部本地运行。"},
    "viewer.wm_installing": {
        "ru": "Устанавливаю модуль удаления водяных знаков (pip, два шага: без Pillow и gradio, с шимами для новых Python)…",
        "en": "Installing the watermark removal module (pip, two steps: no Pillow/gradio, with shims for newer Pythons)…",
        "zh": "正在安装水印去除模块（pip，两步：不含 Pillow/gradio，带新版 Python 的垫片）…"},
    "viewer.wm_install_ok": {
        "ru": "Модуль удаления водяных знаков установлен",
        "en": "Watermark removal module installed",
        "zh": "水印去除模块已安装"},
    "viewer.wm_install_fail": {
        "ru": "Не удалось установить модуль удаления водяных знаков: {info}",
        "en": "Failed to install the watermark removal module: {info}",
        "zh": "安装水印去除模块失败：{info}"},
    "viewer.wm_uninst_q": {
        "ru": "Удалить модуль водяных знаков и скачанные модели ({mb})?\n"
              "С диска будет вычищено всё, что ставил модуль.",
        "en": "Remove the watermark removal module and the downloaded models ({mb})?\n"
              "Everything the module installed will be wiped from the disk.",
        "zh": "删除水印去除模块及已下载的模型（{mb}）？\n模块安装的所有内容将从磁盘完全清除。"},
    "viewer.wm_uninstalling": {
        "ru": "Удаляю модуль водяных знаков и модели…",
        "en": "Removing the watermark removal module and models…",
        "zh": "正在删除水印去除模块和模型…"},
    "viewer.wm_uninst_ok": {
        "ru": "Модуль водяных знаков и модели удалены (освобождено {mb})",
        "en": "Watermark removal module and models removed ({mb} freed)",
        "zh": "水印去除模块和模型已删除（释放 {mb}）"},
    "viewer.wm_uninst_fail": {
        "ru": "Не удалось удалить модуль водяных знаков: {info}",
        "en": "Failed to remove the watermark removal module: {info}",
        "zh": "删除水印去除模块失败：{info}"},
    "viewer.wm_menu_install": {
        "ru": "Установить модуль водяных знаков (Florence-2 + LaMa)…",
        "en": "Install the watermark removal module (Florence-2 + LaMa)…",
        "zh": "安装水印去除模块（Florence-2 + LaMa）…"},
    "viewer.wm_menu_uninstall": {
        "ru": "Удалить модуль водяных знаков и модели…",
        "en": "Uninstall the watermark removal module and models…",
        "zh": "卸载水印去除模块和模型…"},
    "viewer.wm_model_menu": {
        "ru": "Модель детекции Florence-2", "en": "Florence-2 detection model",
        "zh": "Florence-2 检测模型"},
    "viewer.wm_model_base": {
        "ru": "Florence-2-base (быстрый, ~0,5 ГБ)",
        "en": "Florence-2-base (fast, ~0.5 GB)",
        "zh": "Florence-2-base（快，约 0.5 GB）"},
    "viewer.wm_model_large": {
        "ru": "Florence-2-large (точнее, ~1,6 ГБ)",
        "en": "Florence-2-large (better, ~1.6 GB)",
        "zh": "Florence-2-large（更准，约 1.6 GB）"},
    "viewer.wm_prepare": {
        "ru": "Готовлю модели (при первом запуске скачаются): {model}",
        "en": "Preparing the models (downloaded on first run): {model}",
        "zh": "正在准备模型（首次运行会下载）：{model}"},
    "viewer.wm_ready": {
        "ru": "Модели готовы: {model}", "en": "Models are ready: {model}",
        "zh": "模型已就绪：{model}"},
    # ---------- процесс модулей в статус-баре (v0.8.20) ----------
    # пожелание: «сделай, чтобы можно было видеть в строке статуса процесс
    # и/или статус работы модулей, особенно модуля удаления ватермарков»
    "modstatus.elapsed": {
        "ru": " · {sec} с", "en": " · {sec} s", "zh": " · {sec} 秒"},
    "viewer.wm_phase": {
        "ru": "Удаление водяных знаков: {done}/{n} — {name}: {phase}",
        "en": "Removing watermarks: {done}/{n} — {name}: {phase}",
        "zh": "去除水印：{done}/{n} — {name}：{phase}"},
    "viewer.wm_phase_detect": {
        "ru": "поиск знаков", "en": "detecting watermarks", "zh": "检测水印"},
    "viewer.wm_phase_found": {
        "ru": "знаков найдено: {n}", "en": "watermarks found: {n}",
        "zh": "发现水印：{n}"},
    "viewer.wm_phase_inpaint": {
        "ru": "закраска", "en": "inpainting", "zh": "修复填充"},
    "viewer.wm_phase_save": {
        "ru": "сохранение", "en": "saving", "zh": "保存"},
    "viewer.wm_phase_repair": {
        "ru": "починка конвейера (pip)…",
        "en": "repairing the pipeline (pip)…",
        "zh": "修复流水线（pip）…"},
    "viewer.wm_phase_repair_done": {
        "ru": "зависимости восстановлены, загружаю модели",
        "en": "dependencies restored, loading the models",
        "zh": "依赖已恢复，正在加载模型"},
    "viewer.wm_dl_start": {
        "ru": "Скачивается модель {model}…",
        "en": "Downloading the {model} model…",
        "zh": "正在下载模型 {model}…"},
    "viewer.wm_dl_prog": {
        "ru": "Скачивается модель {model}: {done} из {total} ({pct} %)",
        "en": "Downloading the {model} model: {done} of {total} ({pct} %)",
        "zh": "正在下载模型 {model}：{done}/{total}（{pct} %）"},
    "viewer.wm_dl_prog_na": {
        "ru": "Скачивается модель {model}: {done}",
        "en": "Downloading the {model} model: {done}",
        "zh": "正在下载模型 {model}：{done}"},
    "log.event.wm_start": {
        "ru": "🧽 Убираю водяные знаки: файлов {n}, модель {model}",
        "en": "🧽 Removing watermarks: {n} file(s), model {model}",
        "zh": "🧽 正在去除水印：{n} 个文件，模型 {model}"},
    "log.event.wm_file_err": {
        "ru": "🧽 Не удалось убрать водяные знаки: {name} — {err}",
        "en": "🧽 Watermark removal failed: {name} — {err}",
        "zh": "🧽 去除水印失败：{name} — {err}"},
    "log.event.wm_repair": {
        "ru": "🧽 Конвейер сломан — восстанавливаю зависимости по пинам iopaint (pip), это может занять пару минут",
        "en": "🧽 Pipeline broken — restoring dependencies to the iopaint pins (pip), this may take a couple of minutes",
        "zh": "🧽 流水线损坏——正在按 iopaint 的版本锁定恢复依赖（pip），可能需要几分钟"},
    "log.event.wm_repair_ok": {
        "ru": "🧽 Зависимости восстановлены — пробую загрузить модели ещё раз",
        "en": "🧽 Dependencies restored — trying to load the models again",
        "zh": "🧽 依赖已恢复——再次尝试加载模型"},
    "log.event.wm_cover": {
        "ru": "маска заняла {pct}% кадра — детектор не отделил знак от картинки, файл не тронут",
        "en": "the mask covered {pct}% of the frame — the detector failed to separate the watermark; the file is untouched",
        "zh": "遮罩覆盖了画面的 {pct}% —— 检测器未能分离水印，文件未作改动"},
    "log.event.wm_sel_cover": {
        "ru": "выделение заняло {pct}% картинки — закрасить его целиком нельзя, картинка не тронута",
        "en": "the selection covers {pct}% of the image — filling it entirely is not possible; the image is untouched",
        "zh": "选区覆盖了图片的 {pct}% —— 无法整幅填充，图片未作改动"},
    "log.event.wm_done": {
        "ru": "🧽 Водяные знаки убраны: обработано {ok}, чистых {clean}, ошибок {fail} ({ms} мс)",
        "en": "🧽 Watermark removal finished: {ok} processed, {clean} clean, {fail} failed ({ms} ms)",
        "zh": "🧽 水印去除完成：处理 {ok}，无水印 {clean}，失败 {fail}（{ms} 毫秒）"},
    "log.event.wm_skip": {
        "ru": "🧽 Пропущено файлов: {n} (уже «_nowm» или GIF)",
        "en": "🧽 Skipped {n} file(s) (already *_nowm results or GIF)",
        "zh": "🧽 跳过 {n} 个文件（已是 *_nowm 结果或 GIF）"},
    "log.event.wm_sel_start": {
        "ru": "🧽 Убираю водяные знаки в выделении {w}×{h}: {name}, модель {model}",
        "en": "🧽 Removing watermarks in the {w}×{h} selection: {name}, model {model}",
        "zh": "🧽 正在去除 {w}×{h} 选区内的水印：{name}，模型 {model}"},
    "log.event.wm_tiled_start": {
        "ru": "🧽 Убираю все повторы знака: {name}, семя {w}×{h}, модель {model}",
        "en": "🧽 Removing all repeats of the mark: {name}, seed {w}×{h}, model {model}",
        "zh": "🧽 正在去除该标志的所有重复：{name}，种子 {w}×{h}，模型 {model}"},
    "log.event.wm_tiles": {
        "ru": "🧽 Знак повторяется: в маску добавлено ещё {n} экземпляров по решётке",
        "en": "🧽 The mark repeats: {n} more instances added to the mask on the lattice",
        "zh": "🧽 标志重复：按网格向掩码额外添加了 {n} 个实例"},
    "log.event.wm_model": {
        "ru": "🧽 Модель детекции: {model}", "en": "🧽 Detection model: {model}",
        "zh": "🧽 检测模型：{model}"},
    "log.event.wm_install_start": {
        "ru": "🧽 Устанавливаю модуль водяных знаков (pip: iopaint без зависимостей, затем его зависимости из метаданных без Pillow и gradio + transformers/timm + шимы standard-imghdr/setuptools для новых Python)…",
        "en": "🧽 Installing the watermark removal module (pip: iopaint without deps, then its metadata dependencies without Pillow/gradio + transformers/timm + standard-imghdr/setuptools shims for newer Pythons)…",
        "zh": "🧽 正在安装水印去除模块（pip：先装 iopaint 本体，再装其元数据依赖（不含 Pillow 和 gradio）+ transformers/timm + 新版 Python 的垫片 standard-imghdr/setuptools）…"},
    "log.event.wm_install_done": {
        "ru": "🧽 Модуль водяных знаков установлен",
        "en": "🧽 Watermark removal module installed",
        "zh": "🧽 水印去除模块已安装"},
    "log.event.wm_install_fail": {
        "ru": "🧽 Ошибка установки модуля водяных знаков: {info}",
        "en": "🧽 Watermark removal module installation error: {info}",
        "zh": "🧽 水印去除模块安装错误：{info}"},
    "log.event.wm_uninstall_start": {
        "ru": "🧽 Удаляю модуль водяных знаков и модели…",
        "en": "🧽 Removing the watermark removal module and models…",
        "zh": "🧽 正在删除水印去除模块和模型…"},
    "log.event.wm_uninstall_done": {
        "ru": "🧽 Модуль водяных знаков удалён, освобождено {mb} МБ",
        "en": "🧽 Watermark removal module removed, {mb} MB freed",
        "zh": "🧽 水印去除模块已删除，释放 {mb} MB"},
    "log.event.wm_uninstall_fail": {
        "ru": "🧽 Ошибка удаления модуля водяных знаков: {info}",
        "en": "🧽 Watermark removal module removal error: {info}",
        "zh": "🧽 水印去除模块删除错误：{info}"},
    "viewer.wm_menu_update": {
        "ru": "Обновить модуль водяных знаков…",
        "en": "Update the watermark removal module…",
        "zh": "更新水印去除模块…"},
    "viewer.wm_updating": {
        "ru": "Обновляю модуль водяных знаков: сверяю пакеты (PyPI) и модели (Hugging Face)…",
        "en": "Updating the watermark removal module: checking packages (PyPI) and models (Hugging Face)…",
        "zh": "正在更新水印去除模块：核对软件包（PyPI）与模型（Hugging Face）…"},
    "viewer.wm_update_done": {
        "ru": "Модуль водяных знаков: {what}",
        "en": "Watermark removal module: {what}",
        "zh": "水印去除模块：{what}"},
    "viewer.wm_update_fail": {
        "ru": "Не удалось обновить модуль водяных знаков: {info}",
        "en": "Failed to update the watermark removal module: {info}",
        "zh": "更新水印去除模块失败：{info}"},
    "viewer.wm_update_nothing": {
        "ru": "обновлений нет — пакеты и модели актуальны ({pkgs})",
        "en": "nothing to update — packages and models are up to date ({pkgs})",
        "zh": "无需更新——软件包与模型均为最新（{pkgs}）"},
    "viewer.wm_update_model": {
        "ru": "модель {model} обновлена (свежая ревизия Hugging Face)",
        "en": "{model} model updated (fresh Hugging Face revision)",
        "zh": "{model} 模型已更新（Hugging Face 最新版本）"},
    "viewer.wm_update_lama": {
        "ru": "big-lama перекачан (свежий релиз)",
        "en": "big-lama re-downloaded (fresh release)",
        "zh": "big-lama 已重新下载（最新版本）"},
    "viewer.wm_update_model_fail": {
        "ru": "модель {model}: проверить не удалось ({info})",
        "en": "{model} model: check failed ({info})",
        "zh": "{model} 模型：检查失败（{info}）"},
    "viewer.wm_update_lama_fail": {
        "ru": "big-lama: проверить не удалось ({info})",
        "en": "big-lama: check failed ({info})",
        "zh": "big-lama：检查失败（{info}）"},
    "viewer.wm_update_pypi_fail": {
        "ru": "pypi.org недоступен — версию {name} сверить не удалось",
        "en": "pypi.org is unreachable — cannot check {name}",
        "zh": "pypi.org 不可用——无法核对 {name} 的版本"},
    "viewer.wm_update_stuck": {
        # репорт v0.8.17: pip отчитался успехом, но пакет остался старым
        # (резолвер общей команды откатил его под чужое требование или
        # свежая версия не подошла Python) — честная неудача вместо
        # ложного «X → Y»; застрявшего перед этим спасает одиночный pip
        "ru": "{name}: остался на {ver} — обновить не удалось",
        "en": "{name}: still on {ver} — the update did not take",
        "zh": "{name}：仍为 {ver}——更新未生效"},
    "viewer.wm_update_restart": {
        "ru": "перезапустите Image Hunter — меню «Модули» → «Перезагрузить Image Hunter»",
        "en": "restart Image Hunter — menu “Modules” → “Restart Image Hunter”",
        "zh": "请重启 Image Hunter — 菜单“模块”→“重启 Image Hunter”"},
    "log.event.wm_update_start": {
        "ru": "🧽 Обновляю модуль водяных знаков: пакеты (PyPI), Florence-2 (Hugging Face), big-lama (релиз)…",
        "en": "🧽 Updating the watermark removal module: packages (PyPI), Florence-2 (Hugging Face), big-lama (release)…",
        "zh": "🧽 正在更新水印去除模块：软件包（PyPI）、Florence-2（Hugging Face）、big-lama（发布版）…"},
    "log.event.wm_update_done": {
        "ru": "🧽 Модуль водяных знаков: {what}",
        "en": "🧽 Watermark removal module: {what}",
        "zh": "🧽 水印去除模块：{what}"},
    "log.event.wm_update_fail": {
        "ru": "🧽 Ошибка обновления модуля водяных знаков: {info}",
        "en": "🧽 Watermark removal module update error: {info}",
        "zh": "🧽 水印去除模块更新错误：{info}"},
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
    "viewer.loading": {
        "ru": "загрузка…", "en": "loading…", "zh": "加载中…"},
    "viewer.of": {
        "ru": "{i} из {n}", "en": "{i} of {n}", "zh": "第 {i} 张，共 {n} 张"},
    # ---------- изменение размера картинки мышью (v0.8.6) ----------
    "viewer.resize": {
        "ru": "⇲ Размер", "en": "⇲ Resize", "zh": "⇲ 大小"},
    "viewer.resize_tip": {
        "ru": "Задать размер картинки мышью: тяните угол рамки (пропорционально)\n"
              "или правый/нижний край (одну сторону). «💾 Сохранить» запишет\n"
              "результат отдельным файлом рядом с оригиналом. Esc — выйти.",
        "en": "Set the image size with the mouse: drag the frame corner (keeps\n"
              "proportions) or the right/bottom edge (one side). “💾 Save” writes\n"
              "the result as a separate file next to the original. Esc — leave.",
        "zh": "用鼠标设定图片大小：拖动边框角点（保持比例）\n"
              "或右/下边缘（单边）。“💾 保存”将结果另存为\n"
              "原图旁边的单独文件。Esc — 退出。"},
    "viewer.resize_save": {
        "ru": "💾 Сохранить", "en": "💾 Save", "zh": "💾 保存"},
    "viewer.resize_save_tip": {
        "ru": "Записать картинку нового размера рядом с оригиналом отдельным файлом\n"
              "«имя_ШxВ.ext» — оригинал не меняется, существующие файлы не затираются",
        "en": "Write the resized image next to the original as a separate file\n"
              "“name_WxH.ext” — the original stays untouched, nothing is overwritten",
        "zh": "将调整大小后的图片作为单独文件“名字_WxH.ext”保存到原图旁边 —\n"
              "原图不变，不会覆盖现有文件"},
    "viewer.resize_enter": {
        "ru": "✂ {new} (исходник {orig}) — тяните угол или края рамки; Esc — выход",
        "en": "✂ {new} (original {orig}) — drag the corner or edges of the frame; Esc to leave",
        "zh": "✂ {new}（原图 {orig}）— 拖动角点或边框；Esc 退出"},
    "viewer.resize_status": {
        "ru": "✂ {new} из {orig}", "en": "✂ {new} of {orig}", "zh": "✂ {new} / {orig}"},
    "viewer.resize_saving": {
        "ru": "Сохраняю картинку нового размера…",
        "en": "Saving the resized image…",
        "zh": "正在保存调整大小后的图片…"},
    "viewer.resize_saved": {
        "ru": "Сохранено: {name} ({w}×{h}) — оригинал не тронут",
        "en": "Saved: {name} ({w}×{h}) — the original is untouched",
        "zh": "已保存：{name}（{w}×{h}）— 原图未变"},
    "viewer.resize_save_err": {
        "ru": "Не удалось сохранить: {err}", "en": "Failed to save: {err}", "zh": "保存失败：{err}"},
    "log.event.resize": {
        "ru": "Изменён размер картинки: {src} → {dst} ({w}×{h})",
        "en": "Image resized: {src} → {dst} ({w}×{h})",
        "zh": "图片大小已调整：{src} → {dst}（{w}×{h}）"},
    "log.event.resize_err": {
        "ru": "Не удалось сохранить новый размер {name}: {err}",
        "en": "Failed to save the new size of {name}: {err}",
        "zh": "无法保存 {name} 的新尺寸：{err}"},
    "perf.op.resize": {
        "ru": "resize: {name}", "en": "resize: {name}", "zh": "resize：{name}"},
    # ---------- обрезка картинки мышью, как в XnView (v0.8.7) ----------
    "viewer.crop": {
        "ru": "✂ Обрезать", "en": "✂ Crop", "zh": "✂ 裁剪"},
    "viewer.crop_tip": {
        "ru": "Обрезать картинку, как в XnView: растяните рамку мышью по картинке,\n"
              "поправьте за янтарные рукоятки (углы и края) или перетащите рамку\n"
              "целиком; внутри — сетка третей. «💾 Сохранить» запишет выделенное\n"
              "отдельным файлом «имя_crop.ext» рядом с оригиналом, «💾 Как…» —\n"
              "с выбором имени и папки, «✂▶ К следующему» — сохранит и откроет\n"
              "следующую картинку папки. Зум в режиме работает. Esc — выйти.",
        "en": "Crop the image like in XnView: drag a rectangle over the picture,\n"
              "adjust it by the amber handles (corners and edges) or drag the\n"
              "whole rectangle; a thirds grid is drawn inside. “💾 Save” writes\n"
              "the selection as a separate file “name_crop.ext” next to the\n"
              "original, “💾 As…” — with a name and folder of your choice,\n"
              "“✂▶ Save & next” — saves and opens the next picture of the\n"
              "folder. Zoom works in this mode. Esc — leave.",
        "zh": "像 XnView 一样裁剪图片：在图片上拖动出矩形选框，用琥珀色手柄\n"
              "（角点和边点）微调，或整体拖动选框；内部显示三分构图线。\n"
              "“💾 保存”将所选区域另存为原图旁边的单独文件“名字_crop.ext”，\n"
              "“💾 另存为…”可选择名称和文件夹，“✂▶ 裁剪下一张”保存并打开\n"
              "文件夹中的下一张图片。此模式下缩放可用。Esc — 退出。"},
    "viewer.crop_save": {
        "ru": "💾 Сохранить", "en": "💾 Save", "zh": "💾 保存"},
    "viewer.crop_save_tip": {
        "ru": "Записать выделенную область отдельным файлом «имя_crop.ext» рядом\n"
              "с оригиналом — оригинал не меняется, существующие файлы не затираются",
        "en": "Write the selected area as a separate file “name_crop.ext” next to\n"
              "the original — the original stays untouched, nothing is overwritten",
        "zh": "将所选区域作为单独文件“名字_crop.ext”保存到原图旁边 —\n"
              "原图不变，不会覆盖现有文件"},
    "viewer.crop_saveas": {
        "ru": "💾 Как…", "en": "💾 As…", "zh": "💾 另存为…"},
    "viewer.crop_saveas_tip": {
        "ru": "Сохранить выделенную область с выбором имени и папки",
        "en": "Save the selected area with a name and folder of your choice",
        "zh": "保存所选区域，并可自选名称和文件夹"},
    "viewer.crop_saveas_title": {
        "ru": "Сохранить выделенную область как",
        "en": "Save selected area as",
        "zh": "将所选区域另存为"},
    "viewer.crop_saveas_filter": {
        "ru": "Картинки (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;Все файлы (*)",
        "en": "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All files (*)",
        "zh": "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;所有文件 (*)"},
    "viewer.crop_next": {
        "ru": "✂▶ К следующему", "en": "✂▶ Save & next", "zh": "✂▶ 裁剪下一张"},
    "viewer.crop_next_tip": {
        "ru": "Сохранить выделенное и открыть следующую картинку папки —\n"
              "режим остаётся включённым, папку можно пройти одним потоком",
        "en": "Save the selection and open the next picture of the folder —\n"
              "the mode stays on, so a whole folder can be cropped in one flow",
        "zh": "保存所选区域并打开文件夹中的下一张图片 —\n"
              "模式保持开启，可连续裁剪整个文件夹"},
    "viewer.crop_enter": {
        "ru": "✂ Растяните рамку по картинке; «💾 Сохранить» запишет выделенное, Esc — выход",
        "en": "✂ Drag a rectangle over the picture; “💾 Save” writes the selection, Esc to leave",
        "zh": "✂ 在图片上拖动出选框；“💾 保存”保存所选区域，Esc 退出"},
    "viewer.crop_status": {
        "ru": "✂ {sel} из {orig}", "en": "✂ {sel} of {orig}", "zh": "✂ {sel} / {orig}"},
    "viewer.crop_none": {
        "ru": "Выделите рамкой область картинки",
        "en": "Drag a rectangle to select an area of the picture",
        "zh": "拖动选框选择图片区域"},
    "viewer.crop_saving": {
        "ru": "Сохраняю выделенную область…",
        "en": "Saving the selected area…",
        "zh": "正在保存所选区域…"},
    "viewer.crop_saved": {
        "ru": "Обрезано: {name} ({w}×{h}) — оригинал не тронут",
        "en": "Cropped: {name} ({w}×{h}) — the original is untouched",
        "zh": "已裁剪：{name}（{w}×{h}）— 原图未变"},
    "viewer.crop_saved_next": {
        "ru": "Обрезано: {name} ({w}×{h}) — открыл следующую картинку",
        "en": "Cropped: {name} ({w}×{h}) — opened the next picture",
        "zh": "已裁剪：{name}（{w}×{h}）— 已打开下一张图片"},
    "viewer.crop_saved_end": {
        "ru": "Обрезано: {name} ({w}×{h}) — это была последняя картинка папки",
        "en": "Cropped: {name} ({w}×{h}) — that was the last picture of the folder",
        "zh": "已裁剪：{name}（{w}×{h}）— 这是文件夹中的最后一张图片"},
    "viewer.crop_save_err": {
        "ru": "Не удалось обрезать: {err}", "en": "Failed to crop: {err}", "zh": "裁剪失败：{err}"},
    "log.event.crop": {
        "ru": "Обрезана картинка: {src} → {dst} ({w}×{h})",
        "en": "Image cropped: {src} → {dst} ({w}×{h})",
        "zh": "图片已裁剪：{src} → {dst}（{w}×{h}）"},
    "log.event.crop_err": {
        "ru": "Не удалось обрезать {name}: {err}",
        "en": "Failed to crop {name}: {err}",
        "zh": "无法裁剪 {name}：{err}"},
    "perf.op.crop": {
        "ru": "crop: {name}", "en": "crop: {name}", "zh": "crop：{name}"},
    # ---------- пипетка и закрашивание выделенной области (v0.8.8) ----------
    "viewer.picker": {
        "ru": "💧 Пипетка", "en": "💧 Picker", "zh": "💧 取色器"},
    "viewer.picker_tip": {
        "ru": "Пипетка: включите режим и кликните по картинке — цвет пикселя\n"
              "скопируется в буфер обмена, образец появится на панели.\n"
              "Наведение показывает цвет под курсором. ПРАВЫЙ клик по картинке\n"
              "берёт цвет в любом режиме. Взятый цвет использует кнопка\n"
              "«🪣 Закрасить» в режиме обрезки. Esc — выйти.",
        "en": "Color picker: turn the mode on and click the picture — the\n"
              "pixel color is copied to the clipboard and a sample appears\n"
              "on the panel. Hovering shows the color under the cursor.\n"
              "RIGHT-click on the picture picks the color in any mode.\n"
              "The “🪣 Fill” button in crop mode uses the picked color.\n"
              "Esc — leave.",
        "zh": "取色器：开启模式后点击图片 — 像素颜色将复制到剪贴板，\n"
              "面板上会出现色样。悬停时显示光标下的颜色。在任意模式下\n"
              "右键点击图片均可取色。裁剪模式中的“🪣 填充”按钮\n"
              "使用所选颜色。Esc — 退出。"},
    "viewer.picker_enter": {
        "ru": "💧 Наведите на картинку — покажу цвет; клик — взять цвет; Esc — выход",
        "en": "💧 Hover the picture to see the color; click to pick it; Esc to leave",
        "zh": "💧 悬停在图片上查看颜色；单击取色；Esc 退出"},
    "viewer.picker_hover": {
        "ru": "💧 {hex} · {x},{y} — клик, чтобы взять цвет",
        "en": "💧 {hex} · {x},{y} — click to pick",
        "zh": "💧 {hex} · {x},{y} — 单击取色"},
    "viewer.picker_picked": {
        "ru": "💧 {hex} ({x},{y}) — цвет в буфере обмена",
        "en": "💧 {hex} ({x},{y}) — color copied to the clipboard",
        "zh": "💧 {hex}（{x},{y}）— 颜色已复制到剪贴板"},
    "viewer.picker_chip_tip": {
        "ru": "Цвет, взятый пипеткой (правый клик по картинке — в любом режиме):\n"
              "его использует кнопка «🪣 Закрасить» в режиме обрезки",
        "en": "Color picked with the eyedropper (right-click the picture — in any\n"
              "mode): used by the “🪣 Fill” button in crop mode",
        "zh": "取色器所选的颜色（任意模式下右键点击图片）：\n"
              "裁剪模式中的“🪣 填充”按钮会使用它"},
    "viewer.fill": {
        "ru": "🪣 Закрасить", "en": "🪣 Fill", "zh": "🪣 填充"},
    "viewer.fill_tip": {
        "ru": "Закрасить выделенную область цветом пипетки (возьмите цвет:\n"
              "режим «💧 Пипетка» или правый клик по картинке) и записать\n"
              "результат отдельным файлом «имя_fill.ext» рядом с оригиналом —\n"
              "оригинал не меняется, существующие файлы не затираются",
        "en": "Fill the selected area with the picked color (take it with the\n"
              "“💧 Picker” mode or a right-click on the picture) and write the\n"
              "result as a separate file “name_fill.ext” next to the original —\n"
              "the original stays untouched, nothing is overwritten",
        "zh": "用取色器所选的颜色填充所选区域（取色：开启“💧 取色器”模式\n"
              "或右键点击图片），并将结果另存为原图旁边的单独文件\n"
              "“名字_fill.ext” — 原图不变，不会覆盖现有文件"},
    "viewer.fill_nocolor": {
        "ru": "Сначала возьмите цвет пипеткой 💧 (или правый клик по картинке)",
        "en": "Pick a color with the eyedropper 💧 first (or right-click the picture)",
        "zh": "请先用取色器 💧 取色（或右键点击图片）"},
    "viewer.fill_saving": {
        "ru": "Закрашиваю выделенную область…",
        "en": "Filling the selected area…",
        "zh": "正在填充所选区域…"},
    "viewer.fill_saved": {
        "ru": "Закрашено: {name} ({w}×{h}) — оригинал не тронут",
        "en": "Filled: {name} ({w}×{h}) — the original is untouched",
        "zh": "已填充：{name}（{w}×{h}）— 原图未变"},
    "viewer.fill_save_err": {
        "ru": "Не удалось закрасить: {err}", "en": "Failed to fill: {err}", "zh": "填充失败：{err}"},
    "log.event.fill": {
        "ru": "Закрашена область картинки: {src} → {dst} ({w}×{h})",
        "en": "Image area filled: {src} → {dst} ({w}×{h})",
        "zh": "已填充图片区域：{src} → {dst}（{w}×{h}）"},
    "log.event.fill_err": {
        "ru": "Не удалось закрасить {name}: {err}",
        "en": "Failed to fill {name}: {err}",
        "zh": "无法填充 {name}：{err}"},
    "perf.op.fill": {
        "ru": "fill: {name}", "en": "fill: {name}", "zh": "fill：{name}"},
    # ---------- панель инструментов картинки под верхней панелью (v0.8.9) ----------
    "viewer.tools_title": {
        "ru": "Инструменты картинки:",
        "en": "Image tools:",
        "zh": "图片工具："},
    "viewer.tools_tip": {
        "ru": "Панель инструментов картинки: «⇲ Размер», «✂ Обрезать»,\n"
              "«💧 Пипетка», «🪣 Закрасить» и сопутствующие кнопки —\n"
              "всё работает с картинкой, открытой в просмотре справа.",
        "en": "Image tools panel: “⇲ Resize”, “✂ Crop”, “💧 Eyedropper”,\n"
              "“🪣 Fill” and related buttons — everything works on the\n"
              "image open in the preview on the right.",
        "zh": "图片工具面板：“⇲ 大小”“✂ 裁剪”“💧 吸管”“🪣 填充”\n"
              "及相关按钮 — 全部作用于右侧预览中打开的图片。"},
    "viewer.home": {
        "ru": "🏠 Домой", "en": "🏠 Home", "zh": "🏠 主目录"},
    "viewer.pictures": {
        "ru": "🖼 Изображения", "en": "🖼 Pictures", "zh": "🖼 图片"},
    "viewer.drive_root": {
        "ru": "Диск /", "en": "Drive /", "zh": "磁盘 /"},
    "viewer.free_space": {
        "ru": "Свободно: {free} из {total}", "en": "Free: {free} of {total}", "zh": "可用：{free} / {total}"},
    "viewer.folders_search_ph": {
        "ru": "🔍 Фильтр папок…", "en": "🔍 Filter folders…", "zh": "🔍 筛选文件夹…"},
    "viewer.folders_search_tip": {
        "ru": "Пока вы вводите буквы, в дереве остаются только папки,\n"
              "в имени которых они есть — остальные скрываются, а совпавшие\n"
              "ветки раскрываются. Ищется вглубь ВЫДЕЛЕННОЙ папки или диска:\n"
              "что подсвечено в дереве, то и обыскивается (чужие диски не\n"
              "трогаются — поиск не растягивается на все устройства).\n"
              "Ничего не выделено — поиск по всем дискам. Регистр не важен,\n"
              "масок нет. Enter — открыть первую найденную, Esc — очистить поле.",
        "en": "As you type, the tree keeps only folders whose names contain\n"
              "these letters — the rest are hidden, and matching branches\n"
              "expand. The search goes deep into the HIGHLIGHTED folder or\n"
              "drive: whatever is selected in the tree is what gets searched\n"
              "(other drives are not touched, so the search does not crawl\n"
              "every device). With nothing selected, all drives are searched.\n"
              "Case-insensitive, no masks.\n"
              "Enter opens the first match, Esc clears the field.",
        "zh": "输入时，树中只保留名称包含这些字母的文件夹\n"
              "（其余隐藏，匹配的分支自动展开）。搜索深入到树中当前\n"
              "选中的文件夹或磁盘内（不遍历其他磁盘，因此不会在\n"
              "所有设备上慢慢搜索）；若未选中任何内容，则搜索所有磁盘。\n"
              "不区分大小写，无通配符。回车打开第一个结果，Esc 清空输入框。"},
    "viewer.folders_found": {
        "ru": "Найдено папок: {n}", "en": "Folders found: {n}", "zh": "已找到文件夹：{n}"},
    "viewer.folders_found_in": {
        "ru": "Найдено папок: {n} — в «{where}»",
        "en": "Folders found: {n} — in “{where}”",
        "zh": "已找到文件夹：{n}（在“{where}”内）"},
    "viewer.folders_none": {
        "ru": "Папок с таким именем не найдено",
        "en": "No folders with this name",
        "zh": "未找到同名文件夹"},
    "viewer.folders_none_in": {
        "ru": "Папок с таким именем не найдено (искали в «{where}»)",
        "en": "No folders with this name (searched in “{where}”)",
        "zh": "未找到同名文件夹（搜索范围：“{where}”）"},
    "viewer.ignore_dash": {
        "ru": "игнорировать дефис", "en": "ignore hyphens", "zh": "忽略连字符"},
    "viewer.ignore_dash_tip": {
        "ru": "Искать, не различая дефисы: запрос «23542-23523» найдёт и «2354223523»,\n"
              "и «23542-23523», и наоборот — дефис может стоять не там или отсутствовать.\n"
              "Удобно для артикулов запчастей. Настройка запоминается.",
        "en": "Match without hyphens: the query “23542-23523” finds “2354223523”\n"
              "and “23542-23523” alike — the hyphen may sit elsewhere or be missing.\n"
              "Handy for part numbers. The setting is remembered.",
        "zh": "匹配时不区分连字符：查询“23542-23523”同样能找到“2354223523”\n"
              "和“23542-23523”，反之亦然 — 连字符可能位置不同或没有。\n"
              "适用于零件编号。设置会被记住。"},
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
    "ws.all_query_ph": {
        "ru": "Запрос для всех поисковиков… (Enter — искать везде)",
        "en": "Query for all search engines… (Enter to search everywhere)",
        "zh": "所有搜索引擎共用关键词…（回车全局搜索）"},
    "ws.all_find": {
        "ru": "🔎 Найти везде", "en": "🔎 Search everywhere", "zh": "🔎 全局搜索"},
    "ws.all_find_tip": {
        "ru": "Открыть этот запрос во всех {n} поисковиках сразу — по вкладке на каждый;\nвкладки, уже открытые для этих поисковиков, обновят выдачу",
        "en": "Run this query in all {n} search engines at once — a tab per engine;\ntabs already open for these engines reload their results",
        "zh": "一次在全部 {n} 个搜索引擎中搜索该关键词 — 每个引擎一个标签页；\n已打开的标签页会重新加载搜索结果"},
    "ws.engine_tip": {
        "ru": "Поисковая система", "en": "Search engine", "zh": "搜索引擎"},
    "ws.cb_title": {
        "ru": "Отметить для скачивания большого оригинала",
        "en": "Mark for downloading the full-size original",
        "zh": "勾选以下载原图"},
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
    "ws.tab_new": {
        "ru": "Новая вкладка поиска", "en": "New search tab", "zh": "新建搜索标签页"},
    "ws.tab_new_tip": {
        "ru": "Ещё одна вкладка поиска — со своим поисковиком и браузером (Ctrl+T).\n"
              "Заголовок вкладки — выбранный поисковик, цвет — его фирменный.",
        "en": "One more search tab with its own engine and browser (Ctrl+T).\n"
              "The tab title is the engine, the color is its brand one.",
        "zh": "再开一个搜索标签页 — 独立的搜索引擎和浏览器 (Ctrl+T)。\n标签页标题为搜索引擎，颜色为其品牌色。"},
    "ws.tab_duplicate": {
        "ru": "Дублировать вкладку", "en": "Duplicate tab", "zh": "复制标签页"},
    "ws.tab_duplicate_tip": {
        "ru": "Тот же поисковик и тот же запрос — в новой вкладке",
        "en": "Same engine and same query in a new tab",
        "zh": "在新标签页中使用相同搜索引擎和查询"},
    "ws.tab_close": {
        "ru": "Закрыть вкладку", "en": "Close tab", "zh": "关闭标签页"},
    "ws.tab_close_others": {
        "ru": "Закрыть другие вкладки", "en": "Close other tabs", "zh": "关闭其他标签页"},
    "ws.tab_close_right": {
        "ru": "Закрыть вкладки справа", "en": "Close tabs to the right", "zh": "关闭右侧标签页"},
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
    # ---------- вкладка «Журнал» и события журнала ----------
    "log.title": {
        "ru": "Журнал работы", "en": "Activity log", "zh": "运行日志"},
    "log.empty": {
        "ru": "Здесь появится хроника работы: открытие папок, поиск,\n"
              "перетаскивание, загрузки и ошибки.",
        "en": "The activity log will appear here: folder opening, search,\n"
              "drag-and-drop, downloads and errors.",
        "zh": "这里将显示运行记录：打开文件夹、搜索、\n拖放、下载和错误。"},
    "log.clear": {
        "ru": "🧹 Очистить", "en": "🧹 Clear", "zh": "🧹 清空"},
    "log.clear_tip": {
        "ru": "Очистить журнал", "en": "Clear the log", "zh": "清空日志"},
    "log.copy": {
        "ru": "📋 Копировать всё", "en": "📋 Copy all", "zh": "📋 复制全部"},
    "log.copy_tip": {
        "ru": "Скопировать весь журнал в буфер обмена — удобно приложить к отчёту об ошибке",
        "en": "Copy the whole log to the clipboard — handy to attach to a bug report",
        "zh": "将整个日志复制到剪贴板 — 便于附在错误报告中"},
    "log.copied": {
        "ru": "Журнал скопирован в буфер обмена ({n} строк)",
        "en": "Log copied to the clipboard ({n} lines)",
        "zh": "日志已复制到剪贴板（{n} 行）"},
    "log.cleared": {
        "ru": "Журнал очищен", "en": "Log cleared", "zh": "日志已清空"},
    "log.event.tab_opened": {
        "ru": "Журнал готов", "en": "Log is ready", "zh": "日志已就绪"},
    "log.event.start": {
        "ru": "Image Hunter {version} запущен",
        "en": "Image Hunter {version} started",
        "zh": "Image Hunter {version} 已启动"},
    "log.event.folder": {
        "ru": "Открыта папка: {folder} — {n} картинок",
        "en": "Folder opened: {folder} — {n} images",
        "zh": "已打开文件夹：{folder} — {n} 张图片"},
    "log.event.fav_add": {
        "ru": "В избранное добавлена папка: {folder} (всего {n})",
        "en": "Folder added to favorites: {folder} ({n} total)",
        "zh": "已将文件夹加入收藏夹：{folder}（共 {n} 个）"},
    "log.event.fav_remove": {
        "ru": "Папка убрана из избранного: {folder} (осталось {n})",
        "en": "Folder removed from favorites: {folder} ({n} left)",
        "zh": "已从收藏夹移除文件夹：{folder}（剩余 {n} 个）"},
    "log.event.search_done": {
        "ru": "Поиск «{q}»: найдено {n}",
        "en": "Search “{q}”: found {n}",
        "zh": "搜索“{q}”：找到 {n}"},
    "log.event.folder_filter": {
        "ru": "Фильтр папок «{q}»: найдено {n}",
        "en": "Folder filter “{q}”: {n} found",
        "zh": "文件夹筛选“{q}”：找到 {n} 个"},
    "log.event.folder_filter_in": {
        "ru": "Фильтр папок «{q}»: найдено {n} (в «{where}»)",
        "en": "Folder filter “{q}”: {n} found (in “{where}”)",
        "zh": "文件夹筛选“{q}”：找到 {n} 个（在“{where}”内）"},
    "log.event.gpu_off": {
        "ru": "Сессия Wayland, но плагин wayland не загрузился — встроенный браузер "
              "рендерит программно (защита от зависаний).\nВернуть GPU можно "
              "переменной окружения IH_GPU=1.",
        "en": "Wayland session, but the wayland platform plugin failed to load — the "
              "built-in browser renders in software (freeze protection).\nSet the "
              "IH_GPU=1 environment variable to re-enable GPU.",
        "zh": "Wayland 会话中 wayland 平台插件加载失败——内置浏览器改用软件渲染"
              "（防止卡死）。\n设置环境变量 IH_GPU=1 可恢复 GPU 加速。"},
    "log.event.render_gone": {
        "ru": "[{engine}] Процесс отрисовки вкладки упал (код {code}) — перезапускаю…",
        "en": "[{engine}] Tab render process crashed (code {code}) — restarting…",
        "zh": "[{engine}] 标签页渲染进程崩溃（代码 {code}）——正在重启……"},
    "log.event.load_watchdog": {
        "ru": "[{engine}] Страница не открылась за {sec} с — загрузка остановлена: {url}",
        "en": "[{engine}] Page did not load within {sec} s — load stopped: {url}",
        "zh": "[{engine}] 页面在 {sec} 秒内未加载完成——已停止加载:{url}"},
    "log.event.serp_boxes": {
        "ru": "[{engine}] Выдача: плиток с чекбоксами: {count} (фреймов: {frames})",
        "en": "[{engine}] Image SERP: tiles with checkboxes: {count} (frames: {frames})",
        "zh": "[{engine}] 图片搜索结果:带复选框的图块:{count}(框架:{frames})"},
    "log.event.serp_boxes_zero": {
        "ru": "[{engine}] Выдача найдена, но плиток для чекбоксов не распознано (фреймов: "
              "{frames}) — поисковик сменил разметку. Пришлите этот журнал "
              "разработчику.",
        "en": "[{engine}] Image SERP found, but no checkbox tiles were recognized (frames: "
              "{frames}) — the search engine changed its markup. Please send "
              "this log to the developer.",
        "zh": "[{engine}] 已找到搜索结果页,但未识别出可加复选框的图块(框架:{frames})"
              "——搜索引擎更改了页面结构。请将此日志发送给开发者。"},
    "log.event.sandbox_off": {
        "ru": "Ядро Linux запрещает пользовательские пространства имён — встроенный "
              "браузер работает без песочницы Chromium (иначе вкладки циклически "
              "падали и выглядели зависшими). Вернуть песочницу: IH_NO_SANDBOX=0.",
        "en": "This Linux kernel forbids user namespaces — the built-in browser runs "
              "without the Chromium sandbox (otherwise tabs crashed in a loop and "
              "looked frozen). To re-enable: IH_NO_SANDBOX=0.",
        "zh": "此 Linux 内核禁止用户命名空间——内置浏览器在无 Chromium 沙箱的情况下运行"
              "（否则标签页会反复崩溃并看似卡死）。恢复沙箱请设置:IH_NO_SANDBOX=0。"},
    "log.event.save_file_err": {
        "ru": "[{engine}] ОШИБКА сохранения: {url} — {err}",
        "en": "[{engine}] SAVE ERROR: {url} — {err}",
        "zh": "[{engine}] 保存错误：{url} — {err}"},
    "log.event.dl_file_err": {
        "ru": "ОШИБКА скачивания: {url} — {err}",
        "en": "DOWNLOAD ERROR: {url} — {err}",
        "zh": "下载错误：{url} — {err}"},
    "log.event.avif_no_codec": {
        "ru": "Формат AVIF, но декодер не найден (pillow-avif-plugin).\n"
              "Обновите программу: ImageHunter.bat update",
        "en": "AVIF image but no decoder (pillow-avif-plugin).\nPlease update: ImageHunter.bat update",
        "zh": "AVIF 图片但未找到解码器（pillow-avif-plugin）。\n请更新程序：ImageHunter.bat update"},
    "log.event.search_tabs_restored": {
        "ru": "Вкладки поиска восстановлены: {n}",
        "en": "Search tabs restored: {n}",
        "zh": "已恢复搜索标签页：{n}"},
    "log.event.search_tabs_limit": {
        "ru": "Достигнут предел вкладок поиска ({n})",
        "en": "Search tab limit reached ({n})",
        "zh": "已达到搜索标签页上限（{n}）"},
    "log.event.search_all": {
        "ru": "Поиск везде «{q}»: поисковиков {n}, открыто вкладок {opened}",
        "en": "Search everywhere “{q}”: {n} engines, {opened} tabs opened",
        "zh": "全局搜索“{q}”：{n} 个搜索引擎，新开 {opened} 个标签页"},
    "log.event.drag_start": {
        "ru": "Перетаскивание начато: {n} файлов → {names}",
        "en": "Drag started: {n} files → {names}",
        "zh": "拖放开始：{n} 个文件 → {names}"},
    "log.event.drag_end": {
        "ru": "Перетаскивание завершено: {action}",
        "en": "Drag finished: {action}",
        "zh": "拖放结束：{action}"},
    "log.event.drag_no": {
        "ru": "Плитку зажали и повели, но перетаскивание не началось: {why}",
        "en": "The tile was pressed and moved, but the drag did not start: {why}",
        "zh": "卡片被按住并移动，但拖放未开始：{why}"},
    "log.event.move_start": {
        "ru": "Перемещение начато: {n} файлов → {target}: {names}",
        "en": "Move started: {n} files → {target}: {names}",
        "zh": "移动开始：{n} 个文件 → {target}：{names}"},
    "log.event.move_done": {
        "ru": "Перемещено: {n} → {target}",
        "en": "Moved: {n} → {target}",
        "zh": "已移动：{n} 个 → {target}"},
    "log.event.move_err": {
        "ru": "ОШИБКА перемещения «{path}»: {err}",
        "en": "MOVE ERROR “{path}”: {err}",
        "zh": "移动错误“{path}”：{err}"},
    "log.why.not_selected": {
        "ru": "плитка не выделена",
        "en": "the tile is not selected",
        "zh": "卡片未被选中"},
    "log.act.copy": {
        "ru": "копирование", "en": "copy", "zh": "复制"},
    "log.act.move": {
        "ru": "перемещение", "en": "move", "zh": "移动"},
    "log.act.cancel": {
        "ru": "отменено (файл не брошен)",
        "en": "cancelled (nothing dropped)",
        "zh": "已取消（未放下文件）"},
    "log.event.copy_files": {
        "ru": "Скопировано в буфер обмена: {n} файлов",
        "en": "Copied to clipboard: {n} files",
        "zh": "已复制到剪贴板：{n} 个文件"},
    "log.event.trash": {
        "ru": "Удалено в корзину: {n} — {folder}",
        "en": "Moved to Recycle Bin: {n} — {folder}",
        "zh": "已移入回收站：{n} — {folder}"},
    "log.event.trash_err": {
        "ru": "ОШИБКА удаления: {path} — {err}",
        "en": "DELETE ERROR: {path} — {err}",
        "zh": "删除错误：{path} — {err}"},
    "log.event.delete_perm": {
        "ru": "Удалено окончательно (диск без корзины): {n} — {folder}",
        "en": "Deleted permanently (no Recycle Bin): {n} — {folder}",
        "zh": "已永久删除（磁盘无回收站）：{n} — {folder}"},
    "log.event.rename": {
        "ru": "Переименован файл: {old} → {new}",
        "en": "File renamed: {old} → {new}",
        "zh": "文件已重命名：{old} → {new}"},
    "log.event.rename_err": {
        "ru": "ОШИБКА переименования «{old}»: {err}",
        "en": "RENAME ERROR “{old}”: {err}",
        "zh": "重命名错误“{old}”：{err}"},
    "log.event.collect": {
        "ru": "[{engine}] Собрано ссылок с выдачи: {total}, добавлено в загрузки: {added}",
        "en": "[{engine}] Links collected: {total}, added to downloads: {added}",
        "zh": "[{engine}] 已收集链接：{total}，加入下载：{added}"},
    "log.event.dl_done": {
        "ru": "Загрузка завершена: скачано {ok}, ошибок {fail}",
        "en": "Download batch finished: {ok} downloaded, {fail} errors",
        "zh": "下载批次完成：已下载 {ok} 个，失败 {fail} 个"},
    "log.event.save_done": {
        "ru": "[{engine}] Сохранение завершено: {ok} успешно, ошибок {fail} → {folder}",
        "en": "[{engine}] Saving finished: {ok} saved, {fail} errors → {folder}",
        "zh": "[{engine}] 保存完成：成功 {ok} 个，失败 {fail} 个 → {folder}"},
    "log.event.upd_latest": {
        "ru": "Обновления: последняя версия {version} уже установлена",
        "en": "Updates: the latest version {version} is already installed",
        "zh": "更新：已安装最新版本 {version}"},
    "log.event.upd_available": {
        "ru": "Доступна новая версия: {remote}",
        "en": "New version available: {remote}",
        "zh": "发现新版本：{remote}"},

    # ---------- веб-сервер: удалённый доступ с телефона (v0.8.0) ----------
    "server.title": {
        "ru": "🌐 Веб-сервер — доступ с телефона",
        "en": "🌐 Web server — phone access",
        "zh": "🌐 Web 服务器 — 手机访问"},
    "server.run": {
        "ru": "▶ Запустить сервер",
        "en": "▶ Start the server",
        "zh": "▶ 启动服务器"},
    "server.stop": {
        "ru": "⏹ Остановить сервер",
        "en": "⏹ Stop the server",
        "zh": "⏹ 停止服务器"},
    "server.running": {
        "ru": "Сервер работает — порт {port}",
        "en": "Server is running — port {port}",
        "zh": "服务器运行中 — 端口 {port}"},
    "server.stopped": {
        "ru": "Сервер остановлен (порт {port} сохранён)",
        "en": "Server stopped (port {port} saved)",
        "zh": "服务器已停止（端口 {port} 已保存）"},
    "server.port_lbl": {
        "ru": "Порт:",
        "en": "Port:",
        "zh": "端口："},
    "server.token_lbl": {
        "ru": "Токен доступа (часть адреса):",
        "en": "Access token (part of the address):",
        "zh": "访问令牌（地址的一部分）："},
    "server.token_gen": {
        "ru": "Сгенерировать новый токен",
        "en": "Generate a new token",
        "zh": "生成新令牌"},
    "server.token_copy": {
        "ru": "Скопировать адрес с токеном",
        "en": "Copy the address with the token",
        "zh": "复制带令牌的地址"},
    "server.view_only": {
        "ru": "Только просмотр — без переименования, удаления и удаления фона",
        "en": "View only — no rename, delete or background removal",
        "zh": "仅查看 — 禁止重命名、删除和背景移除"},
    "server.autostart": {
        "ru": "Запускать сервер вместе с программой",
        "en": "Start the server together with the app",
        "zh": "随程序一起启动服务器"},
    "server.apply": {
        "ru": "Применить (и перезапустить сервер, если он работал)",
        "en": "Apply (and restart the server if it was running)",
        "zh": "应用（如服务器在运行则重启）"},
    "server.open_browser": {
        "ru": "🖥 Открыть в браузере на этом компьютере",
        "en": "🖥 Open in the browser on this computer",
        "zh": "🖥 在本机浏览器中打开"},
    "server.urls_lbl": {
        "ru": "Откройте на телефоне (устройства — в одной сети):",
        "en": "Open on your phone (same network):",
        "zh": "在手机上打开（需同一网络）："},
    "server.qr_none": {
        "ru": "QR-код недоступен: библиотека qrcode не установлена",
        "en": "QR code unavailable: the qrcode library is not installed",
        "zh": "二维码不可用：未安装 qrcode 库"},
    "server.qr_install": {
        "ru": "📦 Установить поддержку QR-кода (qrcode)",
        "en": "📦 Install QR support (qrcode)",
        "zh": "📦 安装二维码支持（qrcode）"},
    "server.qr_installing": {
        "ru": "Устанавливаю qrcode…",
        "en": "Installing qrcode…",
        "zh": "正在安装 qrcode…"},
    "server.qr_fail": {
        "ru": "Не удалось установить qrcode: {tail}",
        "en": "Could not install qrcode: {tail}",
        "zh": "无法安装 qrcode：{tail}"},
    "server.firewall": {
        "ru": "Совет: телефон должен быть в той же сети, что и компьютер. Если не подключается — разрешите Image Hunter доступ к частным сетям в брандмауэре.",
        "en": "Tip: the phone must be on the same network as the computer. If it will not connect — allow Image Hunter through the firewall for private networks.",
        "zh": "提示：手机需与电脑在同一网络。如果连不上，请在防火墙中允许 Image Hunter 访问专用网络。"},
    "server.mode_rw": {
        "ru": "полный доступ",
        "en": "full access",
        "zh": "完全访问"},
    "server.mode_ro": {
        "ru": "только просмотр",
        "en": "view only",
        "zh": "仅查看"},

    # ---------- меню «Модули»: настройка, установка и удаление (v0.8.2) ----------
    "menu.modules": {
        "ru": "&Модули", "en": "&Modules", "zh": "模块(&M)"},
    "modules.panel": {
        "ru": "🌐 Панель веб-сервера (порт, токен, QR-код)…",
        "en": "🌐 Web server panel (port, token, QR code)…",
        "zh": "🌐 Web 服务器面板（端口、令牌、二维码）…"},
    "modules.model_menu": {
        "ru": "Модель rembg", "en": "rembg model", "zh": "rembg 模型"},
    "modules.rembg_header": {
        "ru": "🪄 Удаление фона (rembg): {state}",
        "en": "🪄 Background removal (rembg): {state}",
        "zh": "🪄 删除背景（rembg）：{state}"},
    "modules.wm_header": {
        "ru": "🧽 Водяные знаки (Florence-2 + LaMa): {state}",
        "en": "🧽 Watermark removal (Florence-2 + LaMa): {state}",
        "zh": "🧽 水印去除（Florence-2 + LaMa）：{state}"},
    "modules.installed": {
        "ru": "установлен", "en": "installed", "zh": "已安装"},
    "modules.not_installed": {
        "ru": "не установлен", "en": "not installed", "zh": "未安装"},
    "modules.state_on": {
        "ru": "включён", "en": "on", "zh": "开"},
    "modules.state_off": {
        "ru": "выключен", "en": "off", "zh": "关"},
    # версии установленных модулей в меню «Модули» (v0.8.17): под
    # заголовком-состоянием — недоступные строки со справкой; имена
    # пакетов/моделей не переводятся, переводятся только подписи
    "modules.versions": {
        "ru": "Версии: {list}", "en": "Versions: {list}", "zh": "版本：{list}"},
    "modules.models": {
        "ru": "Модели: {list}", "en": "Models: {list}", "zh": "模型：{list}"},
    "modules.version_unknown": {
        "ru": "версия неизвестна", "en": "version unknown", "zh": "版本未知"},
    "modules.model_not_downloaded": {
        "ru": "не скачана", "en": "not downloaded", "zh": "未下载"},
    "modules.size_mb": {
        "ru": "{mb} МБ", "en": "{mb} MB", "zh": "{mb} MB"},
    # перезагрузка программы из меню «Модули» (v0.8.17): новый экземпляр
    # подхватывает обновлённые версии модулей — подсказка после «Обновить
    # модуль» (v0.8.15) больше не требует закрывать программу руками
    "modules.restart": {
        "ru": "🔄 Перезагрузить Image Hunter",
        "en": "🔄 Restart Image Hunter",
        "zh": "🔄 重启 Image Hunter"},
    "modules.restart_title": {
        "ru": "Перезагрузка Image Hunter",
        "en": "Image Hunter restart",
        "zh": "重启 Image Hunter"},
    "modules.restart_fail": {
        "ru": "Не удалось запустить новый экземпляр Image Hunter — запустите программу вручную.",
        "en": "Failed to start a new Image Hunter instance — please start the app manually.",
        "zh": "无法启动新的 Image Hunter 实例——请手动启动程序。"},
    "log.event.app_restart": {
        "ru": "🔄 Перезагружаю Image Hunter…",
        "en": "🔄 Restarting Image Hunter…",
        "zh": "🔄 正在重启 Image Hunter…"},
    "log.event.server_autostart": {
        "ru": "🌐 Автостарт веб-сервера: {state}",
        "en": "🌐 Web server autostart: {state}",
        "zh": "🌐 Web 服务器自启动：{state}"},
    "log.event.server_start": {
        "ru": "🌐 Веб-сервер запущен: порт {port}, режим: {mode}",
        "en": "🌐 Web server started: port {port}, mode: {mode}",
        "zh": "🌐 Web 服务器已启动：端口 {port}，模式：{mode}"},
    "log.event.server_stop": {
        "ru": "🌐 Веб-сервер остановлен (порт {port})",
        "en": "🌐 Web server stopped (port {port})",
        "zh": "🌐 Web 服务器已停止（端口 {port}）"},
    "log.event.webdl_start": {
        "ru": "🛰 Скачивание картинок из интернета: {n} шт. → папка «{folder}»",
        "en": "🛰 Downloading images from the web: {n} → folder “{folder}”",
        "zh": "🛰 从网络下载图片：{n} 个 → 文件夹「{folder}」"},
    "log.event.webdl": {
        "ru": "🛰 Скачана картинка: {name}",
        "en": "🛰 Image downloaded: {name}",
        "zh": "🛰 图片已下载：{name}"},
    "log.event.webdl_err": {
        "ru": "🛰 Не удалось скачать {url}: {err}",
        "en": "🛰 Failed to download {url}: {err}",
        "zh": "🛰 下载失败 {url}：{err}"},
    # ---------- деятельность веб-сервера и API в журнале программы ----------
    "log.event.srv_conn": {
        "ru": "🌐 Открыт веб-интерфейс ({addr})",
        "en": "🌐 Web UI opened ({addr})",
        "zh": "🌐 已打开网页界面（{addr}）"},
    "log.event.srv_search": {
        "ru": "🔎 Поиск с телефона «{q}» ({engine}): найдено {n}",
        "en": "🔎 Phone search “{q}” ({engine}): {n} found",
        "zh": "🔎 手机搜索「{q}」（{engine}）：找到 {n} 条"},
    "log.event.srv_search_err": {
        "ru": "🔎 Поиск с телефона «{q}» ({engine}) не удался: {err}",
        "en": "🔎 Phone search “{q}” ({engine}) failed: {err}",
        "zh": "🔎 手机搜索「{q}」（{engine}）失败：{err}"},
    "log.event.srv_dl_dev": {
        "ru": "⬇ Сохранено на устройство с телефона: {name}",
        "en": "⬇ Saved to device from phone: {name}",
        "zh": "⬇ 已从手机保存到设备：{name}"},
    "log.event.srv_rename": {
        "ru": "✏️ Переименовано с телефона: {old} → {new}",
        "en": "✏️ Renamed from phone: {old} → {new}",
        "zh": "✏️ 手机重命名：{old} → {new}"},
    "log.event.srv_delete": {
        "ru": "🗑 Удалено с телефона: {n} шт. ({names})",
        "en": "🗑 Deleted from phone: {n} ({names})",
        "zh": "🗑 已从手机删除：{n} 个（{names}）"},
    "log.event.srv_nobg": {
        "ru": "🪄 Удаление фона с телефона: {n} файл(ов), модель {model}",
        "en": "🪄 Background removal from phone: {n} file(s), model {model}",
        "zh": "🪄 手机启动去除背景：{n} 个文件，模型 {model}"},
    "log.event.srv_denied": {
        "ru": "🔒 Отказано (только просмотр): {op}",
        "en": "🔒 Denied (view-only): {op}",
        "zh": "🔒 已拒绝（仅查看）：{op}"},
    "srv.op.rename": {
        "ru": "переименование", "en": "rename", "zh": "重命名"},
    "srv.op.delete": {
        "ru": "удаление", "en": "delete", "zh": "删除"},
    "srv.op.rembg": {
        "ru": "удаление фона", "en": "background removal", "zh": "去除背景"},
    "srv.op.download": {
        "ru": "скачивание в папку", "en": "download to folder", "zh": "下载到文件夹"},
    # ---------- отладка производительности: тайминги операций в журнале ----------
    "log.event.timing": {
        "ru": "⏱ {op}: {ms} мс{extra}",
        "en": "⏱ {op}: {ms} ms{extra}",
        "zh": "⏱ {op}：{ms} 毫秒{extra}"},
    "log.event.timing_slow": {
        "ru": "⏱ МЕДЛЕННО: {op} — {ms} мс, это блокирует интерфейс{extra}",
        "en": "⏱ SLOW: {op} — {ms} ms, this blocks the UI{extra}",
        "zh": "⏱ 缓慢：{op} —— {ms} 毫秒，这会阻塞界面{extra}"},
    "log.event.timing_slow_worker": {
        "ru": "⏱ МЕДЛЕННО (фоном, интерфейс жив): {op} — {ms} мс{extra}",
        "en": "⏱ SLOW (in background, UI stays alive): {op} — {ms} ms{extra}",
        "zh": "⏱ 缓慢（后台执行，界面正常）：{op} —— {ms} 毫秒{extra}"},
    "log.event.ui_freeze": {
        "ru": "⚠ Интерфейс не отвечал ≈{ms} мс — GUI-поток был заблокирован. "
              "Что происходило перед этим — см. строки ⏱ выше",
        "en": "⚠ The UI did not respond for ≈{ms} ms — the GUI thread was blocked. "
              "See the ⏱ lines above for what happened just before",
        "zh": "⚠ 界面无响应约 {ms} 毫秒——GUI 线程被阻塞。"
              "此前发生了什么，请查看上方的 ⏱ 行"},
    "log.event.watchdog_on": {
        "ru": "Сторож интерфейса включён: зависания GUI-потока будут отмечены в журнале",
        "en": "UI watchdog is on: GUI-thread stalls will be noted in the log",
        "zh": "界面看门狗已开启：GUI 线程卡顿将记录在日志中"},
    "log.event.select_all": {
        "ru": "Выделено файлов: {n} (Ctrl+A)",
        "en": "Selected files: {n} (Ctrl+A)",
        "zh": "已选中文件：{n} 个 (Ctrl+A)"},
    "perf.op.load_folder": {
        "ru": "открытие папки", "en": "open folder", "zh": "打开文件夹"},
    "perf.op.scan_folder": {
        "ru": "сканирование папки", "en": "folder scan", "zh": "扫描文件夹"},
    "perf.op.filter_tree_load": {
        "ru": "догрузка дерева для фильтра", "en": "tree loading for filter",
        "zh": "为筛选加载目录树"},
    "perf.op.folder_filter": {
        "ru": "фильтр папок", "en": "folder filter", "zh": "文件夹筛选"},
    "perf.op.populate_children": {
        "ru": "чтение подпапок «{folder}»", "en": "subfolder scan of “{folder}”",
        "zh": "读取子文件夹“{folder}”"},
    "perf.op.refresh_drives": {
        "ru": "обновление дерева дисков", "en": "drive tree refresh", "zh": "刷新磁盘树"},
    "perf.op.thumbs_batch": {
        "ru": "применение миниатюр", "en": "thumbnail batch", "zh": "应用缩略图"},
    "perf.op.thumb_decode": {
        "ru": "миниатюра «{name}»", "en": "thumbnail “{name}”", "zh": "缩略图“{name}”"},
    "perf.op.view_decode": {
        "ru": "полный просмотр «{name}»", "en": "full view of “{name}”", "zh": "查看原图“{name}”"},
    "perf.op.search_scan": {
        "ru": "поиск по файлам «{q}»", "en": "file search “{q}”", "zh": "文件搜索“{q}”"},
    "perf.op.download": {
        "ru": "скачивание «{name}»", "en": "download “{name}”", "zh": "下载“{name}”"},
    "perf.op.download_batch": {
        "ru": "пакет скачивания", "en": "download batch", "zh": "下载批次"},
    "perf.op.save_file": {
        "ru": "сохранение «{name}»", "en": "save “{name}”", "zh": "保存“{name}”"},
    "perf.op.save_batch": {
        "ru": "пакет сохранения", "en": "save batch", "zh": "保存批次"},
    "perf.op.delete_files": {
        "ru": "удаление файлов", "en": "delete files", "zh": "删除文件"},
    "perf.op.move_files": {
        "ru": "перемещение файлов в папку дерева", "en": "move files to a tree folder",
        "zh": "移动文件到目录树文件夹"},
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
