"""PNG-графики прогресса пользователя (matplotlib без GUI)."""

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Optional

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Circle, FancyBboxPatch

from .database import get_db, get_user
from .gamification import get_streak
from .nutrition_calc import get_nutrition_plan

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False

_BACKGROUND = "#F7F9FC"
_TEXT = "#172033"
_MUTED = "#667085"
_GRID = "#DDE3EC"
_ACCENT = "#4F7CFF"
_SECONDARY = "#22A88A"
_TARGET = "#E35D6A"
_WEEKDAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _context(user_id: int) -> Optional[tuple[dict, int, date]]:
    user = get_user(user_id)
    if not user:
        return None
    offset = int(user.get("timezone_offset") or 0)
    today = (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()
    return user, offset, today


def _offset_modifier(offset: int) -> str:
    return f"{offset:+d} minutes"


def _new_figure(title: str):
    fig, ax = plt.subplots(figsize=(10, 5), dpi=100)
    fig.patch.set_facecolor(_BACKGROUND)
    ax.set_facecolor(_BACKGROUND)
    ax.set_title(title, fontsize=18, fontweight="bold", color=_TEXT, pad=18)
    ax.grid(axis="y", color=_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(_GRID)
    ax.spines["bottom"].set_color(_GRID)
    ax.tick_params(colors=_MUTED, labelsize=11)
    return fig, ax


def _to_png(fig) -> bytes:
    buffer = BytesIO()
    try:
        fig.tight_layout(pad=2.2)
        fig.savefig(buffer, format="png", dpi=100, facecolor=fig.get_facecolor())
        return buffer.getvalue()
    finally:
        plt.close(fig)


def _signed(value: float) -> str:
    if value > 0:
        return f"+{value:.1f}"
    if value < 0:
        return f"−{abs(value):.1f}"
    return "0.0"


def generate_weight_chart(user_id: int) -> Optional[bytes]:
    """Вес за 30 локальных дней: линия, точки и изменение за период."""
    context = _context(user_id)
    if not context:
        return None
    _, offset, today = context
    first_day = today - timedelta(days=29)
    cutoff = (first_day - timedelta(days=1)).isoformat()
    rows = get_db().execute(
        """SELECT logged_at, weight_kg, datetime(logged_at, ?) AS local_logged_at
           FROM weight_log
           WHERE user_id = ? AND logged_at >= ?
           ORDER BY logged_at""",
        (_offset_modifier(offset), user_id, cutoff),
    ).fetchall()

    points = []
    for row in rows:
        try:
            logged_at = datetime.fromisoformat(row["local_logged_at"])
            weight = float(row["weight_kg"])
        except (TypeError, ValueError):
            continue
        if first_day <= logged_at.date() <= today:
            points.append((logged_at, weight))
    if len(points) < 2:
        return None

    dates = [point[0] for point in points]
    weights = [point[1] for point in points]
    delta = weights[-1] - weights[0]

    fig, ax = _new_figure("Вес за 30 дней")
    ax.plot(dates, weights, color=_ACCENT, linewidth=2.4, marker="o", markersize=6)
    ax.set_ylabel("кг", color=_MUTED, fontsize=12)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.text(
        0.02,
        0.96,
        f"{_signed(delta)} кг за период",
        transform=ax.transAxes,
        va="top",
        fontsize=13,
        color=_SECONDARY if delta <= 0 else _TARGET,
        fontweight="bold",
    )
    padding = max((max(weights) - min(weights)) * 0.2, 0.5)
    ax.set_ylim(min(weights) - padding, max(weights) + padding)
    return _to_png(fig)


def _daily_nutrition(user_id: int, offset: int, first_day: date, today: date) -> dict[date, dict]:
    cutoff = (first_day - timedelta(days=1)).isoformat()
    rows = get_db().execute(
        """SELECT date(logged_at, ?) AS day,
                  SUM(calories) AS calories,
                  SUM(protein_g) AS protein_g,
                  COUNT(*) AS entries
           FROM food_log_new
           WHERE user_id = ? AND logged_at >= ?
           GROUP BY day""",
        (_offset_modifier(offset), user_id, cutoff),
    ).fetchall()
    result = {}
    for row in rows:
        try:
            day = date.fromisoformat(row["day"])
        except (TypeError, ValueError):
            continue
        if first_day <= day <= today:
            result[day] = {
                "calories": float(row["calories"] or 0),
                "protein_g": float(row["protein_g"] or 0),
                "entries": int(row["entries"] or 0),
            }
    return result


def _day_labels(days: list[date]) -> list[str]:
    return [f"{_WEEKDAYS_SHORT[day.weekday()]}\n{day.strftime('%d.%m')}" for day in days]


def generate_calories_chart(user_id: int) -> Optional[bytes]:
    """Калории за 7 локальных дней и горизонтальная линия нормы."""
    context = _context(user_id)
    if not context:
        return None
    _, offset, today = context
    first_day = today - timedelta(days=6)
    nutrition = _daily_nutrition(user_id, offset, first_day, today)
    if not nutrition or not any(item["calories"] > 0 for item in nutrition.values()):
        return None

    plan = get_nutrition_plan(user_id)
    target = float(plan.get("target_calories") or 0)
    if target <= 0:
        return None

    days = [first_day + timedelta(days=index) for index in range(7)]
    values = [nutrition.get(day, {}).get("calories", 0) for day in days]

    fig, ax = _new_figure("Калории за 7 дней")
    bars = ax.bar(_day_labels(days), values, color=_ACCENT, width=0.62)
    ax.axhline(
        target,
        color=_TARGET,
        linewidth=2,
        linestyle="--",
        label=f"Норма: {target:.0f} ккал",
    )
    ax.set_ylabel("ккал", color=_MUTED, fontsize=12)
    ax.legend(frameon=False, loc="upper right", fontsize=11)
    ax.set_ylim(0, max(max(values), target) * 1.2)
    for bar, value in zip(bars, values):
        if value > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value,
                f"{value:.0f}",
                ha="center",
                va="bottom",
                fontsize=10,
                color=_TEXT,
            )
    return _to_png(fig)


def generate_workouts_chart(user_id: int) -> Optional[bytes]:
    """Суммарная длительность тренировок по дням за 7 дней."""
    context = _context(user_id)
    if not context:
        return None
    _, _, today = context
    first_day = today - timedelta(days=6)
    rows = get_db().execute(
        """SELECT date(date) AS day, SUM(COALESCE(duration_min, 0)) AS duration_min
           FROM workout_sessions
           WHERE user_id = ? AND date >= ? AND date <= ?
           GROUP BY day""",
        (user_id, first_day.isoformat(), today.isoformat()),
    ).fetchall()
    durations = {}
    for row in rows:
        try:
            day = date.fromisoformat(row["day"])
        except (TypeError, ValueError):
            continue
        durations[day] = float(row["duration_min"] or 0)
    if not any(value > 0 for value in durations.values()):
        return None

    days = [first_day + timedelta(days=index) for index in range(7)]
    values = [durations.get(day, 0) for day in days]

    fig, ax = _new_figure("Тренировки за 7 дней")
    bars = ax.bar(_day_labels(days), values, color=_SECONDARY, width=0.62)
    ax.set_ylabel("минут", color=_MUTED, fontsize=12)
    ax.set_ylim(0, max(values) * 1.2)
    for bar, value in zip(bars, values):
        if value > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value,
                f"{value:.0f}",
                ha="center",
                va="bottom",
                fontsize=10,
                color=_TEXT,
            )
    return _to_png(fig)


def _health_metrics_by_day(
    user_id: int, offset: int, first_day: date, today: date, metric_type: str
) -> dict[date, float]:
    """Сумма значений метрики здоровья по локальным дням пользователя."""
    cutoff = (first_day - timedelta(days=1)).isoformat()
    rows = get_db().execute(
        """SELECT date(ts, ?) AS day, SUM(value) AS total
           FROM health_metrics
           WHERE user_id = ? AND metric_type = ? AND ts >= ?
           GROUP BY day""",
        (_offset_modifier(offset), user_id, metric_type, cutoff),
    ).fetchall()
    result: dict[date, float] = {}
    for row in rows:
        try:
            day = date.fromisoformat(row["day"])
        except (TypeError, ValueError):
            continue
        if first_day <= day <= today:
            result[day] = float(row["total"] or 0)
    return result


def chart_steps(user_id: int, days: int = 14) -> Optional[bytes]:
    """Столбики шагов по дням за N локальных дней. Меньше 2 дней данных → None."""
    context = _context(user_id)
    if not context:
        return None
    _, offset, today = context
    days = max(2, days)
    first_day = today - timedelta(days=days - 1)
    by_day = _health_metrics_by_day(user_id, offset, first_day, today, "steps")
    if sum(1 for value in by_day.values() if value > 0) < 2:
        return None

    day_list = [first_day + timedelta(days=index) for index in range(days)]
    values = [by_day.get(day, 0) for day in day_list]

    fig, ax = _new_figure(f"Шаги за {days} дней")
    labels = (
        _day_labels(day_list) if days <= 7
        else [day.strftime("%d.%m") for day in day_list]
    )
    bars = ax.bar(labels, values, color=_ACCENT, width=0.62)
    ax.set_ylabel("шагов", color=_MUTED, fontsize=12)
    ax.set_ylim(0, max(values) * 1.2 if values else 1)
    if days > 7:
        ax.tick_params(axis="x", labelsize=9, rotation=45)
    for bar, value in zip(bars, values):
        if value > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value,
                f"{value / 1000:.1f}k" if value >= 1000 else f"{value:.0f}",
                ha="center",
                va="bottom",
                fontsize=9,
                color=_TEXT,
            )
    return _to_png(fig)


def chart_sleep(user_id: int, days: int = 14) -> Optional[bytes]:
    """Столбики сна по дням за N локальных дней + пунктирная норма 8 ч."""
    context = _context(user_id)
    if not context:
        return None
    _, offset, today = context
    days = max(2, days)
    first_day = today - timedelta(days=days - 1)
    by_day = _health_metrics_by_day(user_id, offset, first_day, today, "sleep_hours")
    if sum(1 for value in by_day.values() if value > 0) < 2:
        return None

    day_list = [first_day + timedelta(days=index) for index in range(days)]
    values = [by_day.get(day, 0) for day in day_list]

    fig, ax = _new_figure(f"Сон за {days} дней")
    labels = (
        _day_labels(day_list) if days <= 7
        else [day.strftime("%d.%m") for day in day_list]
    )
    colors = [_SECONDARY if value >= 7 else _ACCENT for value in values]
    bars = ax.bar(labels, values, color=colors, width=0.62)
    ax.axhline(8, color=_TARGET, linewidth=2, linestyle="--", label="Норма: 8 ч")
    ax.set_ylabel("часов", color=_MUTED, fontsize=12)
    ax.legend(frameon=False, loc="upper right", fontsize=11)
    ax.set_ylim(0, max(max(values), 8) * 1.2)
    if days > 7:
        ax.tick_params(axis="x", labelsize=9, rotation=45)
    for bar, value in zip(bars, values):
        if value > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value,
                f"{value:g}",
                ha="center",
                va="bottom",
                fontsize=9,
                color=_TEXT,
            )
    return _to_png(fig)


def build_share_card(user_id: int) -> Optional[bytes]:
    """Квадратная PNG-карточка недели для шеринга."""
    context = _context(user_id)
    if not context:
        return None
    _, offset, today = context
    first_day = today - timedelta(days=6)
    nutrition = _daily_nutrition(user_id, offset, first_day, today)
    plan = get_nutrition_plan(user_id)
    calorie_target = float(plan.get("target_calories") or 0)
    average_calories = sum(item["calories"] for item in nutrition.values()) / 7

    workouts = get_db().execute(
        """SELECT COUNT(*) FROM workout_sessions
           WHERE user_id = ? AND date >= ? AND date <= ?""",
        (user_id, first_day.isoformat(), today.isoformat()),
    ).fetchone()[0]

    cutoff = (first_day - timedelta(days=1)).isoformat()
    weight_rows = get_db().execute(
        """SELECT weight_kg, datetime(logged_at, ?) AS local_logged_at
           FROM weight_log
           WHERE user_id = ? AND logged_at >= ?
           ORDER BY logged_at""",
        (_offset_modifier(offset), user_id, cutoff),
    ).fetchall()
    weights = []
    for row in weight_rows:
        try:
            logged_at = datetime.fromisoformat(row["local_logged_at"])
            weight = float(row["weight_kg"])
        except (TypeError, ValueError):
            continue
        if first_day <= logged_at.date() <= today:
            weights.append(weight)
    weight_text = "нет данных"
    if len(weights) >= 2:
        weight_text = f"{_signed(weights[-1] - weights[0])} кг"
    elif weights:
        weight_text = f"{weights[-1]:.1f} кг"

    streak = get_streak(user_id)["current"]
    gradient = [[index / 999] for index in range(1000)]
    cmap = LinearSegmentedColormap.from_list("share", ["#EAF0FF", "#F7FBFF", "#E9FFF8"])
    fig, ax = plt.subplots(figsize=(10, 10), dpi=100)
    try:
        fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
        ax.imshow(gradient, extent=(0, 100, 0, 100), aspect="auto", cmap=cmap)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.axis("off")

        avatar = Circle((50, 77), 9.5, facecolor="#FFFFFF", edgecolor=_ACCENT, linewidth=3, alpha=0.96)
        ax.add_patch(avatar)
        ax.text(50, 77, "BP", ha="center", va="center", fontsize=28, fontweight="bold", color=_ACCENT)
        ax.text(50, 92, "@BodyPilot2_bot", ha="center", va="center", fontsize=18, color=_MUTED)
        ax.text(50, 62, "Моя неделя", ha="center", va="center", fontsize=34, fontweight="bold", color=_TEXT)

        cards = (
            (14, 43, "Средние калории", f"{average_calories:.0f} / {calorie_target:.0f} ккал"),
            (54, 43, "Тренировки", str(int(workouts))),
            (14, 27, "Серия", f"{streak} дн."),
            (54, 27, "Вес", weight_text),
        )
        for x, y, label, value in cards:
            card = FancyBboxPatch(
                (x, y),
                32,
                13,
                boxstyle="round,pad=0.8,rounding_size=2.5",
                facecolor="#FFFFFF",
                edgecolor="#DDE3EC",
                linewidth=1.5,
                alpha=0.94,
            )
            ax.add_patch(card)
            ax.text(x + 16, y + 8.6, label, ha="center", va="center", fontsize=14, color=_MUTED)
            value_x = x + 16
            if label == "Серия":
                value_x = x + 18
                ax.fill([x + 8.4, x + 11.0, x + 9.8], [y + 2.5, y + 2.5, y + 7.0], color="#FF7A45")
                ax.add_patch(Circle((x + 9.7, y + 3.2), 1.5, facecolor="#FFB26B", edgecolor="none"))
            ax.text(value_x, y + 4.2, value, ha="center", va="center", fontsize=22,
                    fontweight="bold", color=_TEXT)

        ax.text(50, 14, "Я тренируюсь с BodyPilot", ha="center", va="center", fontsize=24,
                fontweight="bold", color=_SECONDARY)
        ax.text(50, 8, "Подключайся и соревнуйся со мной", ha="center", va="center", fontsize=15, color=_MUTED)
        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=100, facecolor=fig.get_facecolor())
        return buffer.getvalue()
    finally:
        plt.close(fig)
