"""Инструменты визуализации для текстовых отчётов."""

from typing import List


def progress_bar(current: float, target: float, length: int = 10) -> str:
    """Прогресс-бар от 0 до 1 (current/target). Пример: [████████░░] 80%"""
    if target == 0:
        return "[░░░░░░░░░░] 0%"
    ratio = max(0.0, min(1.0, current / target))
    filled = int(round(ratio * length))
    bar = "█" * filled + "░" * (length - filled)
    percent = int(ratio * 100)
    return f"[{bar}] {percent}%"


def trend_emoji(current: float, previous: float) -> str:
    """Возвращает эмодзи тренда: 📈 рост (>5%), 📉 падение (>5%), ➡️ стабильно."""
    if previous == 0:
        return "➡️"
    change = (current - previous) / abs(previous)
    if change > 0.05:
        return "📈"
    elif change < -0.05:
        return "📉"
    else:
        return "➡️"


def mini_graph(values: List[float], width: int = 10, max_val: float = None) -> str:
    """Текстовая мини-гистограмма из значений. Высокие столбцы — жирнее."""
    if not values:
        return "нет данных"
    if max_val is None:
        max_val = max(values) if max(values) > 0 else 1
    # символы разной высоты
    bars = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    result = []
    step = max(width, len(values)) // len(values)
    for v in values:
        idx = int((v / max_val) * (len(bars) - 1))
        result.append(bars[min(idx, len(bars) - 1)] * step)
    return "".join(result)


def status_icon(value: float, target: float, threshold: float = 0.8) -> str:
    """🟢 если >= target, 🟡 если >= threshold*target, 🔴 иначе."""
    if target == 0:
        return "⚪"
    ratio = value / target
    if ratio >= 1.0:
        return "🟢"
    elif ratio >= threshold:
        return "🟡"
    else:
        return "🔴"


def bmi_status(bmi: float) -> str:
    """Возвращает категорию BMI с эмодзи."""
    if bmi is None:
        return "⚪ неизвестно"
    if bmi < 18.5:
        return "🔵 недостаточный"
    elif bmi < 25:
        return "🟢 норма"
    elif bmi < 30:
        return "🟡 избыточный"
    else:
        return "🔴 ожирение"