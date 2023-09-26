from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

router = Router()


@router.message(Command('clinic_details'))
async def start(message: Message):
    await message.answer('Узнать больше о нашей клинике вы можете по ссылке https://uniclinic.pro/ на сайте и по ссылке https://t.me/surgerymgy в нашем телеграм канале')


# def register_start(dp: Dispatcher):