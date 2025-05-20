# ##main.py
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from bot_core import LunchBot

def setup_logging():
    """Настройка системы логирования"""
    handler = RotatingFileHandler(
        'bot.log',
        maxBytes=5*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[handler]
    )
    # Уменьшаем логирование от библиотек
    logging.getLogger('telegram').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)

async def run_bot():
    """Основная асинхронная функция запуска"""
    logger = logging.getLogger(__name__)
    try:
        logger.info("Инициализация бота...")
        bot = LunchBot()
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        raise

def main():
    """Точка входа для синхронного запуска"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("Запуск бота...")
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Приложение завершено")
    except Exception as e:
        logger.critical(f"Фатальная ошибка: {e}", exc_info=True)

if __name__ == "__main__":
    main()