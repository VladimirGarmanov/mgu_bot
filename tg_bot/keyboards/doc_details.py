from  aiogram.types import ReplyKeyboardRemove,ReplyKeyboardMarkup,InlineKeyboardMarkup,InlineKeyboardButton
gm = InlineKeyboardButton(text="Гарманова Татьяна Николаевна",url="https://uniclinic.pro/doctors/garmanova-tatyana-nikolaevna/")
mk = InlineKeyboardButton(text="Маркарьян Даниил Рафаэлович",url="https://uniclinic.pro/doctors/markaryan-daniil-rafaelevich/")
rd = InlineKeyboardButton(text="Родимов Сергей Викторович",url="https://uniclinic.pro/doctors/rodimov-sergey-viktorovich/")
docs = InlineKeyboardMarkup(inline_keyboard=[[gm,mk,rd]])