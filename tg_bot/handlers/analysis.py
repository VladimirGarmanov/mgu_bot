# coding=utf-8
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, PhotoSize, FSInputFile
import os
from datetime import datetime
router = Router()


class PhotoSendState(StatesGroup):
    name = State()
    sending = State()
    photos = State()


@router.message(Command('send_analysis'), F.chat.type == 'private')
async def start_handling_photos(msg: Message, state: FSMContext):
    await state.set_state(PhotoSendState.name)
    await msg.reply("Напишите свое имя:")


@router.message(PhotoSendState.name, F.chat.type == 'private')
async def start_handling_photos(msg: Message, state: FSMContext):
    if msg.text is None:
        return

    await state.set_state(PhotoSendState.sending)
    await state.update_data(photos=[], name=msg.text)
    await msg.reply("Отправляйте фотографии. Напишите 'стоп', чтобы завершить.")




@router.message(PhotoSendState.sending, F.chat.type == 'private')
async def handle_photo(msg: Message, state: FSMContext, bot: Bot):
    if not ((msg.photo is not None) or (msg.text is not None)):
        return

    if msg.text == 'стоп':
        await msg.answer('Ваши фотографии отправлены врачу')
        await state.set_state(None)
        data = await state.get_data()
        date = datetime.now()
        photos: list = data["photos"]
        name: str = data["name"]
        photo_dir = f'photos/{name}{date}'
        os.makedirs(photo_dir, exist_ok=True)
        for file_id in photos:
            print(f"doing {file_id}")
            file = await bot.get_file(file_id)
            file_path = file.file_path
            file_num = len(os.listdir(rf"./{photo_dir}"))+1
            await bot.download_file(file_path, rf"{photo_dir}/photo_{file_num}.jpg")
            await bot.send_photo('1474046178', FSInputFile(rf"{photo_dir}/photo_{file_num}.jpg"))


        return

    data = await state.get_data()
    photos: list = data["photos"]
    photos.append(msg.photo[-1].file_id)

    await state.update_data(photos=photos)
    await msg.reply("Фотография принята, продолжайте отправку или напишите 'стоп' чтобы закончить.")