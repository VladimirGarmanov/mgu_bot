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
            await self.say(chat, 'Пока нет подключённых чатов клиники. Заявка не отправлена. Позвоните '+PHONE+' или повторите «Отправить заявку» позже.')
            return
        await self.say(chat, 'Получатели заявки (все подключённые чаты, где бот администратор):')
        # Keep every destination visible even if the registry exceeds Telegram's message limit.
        lines = [f'• {t["title"][:150]} · {"канал" if t["kind"] == "channel" else "группа"}' + (' · публичный @'+t['username'] if t['username'] else '') for t in targets]
        chunk = ''
        for line in lines:
            if len(chunk)+len(line)>3500:
                await self.say(chat, chunk); chunk = ''
            chunk += line+'\n'
        if chunk:
            await self.say(chat, chunk)
        await self.say(chat, 'Подтверждаете передачу имени, телефона и описания обращения всем перечисленным получателям? /cancel — отменить, /start — заполнить заново.',
                       {'keyboard': [[{'text': 'Отправить заявку'}]], 'resize_keyboard': True, 'one_time_keyboard': True})
    async def validate(self):
        await self.identity()
        if (await self.telegram('getWebhookInfo')).get('url'):
            raise RuntimeError('У бота настроен webhook. Сначала остановите прежний сервис; webhook автоматически не удаляется.')
        if self.settings.group:
            await self.discover(self.settings.group)
        print('Telegram verified. Admin chats are discovered automatically.', flush=True)
    async def ai_reply(self, concern):
        if not self.settings.key:
            return 'Спасибо, я сохраню описание для сотрудников клиники. Врач сможет обсудить медицинские вопросы на консультации.'
        # Separately collected name/phone/Telegram IDs are excluded. Redact contacts in free text too.
        redacted = re.sub(r'\+?\d[\d ()-]{6,}\d|[\w.+-]+@[\w.-]+|https?://\S+|@\w+', '[контакт скрыт]', concern)
        try:
            response = await self.client.post('https://api.openai.com/v1/responses', headers={'Authorization': 'Bearer '+self.settings.key}, json={
                'model': self.settings.model, 'instructions': self.settings.instructions,
                'input': [{'role': 'user', 'content': redacted}], 'store': False, 'max_output_tokens': 1200,
            })
            response.raise_for_status()
            body = response.json()
            if body.get('status') != 'completed':
                return 'Описание сохранено. Медицинские вопросы передадим сотрудникам клиники.'
            text = '\n'.join(part.get('text', '') for item in body.get('output', []) if item.get('type') == 'message' for part in item.get('content', []) if part.get('type') == 'output_text')
            return text[:1600] or 'Описание сохранено для сотрудников клиники.'
        except (httpx.HTTPError, ValueError, KeyError):
            return 'Описание сохранено. Продолжим оформление обращения для сотрудников клиники.'
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
            await self.say(chat_id, f'Я виртуальный помощник клиники. /start — начать; /cancel — отменить; /delete — удалить неотправленное; /operator — без OpenAI; /ask ваш вопрос — вопрос помощнику после согласия. Телефон клиники: {PHONE}. {EMERGENCY}')
            return
        if re.search(r'не могу дышать|теряю сознание|сильн\w* кровотеч|кровь не останавливается|сильн\w* боль в груди', text.lower()):
            await self.say(chat_id, EMERGENCY)
        state = self.store.get(chat_id)
        if text == '/operator':
            state = {'step': 'consent', 'ai': False}
            self.store.save(chat_id, state)
            text = ''
        if state['step'] == 'consent':
            if text != 'Согласен':
                await self.say(chat_id, 'Я виртуальный помощник, не врач. Соберу имя, причину обращения и контакт. Перед отправкой покажу заявку: она будет передана во все подключённые группы и каналы, где бот администратор. Перед подтверждением вы увидите список получателей, включая отметки публичных чатов. '+('Краткое описание может обрабатываться OpenAI; не пишите в нём имя, телефон и другие идентифицирующие сведения. Для обращения без OpenAI: /operator. ' if state.get('ai', True) else 'OpenAI для этого обращения отключён. ')+'Политика: https://uniclinic.pro/privacy. Подтверждаете обработку и передачу указанных данных для ответа клиники? /cancel — отказаться.', {'keyboard': [[{'text': 'Согласен'}]], 'resize_keyboard': True, 'one_time_keyboard': True})
                return
            state.update(step='name', consent=CONSENT, consent_at=time.time(), ai=state.get('ai', True))
            self.store.save(chat_id, state)
            await self.say(chat_id, 'Как к вам обращаться? Достаточно имени.')
            return
        if text.startswith('/ask '):
            question = text[5:].strip()
            if not 3 <= len(question) <= 1500:
                await self.say(chat_id, 'После /ask напишите вопрос длиной от 3 до 1500 символов.')
                return
            answer = await self.ai_reply(question) if state.get('ai') else 'OpenAI отключён. Передайте вопрос сотрудникам через описание обращения или позвоните в клинику.'
            await self.say(chat_id, answer + '\n\nМожно продолжить анкету с предыдущего вопроса или начать заново: /start.')
            return
        if not text and not message.get('contact'):
            await self.say(chat_id, 'Пожалуйста, ответьте текстом. Документы, фото и голосовые сообщения бот не обрабатывает.')
            return
        if state['step'] == 'name':
            if not 1 <= len(text) <= 80 or text.startswith('/'):
                await self.say(chat_id, 'Напишите имя, до 80 символов.'); return
            state.update(name=text, step='concern')
            self.store.save(chat_id, state)
            await self.say(chat_id, 'Что вас беспокоит или по какому вопросу хотите обратиться? Кратко опишите, без документов и личных данных.')
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
            await self.say(chat_id, 'Оставьте телефон для связи или отправьте свой контакт кнопкой.', {'keyboard': [[{'text': 'Отправить мой телефон', 'request_contact': True}]], 'resize_keyboard': True, 'one_time_keyboard': True})
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
            await self.say(chat_id, f'Заявка {code} сохранена и ожидает передачи. Я сообщу, когда она будет доставлена сотрудникам. Это ещё не подтверждение записи на приём.')
    @staticmethod
    def summary(state):
        return f'Имя: {state["name"]}\nТелефон: {state["phone"]}\nОбращение: {state["concern"]}\nКак давно: {state["duration"]}'
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
                    result = f'передана: {receipts["delivered"]} из {receipts["total"]} чатов'
                else:
                    result = 'не доставлена: у получателей сняты права или изменены условия доступа'
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
    lock = settings.database.with_suffix('.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    logging.getLogger('httpx').setLevel(logging.CRITICAL)
    logging.getLogger('httpcore').setLevel(logging.CRITICAL)
    async with httpx.AsyncClient(timeout=45) as client:
        bot = Bot(settings, client, store)
        await bot.validate()
        while True:
            try:
                store.cleanup(settings.retention)
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
