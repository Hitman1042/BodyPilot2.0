"""Парсинг barcode-list.ru через ПОИСК по ключевым словам."""

import sys
import os
import httpx
from bs4 import BeautifulSoup

# Добавляем корень проекта в path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.database import get_db

# Ключевые слова для поиска (по ним найдётся много продуктов)
SEARCH_TERMS = [
    "хлеб",           # Хлебобулочные
    "шоколад",        # Шоколад
    "конфеты",        # Конфеты
    "печенье",        # Печенье
    "молоко",         # Молочные
    "кефир",          # Кисломолочные
    "йогурт",         # Йогурты
    "сок",            # Соки
    "вода",           # Вода
    "чай",            # Чай
    "кофе",           # Кофе
    "сахар",          # Сахар
    "мука",           # Мука
    "крупа",          # Крупы
    "макароны",       # Макароны
    "колбаса",        # Колбасы
    "сыр",            # Сыры
    "масло",          # Масло
    "яйца",           # Яйца
    "курица",         # Курица
    "говядина",       # Говядина
    "свинина",        # Свинина
    "рыба",           # Рыба
    "консервы",       # Консервы
    "овощи",          # Овощи
    "фрукты",         # Фрукты
    "орехи",          # Орехи
    "сухофрукты",     # Сухофрукты
    "снеки",          # Снеки
    "чипсы",          # Чипсы
]

async def parse_search_term(term: str, limit: int = 100):
    """Спарсить поиск по ключевому слову."""
    # Кодируем запрос для URL
    from urllib.parse import quote
    encoded_term = quote(term)

    url = f"https://barcode-list.ru/barcode/RU/Поиск.htm?barcode={encoded_term}"

    print(f"   🔍 Поиск: {term} → {url}")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )

        if resp.status_code != 200:
            print(f"   ❌ Ошибка: {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', class_='table')

        if not table:
            print(f"   ⚠️ Нет таблицы")
            return []

        products = []
        rows = table.find_all('tr')[1:]  # Пропускаем заголовок

        for row in rows[:limit]:
            cells = row.find_all('td')
            if len(cells) >= 2:
                barcode = cells[0].get_text().strip()
                name = cells[1].get_text().strip()

                # Пропускаем пустые штрих-коды
                if not barcode or len(barcode) < 8:
                    continue

                products.append({
                    "barcode": barcode,
                    "name": name,
                    "search_term": term,
                })

        print(f"   ✅ Найдено: {len(products)}")
        return products


async def save_to_db(products: list):
    """Сохранить продукты в локальную БД."""
    conn = get_db()

    # Создаём таблицу если нет
    conn.execute("""
        CREATE TABLE IF NOT EXISTS barcode_cache (
            barcode TEXT PRIMARY KEY,
            name TEXT,
            brand TEXT,
            calories_100g REAL,
            protein_100g REAL,
            fat_100g REAL,
            carbs_100g REAL,
            source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    saved = 0
    skipped = 0
    for p in products:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO barcode_cache 
                (barcode, name, brand, source)
                VALUES (?, ?, ?, ?)
            """, (p["barcode"], p["name"], "Неизвестно", "barcode-list.ru"))
            saved += 1
        except Exception as e:
            skipped += 1

    conn.commit()
    conn.close()
    print(f"\n✅ Сохранено: {saved}, Пропущено: {skipped}")


async def main():
    """Запустить парсинг."""
    print("🚀 Парсинг barcode-list.ru через поиск...")
    print(f"📂 Ключевых слов: {len(SEARCH_TERMS)}")
    print("=" * 60)

    all_products = []
    for i, term in enumerate(SEARCH_TERMS, 1):
        print(f"[{i}/{len(SEARCH_TERMS)}] Категория: {term}")
        products = await parse_search_term(term, limit=50)
        all_products.extend(products)

    print("=" * 60)
    print(f"📊 Всего найдено: {len(all_products)}")

    if all_products:
        await save_to_db(all_products)

    print("✅ Готово!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())