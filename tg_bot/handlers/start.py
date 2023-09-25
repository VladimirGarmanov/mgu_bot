from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
router = Router()
@router.message(Command('start'))
async def start(message: Message):
    await message.answer('Добрый день!')

#def register_start(dp: Dispatcher):
#    return dp.message.register(start)