"""Гибридный AI-маршрутизатор для BodyPilot."""

import hashlib
import json
import re
import time
from typing import Optional, Dict, Tuple
from datetime import datetime, timezone

from core.database import get_db
from core.referrals import check_subscription_active

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

# Уровни AI
ROUTE_CACHE = "cache"  # Кэш (0.1 сек, $0)
ROUTE_TEMPLATE = "template"  # Шаблон (0.1 сек, $0)
ROUTE_HYBRID = "hybrid"  # Шаблон + данные (1 сек, $0.001)
ROUTE_FULL_AI = "full_ai"  # Полный Gemini (5 сек, $0.01)

# Лимиты для Free
FREE_LIMITS = {
    ROUTE_CACHE: 0,  # Безлимит
    ROUTE_TEMPLATE: 0,  # Безлимит
    ROUTE_HYBRID: 5,  # 5 в неделю
    ROUTE_FULL_AI: 1,  # 1 в неделю
}

# Лимиты для Premium
PREMIUM_LIMITS = {
    ROUTE_CACHE: 0,
    ROUTE_TEMPLATE: 0,
    ROUTE_HYBRID: 20,  # 20 в неделю
    ROUTE_FULL_AI: 5,  # 5 в неделю
}


# ═══════════════════════════════════════════════════════════════
# ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════

def hash_question(question: str, context: Dict = None) -> str:
    """Создать хэш вопроса для поиска в кэше."""
    # Нормализуем вопрос
    q = question.lower().strip()
    q = re.sub(r'\s+', ' ', q)  # Убираем лишние пробелы
    q = re.sub(r'[^\w\sа-яё]', '', q)  # Убираем спецсимволы

    # Добавляем контекст если есть
    if context:
        ctx_str = json.dumps(context, sort_keys=True)
        q = f"{q}|{ctx_str}"

    return hashlib.md5(q.encode('utf-8')).hexdigest()


def find_in_cache(question_hash: str) -> Optional[Dict]:
    """Найти ответ в кэше по хэшу."""
    # Общее thread-local соединение: не закрывать и не менять row_factory
    conn = get_db()

    # ИЩЕМ ПО ХЭШУ (без проверки рейтинга — новые записи тоже отдаём)
    result = conn.execute("""
        SELECT * FROM ai_knowledge_base
        WHERE question_hash = ?
    """, (question_hash,)).fetchone()

    if result:
        # Увеличиваем счётчик использования
        conn.execute("""
            UPDATE ai_knowledge_base
            SET usage_count = usage_count + 1, updated_at = datetime('now')
            WHERE id = ?
        """, (result["id"],))
        conn.commit()

        return {
            "route": ROUTE_CACHE,
            "answer": result["answer_full"],
            "from_cache": True,
            "usage_count": result["usage_count"] + 1,
            "rating": result["avg_rating"],
        }

    return None


def find_template_match(question: str, user_profile: Dict = None) -> Optional[Dict]:
    """Найти шаблон по паттерну вопроса."""
    conn = get_db()

    # Ищем совпадения по паттернам
    templates = conn.execute("""
        SELECT * FROM ai_question_templates
        WHERE is_active = TRUE
        ORDER BY priority DESC
    """).fetchall()

    for tpl in templates:
        if re.match(tpl["pattern"], question):
            # Персонализируем шаблон
            answer = tpl["template_text"]

            # Заполняем переменные из профиля
            if user_profile:
                answer = answer.format(
                    goal=user_profile.get("goal", "поддержание"),
                    weight=user_profile.get("weight", 70),
                    protein=user_profile.get("protein_target", 100),
                    calories=user_profile.get("calorie_target", 2000),
                    target_calories=user_profile.get("target_calories", 2200),
                    food_options="курица, рис, овощи",
                    kbzhu="Б: 30г, Ж: 10г, У: 50г",
                    muscle="грудь",
                    exercises="жим лёжа, отжимания, разводка",
                    workout_plan="Пн: грудь, Ср: спина, Пт: ноги",
                    frequency="3",
                    check_list="калории, белок, сон",
                )

            return {
                "route": ROUTE_TEMPLATE,
                "answer": answer,
                "category": tpl["category"],
                "template_id": tpl["id"],
            }

    return None


def determine_route(user_id: int, question: str, context: Dict = None) -> str:
    """
    Определить какой уровень AI использовать.

    Returns: ROUTE_CACHE, ROUTE_TEMPLATE, ROUTE_HYBRID, или ROUTE_FULL_AI
    """
    # 1. Проверяем кэш
    question_hash = hash_question(question, context)
    cached = find_in_cache(question_hash)
    if cached:
        return ROUTE_CACHE

    # 2. Проверяем шаблоны
    user_profile = _get_user_profile(user_id)
    template = find_template_match(question, user_profile)
    if template:
        return ROUTE_TEMPLATE

    # 3. Проверяем важность вопроса
    if _is_critical_question(question):
        return ROUTE_FULL_AI

    # 4. Проверяем Premium
    is_premium = check_subscription_active(user_id)

    # 5. Проверяем лимиты
    limits = PREMIUM_LIMITS if is_premium else FREE_LIMITS

    # Для простоты — если не кэш и не шаблон, то полный AI
    # (в будущем можно добавить hybrid)
    return ROUTE_FULL_AI


def _get_user_profile(user_id: int) -> Dict:
    """Получить профиль пользователя для персонализации."""
    from core.database import get_user

    user = get_user(user_id)
    if not user:
        return {}

    weight = user.get("weight_kg", 70)
    goal = user.get("goal", "maintain")

    # Простой расчёт калорий и белка
    if goal == "gain":
        calories = int(weight * 35)  # Профицит
        protein = int(weight * 2.0)
    elif goal == "lose":
        calories = int(weight * 25)  # Дефицит
        protein = int(weight * 2.2)
    else:  # maintain
        calories = int(weight * 30)
        protein = int(weight * 1.6)

    return {
        "goal": goal,
        "weight": weight,
        "height": user.get("height_cm", 175),
        "age": user.get("age", 25),
        "gender": user.get("gender", "male"),
        "sport": user.get("sport_level", "beginner"),
        "protein_target": protein,
        "calorie_target": calories,
        "target_calories": calories,
        "fat_target": int(weight * 1.0),
        "carbs_target": int((calories - (protein * 4) - (weight * 9)) / 4),
    }


def _is_critical_question(question: str) -> bool:
    """Проверить вопрос на важность (требует полного AI)."""
    critical_keywords = [
        "плато", "не получается", "проблема", "боль", "травма",
        "почему нет", "как ускорить", "индивидуальный", "персональный",
    ]

    # Уникальные вопросы с деталями — отправляем в Gemini
    long_question = len(question.split()) > 8

    q = question.lower()
    return any(kw in q for kw in critical_keywords) or long_question


def log_response(
        user_id: int,
        question: str,
        answer: str,
        route: str,
        response_time_ms: int,
        gemini_cost: float = 0,
        user_rating: int = None,
):
    """Записать ответ в лог."""
    conn = get_db()

    try:
        conn.execute("""
            INSERT INTO ai_response_log 
            (user_id, question, answer, route, response_time_ms, gemini_cost, user_rating)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, question, answer, route, response_time_ms, gemini_cost, user_rating))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"⚠️ Ошибка логирования ответа: {e}")


def save_to_knowledge_base(
        question: str,
        answer: str,
        context_tags: Dict = None,
):
    """Сохранить ответ в базу знаний для будущего кэширования."""
    question_hash = hash_question(question, context_tags)

    conn = get_db()

    try:
        conn.execute("""
            INSERT INTO ai_knowledge_base 
            (question_hash, question_template, answer_template, answer_full, context_tags)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(question_hash) DO UPDATE SET
                answer_full = excluded.answer_full,
                updated_at = datetime('now')
        """, (
            question_hash,
            question[:200],  # Короткая версия вопроса
            answer[:500],  # Шаблон ответа
            answer,  # Полный ответ
            json.dumps(context_tags) if context_tags else None,
        ))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"⚠️ Ошибка сохранения в базу знаний: {e}")


def rate_response(response_id: int, rating: int) -> bool:
    """Оценить ответ (1-5 звёзд)."""
    if rating < 1 or rating > 5:
        print(f"❌ rate_response: неверный рейтинг {rating}")
        return False

    conn = get_db()

    try:
        # Обновляем оценку в логе
        result = conn.execute("""
            UPDATE ai_response_log
            SET user_rating = ?
            WHERE id = ?
        """, (rating, response_id))

        # Проверяем что запись найдена
        if result.rowcount == 0:
            print(f"❌ rate_response: запись {response_id} не найдена")
            return False

        # Обновляем средний рейтинг в базе знаний
        conn.execute("""
            UPDATE ai_knowledge_base
            SET avg_rating = (
                SELECT AVG(user_rating) FROM ai_response_log
                WHERE answer = (SELECT answer FROM ai_response_log WHERE id = ?)
                AND user_rating IS NOT NULL
            ),
            total_ratings = (
                SELECT COUNT(*) FROM ai_response_log
                WHERE answer = (SELECT answer FROM ai_response_log WHERE id = ?)
                AND user_rating IS NOT NULL
            )
            WHERE answer_full = (SELECT answer FROM ai_response_log WHERE id = ?)
        """, (response_id, response_id, response_id))

        conn.commit()

        print(f"✅ rate_response: оценка {rating}⭐ сохранена для log_id={response_id}")

        return True

    except Exception as e:
        conn.rollback()
        print(f"❌ rate_response ошибка: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
# AI-МАРШРУТИЗАТОР (основная функция)
# ═══════════════════════════════════════════════════════════════

class AIRouter:
    """Гибридный AI-маршрутизатор."""

    def __init__(self):
        self.stats = {
            "cache_hits": 0,
            "template_hits": 0,
            "hybrid_calls": 0,
            "full_ai_calls": 0,
            "total_cost": 0,
        }

    async def get_answer(
            self,
            user_id: int,
            question: str,
            context: Dict = None,
    ) -> Dict:
        """
        Получить ответ через гибридный AI.

        Returns:
            {
                "answer": str,
                "route": str,
                "response_time_ms": int,
                "from_cache": bool,
                "cost": float,
                "log_id": int,
            }
        """
        start_time = time.time()

        # 1. ПРОВЕРЯЕМ Кэш (всегда безлимитно!)
        question_hash = hash_question(question, context)
        cached = find_in_cache(question_hash)

        if cached:
            self.stats["cache_hits"] += 1

            response_time_ms = int((time.time() - start_time) * 1000)

            # ═══════════════════════════════════════════════════════════════
            # ЛОГИРУЕМ ОТВЕТ (чтобы можно было оценить!)
            # ═══════════════════════════════════════════════════════════════

            log_id = self._log_response(
                user_id=user_id,
                question=question,
                answer=cached["answer"],
                route=ROUTE_CACHE,
                response_time_ms=response_time_ms,
                cost=0,
            )

            return {
                "answer": cached["answer"],
                "route": ROUTE_CACHE,
                "response_time_ms": response_time_ms,
                "from_cache": True,
                "cost": 0,
                "log_id": log_id,  # ← ТЕПЕРЬ ID!
            }

        # 2. ПРОВЕРЯЕМ ШАБЛОНЫ (тоже безлимитно!)
        user_profile = _get_user_profile(user_id)
        template = find_template_match(question, user_profile)

        if template:
            self.stats["template_hits"] += 1

            response_time_ms = int((time.time() - start_time) * 1000)

            # ═══════════════════════════════════════════════════════════════
            # ЛОГИРУЕМ ОТВЕТ (чтобы можно было оценить!)
            # ═══════════════════════════════════════════════════════════════

            log_id = self._log_response(
                user_id=user_id,
                question=question,
                answer=template["answer"],
                route=ROUTE_TEMPLATE,
                response_time_ms=response_time_ms,
                cost=0,
            )

            return {
                "answer": template["answer"],
                "route": ROUTE_TEMPLATE,
                "response_time_ms": response_time_ms,
                "from_cache": False,
                "cost": 0,
                "log_id": log_id,  # ← ТЕПЕРЬ ЕСТЬ ID!
            }

        # 3. ГИБРИД ИЛИ ПОЛНЫЙ AI (тут уже лимиты!)
        # Для простоты — сразу полный AI
        result = await self._get_full_ai_answer(user_id, question, context)

        self.stats["full_ai_calls"] += 1

        # Считаем время
        response_time_ms = int((time.time() - start_time) * 1000)

        # Логируем
        log_id = self._log_response(
            user_id, question, result["answer"], ROUTE_FULL_AI,
            response_time_ms, result.get("cost", 0)
        )

        # Сохраняем в базу знаний
        if result["answer"] and "ошибка" not in result["answer"].lower():
            save_to_knowledge_base(
                question=question,
                answer=result["answer"],
                context_tags=context,
            )

        return {
            "answer": result["answer"],
            "route": ROUTE_FULL_AI,
            "response_time_ms": response_time_ms,
            "from_cache": False,
            "cost": result.get("cost", 0),
            "log_id": log_id,
        }

    async def _get_cached_answer(self, user_id: int, question: str, context: Dict) -> Dict:
        """Получить ответ из кэша."""
        question_hash = hash_question(question, context)
        cached = find_in_cache(question_hash)

        self.stats["cache_hits"] += 1

        return {
            "answer": cached["answer"],
            "cost": 0,
        }

    async def _get_template_answer(self, user_id: int, question: str, context: Dict) -> Dict:
        """Получить ответ из шаблона."""
        user_profile = _get_user_profile(user_id)
        template = find_template_match(question, user_profile)

        self.stats["template_hits"] += 1

        return {
            "answer": template["answer"],
            "cost": 0,
        }

    async def _get_hybrid_answer(self, user_id: int, question: str, context: Dict) -> Dict:
        """Получить гибридный ответ (шаблон + данные)."""
        # TODO: Реализовать гибридный режим
        return await self._get_full_ai_answer(user_id, question, context)

    async def _get_full_ai_answer(self, user_id: int, question: str, context: Dict) -> Dict:
        """Получить полный AI ответ через Gemini."""
        from core.ai.gemini_client import get_gemini_client

        client = get_gemini_client()
        if not client:
            return {
                "answer": "❌ AI-сервис временно недоступен",
                "cost": 0,
            }

        user_profile = _get_user_profile(user_id)

        result = await client.chat_answer(
            user_profile=user_profile,
            question=question,
            context=context,  # ← ПЕРЕДАЁМ КОНТЕКСТ!
        )

        self.stats["full_ai_calls"] += 1

        # Примерная стоимость (за токены)
        cost = 0.01  # ~$0.01 за запрос

        return {
            "answer": result.get("answer", "Не удалось получить ответ"),
            "cost": cost,
        }

    def _log_response(
            self, user_id: int, question: str, answer: str,
            route: str, response_time_ms: int, cost: float
    ) -> int:
        """Записать ответ в лог и вернуть ID."""
        conn = get_db()

        try:
            # Вставляем запись и получаем ID
            cursor = conn.execute("""
                INSERT INTO ai_response_log 
                (user_id, question, answer, route, response_time_ms, gemini_cost, user_rating)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, question, answer, route, response_time_ms, cost, None))

            log_id = cursor.lastrowid
            conn.commit()

            print(f"📝 _log_response: запись создана log_id={log_id}")

            return log_id

        except Exception as e:
            conn.rollback()
            print(f"❌ _log_response ошибка: {e}")
            return 0

    def _update_stats(self, route: str, cost: float):
        """Обновить статистику."""
        if route == ROUTE_CACHE:
            self.stats["cache_hits"] += 1
        elif route == ROUTE_TEMPLATE:
            self.stats["template_hits"] += 1
        elif route == ROUTE_HYBRID:
            self.stats["hybrid_calls"] += 1
        elif route == ROUTE_FULL_AI:
            self.stats["full_ai_calls"] += 1

        self.stats["total_cost"] += cost

    def get_stats(self) -> Dict:
        """Получить статистику использования."""
        return self.stats.copy()


# Глобальный экземпляр
ai_router = AIRouter()