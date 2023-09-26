from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
router = Router()
@router.message(Command('start'))
async def start(message: Message):
    await message.answer(f'Здравствуйте, {message.from_user.first_name} {message.from_user.last_name}. Вас приветсвует официальный бот центра абдоминальной онкологии и проктологии Университетской клиники МГУ им. М.В. Ломоносова')
    await message.answer('Наберите команду /help для того, чтобы узнать функции бота')


#def register_start(dp: Dispatcher):
#    return dp.message.register(start)