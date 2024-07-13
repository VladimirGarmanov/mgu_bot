import asyncio
import logging
import sys
from os import getenv
from typing import Any, Dict



from aiogram import  Dispatcher, F, Router, html, Bot
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
from tg_bot.keyboards.docType import docTypes
from tg_bot.keyboards.consultType import typeCons
from tg_bot.keyboards.default import default
router = Router()


class Form(StatesGroup):
    name = State()
    age = State()
    email = State()
    number = State()
    type = State()
    doc = State()
    time = State()


@router.message(F.text == "Записаться на консультацию")
async def name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(Form.name)
    await message.answer(
        "Введите Ваше имя",
        reply_markup=ReplyKeyboardRemove(),
    )



@router.message(Form.name)
async def age(message: Message, state: FSMContext) -> None:

    await state.update_data(name=message.text)
    await state.set_state(Form.age)
    await message.answer(
        f"Введите Ваш возраст",

    )
    if message.text == 'отмена':
        await state.clear()


@router.message(Form.age)
async def email(message: Message, state: FSMContext) -> None:
    await state.update_data(age=message.text)
    await state.set_state(Form.email)
    await message.answer(
        "Введите ваш email",
        reply_markup=ReplyKeyboardRemove(),
    )
    if message.text == 'отмена':
        await state.clear()


@router.message(Form.email)
async def number(message: Message, state: FSMContext) -> None:
    await state.update_data(email=message.text)
    await state.set_state(Form.number)
    await message.answer(
        "Введите ваш номер телефона",
        reply_markup=ReplyKeyboardRemove(),
    )
    if message.text == 'отмена':
        await state.clear()
@router.message(Form.number)
async def consult(message: Message, state: FSMContext) -> None:
    await state.update_data(number=message.text)
    await state.set_state(Form.type)
    await message.answer(
        "Тип консультации",
        reply_markup=typeCons
    )
@router.message(Form.type)
async def docType(message: Message, state: FSMContext) -> None:
    await state.update_data(type=message.text)
    await state.set_state(Form.doc)
    await message.answer(
        "Выберите врача",
        reply_markup=docTypes
    )
    if message.text == 'отмена':
        await state.clear()
@router.message(Form.doc)
async def time(message: Message, state: FSMContext) -> None:
    await state.update_data(doc=message.text)
    await state.set_state(Form.time)
    await message.answer(
        "Выберите время",
        reply_markup=ReplyKeyboardRemove()
    )
    if message.text == 'отмена':
        await state.clear()
@router.message(Form.time)
async def end(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.update_data(time=message.text)
    await state.set_state(Form.time)
    data = await state.get_data()

    name = data.get('name')
    age = data.get('age')
    email = data.get('email')
    number = data.get('number')
    type_cons = data.get('type')
    doc = data.get('doc')
    time = data.get('time')

    response_message = (
        f"Пришла новая заявка на консультацию\n\n"
        f"ФИО: {name}\n"
        f"Возраст: {age}\n"
        f"Email: {email}\n"
        f"Номер телефона: {number}\n"
        f"Тип консультации: {type_cons}\n"
        f"Врач: {doc}\n"
        f"Удобное время: {time}\n"
    )
    response_message2 = (
        f"Ваша заявка на консультацию отправлена администратору скоро с вами свяжутся \n\n"
        f"Ваши данные\n"
        f"ФИО: {name}\n"
        f"Возраст: {age}\n"
        f"Email: {email}\n"
        f"Номер телефона: {number}\n"
        f"Тип консультации: {type_cons}\n"
        f"Врач: {doc}\n"
        f"Удобное время: {time}\n"
    )
    await state.clear()
    await message.answer(response_message2)
    await bot.send_message(chat_id=6613581898, text=response_message)


