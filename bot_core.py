from telegram.ext import ApplicationBuilder, PicklePersistence
from handlers import setup_handlers
from config import CONFIG
from cron_jobs import setup_cron_jobs
import logging
import asyncio

logger = logging.getLogger(__name__)

class LunchBot:
    def __init__(self):
        self._running = False
        self.persistence = PicklePersistence(filepath='bot_persistence.pickle')
        self.application = (
            ApplicationBuilder()
            .token(CONFIG['token'])
            .persistence(persistence=self.persistence)
            .read_timeout(30)
            .write_timeout(30)
            .connect_timeout(30)
            .pool_timeout(30)
            .get_updates_read_timeout(30)
            .http_version('1.1')
            .build()
        )
        setup_handlers(self.application)
        self.updater = None

    async def run(self):
        self._running = True
        try:
            await self.application.initialize()
            await self.application.start()
            
            # Запускаем long polling
            self.updater = self.application.updater
            if self.updater:
                await self.updater.start_polling()
            
            await setup_cron_jobs(self.application)
            logger.info("Бот запущен и готов к работе")
            
            # Бесконечный цикл обработки
            while self._running:
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Ошибка в работе бота: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        if not self._running:
            return
            
        self._running = False
        try:
            if self.updater and self.updater.running:
                await self.updater.stop()
            
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Бот корректно остановлен")
            
        except Exception as e:
            logger.error(f"Ошибка при остановке: {e}")
            raise
