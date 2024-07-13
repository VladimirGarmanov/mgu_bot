from random import randint

from aiogram import Router, F, types, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.types.input_file import FSInputFile
router = Router()

@router.message(F.text == "Памятка по госпитализации")
async def cmd_random(message: types.Message):

        builder = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Анализы для операции по "Малой проктологии"', callback_data='small')],
                                                        [InlineKeyboardButton(text='Анализы при операции по "Общей хирургии"', callback_data='general')],
                                                        [InlineKeyboardButton(
                                                            text='Анализы и обследования при "Онкологии"',
                                                            callback_data='oncology')],
                                                        [InlineKeyboardButton(text='Анализы перед "Эндоскопической операцией"', callback_data='endoscopy')],])


        await message.answer(
            "Выберите заболевание по которому вы проходили лечение",
            reply_markup=builder
        )
@router.callback_query(F.data == "small")
async def send_random_value(callback: types.CallbackQuery):
    document = FSInputFile('files/Small.pdf')
    await callback.message.answer_document(document)

@router.callback_query(F.data == "general")
async def send_random_value(callback: types.CallbackQuery):
    document = FSInputFile('files/General.pdf')
    await callback.message.answer_document(document)
@router.callback_query(F.data == "oncology")
async def send_random_value(callback: types.CallbackQuery):
    document = FSInputFile('files/oncology.pdf')
    await callback.message.answer_document(document)
@router.callback_query(F.data == "endoscopy")
async def send_random_value(callback: types.CallbackQuery):
    document = FSInputFile('files/endoscopy.pdf')
    await callback.message.answer_document(document)