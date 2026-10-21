import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from bot import Bot, Settings, Store, main

class BotTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = Settings('1:synthetic', -100123, None, '', 'gpt-5-mini', Path(self.directory.name)/'test.sqlite', 'Collect requests, never diagnose.')
        self.store = Store(self.settings.database)
        self.client = httpx.AsyncClient()
        self.bot = Bot(self.settings, self.client, self.store)
        self.chats = {-100123: {'id': -100123, 'type': 'supergroup', 'title': 'Clinic A'}}
        self.members = {-100123: {'status': 'administrator'}}
        self.failed_chats = set()
        async def telegram(method, **args):
            if method == 'getMe': return {'id': 1}
            if method == 'getChat': return self.chats[args['chat_id']]
            if method == 'getChatMember': return self.members.get(args['chat_id'], {'status': 'left'})
            if method == 'sendMessage' and args['chat_id'] in self.failed_chats: raise RuntimeError('offline')
            if method == 'getWebhookInfo': return {}
            return {'message_id': 55}
        self.telegram_stub = telegram
        self.bot.telegram = AsyncMock(side_effect=telegram)
        await self.bot.discover(-100123)
        self.bot.telegram.reset_mock()
        self.index = 0
    async def asyncTearDown(self):
        self.store.db.close()
        await self.client.aclose()
        self.directory.cleanup()
    async def message(self, text='', contact=None):
        self.index += 1
        message = {'chat': {'id': 15, 'type': 'private'}, 'from': {'id': 15}, 'text': text}
        if contact:
            message['contact'] = contact
        await self.bot.process({'update_id': self.index, 'message': message})
    async def fill(self):
        for text in ['/start', 'Согласен', 'Записаться', 'Тест', 'Хочу консультацию', '+79990001234']:
            await self.message(text)
    async def test_consent_preview_and_exact_destination(self):
        await self.message('Несогласованный медицинский текст')
        self.assertEqual(self.store.get(15), {'step': 'consent'})
        await self.fill()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM delivery').fetchone()[0], 0)
        await self.message('Отправить заявку')
        await self.bot.flush()
        calls = [call.kwargs for call in self.bot.telegram.await_args_list if call.args[0] == 'sendMessage' and call.kwargs.get('chat_id') == -100123]
        self.assertEqual(len(calls), 1)
        self.assertIn('+79990001234', calls[0]['text'])
        row = self.store.db.execute('SELECT * FROM delivery').fetchone()
        self.assertEqual(row['payload'], '{}')
        self.assertEqual(row['notified'], 1)
        await self.bot.flush()
        self.assertEqual(len([c for c in self.bot.telegram.await_args_list if c.args[0] == 'sendMessage' and c.kwargs.get('chat_id') == -100123]), 1)
    async def test_failed_staff_delivery_retries_not_false_success(self):
        await self.fill(); await self.message('Отправить заявку')
        self.bot.telegram.side_effect = RuntimeError('offline')
        await self.bot.flush()
        row = self.store.db.execute('SELECT * FROM delivery').fetchone()
        self.assertEqual(row['sent'], 0)
        self.assertIn('Хочу консультацию', row['payload'])
        self.bot.telegram.side_effect = self.telegram_stub
        with self.store.db:
            self.store.db.execute('UPDATE delivery SET next_attempt=0')
        await self.bot.flush()
        self.assertEqual(self.store.db.execute('SELECT notified FROM delivery').fetchone()[0], 1)
    async def test_staff_messages_ignored_and_delete_cancels(self):
        await self.bot.process({'message': {'chat': {'id': -100123, 'type': 'supergroup'}, 'text': 'Секрет'}})
        self.bot.telegram.assert_not_awaited()
        await self.fill(); await self.message('Отправить заявку'); await self.message('/delete')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM delivery').fetchone()[0], 0)
    async def test_contact_must_belong_to_sender(self):
        for text in ['Согласен', 'Записаться', 'Тест', 'Вопрос']:
            await self.message(text)
        await self.message(contact={'user_id': 999, 'phone_number': '+79990001234'})
        self.assertEqual(self.store.get(15)['step'], 'phone')
    async def test_openai_payload_does_not_include_collected_contacts(self):
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Передадим вопрос сотрудникам.'}]}]})
        self.settings.key = 'synthetic-key'
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self.bot.client = client
            answer = await self.bot.ai_reply('Вопрос. Телефон +7 999 000 12 34; test@example.com')
        self.assertIn('Передадим', answer)
        self.assertFalse(requests[0]['store'])
        self.assertNotIn('test@example.com', json.dumps(requests))
        self.assertNotIn('999 000', json.dumps(requests))
        self.assertNotIn('tools', requests[0])
    async def test_operator_disables_ai(self):
        await self.message('/operator'); await self.message('Согласен'); await self.message('Записаться'); await self.message('Тест')
        self.bot.ai_reply = AsyncMock()
        await self.message('Нужна консультация')
        self.bot.ai_reply.assert_not_awaited()

    async def test_conversation_then_callback_without_medical_question(self):
        await self.message('Согласен')
        self.bot.ai_reply = AsyncMock(return_value='Первичный приём — 2 500 ₽.')
        await self.message('Сколько стоит консультация?')
        self.assertEqual(self.store.get(15)['step'], 'chat')
        await self.message('Перезвоните мне')
        await self.message('Тест')
        self.assertEqual(self.store.get(15)['step'], 'phone')
        await self.message('+79990001234')
        await self.message('Отправить заявку')
        await self.bot.flush()
        self.assertEqual(self.store.db.execute('SELECT sent FROM delivery').fetchone()[0], 1)
        self.assertEqual(self.store.get(15)['step'], 'chat')

    async def test_question_during_intake_does_not_become_phone(self):
        for text in ['Согласен', 'Перезвоните мне', 'Тест']:
            await self.message(text)
        self.bot.ai_reply = AsyncMock(return_value='Москва, Ломоносовский проспект, 27, корпус 10.')
        await self.message('Где находится клиника?')
        self.assertEqual(self.store.get(15)['step'], 'phone')
        self.assertNotIn('phone', self.store.get(15))

    async def test_all_admin_chats_and_independent_retries(self):
        self.chats[-100222] = {'id': -100222, 'type': 'channel', 'title': 'Clinic B', 'username': 'clinic_public'}
        self.members[-100222] = {'status': 'administrator', 'can_post_messages': True}
        await self.bot.process({'my_chat_member': {'chat': self.chats[-100222], 'new_chat_member': self.members[-100222]}})
        await self.fill()
        self.assertEqual(len(self.store.get(15)['destinations']), 2)
        self.assertTrue(any('публичный @clinic_public' in c.kwargs.get('text','') for c in self.bot.telegram.await_args_list))
        await self.message('Отправить заявку')
        self.failed_chats.add(-100222)
        await self.bot.flush()
        self.assertEqual(self.store.db.execute('SELECT sent FROM recipients WHERE chat=-100123').fetchone()[0], 55)
        self.assertEqual(self.store.db.execute('SELECT notified FROM delivery').fetchone()[0], 0)
        self.failed_chats.clear()
        with self.store.db: self.store.db.execute('UPDATE delivery SET next_attempt=0')
        await self.bot.flush()
        group_calls = [c for c in self.bot.telegram.await_args_list if c.args[0]=='sendMessage' and c.kwargs.get('chat_id')==-100123]
        self.assertEqual(len(group_calls), 1)
        self.assertEqual(self.store.db.execute('SELECT notified FROM delivery').fetchone()[0], 1)
    async def test_revoked_admin_is_not_sent_patient_data(self):
        await self.fill(); await self.message('Отправить заявку')
        self.members[-100123] = {'status': 'member'}
        await self.bot.process({'my_chat_member': {'chat': self.chats[-100123], 'new_chat_member': self.members[-100123]}})
        await self.bot.flush()
        calls = [c for c in self.bot.telegram.await_args_list if c.args[0]=='sendMessage' and c.kwargs.get('chat_id')==-100123]
        self.assertEqual(calls, [])
        self.assertTrue(any('не доставлена' in c.kwargs.get('text','') for c in self.bot.telegram.await_args_list))
    async def test_later_chat_does_not_receive_old_application(self):
        await self.fill(); await self.message('Отправить заявку')
        self.chats[-100333] = {'id': -100333, 'type': 'supergroup', 'title': 'Later'}
        self.members[-100333] = {'status': 'administrator'}
        await self.bot.discover(-100333)
        await self.bot.flush()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM recipients').fetchone()[0], 1)
    async def test_channel_without_post_permission_not_registered(self):
        self.chats[-100444] = {'id': -100444, 'type': 'channel', 'title': 'No posts'}
        self.members[-100444] = {'status': 'administrator', 'can_post_messages': False}
        self.assertIsNone(await self.bot.discover(-100444))
    async def test_no_groups_no_false_delivery(self):
        with self.store.db: self.store.db.execute('DELETE FROM destinations')
        await self.fill(); await self.message('Отправить заявку')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM delivery').fetchone()[0], 0)
    async def test_new_chat_discovery_from_group_message(self):
        self.chats[-100555] = {'id': -100555, 'type': 'supergroup', 'title': 'Discovered'}
        self.members[-100555] = {'status': 'administrator'}
        await self.bot.process({'message': {'chat': self.chats[-100555], 'text': '/register'}})
        self.assertEqual(self.store.db.execute('SELECT active FROM destinations WHERE chat=-100555').fetchone()[0], 1)
    async def test_registry_survives_restart(self):
        other = Store(self.settings.database)
        try: self.assertEqual(other.db.execute('SELECT active FROM destinations WHERE chat=-100123').fetchone()[0], 1)
        finally: other.db.close()

    async def run_main_until_next_poll(self, updates):
        batches = iter(updates)
        async def telegram(method, **args):
            if method == 'getUpdates':
                try:
                    return next(batches)
                except StopIteration:
                    raise asyncio.CancelledError
            return await self.telegram_stub(method, **args)
        self.bot.telegram.side_effect = telegram
        with patch('bot.Settings.load', return_value=self.settings), patch('bot.Store', return_value=self.store), patch('bot.Bot', return_value=self.bot):
            with self.assertRaises(asyncio.CancelledError):
                await main()

    async def test_main_delivers_existing_queue_without_new_messages(self):
        await self.fill()
        await self.message('Отправить заявку')
        await self.run_main_until_next_poll([])
        row = self.store.db.execute('SELECT sent,notified FROM delivery').fetchone()
        self.assertEqual(tuple(row), (1, 1))

    async def test_main_delivers_new_confirmation_and_does_not_duplicate(self):
        await self.fill()
        update = {'update_id': 100, 'message': {'chat': {'id': 15, 'type': 'private'}, 'from': {'id': 15}, 'text': 'Отправить заявку'}}
        await self.run_main_until_next_poll([[update], []])
        row = self.store.db.execute('SELECT sent,notified FROM delivery').fetchone()
        self.assertEqual(tuple(row), (1, 1))
        deliveries = [call for call in self.bot.telegram.await_args_list if call.args[0] == 'sendMessage' and call.kwargs.get('chat_id') == -100123]
        self.assertEqual(len(deliveries), 1)

if __name__ == '__main__':
    unittest.main()
