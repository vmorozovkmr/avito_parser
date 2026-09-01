import os
import json
import re
from datetime import datetime
import time
import threading
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import gspread
import undetected_chromedriver as uc
from urllib.parse import urlparse, parse_qs, urlencode
from utils import (
    DEFAULTS, SELECTORS, DELAYS, random_delay, parse_relative_time_russian_fragment,
    canonicalize_link, is_blacklisted, is_whitelisted, RELATIVE_PATTERN, ABSOLUTE_DAY_MONTH_WITH_TIME
)

class AvitoParser:
    def __init__(self, config, log_callback, stop_event):
        self.config = config
        self.log = log_callback
        self.stop_event = stop_event
        self.driver = None
        self.blacklist_sellers = [
            s.strip().lower()
            for s in config.get("BLACKLIST_SELLERS", "").splitlines()
            if s.strip()
        ]
        self.whitelist_words = [
            w.strip().lower()
            for w in config.get("WHITELIST_WORDS", "").splitlines()
            if w.strip()
        ]
        self.blacklist_words = [
            w.strip().lower()
            for w in config.get("BLACKLIST_WORDS", "").splitlines()
            if w.strip()
        ]
        self.infinite_loop = config.get("INFINITE_LOOP", False)
        self.loop_interval_min = int(config.get("LOOP_INTERVAL_MIN", 30))
        self.new_sheet = config.get("NEW_SHEET", False)
        self.target_sheet_name = config.get("TARGET_SHEET_NAME", "Новые")
        self.main_sheet_name = "Avito"

    def get_driver(self):
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")
        options.add_argument("--log-level=3")
        version_main = int(os.getenv("CHROME_VERSION", "150"))
        self.log(f"✅ Браузер запущен (UC v{version_main})!")
        return uc.Chrome(version_main=version_main, options=options)

    def load_existing_links(self, sheet):
        existing = {}
        try:
            all_values = sheet.get_all_values()
            if not all_values:
                return existing
            headers = all_values[0]
            self.log(f"Лист '{sheet.title}': заголовки {headers[:4] if headers else '[]'}...")
            link_idx = next((i for i, h in enumerate(headers) if any(k in (h or '').lower() for k in ['ссылк', 'link', 'url', 'ссылка'])), 2)
            self.log(f"link_idx={link_idx} ('{headers[link_idx] if link_idx < len(headers) else 'N/A'}') в листе '{sheet.title}'")
            loaded_count = 0
            for row_num, row in enumerate(all_values[1:], start=2):
                if len(row) > link_idx:
                    raw = row[link_idx].strip()
                    if raw:
                        canon = canonicalize_link(raw)
                        if canon:
                            existing[canon] = row_num
                            loaded_count += 1
                            if loaded_count <= 3:
                                self.log(f"  Загружено из '{sheet.title}' row{row_num}: raw='{raw[:60]}...' → canon='{canon}'")
            self.log(f"Загружено {loaded_count} уникальных из '{sheet.title}' (всего {len(existing)})")
        except Exception as e:
            self.log(f"⚠️ Ошибка при чтении '{sheet.title}': {e}")
        return existing

    def update_row(self, sheet, row_num, data):
        try:
            end_col = chr(ord("A") + len(data) - 1)
            rng = f"A{row_num}:{end_col}{row_num}"
            sheet.update(rng, [data], value_input_option="USER_ENTERED")
            return True
        except Exception as e:
            self.log(f"⚠️ Не удалось обновить строку {row_num}: {e}")
            return False

    def append_row_and_get_index(self, sheet, data):
        try:
            sheet.append_row(data, value_input_option="USER_ENTERED")
            return len(sheet.get_all_values())
        except Exception as e:
            self.log(f"⚠️ Не удалось добавить строку: {e}")
            return None

    def get_item_age_days(self, item):
        candidates = []
        try:
            for e in item.find_elements(By.TAG_NAME, SELECTORS['time_tag']):
                dt_attr = e.get_attribute("datetime")
                txt = e.text.strip()
                if dt_attr:
                    try:
                        dt = datetime.fromisoformat(dt_attr)
                        return (datetime.now() - dt).total_seconds() / 86400.0
                    except Exception:
                        pass
                if txt and RELATIVE_PATTERN.search(txt):
                    candidates.append(txt)
        except Exception:
            pass
        for sel in SELECTORS['date']:
            try:
                for e in item.find_elements(By.CSS_SELECTOR, sel):
                    txt = e.text.strip()
                    dt_attr = e.get_attribute("datetime")
                    if dt_attr:
                        try:
                            dt = datetime.fromisoformat(dt_attr)
                            return (datetime.now() - dt).total_seconds() / 86400.0
                        except Exception:
                            pass
                    if txt and (RELATIVE_PATTERN.search(txt) or ABSOLUTE_DAY_MONTH_WITH_TIME.search(txt)):
                        candidates.append(txt)
            except Exception:
                pass
        try:
            full = item.text.strip()
            if full:
                m = RELATIVE_PATTERN.search(full)
                if m:
                    candidates.append(m.group(0))
                m2 = ABSOLUTE_DAY_MONTH_WITH_TIME.search(full)
                if m2:
                    candidates.append(m2.group(0))
        except Exception:
            pass
        for txt in candidates:
            days = parse_relative_time_russian_fragment(txt)
            if days is not None:
                return float(days)
        return None

    def get_seller_name(self, item) -> str:
        for sel in SELECTORS['seller']:
            try:
                for e in item.find_elements(By.CSS_SELECTOR, sel):
                    txt = e.text.strip()
                    if txt and len(txt) < 80:
                        return txt
            except Exception:
                pass
        return ""

    def detect_captcha(self, driver):
        try:
            captcha_selectors = ", ".join(SELECTORS['captcha'])
            if driver.find_elements(By.CSS_SELECTOR, captcha_selectors):
                return True
            url = driver.current_url.lower()
            if "captcha" in url or "sorry" in url:
                return True
            body = driver.find_element(By.TAG_NAME, "body").text.lower()
            if "не робот" in body or ("подтвердите" in body and "робот" in body):
                return True
        except Exception:
            pass
        return False

    def wait_for_captcha(self, driver):
        if not self.detect_captcha(driver):
            return True
        self.log("⚠️ Обнаружена капча. Решите её в окне браузера.")
        while not self.stop_event.is_set():
            random_delay('captcha_check')
            if not self.detect_captcha(driver):
                try:
                    WebDriverWait(driver, 12).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-marker*='item'], article"))
                    )
                    self.log("✅ Капча решена, объявления появились.")
                    return True
                except Exception:
                    try:
                        driver.refresh()
                        WebDriverWait(driver, 12).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-marker*='item'], article"))
                        )
                        return True
                    except Exception:
                        pass
        return False

    def go_to_next_page(self, driver, current_page):
        self.log(f"🔄 Переход на стр {current_page+1} ({len(SELECTORS['next_page'])} селекторов)")
        for sel in SELECTORS['next_page']:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, sel)
                for e in elements:
                    if e.is_displayed() and e.is_enabled():
                        self.log(f"  Клик по {sel}")
                        try:
                            e.click()
                            WebDriverWait(driver, 8).until(lambda d: d.current_url != driver.current_url or EC.presence_of_element_located((By.CSS_SELECTOR, SELECTORS['items'][0])))
                            random_delay('page_short')
                            self.log(f"✅ Переход успешен: {driver.current_url[:80]}...")
                            return True
                        except Exception:
                            driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", e)
                            WebDriverWait(driver, 8).until(lambda d: d.current_url != driver.current_url or EC.presence_of_element_located((By.CSS_SELECTOR, SELECTORS['items'][0])))
                            random_delay('page_short')
                            self.log(f"✅ JS-клик успешен: {driver.current_url[:80]}...")
                            return True
            except Exception as e:
                self.log(f"  Ошибка {sel}: {e}")
                continue

        # Manual URL
        self.log("🔄 Manual URL p={}".format(current_page+1))
        try:
            from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
            parsed = urlparse(driver.current_url)
            qs = parse_qs(parsed.query)
            qs['p'] = [str(current_page + 1)]
            new_query = urlencode(qs, doseq=True)
            new_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
            if new_url != driver.current_url:
                self.log(f"  GET {new_url[:100]}...")
                driver.get(new_url)
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, SELECTORS['items'][0])))
                random_delay('page_short')
                self.log(f"✅ Manual URL успешен")
                return True
        except Exception as e:
            self.log(f"  Manual URL ошибка: {e}")

        # Scroll fallback
        self.log("🔄 Scroll fallback")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        random_delay('page_long')
        if driver.find_elements(By.CSS_SELECTOR, SELECTORS['items'][0]):
            self.log("✅ Scroll загрузил новые")
            return True

        self.log("❌ Нет следующей страницы")
        return False

    def run(self):
        # Подготовка листов
        self.log("✅ Подключаемся к Google Таблице...")
        client = gspread.service_account(filename=DEFAULTS["CREDENTIALS_FILE"])
        workbook = client.open_by_key(DEFAULTS["GOOGLE_SHEET_ID"])
        self.main_sheet = workbook.worksheet(self.main_sheet_name)

        try:
            self.target_sheet = workbook.worksheet(self.target_sheet_name)
            self.log(f"✅ Лист новых: '{self.target_sheet_name}'")
        except gspread.WorksheetNotFound:
            self.target_sheet = workbook.add_worksheet(title=self.target_sheet_name, rows=1000, cols=4)
            self.target_sheet.update("A1", [["Название", "Цена", "Ссылка", "Дата"]])
            self.log(f"✅ Создан лист новых: '{self.target_sheet_name}' с заголовками")
        except Exception as e:
            self.log(f"⚠️ Ошибка листа '{self.target_sheet_name}': {e}. Использую основной.")
            self.target_sheet = self.main_sheet
        else:
            if not self.new_sheet:
                self.target_sheet = self.main_sheet

        if self.blacklist_sellers:
            self.log(f"Чёрный список продавцов: {len(self.blacklist_sellers)} шт.")
        if self.whitelist_words:
            self.log(f"Белый список слов: {len(self.whitelist_words)} шт.")
        self.log(f"Чёрный список слов: {len(self.blacklist_words)} шт.")

        self.log("✅ Google Таблица подключена!")

        self.driver = self.get_driver()
        self.log("✅ Браузер запущен для всего цикла!")

        while not self.stop_event.is_set():
            existing_links_main = self.load_existing_links(self.main_sheet)
            existing_links_target = self.load_existing_links(self.target_sheet) if self.new_sheet else {}
            existing_links = {**existing_links_main, **existing_links_target}
            self.log(f"Найдено {len(existing_links)} уникальных объявлений (Avito+Новые).")

            try:
                total_new = 0
                urls = [u.strip() for u in self.config["URLS"].splitlines() if u.strip()]

                for base_url in urls:
                    if self.stop_event.is_set():
                        break
                    self.log(f"\n🔍 Открываю: {base_url}")
                    self.driver.get(base_url)
                    random_delay('load')
                    if not self.wait_for_captcha(self.driver):
                        self.log("⚠️ Капча не решена — пропускаю URL.")
                        continue

                    for page in range(1, int(self.config["MAX_PAGES"]) + 1):
                        if self.stop_event.is_set():
                            break
                        self.log(f"📄 Страница {page}...")
                        try:
                            WebDriverWait(self.driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-marker*='item'], article"))
                            )
                        except Exception:
                            pass

                        items = []
                        for sel in SELECTORS['items']:
                            items = self.driver.find_elements(By.CSS_SELECTOR, sel)
                            if items:
                                break
                        self.log(f"Найдено: {len(items)} объявлений")

                        for item in items:
                            if self.stop_event.is_set():
                                break
                            try:
                                title = ""
                                for sel in SELECTORS['title']:
                                    try:
                                        title = item.find_element(By.CSS_SELECTOR, sel).text.strip()
                                        break
                                    except Exception:
                                        pass
                                if not title:
                                    continue

                                age_days = self.get_item_age_days(item)
                                if age_days is None or age_days > float(self.config["MAX_DAYS_AGE"]):
                                    continue

                                price_text = ""
                                for sel in SELECTORS['price']:
                                    try:
                                        price_text = item.find_element(By.CSS_SELECTOR, sel).text
                                        break
                                    except Exception:
                                        pass
                                digits = re.sub(r"\D", "", price_text)
                                if not digits:
                                    continue
                                price = int(digits)
                                if price == 0 or price > int(self.config["MAX_PRICE"]):
                                    continue

                                raw_link = ""
                                try:
                                    raw_link = item.find_element(By.TAG_NAME, "a").get_attribute("href") or ""
                                except Exception:
                                    pass
                                canonical = canonicalize_link(raw_link)
                                if not canonical:
                                    continue

                                self.log(f"Парсер: raw='{raw_link[:60]}...' → canon='{canonical}'")

                                seller = self.get_seller_name(item)
                                item_text = item.text

                                reason = is_blacklisted(title, item_text, seller, self.blacklist_sellers, self.blacklist_words)
                                if reason:
                                    self.log(f"⛔ Пропуск: {reason} — {title[:50]}...")
                                    continue

                                if self.whitelist_words and not is_whitelisted(title, item_text, self.whitelist_words):
                                    self.log(f"⛔ Пропуск: не содержит белый список — {title[:50]}...")
                                    continue

                                data = [title, price, canonical, datetime.now().strftime("%Y-%m-%d %H:%M:%S")]

                                if canonical in existing_links:
                                    if not self.new_sheet:
                                        row_num = existing_links_main.get(canonical)
                                        if row_num and self.update_row(self.main_sheet, row_num, data):
                                            self.log(f"🔁 Обновлено в основном: {price}₽ — {title[:55]}...")
                                    else:
                                        self.log(f"⛔ Уже известно (Avito/Новые): {title[:55]}...")
                                else:
                                    # Новое: добавить в оба листа
                                    new_row_main = self.append_row_and_get_index(self.main_sheet, data)
                                    new_row_target = self.append_row_and_get_index(self.target_sheet, data)
                                    if new_row_main and new_row_target:
                                        total_new += 1
                                        self.log(f"✅ Новое в Avito+Новые: {price}₽ — {title[:55]}...")
                                    else:
                                        self.log(f"⚠️ Ошибка добавления нового: {title[:55]}...")
                                random_delay('item')
                            except Exception as e:
                                self.log(f"Ошибка объявления: {e}")

                        if page < int(self.config["MAX_PAGES"]):
                            if not self.go_to_next_page(self.driver, page):
                                self.log("Последняя страница.")
                                break
                            random_delay('page_long')

                self.log(f"\n🎉 Цикл завершён! Добавлено {total_new} новых объявлений.")
            except Exception as e:
                self.log(f"⚠️ Ошибка обработки URL: {e}")
            # НЕ quit driver в цикле

            if not self.infinite_loop or self.stop_event.is_set():
                break

            self.log(f"⏳ Ожидание {self.loop_interval_min} мин до следующего цикла...")
            self.stop_event.wait(timeout=self.loop_interval_min * 60)

        self.log(f"\n🎉 Парсинг завершён!")

    pass  # Браузер закроется при завершении daemon потока