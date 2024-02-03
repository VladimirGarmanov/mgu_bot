from  aiogram.types import ReplyKeyboardRemove,ReplyKeyboardMarkup,InlineKeyboardMarkup,InlineKeyboardButton, KeyboardButton
maskulin = KeyboardButton(text="Мужчина")
feminin = KeyboardButton(text="Женщина")
pol = ReplyKeyboardMarkup(keyboard=[[maskulin],[feminin]])
jun = KeyboardButton(text="от 18 до 39")
middle = KeyboardButton(text="от 40 до 60")
senior = KeyboardButton(text="больше 60")
age_k = ReplyKeyboardMarkup(keyboard=[[jun],[middle], [senior]])