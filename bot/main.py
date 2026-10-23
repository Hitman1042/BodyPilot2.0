"""Точка входа Telegram-бота BodyPilot."""

import asyncio
import logging
import socket
import sys

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from core.config import settings
from bot.logging_config import setup_logging

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
_log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
setup_logging(log_file="logs/botpilot.log", level=_log_level)
logger = logging.getLogger(__name__)


class IPv4Session(AiohttpSession):
    """Сессия с принудительным IPv4 и прокси."""

    def __init__(self, proxy_url: str | None = None):
        self.proxy_url = proxy_url
        super().__init__()

    async def create_session(self, **kwargs) -> aiohttp.ClientSession:
        # ВАЖНО: aiogram вызывает create_session() на КАЖДЫЙ запрос —
        # сессию нужно кэшировать, иначе каждый getUpdates создаёт новую
        # (и старая утекает: «Unclosed client session» в логах).
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                family=socket.AF_INET,  # Только IPv4
                limit=30,
                ttl_dns_cache=300,
            )

            # Прокси для обхода блокировок (если указан)
            proxy = self.proxy_url if self.proxy_url else None

            self._session = aiohttp.ClientSession(
                connector=connector,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=30),
                # Подхватывать системный прокси (Win-реестр / env-переменные),
                # если proxy_url не задан явно — иначе на машинах с прокси/VPN
                # прямое соединение с api.telegram.org уходит в таймаут.
                trust_env=proxy is None,
            )
        return self._session


async def main() -> None:
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК BODYPILOT БОТА")
    logger.info("=" * 60)
    logger.info("Версия Python: %s", sys.version)
    logger.info("Токен бота: %s...%s", settings.TELEGRAM_BOT_TOKEN[:10], settings.TELEGRAM_BOT_TOKEN[-5:])
    logger.info("База данных: %s", settings.DATABASE_PATH)

    # === ИНИЦИАЛИЗАЦИЯ БД (миграции) ===
    from core.database.connection import init_database
    init_database()
    logger.info("✅ База данных инициализирована (миграции применены)")

    # === ПРОКСИ (опционально) ===
    # Раскомментируй и укажи свой прокси если нужны обходы блокировок
    # proxy_url = "http://proxy-server:port"
    proxy_url = None  # Без прокси
    session = IPv4Session(proxy_url=proxy_url)

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    dp = Dispatcher(storage=MemoryStorage())

    # === MINI APP: кнопка слева от поля ввода ===
    if settings.MINIAPP_URL:
        try:
            from aiogram.types import MenuButtonWebApp, WebAppInfo
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="📱 Приложение",
                    web_app=WebAppInfo(url=settings.MINIAPP_URL),
                )
            )
            logger.info("✅ Menu Button Mini App установлена: %s", settings.MINIAPP_URL)
        except Exception as e:
            logger.warning("⚠️ Не удалось установить Menu Button Mini App: %s", e)

    # === MIDDLEWARE ===
    logger.info("📦 Подключение middleware...")
    from bot.middleware.throttling import ThrottlingMiddleware
    dp.message.middleware(ThrottlingMiddleware(message_interval=1.0, callback_interval=0.5))
    dp.callback_query.middleware(ThrottlingMiddleware(message_interval=1.0, callback_interval=0.5))
    logger.info("✅ Middleware подключены (Throttling)")

    from bot.middleware.db_session import DBSessionMiddleware
    dp.message.middleware(DBSessionMiddleware())
    dp.callback_query.middleware(DBSessionMiddleware())
    logger.info("✅ Middleware подключены")

    from bot.middleware.premium_check import PremiumMiddleware
    dp.message.middleware(PremiumMiddleware())
    dp.callback_query.middleware(PremiumMiddleware())
    logger.info("✅ Middleware подключены (Premium)")

    # === ROUTERS ===
    logger.info("📦 Подключение routers...")

    from bot.handlers.help import router as help_router
    dp.include_router(help_router)
    logger.info("  ✓ help_router")

    from bot.handlers.profile import router as profile_router
    dp.include_router(profile_router)
    logger.info("  ✓ profile_router")

    from bot.handlers.workout import router as workout_router
    dp.include_router(workout_router)
    logger.info("  ✓ workout_router")

    from bot.handlers.weight import router as weight_router
    dp.include_router(weight_router)
    logger.info("  ✓ weight_router")

    from bot.handlers.stats import router as stats_router
    dp.include_router(stats_router)
    logger.info("  ✓ stats_router")

    from bot.handlers.digest_handlers import router as digest_router
    dp.include_router(digest_router)
    logger.info("  ✓ digest_router")

    from bot.handlers.api_key import router as api_key_router
    dp.include_router(api_key_router)
    logger.info("  ✓ api_key_router")

    from bot.handlers.menu import router as menu_router
    dp.include_router(menu_router)
    logger.info("  ✓ menu_router")

    from bot.handlers.premium import router as premium_router
    dp.include_router(premium_router)
    logger.info("  ✓ premium_router")

    from bot.handlers.plans import router as plans_router
    dp.include_router(plans_router)
    logger.info("  ✓ plans_router")

    from bot.handlers.admin import router as admin_router
    dp.include_router(admin_router)
    logger.info("  ✓ admin_router")

    from bot.handlers.sport_selector import router as sport_router
    dp.include_router(sport_router)

    from bot.handlers.nutrition import router as nutrition_router
    dp.include_router(nutrition_router)

    from bot.handlers.food_tracker import router as food_tracker_router
    dp.include_router(food_tracker_router)
    logger.info("  ✓ food_tracker_router")

    # Фото прогресса — ДО ai_food: FSM «жду фото прогресса» должен иметь
    # приоритет над F.photo-хендлерами распознавания еды
    from bot.handlers.progress_photos import router as progress_photos_router
    dp.include_router(progress_photos_router)
    logger.info("  ✓ progress_photos_router")

    from bot.handlers.ai_food import router as ai_food_router
    dp.include_router(ai_food_router)

    from bot.handlers.ai_analyze import router as ai_analyze_router
    dp.include_router(ai_analyze_router)

    from bot.handlers.ai_chat import router as ai_chat_router
    dp.include_router(ai_chat_router)

    from bot.handlers.ai_nutrition import router as ai_nutrition_router
    dp.include_router(ai_nutrition_router)
    logger.info("  ✓ ai_nutrition_router")

    # Вечерний чек-ин — до smart_input: его FSM-состояние должно иметь приоритет
    from bot.handlers.checkin import router as checkin_router
    dp.include_router(checkin_router)
    logger.info("  ✓ checkin_router")

    # «Что съесть?» — команда и кнопки, конфликтов со smart_input нет
    from bot.handlers.what_to_eat import router as what_to_eat_router
    dp.include_router(what_to_eat_router)
    logger.info("  ✓ what_to_eat_router")

    # Ручной ввод активности (шаги/сон) — до smart_input
    from bot.handlers.health_log import router as health_log_router
    dp.include_router(health_log_router)
    logger.info("  ✓ health_log_router")

    # Свободный текст — ПОСЛЕДНИМ: команды, FSM и меню срабатывают раньше
    from bot.handlers.smart_input import router as smart_input_router
    dp.include_router(smart_input_router)
    logger.info("  ✓ smart_input_router")

    logger.info("✅ Все routers подключены")

    # === GLOBAL ERROR HANDLER ===
    from aiogram.types import ErrorEvent

    @dp.error()
    async def global_error_handler(event: ErrorEvent) -> bool:
        logger.exception("Необработанная ошибка: %s", event.exception, exc_info=event.exception)
        error_text = "⚠️ Произошла ошибка, мы уже разбираемся. Попробуйте ещё раз или /start"
        try:
            update = event.update
            if update.callback_query:
                await update.callback_query.message.answer(error_text)
                await update.callback_query.answer()
            elif update.message:
                await update.message.answer(error_text)
        except Exception as notify_error:
            logger.warning("Не удалось уведомить пользователя об ошибке: %s", notify_error)
        return True

    # === SCHEDULER ===
    logger.info("⏰ Запуск планировщика...")
    from core.scheduler import start_scheduler
    scheduler = start_scheduler(bot)
    logger.info("✅ Планировщик запущен")

    # === POLLING ===
    logger.info("=" * 60)
    logger.info("🎯 НАЧАЛО POLLING...")
    logger.info("=" * 60)

    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("⚠️  Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.exception("❌ Критическая ошибка polling: %s", e)
    finally:
        logger.info("🛑 Остановка бота...")
        if scheduler:
            scheduler.shutdown(wait=False)
            logger.info("⏹️  Планировщик остановлен")
        try:
            from core.ai.gemini_client import get_gemini_client
            gemini = get_gemini_client()
            if gemini is not None:
                await gemini.close()
                logger.info("⏹️  Gemini-клиент закрыт")
        except Exception as e:
            logger.warning("⚠️ Ошибка закрытия Gemini-клиента: %s", e)
        await bot.session.close()
        logger.info("✅ Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())