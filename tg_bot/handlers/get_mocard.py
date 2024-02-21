from random import randint

from aiogram import Router, F, types, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.types.input_file import FSInputFile
router = Router()
bot = Bot(token='6517527928:AAHtrSHL1C0B7A5ALXapsYrjVl-h9UY-cpc')
@router.message(Command('get_moncard'))
async def cmd_random(message: types.Message):
        builder = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Рак прямой кишки', callback_data='random_value')],
                                                        [InlineKeyboardButton(text='Рак ободочной кишки', callback_data='right')]])


        await message.answer(
            "Выберите заболевание по которому вы проходили лечение",
            reply_markup=builder
        )
@router.callback_query(F.data == "random_value")
async def send_random_value(callback: types.CallbackQuery):
    document = FSInputFile('files/monCardStraightColon.pdf')
    await callback.message.answer_document(document)

@router.callback_query(F.data == "right")
async def send_random_value(callback: types.CallbackQuery):
    document = FSInputFile('files/monCardColon.pdf')
    await callback.message.answer_document(document)