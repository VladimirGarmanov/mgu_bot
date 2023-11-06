from  aiogram.types import ReplyKeyboardRemove,ReplyKeyboardMarkup,InlineKeyboardMarkup,InlineKeyboardButton, KeyboardButton
gm = KeyboardButton(text="Гарманова Татьяна Николаевна")
mk = KeyboardButton(text="Маркарьян Даниил Рафаэлович")
rd = KeyboardButton(text="Родимов Сергей Викторович")
docTypes = ReplyKeyboardMarkup(keyboard=[[gm],[mk],[rd]])