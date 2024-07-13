import asyncio
import logging
import sys
from os import getenv
from typing import Any, Dict



from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from tg_bot.keyboards.check_up import pol,age_k
from tg_bot.keyboards.docType import docTypes
from tg_bot.keyboards.consultType import typeCons
router = Router()
from tg_bot.keyboards.default import default


class Form_c(StatesGroup):
    gender = State()
    age = State()



@router.message(Command('check_up'))
async def name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(Form_c.gender)
    await message.answer(
        "Вы мужчина или женщина?",
        reply_markup=pol,
    )




@router.message(Form_c.gender)
async def age(message: Message, state: FSMContext) -> None:
    await state.update_data(gender=message.text)
    await state.set_state(Form_c.age)
    await message.answer(
        f"Выберите возрастной диапазон, в котором вы находитесь ",
        reply_markup=age_k

    )
@router.message(Form_c.age)
async def end(message: Message, state: FSMContext) -> None:
    await state.update_data(age=message.text)
    await state.set_state(Form_c.age)
    data = await state.get_data()


    gender = data.get('gender')
    age = data.get('age')
    print(gender)
    if gender == 'Женщина':
        if age == 'от 18 до 39':
            await message.answer('Высылаю список анализов'+"\n"+"Пока нет списка анализов", reply_markup=default)
        if age == 'от 40 до 60':
            await message.answer('Высылаю список анализов'+"\n"+"Пока нет списка анализов", reply_markup=default)
        if age == 'больше 60':
            await message.answer('Высылаю список анализов'+"\n"+"Пока нет списка анализов", reply_markup=default)
    if gender == 'Мужчина':
        if age == 'от 18 до 39':
            await message.answer('Высылаю список анализов' + "\n" + "Пока нет списка анализов", reply_markup=default)
        if age == 'от 40 до 60':
            await message.answer('Высылаю список анализов' + "\n" + "Пока нет списка анализов", reply_markup=default)
        if age == 'больше 60':
            await message.answer('Высылаю список анализов' + "\n" + "Пока нет списка анализов", reply_markup=default)





    await state.clear()

     #await bot.send_message(chat_id=6613581898, text=response_message)
@router.message(Command("cancel"))
@router.message(F.text.casefold() == "cancel")
async def cancel_handler(message: Message, state: FSMContext) -> None:
    """
    Allow user to cancel any action
    """
    current_state = await state.get_state()
    if current_state is None:
        return

    logging.info("Cancelling state %r", current_state)
    await state.clear()
    await message.answer(
        "Cancelled.",
        reply_markup=ReplyKeyboardRemove(),
    )