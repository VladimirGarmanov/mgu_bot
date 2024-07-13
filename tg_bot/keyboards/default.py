from  aiogram.types import ReplyKeyboardRemove,ReplyKeyboardMarkup,InlineKeyboardMarkup,InlineKeyboardButton, KeyboardButton
reg = KeyboardButton(text="Записаться на консультацию")
pam = KeyboardButton(text="Памятка по госпитализации")

default = ReplyKeyboardMarkup(keyboard=[[reg],[pam]])