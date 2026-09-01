# Парсер объявлений Avito (Телефоны, Кемерово)

Парсер с помощью **Selenium + undetected-chromedriver** собирает информацию с частных объявлений категории **"Телефоны"** в Кемерово. Сохраняет в **Google Sheets**. Фильтры: цена ≤15k₽, возраст ≤3 дней, чёрные списки.

## Установка

1. Клонировать репозиторий.
2. `pip install -r requirements.txt`
3. Скопировать `.env.example` → `.env`, заполнить `GOOGLE_SHEET_ID`.
4. Поместить `credentials.json` (Google Service Account).

## Запуск

- CLI: `python avitoparser.py`
- GUI: `python avito_gui.py`

Браузер видимый для капчи. Решайте вручную.

## Настройки

В `.env` или GUI: URLS, MAX_PRICE, MAX_PAGES, MAX_DAYS_AGE, чёрные списки.

## Структура

- `avitoparser.py` — CLI парсер.
- `avito_gui.py` — GUI (CustomTkinter).
- `profiles/` — JSON профили настроек.
