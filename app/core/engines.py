"""Поисковики Image Hunter — чистые данные и логика адресов (без Qt).

Модуль вынесен из app/ui/web_search.py, чтобы «что искать» было отделено
от «чем показывать»: список поисковиков, шаблоны адресов и распознавание
страниц выдачи можно использовать и переиспользовать где угодно
(интерфейс, тесты, будущий фоновый поиск), не тянув за собой QtWebEngine.

Каждый движок — кортеж:
    (полное имя в списке, шаблон поиска, короткое имя вкладки, цвет бренда)
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

# (полное имя в списке, шаблон поиска, короткое имя вкладки, фирменный цвет бренда)
ENGINES: list[tuple[str, str, str, str]] = [
    ("Яндекс.Картинки", "https://ya.ru/images/search?text={}",
     "Яндекс", "#FC3F1D"),
    # iax=images&ia=images — канонический адрес выдачи картинок DDG (устаревший
    # iar=images страницу картинок больше не открывает); kp=1 — строгий safe search
    ("DuckDuckGo (safe)", "https://duckduckgo.com/?q={}&iax=images&ia=images&kp=1&t=h_",
     "DuckDuckGo", "#DE5833"),
    ("Google Картинки", "https://www.google.com/search?q={}&udm=2",
     "Google", "#4285F4"),
    ("Bing Картинки", "https://www.bing.com/images/search?q={}",
     "Bing", "#008373"),
    ("Brave Картинки", "https://search.brave.com/images?q={}",
     "Brave", "#FB542B"),
    ("Startpage Картинки", "https://www.startpage.com/sp/search?query={}&cat=images",
     "Startpage", "#6573FF"),
    ("Mojeek Картинки", "https://www.mojeek.com/images?q={}",
     "Mojeek", "#455A64"),
    ("Baidu Картинки", "https://image.baidu.com/search/index?tn=baiduimage&ie=utf-8&word={}",
     "Baidu", "#2932E1"),
    ("Sogou Картинки", "https://pic.sogou.com/pics?query={}",
     "Sogou", "#FF6A00"),
    ("Naver Картинки", "https://search.naver.com/search.naver?where=image&query={}",
     "Naver", "#03C75A"),
    ("Mail.ru Картинки", "https://go.mail.ru/search_images?q={}",
     "Mail.ru", "#005FF9"),
]

_YANDEX_HOSTS = ("ya.ru", "yandex.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.uz")


def is_image_search_url(url: str) -> bool:
    """Это страница картинок известного поисковика? (только там ставим чекбоксы)"""
    try:
        parts = urlparse(url)
        host = (parts.hostname or "").lower()
        path = parts.path or ""
        query = parse_qs(parts.query or "")
    except Exception:
        return False
    have = lambda k: (query.get(k) or [""])[0]  # noqa: E731
    if any(host == h or host.endswith("." + h) for h in _YANDEX_HOSTS):
        return path.startswith("/images")
    if host.endswith("duckduckgo.com"):
        # выдача картинок: iax/ia (актуально) или iar (старые сохранённые ссылки)
        return "images" in (have("ia"), have("iax"), have("iar"))
    if host.endswith(("google.com", "google.ru", "google.by", "google.kz", "google.com.ua")):
        return (query.get("udm") or [""])[0] == "2" or path.startswith("/imgres")
    if host.endswith("bing.com"):
        return path.startswith("/images")
    if host.endswith("brave.com"):
        return path.startswith("/images")
    if host.endswith("mojeek.com"):
        return path.startswith("/images")
    if host == "image.baidu.com":
        return True
    if host == "pic.sogou.com":
        return True
    if host.endswith("naver.com"):
        return have("where") == "image" or path.startswith("/image-search")
    if host.endswith("startpage.com"):
        return path.startswith(("/sp/search", "/do/search")) and have("cat") == "images"
    if host == "go.mail.ru":
        return path.startswith("/search_images")
    return False
