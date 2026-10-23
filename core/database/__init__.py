"""Database layer for BodyPilot 2.0.

Модульная структура:
- connection: подключение, миграции
- users: пользователи, чаты
- workout: тренировки, упражнения
- weight: вес
- plans: планы питания/тренировок
- subscriptions: подписки, бонусы, рефералы
- stats: статистика

Питание (дневник, продукты) — в core/nutrition_tracker.py.
"""

from .connection import get_db, init_database
from .migrations import SCHEMA_VERSION
from .users import (
    get_user, get_user_by_referral_code, get_or_create_user, update_user,
    ensure_user_chat, get_user_chats
)
from .workout import (
    get_exercises_by_muscle, get_custom_exercises, add_exercise, get_workout_log,
    create_session, add_exercise_to_session, add_set,
    generate_daily_workout_plan, get_daily_plan, get_session_history,
    get_weekly_tonnage, get_exercise_history, suggest_progression,
    generate_weekly_workout_plan, get_tonnage_history
)
from .weight import log_weight, get_weight_log, get_weight_history, get_weight_history_local
from .progress_photos import add_progress_photo, get_progress_photos, count_progress_photos
from .plans import save_plan, mark_plan_sent, get_plan, get_pending_digests, confirm_digest_delivery
from .subscriptions import (
    get_subscription, create_subscription, update_subscription,
    check_subscription_active, get_subscription_info
)
from .referrals import (
    add_bonus_days, activate_bonus_days, cleanup_expired_bonus_days,
    get_bonus_balance, create_referral, get_referral, get_referral_by_invited,
    mark_referral_paid, get_referral_list, process_referral_payment
)
from .stats import get_weekly_stats, get_users_due_for_digest

__all__ = [
    # Connection
    'get_db', 'init_database', 'SCHEMA_VERSION',
    # Users
    'get_user', 'get_user_by_referral_code', 'get_or_create_user', 'update_user',
    'ensure_user_chat', 'get_user_chats',
    # Workout
    'get_exercises_by_muscle', 'get_custom_exercises', 'add_exercise', 'get_workout_log',
    'create_session', 'add_exercise_to_session', 'add_set',
    'generate_daily_workout_plan', 'get_daily_plan', 'get_session_history',
    'get_weekly_tonnage', 'get_exercise_history', 'suggest_progression',
    'generate_weekly_workout_plan', 'get_tonnage_history',
    # Weight
    'log_weight', 'get_weight_log', 'get_weight_history', 'get_weight_history_local',
    # Progress photos
    'add_progress_photo', 'get_progress_photos', 'count_progress_photos',
    # Plans
    'save_plan', 'mark_plan_sent', 'get_plan', 'get_pending_digests', 'confirm_digest_delivery',
    # Subscriptions
    'get_subscription', 'create_subscription', 'update_subscription',
    'check_subscription_active', 'get_subscription_info',
    # Referrals
    'add_bonus_days', 'activate_bonus_days', 'cleanup_expired_bonus_days',
    'get_bonus_balance', 'create_referral', 'get_referral', 'get_referral_by_invited',
    'mark_referral_paid', 'get_referral_list', 'process_referral_payment',
    # Stats
    'get_weekly_stats', 'get_users_due_for_digest',
]