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


_DELETE_INTENT_RE = re.compile(
    r"^\s*(удали(ть)?|отмени(ть)?|убери|убрать|не\s+то\s+записал|не\s+надо\s+записывать)\b",
    re.IGNORECASE,
)


def is_delete_intent(text: str) -> bool:
    """True, если сообщение — просьба удалить/отменить запись еды.

    Работает и внутри FSM-сценариев: такие сообщения не должны попадать
    в поля ввода (вес, граммы и т.п.).
    """
    return bool(_DELETE_INTENT_RE.match(text or ""))


def extract_delete_target(text: str) -> str:
    """Название продукта из просьбы удалить: «удали курицу» → «курицу».

    Пустая строка = удалить последнюю запись.
    """
    if not text:
        return ""
    target = _DELETE_INTENT_RE.sub("", text, count=1).strip(" .!,")
    return target
