"""История диалога с AI-коучем (в памяти, последние сообщения).

Общий модуль для ai_chat.py и smart_input.py: раньше история жила
в ai_chat.py и была недоступна обработчику свободного текста.
"""

# История диалога для function calling: user_id → [{"role": ..., "text": ...}]
_chat_histories: dict[int, list] = {}


def get_history(user_id: int) -> list:
    """Последние ~6 сообщений диалога для контекста chat_with_tools."""
    return _chat_histories.get(user_id, [])[-6:]


def append_history(user_id: int, question: str, answer: str) -> None:
    """Добавить пару вопрос-ответ в историю (храним до 12 записей)."""
    hist = _chat_histories.setdefault(user_id, [])
    hist.append({"role": "user", "text": question})
    hist.append({"role": "model", "text": answer})
    del hist[:-12]


def append_event(user_id: int, event_text: str) -> None:
    """Добавить системное событие в историю (например, запись еды из фото).

    События уходят в contents с ролью model (Gemini принимает только
    user/model) — так «таких 2 штуки» попадает в контекст chat_with_tools.
    """
    hist = _chat_histories.setdefault(user_id, [])
    hist.append({"role": "model", "text": event_text})
    del hist[:-12]
