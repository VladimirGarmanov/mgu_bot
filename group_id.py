"""Print only group/topic IDs after /groupid; never expose message contents or tokens."""
import asyncio
import os
from pathlib import Path
import httpx
from dotenv import load_dotenv

async def main():
    load_dotenv(Path(__file__).with_name('.env'))
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    if not token:
        raise RuntimeError('Заполните TELEGRAM_BOT_TOKEN в .env')
    async with httpx.AsyncClient(timeout=40) as client:
        async def call(method, data):
            response = await client.post('https://api.telegram.org/bot'+token+'/'+method, json=data)
            payload = response.json()
            if not payload.get('ok'):
                raise RuntimeError('Telegram отклонил запрос. Проверьте токен и остановите другой polling-процесс.')
            return payload['result']
        if (await call('getWebhookInfo', {})).get('url'):
            raise RuntimeError('Webhook активен. Сначала остановите прежний сервис и отключите webhook.')
        print('Отправьте /groupid в приватную группу, в которой бот является администратором. Ctrl+C — выход.')
        offset = 0
        while True:
            for update in await call('getUpdates', {'offset': offset, 'timeout': 25, 'allowed_updates': ['message']}):
                # Do not acknowledge updates: the intake process must still see them.
                message = update.get('message', {})
                if message.get('chat', {}).get('type') in {'group', 'supergroup'} and (message.get('text') or '').split('@')[0] == '/groupid':
                    print('TELEGRAM_GROUP_ID='+str(message['chat']['id']))
                    print('TELEGRAM_TOPIC_ID='+str(message.get('message_thread_id', '')))
                    return
            await asyncio.sleep(2)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else 'Ошибка подключения: '+type(error).__name__)
        raise SystemExit(1)
