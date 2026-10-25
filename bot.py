"""Polling Telegram intake with durable delivery queue and optional Responses API."""
import asyncio
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

CONSENT = '2026-10-11-multichat'
MENU = {'keyboard': [[{'text': 'Записаться'}, {'text': 'Перезвоните мне'}]], 'resize_keyboard': True}
PHONE = '+7 (967) 136-77-06'
EMERGENCY = 'Если состояние угрожает жизни, есть сильное кровотечение, потеря сознания или затруднение дыхания — звоните 112 или 103. Не ждите ответа в чате.'

@dataclass
class Settings:
    token: str
    group: int | None
    topic: int | None
    key: str
    model: str
    database: Path
    instructions: str
    retention: int = 7

    @classmethod
    def load(cls):
        load_dotenv(Path(__file__).with_name('.env'), override=False)
        token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        group = os.getenv('TELEGRAM_GROUP_ID', '')
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token):
            raise RuntimeError('Заполните TELEGRAM_BOT_TOKEN в TelegramBot/.env')
        if group and not re.fullmatch(r'-\d+', group):
            raise RuntimeError('Необязательный TELEGRAM_GROUP_ID должен быть отрицательным числом')
        instructions = Path(os.getenv('BOT_INSTRUCTIONS_PATH') or Path(__file__).with_name('instructions.txt')).read_text()
        instructions += '\n\nСПРАВОЧНИК КЛИНИКИ (информация владельца, 21.10.2026):\n' + Path(__file__).with_name('knowledge.txt').read_text()
        return cls(token, int(group) if group else None, int(os.environ['TELEGRAM_TOPIC_ID']) if os.getenv('TELEGRAM_TOPIC_ID') else None,
                   os.getenv('OPENAI_API_KEY', ''), os.getenv('OPENAI_MODEL', 'gpt-5-mini'),
                   Path(os.getenv('BOT_DB_PATH', './data/telegram-bot.sqlite')), instructions,
                   max(1, int(os.getenv('BOT_RETENTION_DAYS', '7'))))

class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS sessions(chat INTEGER PRIMARY KEY, payload TEXT NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS delivery(code TEXT PRIMARY KEY, chat INTEGER NOT NULL, payload TEXT NOT NULL,
            created REAL NOT NULL, sent INTEGER NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS destinations(chat INTEGER PRIMARY KEY, title TEXT NOT NULL,
            kind TEXT NOT NULL, username TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS recipients(code TEXT NOT NULL REFERENCES delivery(code) ON DELETE CASCADE,
            chat INTEGER NOT NULL, topic INTEGER, sent INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(code,chat));
        CREATE TABLE IF NOT EXISTS limits(chat INTEGER PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL);
        ''')
    def get(self, chat):
        row = self.db.execute('SELECT payload FROM sessions WHERE chat=? AND updated>?', (chat, time.time()-86400)).fetchone()
        return json.loads(row[0]) if row else {'step': 'consent'}
    def save(self, chat, payload):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)', (chat, json.dumps(payload, ensure_ascii=False), time.time()))
    def clear(self, chat):
        with self.db:
            self.db.execute('DELETE FROM sessions WHERE chat=?', (chat,))
    def allow(self, chat):
        now = time.time()
        row = self.db.execute('SELECT * FROM limits WHERE chat=?', (chat,)).fetchone()
        count = row['count']+1 if row and row['started'] > now-60 else 1
        start = row['started'] if row and row['started'] > now-60 else now
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO limits VALUES(?,?,?)', (chat, start, count))
        return count <= 10
    def queue(self, chat, payload):
        code = 'TG-' + secrets.token_hex(5).upper()
        with self.db:
            self.db.execute('INSERT INTO delivery(code,chat,payload,created) VALUES(?,?,?,?)', (code, chat, json.dumps(payload, ensure_ascii=False), time.time()))
            for target in payload.get('destinations', []):
                self.db.execute('INSERT INTO recipients(code,chat,topic) VALUES(?,?,?)', (code, target['chat'], target.get('topic')))
            self.db.execute('DELETE FROM sessions WHERE chat=?', (chat,))
        return code
    def cleanup(self, days):
        with self.db:
            self.db.execute('DELETE FROM sessions WHERE updated<?', (time.time()-86400,))
            self.db.execute('DELETE FROM limits WHERE started<?', (time.time()-3600,))
            self.db.execute('DELETE FROM delivery WHERE created<?', (time.time()-days*86400,))

class Bot:
    def __init__(self, settings, client, store):
        self.settings, self.client, self.store = settings, client, store
    async def telegram(self, method, **payload):
        # Never log exceptions with request URLs: Telegram puts the token in the URL.
        try:
            response = await self.client.post(f'https://api.telegram.org/bot{self.settings.token}/{method}', json=payload)
            data = response.json()
            if response.status_code != 200 or not data.get('ok'):
                raise RuntimeError('Telegram request failed')
            return data['result']
        except (httpx.HTTPError, ValueError):
            raise RuntimeError('Telegram network error') from None
    async def say(self, chat, text, keyboard=None):
        return await self.telegram('sendMessage', chat_id=chat, text=text[:4000], protect_content=True,
                                   link_preview_options={'is_disabled': True}, reply_markup=keyboard or {'remove_keyboard': True})
    async def identity(self):
        if not getattr(self, 'bot_id', None):
            self.bot_id = (await self.telegram('getMe'))['id']
        return self.bot_id
    async def discover(self, chat_id):
        """Trust Telegram's live membership, never message text or the model."""
        info = await self.telegram('getChat', chat_id=chat_id)
        if info.get('type') not in {'group', 'supergroup', 'channel'}:
            return None
        member = await self.telegram('getChatMember', chat_id=chat_id, user_id=await self.identity())
        active = member.get('status') in {'administrator', 'creator'}
        if info['type'] == 'channel' and member.get('status') != 'creator':
            active = active and bool(member.get('can_post_messages'))
        with self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO destinations VALUES(?,?,?,?,?)',
                (chat_id, info.get('title', str(chat_id)), info['type'], info.get('username', ''), int(active)))
        return {'chat': chat_id, 'title': info.get('title', str(chat_id)), 'kind': info['type'],
                'username': info.get('username', ''),
                'topic': self.settings.topic if chat_id == self.settings.group else None} if active else None
    async def destinations(self):
        result = []
        for row in self.store.db.execute('SELECT chat FROM destinations WHERE active=1 ORDER BY chat').fetchall():
            target = await self.discover(row['chat'])
            if target:
                result.append(target)
        return result
    async def show_confirmation(self, chat, state):
        targets = await self.destinations()
        state['destinations'] = targets
        self.store.save(chat, state)
        await self.say(chat, self.summary(state))
        if not targets:
            await self.say(chat, 'Сейчас не получается отправить заявку. Позвоните '+PHONE+' или повторите «Отправить заявку» позже.')
            return
        await self.say(chat, 'Всё верно? Нажмите «Отправить заявку». Исправить данные: /start. Отменить: /cancel.',
                       {'keyboard': [[{'text': 'Отправить заявку'}]], 'resize_keyboard': True, 'one_time_keyboard': True})
    async def validate(self):
        await self.identity()
        if (await self.telegram('getWebhookInfo')).get('url'):
            raise RuntimeError('У бота настроен webhook. Сначала остановите прежний сервис; webhook автоматически не удаляется.')
        if self.settings.group:
            await self.discover(self.settings.group)
        print('Telegram verified. Admin chats are discovered automatically.', flush=True)
    async def ai_reply(self, concern, history=None):
        if not self.settings.key:
            return self.fallback_reply(concern)
        # Separately collected name/phone/Telegram IDs are excluded. Redact contacts in free text too.
        redacted = re.sub(r'\+?\d[\d ()-]{6,}\d|[\w.+-]+@[\w.-]+|https?://\S+|@\w+', '[контакт скрыт]', concern)
        try:
            response = await self.client.post('https://api.openai.com/v1/responses', headers={'Authorization': 'Bearer '+self.settings.key}, json={
                'model': self.settings.model, 'instructions': self.settings.instructions,
                'input': (history or [])[-6:] + [{'role': 'user', 'content': redacted}], 'store': False, 'max_output_tokens': 2000,
            })
            response.raise_for_status()
            body = response.json()
            if body.get('status') != 'completed':
                return self.fallback_reply(concern)
            text = '\n'.join(part.get('text', '') for item in body.get('output', []) if item.get('type') == 'message' for part in item.get('content', []) if part.get('type') == 'output_text')
            return text[:3500] or self.fallback_reply(concern)
        except (httpx.HTTPError, ValueError, KeyError):
            return self.fallback_reply(concern)
    @staticmethod
    def fallback_reply(text):
        text = text.lower()
        if re.search(r'адрес|добраться|где наход|контакт', text):
            return f'Москва, Ломоносовский проспект, 27, корпус 10. Телефон {PHONE}, почта info@uniclinic.pro. Карта: https://uniclinic.pro/contacts.'
        if 'колоноскоп' in text:
            return 'Запись на колоноскопию: +7 (910) 666-34-32 — заведующий отделением Бабаджанян Арутюн Родионович.'
        if 'омс' in text or '057' in text:
            return 'Для консультации по ОМС в клинике требуется направление 057/у из государственной поликлиники. Возможность лечения по ОМС для вашего случая уточнит сотрудник — можно заказать обратный звонок.'
        if re.search(r'онлайн|дистанц', text):
            return 'Онлайн-консультации возможны. Нажмите «Записаться»: укажите врача и удобное время, а сотрудник согласует детали.'
        if re.search(r'^привет|^здравств|^добрый', text):
            return 'Здравствуйте! Помогу разобраться с записью, консультациями и условиями лечения. Что хотите уточнить?'
        return f'Сейчас не получается уточнить этот вопрос автоматически. Можно заказать звонок кнопкой «Перезвоните мне» или связаться с клиникой: {PHONE}.'
    async def answer_question(self, chat, state, question):
        if not 3 <= len(question) <= 1500:
            await self.say(chat, 'Напишите вопрос текстом, до 1500 символов.'); return
        history = state.get('history', [])
        answer = await self.ai_reply(question, history) if state.get('ai') else self.fallback_reply(question)
        # Collected appointment fields never enter model context.
        redacted = re.sub(r'\+?\d[\d ()-]{6,}\d|[\w.+-]+@[\w.-]+|https?://\S+|@\w+', '[контакт скрыт]', question)
        state['history'] = (history + [{'role': 'user', 'content': redacted}, {'role': 'assistant', 'content': answer}])[-6:]
        self.store.save(chat, state)
        await self.say(chat, answer, MENU if state['step'] == 'chat' else None)
    async def process(self, update):
        membership = update.get('my_chat_member')
        if membership:
            chat = membership['chat']
            if chat.get('type') in {'group', 'supergroup', 'channel'}:
                status = membership['new_chat_member']['status']
                if status not in {'administrator', 'creator'}:
                    with self.store.db:
                        self.store.db.execute('UPDATE destinations SET active=0 WHERE chat=?', (chat['id'],))
                else:
                    await self.discover(chat['id'])
            return
        message = update.get('message') or update.get('channel_post') or {}
        chat = message.get('chat', {})
        if chat.get('type') in {'group', 'supergroup', 'channel'}:
            # Only metadata is inspected. Staff text never goes to OpenAI.
            if message.get('migrate_to_chat_id'):
                with self.store.db:
                    self.store.db.execute('UPDATE destinations SET active=0 WHERE chat=?', (chat['id'],))
                await self.discover(message['migrate_to_chat_id'])
            else:
                known = self.store.db.execute('SELECT active FROM destinations WHERE chat=?', (chat['id'],)).fetchone()
                command = (message.get('text') or '').split('@')[0]
                if not known or command == '/register':
                    await self.discover(chat['id'])
            return
        if chat.get('type') != 'private' or message.get('from', {}).get('is_bot'):
            return
        chat_id = chat['id']
        text = (message.get('text') or '').strip()
        if not self.store.allow(chat_id):
            return
        if text.startswith('/start') or text in {'/cancel', '/delete'}:
            self.store.clear(chat_id)
            if text in {'/cancel', '/delete'}:
                with self.store.db:
                    self.store.db.execute('DELETE FROM delivery WHERE chat=? AND sent=0', (chat_id,))
                await self.say(chat_id, 'Незавершённое обращение и ожидающие отправки заявки удалены. Уже переданные сообщения находятся у клиники. Новое обращение: /start')
                return
            text = ''
        if text == '/help':
            await self.say(chat_id, f'Задайте вопрос обычным сообщением или выберите запись / обратный звонок. /start — начать заново; /cancel — отменить; /delete — удалить неотправленное; /operator — обращение без OpenAI. Телефон: {PHONE}.')
            return
        if re.search(r'не могу дышать|теряю сознание|сильн\w* кровотеч|кровь не останавливается|сильн\w* боль в груди', text.lower()):
            await self.say(chat_id, EMERGENCY)
            return
        state = self.store.get(chat_id)
        if text == '/operator':
            state = {'step': 'consent', 'ai': False}
            self.store.save(chat_id, state)
            text = ''
        if state['step'] == 'consent':
            if text != 'Согласен':
                await self.say(chat_id, 'Здравствуйте! Я виртуальный помощник Клиники МГУ. Подскажу по стоимости, ОМС и консультациям, помогу оставить заявку.\n\n'+('Вопросы обрабатываются OpenAI — не указывайте в переписке личные данные. Режим без OpenAI: /operator. ' if state.get('ai', True) else 'Вы выбрали режим без OpenAI. ')+'При записи отдельно попрошу имя и телефон; перед отправкой покажу заявку для проверки.\nПолитика: https://uniclinic.pro/privacy. Нажимая «Согласен», вы соглашаетесь на обработку данных для ответа и передачи заявки. Отмена: /cancel.', {'keyboard': [[{'text': 'Согласен'}]], 'resize_keyboard': True, 'one_time_keyboard': True})
                return
            state.update(step='chat', consent=CONSENT, consent_at=time.time(), ai=state.get('ai', True))
            self.store.save(chat_id, state)
            await self.say(chat_id, 'Что хотите уточнить? Можно написать вопрос или выбрать запись / обратный звонок.', MENU)
            return
        if state['step'] == 'chat':
            if re.fullmatch(r'(?:пожалуйста[, ]+)?(?:перезвоните(?: мне)?|хочу (?:обратный )?звонок)[.! ]*', text.lower()):
                text = 'Перезвоните мне'
            elif re.fullmatch(r'(?:хочу |хотел(?:а)? бы )?записаться(?: на (?:при[её]м|консультацию))?[.! ]*', text.lower()):
                text = 'Записаться'
        if text in {'Записаться', 'Перезвоните мне'}:
            state.update(step='name', request_type='callback' if text == 'Перезвоните мне' else 'appointment', history=[])
            for key in ('name', 'phone', 'concern', 'duration', 'destinations'):
                state.pop(key, None)
            self.store.save(chat_id, state)
            await self.say(chat_id, 'Как к вам обращаться? Достаточно имени.' if state['request_type'] == 'callback' else 'Напишите, пожалуйста, фамилию, имя и отчество для записи.')
            return
        if text.startswith('/ask '):
            question = text[5:].strip()
            if not 3 <= len(question) <= 1500:
                await self.say(chat_id, 'После /ask напишите вопрос длиной от 3 до 1500 символов.')
                return
            await self.answer_question(chat_id, state, question)
            return
        if state['step'] == 'chat':
            await self.answer_question(chat_id, state, text)
            return
        if '?' in text and state['step'] != 'concern':
            await self.answer_question(chat_id, state, text)
            await self.say(chat_id, 'Данные заявки ещё не отправлены. Продолжите с предыдущего вопроса или /cancel — отменить.')
            return
        if not text and not message.get('contact'):
            await self.say(chat_id, 'Пожалуйста, ответьте текстом. Документы, фото и голосовые сообщения бот не обрабатывает.')
            return
        if state['step'] == 'name':
            if not 1 <= len(text) <= 80 or text.startswith('/'):
                await self.say(chat_id, 'Напишите имя, до 80 символов.'); return
            state.update(name=text, step='phone' if state.get('request_type') == 'callback' else 'details')
            self.store.save(chat_id, state)
            if state['step'] == 'phone':
                state.update(concern='Обратный звонок', duration='')
                self.store.save(chat_id, state)
                await self.ask_phone(chat_id)
            else:
                await self.say(chat_id, 'К какому врачу хотите записаться и какое время удобно? Если врача ещё не выбрали, напишите цель консультации. Для онлайн-приёма добавьте «онлайн».')
        elif state['step'] == 'details':
            if not 3 <= len(text) <= 1500:
                await self.say(chat_id, 'Напишите пожелания к записи текстом, до 1500 символов.'); return
            state.update(concern=text, duration='', step='phone')
            self.store.save(chat_id, state)
            await self.ask_phone(chat_id)
        elif state['step'] == 'concern':
            if not 3 <= len(text) <= 1500:
                await self.say(chat_id, 'Опишите вопрос текстом от 3 до 1500 символов.'); return
            state.update(concern=text, step='duration')
            self.store.save(chat_id, state)
            reply = await self.ai_reply(text) if state.get('ai') else 'Описание сохранено для сотрудников клиники.'
            await self.say(chat_id, reply + '\n\nКак давно это беспокоит? Если вопрос организационный, напишите «не относится».')
        elif state['step'] == 'duration':
            if not 1 <= len(text) <= 250:
                await self.say(chat_id, 'Ответьте кратко, до 250 символов.'); return
            state.update(duration=text, step='phone')
            self.store.save(chat_id, state)
            await self.ask_phone(chat_id)
        elif state['step'] == 'phone':
            contact = message.get('contact')
            if contact and contact.get('user_id') != message.get('from', {}).get('id'):
                await self.say(chat_id, 'Отправьте собственный контакт или введите телефон текстом.'); return
            phone = contact.get('phone_number', '') if contact else text
            digits = re.sub(r'\D', '', phone)
            if not 7 <= len(digits) <= 15 or len(phone) > 40:
                await self.say(chat_id, 'Укажите телефон с кодом страны: от 7 до 15 цифр.'); return
            state.update(phone=phone, step='confirm')
            self.store.save(chat_id, state)
            await self.show_confirmation(chat_id, state)
        elif state['step'] == 'confirm':
            if text != 'Отправить заявку':
                await self.say(chat_id, 'Для передачи нажмите «Отправить заявку». Исправить данные: /start. Отменить: /cancel.'); return
            if not state.get('destinations'):
                await self.show_confirmation(chat_id, state)
                return
            # Recheck rights and public/private changes before accepting confirmation.
            current = [target for target in [await self.discover(t['chat']) for t in state['destinations']] if target]
            if current != state['destinations']:
                await self.show_confirmation(chat_id, state)
                return
            code = self.store.queue(chat_id, state)
            self.store.save(chat_id, {'step': 'chat', 'ai': state.get('ai', True), 'consent': state['consent'], 'consent_at': state['consent_at']})
            await self.say(chat_id, f'Заявка {code} принята. Сейчас отправлю её сотрудникам и сообщу о доставке. Время приёма согласует администратор.', MENU)
    async def ask_phone(self, chat):
        await self.say(chat, 'На какой номер вам позвонить? Введите телефон или отправьте свой контакт кнопкой.', {'keyboard': [[{'text': 'Отправить мой телефон', 'request_contact': True}]], 'resize_keyboard': True, 'one_time_keyboard': True})
    @staticmethod
    def summary(state):
        kind = 'Обратный звонок' if state.get('request_type') == 'callback' else 'Запись / консультация'
        summary = f'{kind}\nИмя: {state["name"]}\nТелефон: {state["phone"]}\nПожелания: {state["concern"]}'
        return summary + (f'\nКак давно: {state["duration"]}' if state.get('duration') else '')
    async def flush(self):
        rows = self.store.db.execute('SELECT * FROM delivery WHERE (sent=0 OR notified=0) AND next_attempt<=? ORDER BY created LIMIT 10', (time.time(),)).fetchall()
        for row in rows:
            try:
                if not row['sent']:
                    recipients = self.store.db.execute('SELECT * FROM recipients WHERE code=?', (row['code'],)).fetchall()
                    if not recipients:
                        # Old queued requests had consent for one configured group only.
                        if not self.settings.group:
                            raise RuntimeError('Legacy request requires its original configured group')
                        with self.store.db:
                            self.store.db.execute('INSERT INTO recipients(code,chat,topic) VALUES(?,?,?)', (row['code'], self.settings.group, self.settings.topic))
                        recipients = self.store.db.execute('SELECT * FROM recipients WHERE code=?', (row['code'],)).fetchall()
                    payload = json.loads(row['payload'])
                    for recipient in recipients:
                        if recipient['sent'] or recipient['skipped']:
                            continue
                        try:
                            target = await self.discover(recipient['chat'])
                            approved = next((t for t in payload.get('destinations', []) if t['chat'] == recipient['chat']), None)
                            if not target or (approved and (target['username'] != approved['username'] or target['kind'] != approved['kind'])):
                                with self.store.db:
                                    self.store.db.execute('UPDATE recipients SET skipped=1 WHERE code=? AND chat=?', (row['code'], recipient['chat']))
                                continue
                            args = {'chat_id': recipient['chat'], 'text': f'Новая заявка {row["code"]}\n'+self.summary(payload)+f'\nСогласие: {payload["consent"]}', 'protect_content': True, 'link_preview_options': {'is_disabled': True}}
                            if recipient['topic']:
                                args['message_thread_id'] = recipient['topic']
                            receipt = await self.telegram('sendMessage', **args)
                            with self.store.db:
                                self.store.db.execute('UPDATE recipients SET sent=? WHERE code=? AND chat=?', (receipt['message_id'], row['code'], recipient['chat']))
                        except RuntimeError:
                            # One failed recipient must not block the remaining chats.
                            continue
                    pending = self.store.db.execute('SELECT COUNT(*) FROM recipients WHERE code=? AND sent=0 AND skipped=0', (row['code'],)).fetchone()[0]
                    if pending:
                        raise RuntimeError('Recipient delivery pending')
                    with self.store.db:
                        self.store.db.execute('UPDATE delivery SET sent=1,payload=? WHERE code=?', ('{}', row['code']))
                receipts = self.store.db.execute('SELECT COUNT(*) AS total, SUM(sent>0) AS delivered FROM recipients WHERE code=?', (row['code'],)).fetchone()
                if receipts['total'] == 0:  # Already delivered by the previous single-chat version.
                    result = 'передана сотрудникам клиники'
                elif receipts['delivered']:
                    result = 'передана сотрудникам клиники' if receipts['delivered'] == receipts['total'] else 'передана частично. Уточните получение по телефону клиники'
                else:
                    result = 'не доставлена. Пожалуйста, позвоните в клинику'
                await self.say(row['chat'], f'Заявка {row["code"]} {result}. Телефон клиники: {PHONE}.')
                with self.store.db:
                    self.store.db.execute('UPDATE delivery SET notified=1 WHERE code=?', (row['code'],))
            except RuntimeError:
                with self.store.db:
                    self.store.db.execute('UPDATE delivery SET attempts=attempts+1,next_attempt=? WHERE code=?', (time.time()+min(3600, 30*2**min(row['attempts'], 7)), row['code']))
                print('Delivery deferred; retry scheduled. No patient data logged.', flush=True)

async def main():
    os.umask(0o077)
    settings = Settings.load()
    store = Store(settings.database)
    with settings.database.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logging.getLogger('httpx').setLevel(logging.CRITICAL)
        logging.getLogger('httpcore').setLevel(logging.CRITICAL)
        async with httpx.AsyncClient(timeout=45) as client:
            bot = Bot(settings, client, store)
            await bot.validate()
            while True:
                try:
                    store.cleanup(settings.retention)
                    # Resume persisted requests before waiting for new Telegram messages.
                    await bot.flush()
                    row = store.db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
                    offset = row[0] if row else 0
                    updates = await bot.telegram('getUpdates', offset=offset, timeout=25, allowed_updates=['message', 'channel_post', 'my_chat_member'])
                    for update in updates:
                        try:
                            await bot.process(update)
                        except RuntimeError:
                            # State is persisted before a reply. Replaying this update could
                            # incorrectly consume the old answer as the next intake field.
                            print('Reply unavailable; update acknowledged. Patient can resume or use /start.', flush=True)
                        with store.db:
                            store.db.execute("INSERT OR REPLACE INTO state VALUES('offset',?)", (update['update_id']+1,))
                    await bot.flush()
                except RuntimeError:
                    print('Temporary Telegram failure; reconnecting. No request details logged.', flush=True)
                    await asyncio.sleep(5)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as error:
        # Do not emit a traceback containing Telegram request tokens or response bodies.
        print('Bot stopped:', str(error) if isinstance(error, RuntimeError) else type(error).__name__)
        raise SystemExit(1)
