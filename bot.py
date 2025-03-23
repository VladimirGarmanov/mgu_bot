import configparser
import time
import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, types, executor
import openai



config = configparser.ConfigParser()

# Чтение файла config.ini
config.read('config.ini')

# Загрузка конфигурации из файла
assistant_id = config.get('Config', 'assistant_id')
openai_api_key = config.get('Config', 'openai_api_key')
telegram_token = config.get('Config', 'telegram_token')
admin_id = config.get('Config', 'admin_id')

bot = Bot(token=telegram_token)
dp = Dispatcher(bot)
client = openai.OpenAI(api_key=openai_api_key)
users = []
Assistant_ID = assistant_id
print(Assistant_ID)
conn = sqlite3.connect('users.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    thread TEXT
)''')
conn.commit()
import httpx

async def send_text(login: str, message: str):
    url = "https://heliosai.ru/api/send_req"  # Замените на актуальный URL сервера
    data = {"login": login, "message": message}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=data)
        return response.json()

# Функция для добавления пользователя в базу данных
async def handle_with_assistant(message, chat_id):
    print('генерация началась')
    cursor.execute('SELECT thread FROM users WHERE chat_id = ?', (chat_id,))
    result = cursor.fetchone()
    thread_id = result[0] if result is not None else add_user(chat_id)
    message_answer = client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=f"{message.text}"

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
            content = 'Передали вашу заявку, скоро с вами свяжутся'
            await send_text('tatianagarmanova@gmail.com',)

        await bot.send_message(chat_id=message.chat.id, text=content)


def add_user(chat_id):
    cursor.execute('SELECT chat_id FROM users WHERE chat_id = ?', (chat_id,))
    thread = client.beta.threads.create()
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO users (chat_id, thread) VALUES (?, ?)', (chat_id, thread.id))
        conn.commit()
    print(thread.id)
    return thread.id


async def answer_user(message_response, message):
    await message.answer(message_response)


@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    add_user(message.chat.id)
    await message.answer("Здравствуйте! Рады приветствовать вас в ассистенте Помощь бабушкам с ИИ Чем могу помочь?")


@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def echo_message(message: types.Message):
    await handle_with_assistant(message, message.chat.id)


# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

