import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from tg_bot.config import load_config
from tg_bot.handlers import echo, clinic_details, doc_details, analysis, register

from tg_bot.handlers import start

logger = logging.getLogger(__name__)
def register_all_middlewares(dp):

    pass
def register_all_filters(dp):
    pass
def register_all_handlers(dp):
    pass
async  def main():
    global bot
    logging.basicConfig(level=logging.INFO,
                        format=u'%(filename)s:%(lineno)d #%(levelname)-8s [%(asctime)s] - %(name)s - %(message)s')
    config = load_config(path='.env')
    bot = Bot(token=config.tg_bot.token, parse_mode='HTML')
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_routers(start.router, clinic_details.router,doc_details.router,analysis.router, register.router)
    register_all_middlewares(dp=dp)
    register_all_filters(dp=dp)


    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await dp.storage.close()
        await bot.session.close()
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt,SystemExit):
        logger.error('Bot has stopped!!!')

