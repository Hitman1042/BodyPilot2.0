"""Детектор явных маркеров еды в свободном тексте (без AI, без сети).

Если текст явно сообщает о съеденном/выпитом («съел яблоко», «выпил латте»),
smart_input идёт сразу в chat_with_tools — коуч запишет еду через log_food
без карточки-подтверждения и лишнего вызова recognize_food_from_text.
"""

import re

_FOOD_INTENT_RE = re.compile(
    r"(съел[аи]?|выпил[аи]?|перекусил[аи]?|поел[аи]?|на\s+(завтрак|обед|ужин|перекус))",
    re.IGNORECASE,
)


def has_food_intent(text: str) -> bool:
    """True, если текст содержит явные маркеры приёма пищи."""
    return bool(_FOOD_INTENT_RE.search(text or ""))
