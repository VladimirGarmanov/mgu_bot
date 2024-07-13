from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from tg_bot.keyboards.doc_details import docs

router = Router()
from tg_bot.keyboards.default import default


@router.message(Command('doc_details'))
async def start(message: Message):
    await message.answer('Узнать больше о нашей клинике вы можете по ссылке https://uniclinic.pro/ на сайте и по ссылке https://t.me/surgerymgy в нашем телеграм канале',reply_markup=docs)

# def register_start(dp: Dispatcher):