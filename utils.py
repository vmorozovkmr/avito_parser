import os
import re
from datetime import datetime
from typing import Optional
from random import uniform
from time import sleep
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

MONTHS_RU = {
    'янв': 1, 'января': 1, 'январь': 1,
    'фев': 2, 'февраля': 2, 'февраль': 2,
    'мар': 3, 'марта': 3, 'март': 3,
    'апр': 4, 'апреля': 4, 'апрель': 4,
    'май': 5, 'мая': 5,
    'июн': 6, 'июня': 6, 'июнь': 6,
    'июл': 7, 'июля': 7, 'июль': 7,
    'авг': 8, 'августа': 8, 'август': 8,
    'сен': 9, 'сентября': 9, 'сентябрь': 9,
    'окт': 10, 'октября': 10, 'октябрь': 10,
    'ноя': 11, 'ноября': 11, 'ноябрь': 11,
    'дек': 12, 'декабря': 12, 'декабрь': 12,
}

RELATIVE_PATTERN = re.compile(
    r'\b(?:только что|сейчас|сегодня|вчера|'
    r'\d+\s*(?:минут(?:[а-я]+)?|мин|минута|час(?:а|ов)?|час|ч|дн|день|дня|дней|сутк(?:и)?|нед(?:\.|еля|ели)?|мес(?:\.|яц|ев)?|месяц(?:ев)?|год(?:а|ов)?|лет))\b',
    flags=re.I | re.U
)

ABSOLUTE_DAY_MONTH_WITH_TIME = re.compile(
    r'(\d{1,2})\s+([а-яё]+)(?:\s+в\s+(\d{1,2}:\d{2}))?\s*(\d{4})?',
    flags=re.I | re.U
)

SELECTORS = {
    'items': ["div[data-marker='item']", "article", "[class*='item-']"],
    'title': ["h3", "[data-marker='item-title']", ".title"],
    'price': ["[data-marker='item-price']", ".price"],
    'seller': [
        "[data-marker*='seller']", "[data-marker*='owner']",
        ".seller-info", "[class*='seller']", "[class*='Seller']",
        "a[href*='/user/']", "a[href*='/profile/']"
    ],
    'date': [
        "[data-marker*='item-date']", "[data-marker*='date']",
        ".item-date", ".date", "[class*='date']", ".iva-item-dateStep-uq2W"
    ],
    'next_page': [
        "[data-marker='pagination-button/next']", "a[rel='next']",
        ".pagination-next", ".pagination__next", ".next",
        "button[aria-label*='Следующая']", "[data-marker*='page-next']", ".pagination-button-next", "a[data-marker*='next']",
        "button[title*='Далее']", "[role='button'][data-marker*='next']"
    ],
    'captcha': [
        "iframe[src*='recaptcha'], div.g-recaptcha",
        "input[id*='captcha'], img[src*='captcha'], div[class*='captcha']"
    ],
    'time_tag': "time"
}

DELAYS = {
    'load': (4, 0),
    'item': (0.5, 1.2),
    'page_short': (2, 3.5),
    'page_long': (5, 9),
    'captcha_check': (2, 0)
}

def random_delay(delay_key: str):
    """Случайная задержка по ключу."""
    min_sec, max_sec = DELAYS.get(delay_key, (1, 2))
    sleep(uniform(min_sec, max_sec))

def parse_relative_time_russian_fragment(fragment: str) -> Optional[float]:
    if not fragment:
        return None
    s = re.sub(r'\s+', ' ', fragment.strip().lower())
    if 'только что' in s or 'сейчас' in s or 'сегодня' in s:
        return 0.0
    if 'вчера' in s:
        return 1.0
    m = re.search(
        r'(\d+)\s*(минут(?:[а-я]+)?|мин|м|min|минута|час(?:а|ов)?|час|ч|дн|день|дня|дней|сутки|сут|недел|нед\.?|недели|мес|месяц|месяца|месяцев|год|года|лет)',
        s
    )
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith(('мин', 'м')):
            return n / 60.0 / 24.0
        if unit.startswith(('час', 'ч')):
            return n / 24.0
        if unit.startswith(('день', 'сут', 'дн')):
            return float(n)
        if unit.startswith('нед'):
            return float(n * 7)
        if unit.startswith(('мес', 'месяц')):
            return float(n * 30)
        if unit.startswith(('год', 'лет')):
            return float(n * 365)
    m_iso = re.search(r'(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?)', s)
    if m_iso:
        try:
            iso = m_iso.group(1).replace(' ', 'T')
            dt = datetime.fromisoformat(iso)
            return max(0.0, (datetime.now() - dt).total_seconds() / 86400.0)
        except Exception:
            pass
    m = ABSOLUTE_DAY_MONTH_WITH_TIME.search(s)
    if m:
        try:
            day = int(m.group(1))
            month_str = m.group(2)
            time_part = m.group(3)
            year_str = m.group(4)
            month = None
            for key, val in MONTHS_RU.items():
                if month_str.startswith(key):
                    month = val
                    break
            if month:
                year = int(year_str) if year_str else datetime.now().year
                hour = minute = 0
                if time_part:
                    try:
                        parts = time_part.split(':')
                        hour, minute = int(parts[0]), int(parts[1])
                    except Exception:
                        pass
                dt = datetime(year, month, day, hour, minute)
                now = datetime.now()
                if dt > now:
                    dt = datetime(year - 1, month, day, hour, minute)
                return max(0.0, (now - dt).total_seconds() / 86400.0)
        except Exception:
            pass
    return None

def canonicalize_link(raw_link: str) -> str:
    if not raw_link:
        return ""
    link = raw_link.strip()
    if link.startswith("//"):
        link = "https:" + link
    if link.startswith("/"):
        link = "https://www.avito.ru" + link
    parsed = urlparse(link)
    scheme = parsed.scheme or "https"
    netloc = (parsed.netloc or "").lower().replace("m.avito.ru", "www.avito.ru")
    if ":" in netloc:
        netloc = netloc.split(":", 1)[0]
    path = (parsed.path or "").rstrip("/")
    return urlunparse((scheme, netloc, path, "", "", ""))

def is_blacklisted(title: str, item_text: str, seller: str, blacklist_sellers: list, blacklist_words: list) -> Optional[str]:
    title_l = (title or "").lower()
    text_l = (item_text or "").lower()
    seller_l = (seller or "").lower()
    for ban in blacklist_sellers:
        if ban and ban in seller_l:
            return f"продавец «{seller}» в чёрном списке"
    for word in blacklist_words:
        if word and (word in title_l or word in text_l):
            return f"слово «{word}» в объявлении"
    return None


def is_whitelisted(title: str, item_text: str, whitelist_words: list) -> bool:
    """Проверяет наличие слов из белого списка в заголовке или тексте."""
    if not whitelist_words:
        return True
    title_l = title.lower()
    text_l = item_text.lower()
    for word in whitelist_words:
        if word.strip().lower() in title_l or word.strip().lower() in text_l:
            return True
    return False


DEFAULTS = {
    "GOOGLE_SHEET_ID": os.getenv("GOOGLE_SHEET_ID", "1ivcv6KWBoUENMuIP2UQfvmURri_DziLH8pNpsaf1uzE"),
    "CREDENTIALS_FILE": os.getenv("CREDENTIALS_FILE", "credentials.json"),
    "SHEET_NAME": os.getenv("SHEET_NAME", "Avito"),
    "PROFILES_DIR": "profiles",
    "URLS": os.getenv("URLS", "https://www.avito.ru/kemerovo/telefony"),
    "MAX_PRICE": os.getenv("MAX_PRICE", "15000"),
    "MAX_PAGES": os.getenv("MAX_PAGES", "50"),
    "MAX_DAYS_AGE": os.getenv("MAX_DAYS_AGE", "3"),
}