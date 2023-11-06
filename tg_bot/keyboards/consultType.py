from  aiogram.types import ReplyKeyboardRemove,ReplyKeyboardMarkup,InlineKeyboardMarkup,InlineKeyboardButton, KeyboardButton
gm = KeyboardButton(text="Очная консультация")
mk = KeyboardButton(text="Онлайн консультация")

typeCons = ReplyKeyboardMarkup(keyboard=[[gm],[mk]])