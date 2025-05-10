import asyncio
import signal
import platform
from bot_core import LunchBot
import logging
import os
from bot_core import LunchBot
from handlers import setup_handlers  # Импорт из handlers/__init__.py
from telegram.ext import MessageHandler
from config import CONFIG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='bot.log'
)

async def shutdown(bot):
    print("\n🛑 Завершение работы бота...")
    await bot.stop()

async def main():
    # Добавьте для теста
    print("Проверка конфига:")
    print("Admin IDs:", CONFIG['admin_ids'])
    print("Token:", CONFIG['token'][:5] + "...")
    
    bot = LunchBot()
    setup_handlers(bot.application)  # Настройка обработчиков
    await bot.run()
    
    # Настройка обработки Ctrl+C для всех ОС
    if platform.system() == 'Windows':
        # Для Windows используем простой обработчик KeyboardInterrupt
        try:
            task = asyncio.create_task(bot.run())
            await task
        except asyncio.CancelledError:
            await shutdown(bot)
    else:
        # Для Linux/Unix настраиваем обработчики сигналов
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(shutdown(bot))
            )
        try:
            await bot.run()
        except asyncio.CancelledError:
            pass  # Обработка уже выполнена в shutdown

    print("✅ Работа бота завершена")

if __name__ == "__main__":
    try:
        if platform.system() == 'Windows':
            # Специальная обработка для Windows
            async def windows_main():
                try:
                    await main()
                except KeyboardInterrupt:
                    print("\n🛑 Принудительное завершение")
            
            asyncio.run(windows_main())
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Принудительное завершение")
    except Exception as e:
        print(f"❌ Критическая ошибка: {str(e)}")
