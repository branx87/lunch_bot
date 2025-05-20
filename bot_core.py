# ##handlers/bot_core.py
from telegram.ext import ApplicationBuilder, PicklePersistence
import logging
import asyncio
import platform
import signal

from config import CONFIG

logger = logging.getLogger(__name__)

class LunchBot:
    def __init__(self):
        self.application = None
        self._running = False

    async def run(self):
        """Основной цикл работы бота"""
        from config import CONFIG  # Локальный импорт для избежания циклов
        
        try:
            self._running = True
            self.application = (
                ApplicationBuilder()
                .token(CONFIG['token'])
                .build()
            )
            
            # Инициализация обработчиков
            from handlers import setup_handlers
            setup_handlers(self.application)
            
            # Запуск
            await self.application.initialize()
            await self.application.start()
            
            if self.application.updater:
                await self.application.updater.start_polling()
            
            logging.getLogger(__name__).info("Бот успешно запущен")
            
            # Бесконечный цикл
            while self._running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logging.getLogger(__name__).error(f"Ошибка: {e}", exc_info=True)
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Корректная остановка"""
        if not self._running:
            return
            
        self._running = False
        logger = logging.getLogger(__name__)
        
        try:
            if hasattr(self, 'application') and self.application:
                if self.application.updater and self.application.updater.running:
                    await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            logger.info("Бот корректно остановлен")
        except Exception as e:
            logger.error(f"Ошибка при остановке: {e}", exc_info=True)