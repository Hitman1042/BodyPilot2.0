"""Детектор намерения удаления записи еды (работает и внутри FSM)."""

from core.ai.text_markers import extract_delete_target, is_delete_intent


def test_delete_intent_positive():
    assert is_delete_intent("Удали курица варёная филе")
    assert is_delete_intent("удалить яблоко")
    assert is_delete_intent("отмени")
    assert is_delete_intent("Убери маршмеллоу")
    assert is_delete_intent("не то записал")


def test_delete_intent_negative():
    assert not is_delete_intent("съел яблоко")
    assert not is_delete_intent("300")
    assert not is_delete_intent("курица варёная")
    assert not is_delete_intent("сколько белка мне нужно?")


def test_extract_delete_target():
    assert extract_delete_target("Удали курица варёная филе") == "курица варёная филе"
    assert extract_delete_target("удалить яблоко") == "яблоко"
    assert extract_delete_target("отмени") == ""
    assert extract_delete_target("Убери маршмеллоу.") == "маршмеллоу"
