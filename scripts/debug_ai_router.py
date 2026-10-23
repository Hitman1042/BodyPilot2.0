"""Тест AI-роутера без Telegram."""

import asyncio
from core.ai.ai_router import ai_router


async def test():
    print("🧪 ТЕСТ AI-РОУТЕРА\n")

    try:
        # Тест 1: Кэш
        print("1️⃣ Тест кэша (мгновенно)...")
        result = await ai_router.get_answer(
            user_id=756020893,
            question="сколько белка мне нужно?",
            context={"goal": "gain"},
        )
        print(f"   ✅ Маршрут: {result['route']}")
        print(f"   ✅ Время: {result['response_time_ms']}мс")
        print(f"   ✅ Из кэша: {result['from_cache']}")
        print(f"   ✅ Ответ: {result['answer'][:100]}...\n")
    except Exception as e:
        print(f"   ❌ Ошибка: {e}\n")

    try:
        # Тест 2: Шаблон
        print("2️⃣ Тест шаблона...")
        result = await ai_router.get_answer(
            user_id=756020893,
            question="как набрать вес?",
            context={"goal": "gain"},
        )
        print(f"   ✅ Маршрут: {result['route']}")
        print(f"   ✅ Время: {result['response_time_ms']}мс")
        print(f"   ✅ Ответ: {result['answer'][:100]}...\n")
    except Exception as e:
        print(f"   ❌ Ошибка: {e}\n")

    # Статистика
    print("📊 СТАТИСТИКА:")
    stats = ai_router.get_stats()
    for k, v in stats.items():
        print(f"   {k}: {v}")


if __name__ == "__main__":
    asyncio.run(test())