"""Gemini AI клиент для BodyPilot."""

import json
import aiohttp
from typing import Optional, Dict, List, Any

from core.config import settings

GEMINI_API_KEY = settings.GEMINI_API_KEY
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _model_chain() -> list:
    """Основная модель + fallback-модели из настроек (без дублей)."""
    chain = [settings.GEMINI_MODEL]
    for m in settings.GEMINI_MODELS.split(","):
        m = m.strip()
        if m and m not in chain:
            chain.append(m)
    return chain


def _model_url(model: str) -> str:
    return f"{GEMINI_BASE_URL}/{model}:generateContent"


COACH_PERSONA = """ХАРАКТЕР КОУЧА:
Ты — свой тренер, а не строгий контролёр. Общайся на «ты», по-русски, коротко и поддерживающе. Отмечай даже маленькие успехи. Допускай лёгкий добрый юмор без мемов и занудства. Никогда не ругай за срывы: спокойно скажи, что завтра можно вернуться к плану, и предложи один простой следующий шаг."""

CHAT_TOOLS_SYSTEM_INSTRUCTION = f"""Ты — AI-коуч BodyPilot, эксперт по фитнесу и питанию. Отвечай по-русски, кратко и по делу (2-5 предложений), без markdown-заголовков.

{COACH_PERSONA}

У тебя есть инструменты (function calling):
- log_food — записать ОДИН приём пищи в дневник питания (КБЖУ укажи на ВЕСЬ вес порции, посчитай сам по своим знаниям)
- log_food_batch — записать НЕСКОЛЬКО блюд/приёмов пищи за раз (массив items, максимум 10 позиций)
- adjust_last_food_entry — скорректировать последнюю запись еды за сегодня (умножить порцию на multiplier или задать новый вес new_weight_g)
- get_today_nutrition — сводка сегодняшнего питания и нормы КБЖУ
- get_nutrition_history — история питания за N дней (макс 14)
- log_weight — записать вес
- update_profile — изменить профиль (цель, активность, вес, рост, возраст)
- get_workout_plan_today — план тренировки на сегодня
- log_workout_done — записать ВЫПОЛНЕННУЮ тренировку, о которой отчитался пользователь (длительность, описание, упражнения)
- get_weekly_stats — статистика за 7 дней
- set_training_preferences — сохранить условия тренировок (место home/gym/outdoor, инвентарь, частота, длительность) и перегенерировать план тренировки
- regenerate_workout_plan — перегенерировать план тренировки на сегодня
- set_food_preferences — сохранить нелюбимые продукты/особенности диеты и перегенерировать план питания
- regenerate_meal_plan — перегенерировать план питания на сегодня

ПРАВИЛА:
1. Если пользователь сообщает, что съел/выпил что-то — в ЛЮБОМ формате («съел яблоко», «было 2 блина», «выпил латте», «перекусил орехами») — ВСЕГДА вызывай log_food. Сам оцени КБЖУ и типичный вес порции, если вес не указан, и укажи в ответе, какой вес взял. Не переспрашивай уточнений без крайней нужды.
2. Если пользователь уточняет количество/вес чего-то НЕДАВНО записанного («таких 2 штуки», «съел ещё одно», «это было 300 грамм») — используй контекст последних событий в истории (сообщения вида «[событие: записано ...]») и вызывай adjust_last_food_entry.
3. Вес пользователя, профиль и прочие данные меняй ТОЛЬКО когда пользователь явно просит («запиши», «поставь», «обнови»). На вопросы-справки отвечай текстом без вызова инструментов.
4. После выполнения действия кратко подтверди его (например: «Записал: гречка с курицей, 200 г — 220 ккал»).
5. Если инструмент вернул ошибку — объясни пользователю простыми словами, что пошло не так.
6. Не давай медицинских рекомендаций.
7. У тебя ВСЕГДА есть актуальные данные пользователя (блок «ПРОФИЛЬ И СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЯ» ниже в этой инструкции) плюс инструменты. НИКОГДА не проси пользователя назвать вес, рост, цель или нормы КБЖУ — они у тебя есть. Отвечай предметно, со ссылкой на его цифры. Если блока с данными нет (профиль не заполнен) — мягко предложи пройти регистрацию командой /register.
8. Когда пользователь просит изменить план тренировок или питания, условия тренировок (дома/зал/улица, инвентарь, частота, время) или рацион (нелюбимые продукты, диета) — ВСЕГДА сохраняй это через set_training_preferences / set_food_preferences (они сами перегенерируют планы). При просьбе просто обновить план — regenerate_workout_plan / regenerate_meal_plan. НИКОГДА не говори «план зафиксирован», «план изменён» или «учту», не вызвав соответствующий инструмент.
9. Сообщение может начинаться с префикса «[Голосовое сообщение, расшифровка]:» — это транскрипт голосового сообщения, в нём возможны неточности распознавания; интерпретируй по смыслу, не переспрашивай без крайней нужды.
10. Транскрипт голосового (и вообще любое сообщение) может содержать НЕСКОЛЬКО блюд или приёмов пищи за день («на завтрак омлет, на обед гречка с курицей, вечером творог») — тогда вызывай log_food_batch со ВСЕМИ позициями сразу, сам оценивая вес и КБЖУ каждой. Одно блюдо — можно log_food.
11. Если пользователь отчитывается о выполненной тренировке («сделал тренировку», «сегодня были приседания и отжимания», «пробежал 5 км») — ВСЕГДА вызывай log_workout_done: оцени длительность, если не указана, и занеси упражнения в exercises."""


class GeminiClient:
    """Клиент для работы с Gemini API."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY не найден в .env файле")

        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получить или создать HTTP сессию.

        trust_env=True — подхватывать системный прокси (Win-реестр / env),
        иначе при блокировке Gemini по региону запросы идут напрямую и падают
        с FAILED_PRECONDITION "User location is not supported".
        """
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(trust_env=True)
        return self.session

    async def close(self):
        """Закрыть HTTP сессию."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def _request(
            self,
            prompt: str,
            image_data: bytes = None,
            temperature: float = 0.3,
            max_tokens: int = 1024,
            json_mode: bool = True,
            max_retries: int = 3,
            media_mime_type: str = "image/jpeg",
    ) -> Optional[Dict[str, Any]]:
        """Базовый запрос к Gemini API: цепочка моделей + retry при лимитах.

        Квоты (RPM/TPM/RPD) у Google считаются по каждой модели отдельно,
        поэтому при 429/5xx переходим к следующей модели из _model_chain().
        """
        import asyncio

        parts = []

        if json_mode:
            system_instruction = "Отвечай ТОЛЬКО в формате JSON. Не пиши ничего кроме JSON. Не используй markdown."
            full_prompt = f"{system_instruction}\n\n{prompt}"
        else:
            full_prompt = prompt

        parts.append({"text": full_prompt})

        if image_data:
            import base64
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            parts.append({
                "inline_data": {
                    "mime_type": media_mime_type,
                    "data": image_base64
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json" if json_mode else "text/plain",
            }
        }

        saw_rate_limit = False

        for model in _model_chain():
            url = f"{_model_url(model)}?key={self.api_key}"

            for attempt in range(max_retries):
                try:
                    session = await self._get_session()

                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            data = await response.json()

                            try:
                                text = data["candidates"][0]["content"]["parts"][0]["text"]

                                if json_mode:
                                    text = text.strip()
                                    if text.startswith("```json"):
                                        text = text[7:]
                                    if text.endswith("```"):
                                        text = text[:-3]
                                    text = text.strip()

                                    return json.loads(text)
                                else:
                                    return {"text": text}

                            except (KeyError, IndexError, json.JSONDecodeError) as e:
                                print(f"Gemini parse error ({model}): {e}")
                                return None

                        elif response.status == 429:
                            saw_rate_limit = True
                            error_data = await response.json()
                            retry_delay = 10

                            try:
                                details = error_data.get("error", {}).get("details", [])
                                for detail in details:
                                    if "retryDelay" in detail:
                                        retry_delay = float(detail["retryDelay"].replace("s", ""))
                                        break
                            except Exception:
                                pass

                            if attempt < max_retries - 1:
                                print(f"Gemini rate limit ({model}). Ждём {retry_delay}с... (попытка {attempt + 1}/{max_retries})")
                                await asyncio.sleep(retry_delay)
                                continue
                            # Попытки кончились — переходим к следующей модели
                            print(f"Gemini: квота {model} исчерпана, переключаемся на fallback")
                            break

                        elif response.status in (500, 502, 503):
                            # Временная перегрузка/недоступность модели — короткий бэкофф
                            if attempt < max_retries - 1:
                                delay = 3 * (attempt + 1)
                                print(f"Gemini временно недоступен ({model}, {response.status}). Ждём {delay}с... (попытка {attempt + 1}/{max_retries})")
                                await asyncio.sleep(delay)
                                continue
                            print(f"Gemini {model} недоступен, переключаемся на fallback")
                            break

                        else:
                            error_text = await response.text()
                            print(f"Gemini API error {response.status} ({model}): {error_text}")
                            return None

                except Exception as e:
                    print(f"Gemini request error ({model}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(5)
                        continue
                    break  # к следующей модели

        if saw_rate_limit:
            return {
                "error": "rate_limit",
                "message": "Превышен лимит запросов. Попробуй через несколько минут."
            }
        return None

    # ═══════════════════════════════════════════════════════════
    # МЕТОДЫ ДЛЯ РАЗЛИЧНЫХ ЗАДАЧ
    # ═══════════════════════════════════════════════════════════

    async def recognize_food_from_text(self, user_input: str) -> Optional[Dict]:
        """Распознать еду из текстового ввода."""
        prompt = f"""
Ты — AI-ассистент трекера питания BodyPilot. Извлеки информацию о еде из сообщения пользователя.

Сообщение: "{user_input}"

Верни JSON в формате:
{{
    "food_name": "название блюда или продукта на русском",
    "weight_g": число (вес в граммах, если не указано — 100),
    "calories": число (ккал на ВСЮ порцию weight_g),
    "protein_g": число (белки в граммах на всю порцию),
    "fat_g": число (жиры в граммах на всю порцию),
    "carbs_g": число (углеводы в граммах на всю порцию),
    "meal_type": "breakfast" или "lunch" или "dinner" или "snack",
    "confidence": число 0.0-1.0 (уверенность, что сообщение именно про еду и распознавание верное)
}}

Если сообщение не про еду или не удалось распознать, верни: {{"error": "не распознано", "reason": "причина"}}
"""
        result = await self._request(prompt, json_mode=True)
        return result

    async def recognize_food_from_photo(self, image_data: bytes) -> Optional[Dict]:
        """Распознать фото: блюдо, этикетка с КБЖУ, чек или не еда.

        Один vision-вызов возвращает photo_type ("dish"/"label"/"receipt"/"other")
        и данные, соответствующие типу. Ключи для "dish" не менялись —
        обратная совместимость со старым форматом сохранена.
        """
        prompt = """
Ты — AI-нутрициолог BodyPilot. Проанализируй фото и СНАЧАЛА определи его тип:
- "dish" — готовое блюдо или продукт (тарелка с едой, фрукт, напиток)
- "label" — этикетка/упаковка с таблицей пищевой ценности (КБЖУ на 100 г)
- "receipt" — чек из магазина или кафе со списком покупок/блюд
- "other" — не еда и ничего связанного с питанием

ВЕРНИ ТОЛЬКО JSON. У всех типов есть поле "photo_type".

Если dish — определи название, вес порции, КБЖУ на порцию, тип приёма пищи,
оценку полезности (1-10) и рекомендации:
{
    "photo_type": "dish",
    "food_name": "название на русском",
    "weight_g": число,
    "calories": число (на всю порцию),
    "protein_g": число,
    "fat_g": число,
    "carbs_g": число,
    "meal_type": "breakfast/lunch/dinner/snack",
    "confidence": 0.0-1.0,
    "health_score": 1-10,
    "suggestions": ["совет 1", "совет 2"]
}

Если label — извлеки название продукта и КБЖУ НА 100 Г ровно как на этикетке:
{
    "photo_type": "label",
    "label": {
        "product_name": "название продукта на русском",
        "brand": "бренд или пустая строка",
        "calories_100g": число,
        "protein_100g": число,
        "fat_100g": число,
        "carbs_100g": число
    },
    "confidence": 0.0-1.0
}

Если receipt — извлеки съедобные позиции (пропускай бытовую химию, пакеты,
сдачу и т.п.) и ОЦЕНИ КБЖУ каждой позиции по своим знаниям (на всю порцию/упаковку):
{
    "photo_type": "receipt",
    "receipt": {
        "items": [
            {
                "name": "название позиции на русском",
                "weight_g": число (типичный вес порции/упаковки),
                "calories": число,
                "protein_g": число,
                "fat_g": число,
                "carbs_g": число
            }
        ]
    },
    "confidence": 0.0-1.0
}

Если other:
{"photo_type": "other", "reason": "что на фото"}

Если фото нечитаемо или распознать не удалось:
{"error": "не распознано", "reason": "причина"}
"""
        result = await self._request(
            prompt, image_data=image_data, json_mode=True, max_tokens=2048
        )
        return result

    async def recognize_food_from_voice(
            self,
            audio_bytes: bytes,
            mime_type: str = "audio/ogg",
    ) -> Optional[Dict]:
        """Расшифровать голосовое и извлечь еду (те же поля, что у текста, + transcript)."""
        prompt = """
Ты — AI-ассистент трекера питания BodyPilot. Прислали голосовое сообщение на русском.

ЗАДАЧА:
1. Расшифруй речь (транскрипт).
2. Извлеки информацию о еде из расшифровки.

Верни JSON в формате:
{
    "food_name": "название блюда или продукта на русском",
    "weight_g": число (вес в граммах, если не указано — типичная порция),
    "calories": число (ккал на ВСЮ порцию weight_g),
    "protein_g": число (белки в граммах на всю порцию),
    "fat_g": число (жиры в граммах на всю порцию),
    "carbs_g": число (углеводы в граммах на всю порцию),
    "meal_type": "breakfast" или "lunch" или "dinner" или "snack",
    "confidence": число 0.0-1.0 (уверенность, что речь именно про еду и распознавание верное),
    "transcript": "дословная расшифровка сказанного на русском"
}

Если речь не про еду, неразборчива или не удалось распознать:
{"error": "не распознано", "reason": "причина", "transcript": "что удалось расслышать или пустая строка"}
"""
        result = await self._request(
            prompt, image_data=audio_bytes, media_mime_type=mime_type, json_mode=True
        )
        return result

    async def transcribe_voice(
            self,
            audio_bytes: bytes,
            mime_type: str = "audio/ogg",
    ) -> Optional[Dict]:
        """Транскрибировать голосовое сообщение на русском в текст.

        Возвращает {"transcript": "..."} (или {"error": ...} / None при сбое).
        Никакой интерпретации — только дословная расшифровка; разбор смысла
        дальше делает chat_with_tools с инструментами.
        """
        prompt = """
Ты — модуль распознавания речи BodyPilot. Прислали голосовое сообщение на русском.

ЗАДАЧА: дословно расшифруй речь в текст. Ничего не интерпретируй, не отвечай
на сказанное и не добавляй комментариев — только транскрипт. Сохрани числа,
названия продуктов, блюд и упражнений как сказано.

Верни JSON в формате:
{
    "transcript": "дословная расшифровка сказанного на русском"
}

Если речь неразборчива, слишком тихая или это не русская речь:
{"error": "не распознано", "reason": "причина", "transcript": ""}
"""
        result = await self._request(
            prompt, image_data=audio_bytes, media_mime_type=mime_type,
            json_mode=True, max_tokens=2048,
        )
        return result

    async def analyze_day_nutrition(
            self,
            user_profile: Dict,
            food_log: List[Dict],
            workout_info: Dict = None,
            recovery_info: Dict = None,
            use_cache: bool = True,
    ) -> Optional[Dict]:
        """Анализ питания за день с рекомендациями и кэшированием."""
        from datetime import datetime

        # ПРОВЕРКА КЭША
        if use_cache:
            try:
                from .cache import get_cached, set_cached

                cache_data = {
                    "goal": user_profile.get("goal", "maintain"),
                    "calorie_target": user_profile.get("calorie_target", 2000),
                    "protein_target": user_profile.get("protein_target", 150),
                    "food_log_count": len(food_log),
                    "date": str(datetime.now().date()),
                }

                cached = get_cached("nutrition_analysis", cache_data)
                if cached:
                    print(f"✅ AI nutrition analysis: из кэша (score={cached.get('day_score', '?')})")
                    return cached

            except ImportError:
                print("⚠️ Кэш не подключён, запрашиваем API")
            except Exception as e:
                print(f"⚠️ Ошибка чтения кэша: {e}")

        # ФОРМАТИРОВАНИЕ ДАННЫХ
        log_text = ""
        for entry in food_log:
            meal_type = entry.get("meal_type", "snack")
            meal_names = {"breakfast": "завтрак", "lunch": "обед", "dinner": "ужин", "snack": "перекус"}
            meal_name = meal_names.get(meal_type, meal_type)
            log_text += f"- [{meal_name}] {entry.get('product_name', '?')} ({entry.get('weight_g', 0)}г): {entry.get('calories', 0)} ккал, Б {entry.get('protein_g', 0)}г\n"

        if not log_text:
            log_text = "Пока ничего не съедено."

        workout_text = ""
        if workout_info:
            workout_text = f"ТРЕНИРОВКА СЕГОДНЯ: {workout_info.get('status', 'не было')}\n"

        # ПРОМТ
        prompt = f"""
Ты — AI-нутрициолог BodyPilot. Проанализируй питание пользователя за день.

{COACH_PERSONA}

ДАННЫЕ ПОЛЬЗОВАТЕЛЯ:
- Цель: {user_profile.get('goal', 'maintain')}
- Калории цель: {user_profile.get('calorie_target', 2000)} ккал
- Белок цель: {user_profile.get('protein_target', 150)} г
- Вид спорта: {user_profile.get('sport', 'fitness')}
- Уровень: {user_profile.get('sport_level', 'beginner')}

СЪЕДЕНО ЗА ДЕНЬ:
{log_text}

{workout_text}

ЗАДАЧА:
1. Оцени соответствие питания цели (0-100)
2. Выяви проблемы (недобрал белок, поздно ужинал, мало клетчатки)
3. Дай 3-5 конкретных рекомендаций
4. Если была тренировка — оцени питание вокруг неё

ВЕРНИ ТОЛЬКО JSON:
{{
    "day_score": 0-100,
    "calories_match": true/false,
    "protein_match": true/false,
    "problems": ["проблема 1", "проблема 2"],
    "strengths": ["сильная сторона 1", "сильная сторона 2"],
    "recommendations": [
        {{"priority": "high", "text": "рекомендация 1"}},
        {{"priority": "medium", "text": "рекомендация 2"}},
        {{"priority": "low", "text": "рекомендация 3"}}
    ],
    "workout_nutrition": {{
        "pre_workout": true/false,
        "post_workout": true/false,
        "score": 0-100,
        "advice": "совет по питанию вокруг тренировки"
    }},
    "tomorrow_plan": "план на завтра (2-3 предложения)",
    "motivation": "мотивирующее сообщение (1-2 предложения)"
}}

Если произошла ошибка или недостаточно данных:
{{"error": "ошибка", "message": "описание"}}
"""

        # ЗАПРОС К API
        print(f"🤖 AI nutrition analysis: запрашиваем API...")
        result = await self._request(prompt, json_mode=True)

        # ОБРАБОТКА РЕЗУЛЬТАТА
        if not result:
            print("❌ AI nutrition analysis: пустой ответ от API")
            return None

        if "error" in result:
            error_msg = result.get("error", "")
            if error_msg == "rate_limit":
                print(f"⚠️ AI nutrition analysis: лимит API")
                return {
                    "day_score": 50,
                    "calories_match": None,
                    "protein_match": None,
                    "problems": ["AI временно недоступен"],
                    "strengths": [],
                    "recommendations": [
                        {"priority": "high", "text": "Попробуй позже для детального анализа"}
                    ],
                    "workout_nutrition": {"pre_workout": None, "post_workout": None, "score": None, "advice": ""},
                    "tomorrow_plan": "Продолжай следить за питанием",
                    "motivation": "Каждый день — новый шанс стать лучше!"
                }
            else:
                print(f"❌ AI nutrition analysis: ошибка — {error_msg}")
                return None

        # СОХРАНЕНИЕ В КЭШ
        if use_cache and "error" not in result:
            try:
                from .cache import set_cached
                cache_data = {
                    "goal": user_profile.get("goal", "maintain"),
                    "calorie_target": user_profile.get("calorie_target", 2000),
                    "protein_target": user_profile.get("protein_target", 150),
                    "food_log_count": len(food_log),
                    "date": str(datetime.now().date()),
                }
                set_cached("nutrition_analysis", cache_data, result)
                print(f"✅ AI nutrition analysis: сохранено в кэш (score={result.get('day_score', '?')})")
            except Exception as e:
                print(f"⚠️ Ошибка записи в кэш: {e}")

        return result

    async def recommend_products(
            self,
            current_nutrition: Dict,
            targets: Dict,
            time_of_day: str,
            workout_status: str,
    ) -> Optional[Dict]:
        """Рекомендации по продуктам чтобы добрать нутриенты."""
        prompt = f"""
Ты — AI-нутрициолог BodyPilot. Пользователь хочет добрать нутриенты.

{COACH_PERSONA}

ТЕКУЩАЯ СИТУАЦИЯ:
- Съедено калорий: {current_nutrition.get('calories', 0)} / {targets.get('calories', 2000)}
- Съедено белка: {current_nutrition.get('protein', 0)} / {targets.get('protein', 150)}г
- Съедено углеводов: {current_nutrition.get('carbs', 0)} / {targets.get('carbs', 250)}г
- Съедено жиров: {current_nutrition.get('fat', 0)} / {targets.get('fat', 70)}г
- Время сейчас: {time_of_day}
- Тренировка: {workout_status}

ЗАДАЧА:
1. Определи чего не хватает (белок/углеводы/жиры/клетчатка)
2. Предложи 3-5 конкретных продуктов
3. Укажи сколько грамм каждого продукта съесть
4. Учти время (поздно вечером — не предлагать тяжёлую еду)
5. Учти тренировку (до/после — разные рекомендации)

ВЕРНИ ТОЛЬКО JSON:
{{
    "deficiency": "белок/углеводы/жиры/клетчатка",
    "grams_needed": число,
    "products": [
        {{
            "name": "название продукта",
            "grams": число,
            "calories": число,
            "protein_g": число,
            "reason": "почему этот продукт"
        }}
    ],
    "timing_advice": "когда лучше съесть",
    "warning": "предупреждение если есть"
}}
"""
        result = await self._request(prompt, json_mode=True)
        return result

    async def analyze_workout(
            self,
            workout_data: Dict,
            history: List[Dict],
            recovery: Dict,
            use_cache: bool = True,
    ) -> Optional[Dict]:
        """Анализ качества тренировки с рекомендациями и кэшированием."""
        from datetime import datetime

        # ПРОВЕРКА КЭША
        if use_cache:
            try:
                from .cache import get_cached, set_cached

                cache_data = {
                    "workout_type": workout_data.get("type", "сила"),
                    "duration": workout_data.get("duration", 0),
                    "exercises_count": workout_data.get("exercises_count", 0),
                    "date": str(datetime.now().date()),
                }

                cached = get_cached("workout_analysis", cache_data)
                if cached:
                    print(f"✅ AI workout analysis: из кэша (score={cached.get('workout_score', '?')})")
                    return cached

            except ImportError:
                print("⚠️ Кэш не подключён, запрашиваем API")
            except Exception as e:
                print(f"⚠️ Ошибка чтения кэша: {e}")

        # ФОРМАТИРОВАНИЕ ДАННЫХ
        exercises_text = ""
        if workout_data.get("exercises"):
            for ex in workout_data["exercises"]:
                exercises_text += f"- {ex.get('name', '?')}: {ex.get('sets', 0)} подхода × {ex.get('reps', 0)} повторов, вес {ex.get('weight', 0)}кг\n"
        else:
            exercises_text = "Нет данных"

        history_text = ""
        if history:
            for h in history[:5]:
                history_text += f"- {h.get('date', '?')}: {h.get('type', '?')}, тоннаж {h.get('tonnage', 0)}кг\n"
        else:
            history_text = "Нет предыдущих тренировок"

        # ПРОМТ
        prompt = f"""
        Ты — AI-тренер BodyPilot. Проанализируй тренировку пользователя.

        {COACH_PERSONA}

        ДАННЫЕ ТРЕНИРОВКИ:
        - Тип: {workout_data.get('type', 'сила')}
        - Длительность: {workout_data.get('duration', 0)} мин
        - Упражнений выполнено: {workout_data.get('exercises_count', 0)}
        - Общий тоннаж: {workout_data.get('tonnage', 0)} кг
        - Интенсивность: {workout_data.get('intensity', 5)}/10

        УПРАЖНЕНИЯ:
        {exercises_text}

        ИСТОРИЯ ПОСЛЕДНИХ ТРЕНИРОВОК:
        {history_text}

        ВОССТАНОВЛЕНИЕ:
        - Сон за последнюю неделю: {recovery.get('sleep_hours', 7)} часов
        - Белок за день: {recovery.get('protein_g', 100)}г
        - Дней отдыха: {recovery.get('rest_days', 2)}

        ЗАДАЧА:
        1. Оцени качество тренировки (0-100)
        2. Определи есть прогресс или плато/спад
        3. Выяви проблемы (недовосстановление, слишком легко, перетрен)
        4. Дай рекомендации по следующей тренировке
        5. Предложи корректировку плана если нужно

        ВЕРНИ ТОЛЬКО JSON:
        {{
            "workout_score": 0-100,
            "progress_detected": true/false,
            "progress_percentage": число (от -100 до +100),
            "problems": ["проблема 1", "проблема 2"],
            "strengths": ["сильная сторона 1"],
            "next_workout_advice": [
                {{"exercise": "название упражнения", "change": "увеличить вес на 2.5кг"}},
                {{"exercise": "название упражнения", "change": "добавить 1 подход"}}
            ],
            "recovery_status": "good/needs_attention/poor",
            "recovery_advice": "совет по восстановлению (1-2 предложения)",
            "motivation": "мотивирующее сообщение (1-2 предложения)"
        }}

        Если произошла ошибка или недостаточно данных:
        {{"error": "ошибка", "message": "описание"}}
        """

        # ЗАПРОС К API
        print(f"🤖 AI workout analysis: запрашиваем API...")
        result = await self._request(prompt, json_mode=True)

        # ОБРАБОТКА РЕЗУЛЬТАТА
        if not result:
            print("❌ AI workout analysis: пустой ответ от API")
            return None

        if "error" in result:
            error_msg = result.get("error", "")
            if error_msg == "rate_limit":
                print(f"⚠️ AI workout analysis: лимит API")
                return {
                    "workout_score": 50,
                    "progress_detected": None,
                    "problems": ["AI временно недоступен"],
                    "strengths": [],
                    "next_workout_advice": [],
                    "recovery_status": "unknown",
                    "recovery_advice": "Попробуй позже для детального анализа",
                    "motivation": "Продолжай тренироваться!"
                }
            else:
                print(f"❌ AI workout analysis: ошибка — {error_msg}")
                return None

        # СОХРАНЕНИЕ В КЭШ
        if use_cache and "error" not in result:
            try:
                from .cache import set_cached
                cache_data = {
                    "workout_type": workout_data.get("type", "сила"),
                    "duration": workout_data.get("duration", 0),
                    "exercises_count": workout_data.get("exercises_count", 0),
                    "date": str(datetime.now().date()),
                }
                set_cached("workout_analysis", cache_data, result)
                print(f"✅ AI workout analysis: сохранено в кэш (score={result.get('workout_score', '?')})")
            except Exception as e:
                print(f"⚠️ Ошибка записи в кэш: {e}")

        return result

    async def generate_daily_digest(
            self,
            user_profile: Dict,
            today_plan: Dict,
            yesterday_summary: Dict,
    ) -> Optional[Dict]:
        """Генерация утреннего дайджеста с планом на день (адаптивный)."""
        y = yesterday_summary or {}
        adaptations = y.get("adaptations") or {}

        # Вчерашнее питание
        if y.get("had_food_log"):
            nutrition_text = (
                f"Съедено: {y.get('calories', 0)} ккал из цели "
                f"{user_profile.get('calorie_target', 2000)} ккал; "
                f"Б {y.get('protein_g', 0)} г из {user_profile.get('protein_target', 150)} г, "
                f"Ж {y.get('fat_g', 0)} г из {user_profile.get('fat_target', 70)} г, "
                f"У {y.get('carbs_g', 0)} г из {user_profile.get('carbs_target', 250)} г; "
                f"приёмов пищи: {y.get('meals_count', 0)}"
            )
        else:
            nutrition_text = "Питание вчера не записывалось (нет данных)"

        # Вчерашняя тренировка
        workout_y = y.get("workout")
        if workout_y:
            workout_text = (
                f"Была тренировка: {', '.join(workout_y.get('types', []))}, "
                f"{workout_y.get('duration_min', 0)} мин, "
                f"интенсивность {workout_y.get('intensity', 0)}/10"
            )
            if y.get("heavy_workout"):
                workout_text += " (ТЯЖЁЛАЯ)"
        else:
            workout_text = "Тренировки вчера не было"

        # Вес
        weight_text = ""
        if y.get("latest_weight") is not None:
            delta = y.get("weight_delta_week")
            delta_text = f", динамика за неделю: {'+' if delta and delta > 0 else ''}{delta} кг" if delta is not None else ""
            weight_text = f"- Вес: {y['latest_weight']} кг{delta_text}\n"

        # Адаптации, уже определённые правилами
        flags = []
        if adaptations.get("protein_deficit"):
            flags.append("вчера НЕДОБРАН БЕЛОК — сегодня акцент на белок")
        if adaptations.get("calorie_overshoot"):
            flags.append("вчера ПЕРЕБОР калорий — сегодня держать цель, ужин легче")
        if adaptations.get("calorie_undershoot"):
            flags.append("вчера НЕДОБОР калорий при цели набора — сегодня добрать")
        if adaptations.get("recovery_needed"):
            flags.append("вчера ТЯЖЁЛАЯ тренировка — сегодня приоритет восстановление")
        if adaptations.get("no_food_log"):
            flags.append("вчера питание не записывалось — мягко напомнить вести дневник")
        adaptations_text = "\n".join(f"- {f}" for f in flags) if flags else "- вчерашний день в норме, особых коррекций не требуется"

        prompt = f"""
Ты — AI-коуч BodyPilot. Составь персонализированный план на день с учётом вчерашних результатов.

{COACH_PERSONA}

ПОЛЬЗОВАТЕЛЬ:
- Цель: {user_profile.get('goal', 'maintain')}
- Вид спорта: {user_profile.get('sport', 'fitness')}
- Вес: {user_profile.get('weight', 70)} кг

ПЛАН ТРЕНИРОВКИ НА СЕГОДНЯ:
{today_plan.get('workout', 'Нет тренировки')}

ПЛАН ПИТАНИЯ НА СЕГОДНЯ (нормы):
- Калории: {user_profile.get('calorie_target', 2000)} ккал
- Белок: {user_profile.get('protein_target', 150)} г

ВЧЕРА ({y.get('date', 'вчера')}) — фактические данные:
- Питание: {nutrition_text}
- Тренировка: {workout_text}
{weight_text}
УЖЕ ОПРЕДЕЛЁННЫЕ АДАПТАЦИИ (обязательно учти в формулировках, не противоречь им):
{adaptations_text}

ЗАДАЧА:
1. Кратко оцени вчерашний день (1-2 фразы, по делу, со ссылкой на цифры)
2. Дай фокус на сегодня: питание, тренировка, восстановление
3. Мотивирующее вступление и микро-цель

ВЕРНИ ТОЛЬКО JSON:
{{
    "greeting": "приветствие + мотивация (1-2 предложения)",
    "yesterday_review": "оценка вчерашнего дня (1-2 фразы)",
    "workout_focus": "на чём сосредоточиться на тренировке сегодня",
    "nutrition_focus": "на чём сосредоточиться в питании сегодня",
    "recovery_tip": "совет по восстановлению",
    "micro_goal": "микро-цель на сегодня (маленькая достижимая задача)",
    "motivation_quote": "мотивирующая цитата/фраза"
}}
"""
        result = await self._request(prompt, json_mode=True)
        return result

    async def chat_answer(
                self,
                user_profile: Dict,
                question: str,
                context: str = None,
        ) -> Optional[Dict]:
            """Ответ на вопрос пользователя в AI-чате."""
            prompt = f"""
    Ты — AI-коуч BodyPilot, эксперт по фитнесу и питанию.

    {COACH_PERSONA}

    КОНТЕКСТ ПОЛЬЗОВАТЕЛЯ:
    - Цель: {user_profile.get('goal', 'maintain')}
    - Вид спорта: {user_profile.get('sport', 'fitness')}
    - Уровень: {user_profile.get('sport_level', 'beginner')}
    - Ограничения: {user_profile.get('allergies', 'нет')}

    ВОПРОС ПОЛЬЗОВАТЕЛЯ:
    {question}

    {f'ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ: {context}' if context else ''}

    ПРАВИЛА:
    1. Отвечай конкретно, без воды
    2. Давай практические советы, не теорию
    3. Если вопрос про питание — предлагай конкретные продукты
    4. Если вопрос про тренировку — ссылайся на текущий план
    5. Не давай медицинских рекомендаций
    6. Ответ на русском, 2-5 предложений

    ВЕРНИ ТОЛЬКО JSON:
    {{
        "answer": "ответ на вопрос",
        "action_items": ["действие 1", "действие 2"],
        "related_commands": ["/команда1", "/команда2"],
        "follow_up": "предложение продолжить тему (опционально)"
    }}
    """
            result = await self._request(prompt, json_mode=True)

            # ═══════════════════════════════════════════════════════════════
            # СОХРАНЯЕМ В БАЗУ ЗНАНИЙ ДЛЯ БУДУЩЕГО КЭШИРОВАНИЯ
            # ═══════════════════════════════════════════════════════════════

            if result and "error" not in result:
                from .ai_router import save_to_knowledge_base
                save_to_knowledge_base(
                    question=question,
                    answer=result.get("answer", ""),
                    context_tags={"goal": user_profile.get("goal", "maintain")},
                )

            return result

    async def chat_with_tools(
            self,
            user_id: int,
            question: str,
            history: List[Dict] = None,
    ) -> Optional[Dict]:
        """Чат с function calling: модель может выполнять действия через tools.

        Цикл до 3 раундов (1 раунд = 1 API-вызов): если в ответе functionCall —
        выполняем через execute_tool, добавляем functionResponse в contents и
        повторяем запрос; если текст — возвращаем {"text": ..., "tools_used": [...]}.

        history — последние сообщения диалога [{"role": "user"/"model", "text": ...}],
        необязательный параметр (по умолчанию пустой список).
        """
        from core.ai.tools import TOOL_DECLARATIONS, execute_tool
        from core.ai.context import build_user_context

        # Профиль и текущее состояние пользователя — собираем ОДИН раз и
        # кладём в system_instruction (не дублируем в contents по раундам)
        user_context = build_user_context(user_id)
        if user_context is None:
            return {
                "text": (
                    "Я пока тебя не знаю 🙂 Сначала зарегистрируйся командой "
                    "/register — тогда смогу помогать предметно, с учётом твоих данных."
                ),
                "tools_used": [],
            }
        system_instruction = f"{CHAT_TOOLS_SYSTEM_INSTRUCTION}\n\n{user_context}"

        contents: List[Dict] = []
        for msg in (history or [])[-6:]:
            role = msg.get("role")
            text = msg.get("text")
            if role in ("user", "model") and text:
                contents.append({"role": role, "parts": [{"text": str(text)[:1000]}]})
        contents.append({"role": "user", "parts": [{"text": question}]})

        tool_summaries: List[Dict] = []
        tool_calls_made = 0

        for round_num in range(3):
            data = await self._generate_with_tools(
                contents, TOOL_DECLARATIONS, system_instruction=system_instruction
            )

            if data is None:
                return None
            if data.get("error") == "rate_limit":
                return data

            try:
                parts = data["candidates"][0]["content"]["parts"]
            except (KeyError, IndexError, TypeError) as e:
                print(f"Gemini tools parse error: {e}")
                return None

            calls = [p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p]
            texts = [p["text"] for p in parts if isinstance(p, dict) and "text" in p]

            if not calls:
                text = "\n".join(texts).strip() or "Не удалось получить ответ"
                return {"text": text, "tools_used": tool_summaries}

            # Ответ модели с functionCall возвращаем в contents
            contents.append({"role": "model", "parts": parts})

            response_parts = []
            for call in calls:
                name = call.get("name", "")
                args = call.get("args") or {}

                if tool_calls_made >= 3:
                    result = {"error": "лимит вызовов инструментов на один вопрос исчерпан (макс. 3)"}
                else:
                    tool_calls_made += 1
                    result = execute_tool(user_id, name, args)
                    if "error" not in result:
                        tool_summaries.append({"tool": name, "summary": result.get("summary")})

                response_parts.append({
                    "functionResponse": {"name": name, "response": result}
                })

            contents.append({"role": "user", "parts": response_parts})

        # Раунды кончились, а модель всё ещё просит tools
        return {
            "text": "⚠️ Не удалось завершить действие — попробуй сформулировать запрос проще.",
            "tools_used": tool_summaries,
        }

    async def _generate_with_tools(
            self,
            contents: List[Dict],
            tool_declarations: List[Dict],
            system_instruction: str = None,
    ) -> Optional[Dict]:
        """Один запрос generateContent с tools по цепочке fallback-моделей.

        Без responseMimeType=json — function calling несовместим с forced JSON.
        system_instruction — переопределение системной инструкции (например,
        с блоком контекста пользователя); по умолчанию CHAT_TOOLS_SYSTEM_INSTRUCTION.
        """
        import asyncio

        payload = {
            "contents": contents,
            "system_instruction": {
                "parts": [{"text": system_instruction or CHAT_TOOLS_SYSTEM_INSTRUCTION}]
            },
            "tools": [{"function_declarations": tool_declarations}],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 1024,
            },
        }

        saw_rate_limit = False

        for model in _model_chain():
            url = f"{_model_url(model)}?key={self.api_key}"

            for attempt in range(2):
                try:
                    session = await self._get_session()

                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            return await response.json()

                        elif response.status == 429:
                            saw_rate_limit = True
                            if attempt < 1:
                                print(f"Gemini tools rate limit ({model}), повтор через 10с...")
                                await asyncio.sleep(10)
                                continue
                            print(f"Gemini tools: квота {model} исчерпана, переключаемся на fallback")
                            break

                        elif response.status in (500, 502, 503):
                            if attempt < 1:
                                await asyncio.sleep(3)
                                continue
                            print(f"Gemini tools: {model} недоступен, переключаемся на fallback")
                            break

                        else:
                            error_text = await response.text()
                            print(f"Gemini tools API error {response.status} ({model}): {error_text}")
                            return None

                except Exception as e:
                    print(f"Gemini tools request error ({model}): {e}")
                    if attempt < 1:
                        await asyncio.sleep(3)
                        continue
                    break

        if saw_rate_limit:
            return {
                "error": "rate_limit",
                "message": "Превышен лимит запросов. Попробуй через несколько минут.",
            }
        return None


# ═══════════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЙ КЛИЕНТ
# ═══════════════════════════════════════════════════════════════

gemini_client = GeminiClient() if GEMINI_API_KEY else None


def get_gemini_client() -> Optional[GeminiClient]:
    """Получить глобальный клиент Gemini."""
    return gemini_client