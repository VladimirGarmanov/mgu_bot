import openai
import time
import asyncio
import sqlite3

from aiogram import types, Router, F,Bot
from aiogram.types import Message
from aiogram.filters import Command

client = openai.OpenAI(api_key='sk-proj-EzNl6gwNCPB8zoSzO1yaT3BlbkFJIHcAASWRs7Au7Oi0tc26')
router = Router()
Assistant_ID = 'asst_lOELwEP2IoT5lTRbBNUXayXA'
users = []

conn = sqlite3.connect('users.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    thread TEXT
)''')
conn.commit()


# Функция для добавления пользователя в базу данных
async def handle_with_assistant(message, chat_id, bot):
    print('генерация началась')
    cursor.execute('SELECT thread FROM users WHERE chat_id = ?', (chat_id,))
    result = cursor.fetchone()
    thread_id = result[0] if result is not None else add_user(chat_id)
    message_answer = client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=message.text

    )
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=Assistant_ID,

    )

    time.sleep(10)
    run_status = client.beta.threads.runs.retrieve(
        thread_id=thread_id,
        run_id=run.id
    )

    print(run_status.status)
    while run_status.status == 'in_progress':
        time.sleep(5)
        run_status = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run.id
        )
    print(run_status.status)
    if run_status.status == 'completed':
        messages = client.beta.threads.messages.list(
            thread_id=thread_id
        )

        msg = messages.data[0]
        role = msg.role
        content = msg.content[0].text.value
        print(f"{role.capitalize()}: {content}")
        if 'send' in content:
            await bot.send_message(chat_id='380656544', text=f"{content} {message.from_user.username}")
            await message.answer(text='Я передал вашу заявку нашему администратору')
        else:

            await message.answer(text=content)


def add_user(chat_id):
    cursor.execute('SELECT chat_id FROM users WHERE chat_id = ?', (chat_id,))
    thread = client.beta.threads.create()
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO users (chat_id, thread) VALUES (?, ?)', (chat_id, thread.id))
        conn.commit()
    return thread.id


async def answer_user(message_response, message):
    await message.answer(message_response)


@router.message(Command('manager_help'))
async def start(message: Message):
    add_user(message.chat.id)
    users.append(message.chat.id)
    await message.answer("Начинаем разговор.")

def delete_user(chat_id):
    cursor.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
@router.message(Command('manager_stop'))
async def start(message: Message):
    delete_user(message.chat.id)
    await message.answer("Разговор прекращен.")
    users.remove(message.chat.id)
    print(message.chat.id)

@router.message(F.text)
async def echo_message(message: types.Message):
    if message.chat.id in users:
        await handle_with_assistant(message, message.chat.id, Bot('6517527928:AAHtrSHL1C0B7A5ALXapsYrjVl-h9UY-cpc'))