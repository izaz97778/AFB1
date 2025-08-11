import os
import asyncio
import traceback
from datetime import datetime, timedelta
from pyrogram import Client, filters, errors
from motor.motor_asyncio import AsyncIOMotorClient
from cryptography.fernet import Fernet

MONGO_URI = os.environ.get('MONGO_URI')
mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo.get_default_database()
configs = db['configs']
sessions_col = db['sessions']
forwarded = db['forwarded_messages']
session_logs = db['session_logs']

FERNET_KEY = os.environ.get('FERNET_KEY')
fernet = Fernet(FERNET_KEY.encode())

MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0

class ForwardWorker:
    def __init__(self, controller_app: Client):
        self.controller_app = controller_app
        self.running_clients = {}
        self.client_tasks = {}
        self._stop = False
        self.queue = asyncio.Queue()
        self._queue_task = None

    async def start(self):
        self._queue_task = asyncio.create_task(self._process_queue())
        asyncio.create_task(self._refresh_loop())

    async def stop(self):
        self._stop = True
        if self._queue_task:
            self._queue_task.cancel()
        for sid, client in list(self.running_clients.items()):
            try:
                await client.stop()
            except Exception:
                pass

    async def _refresh_loop(self):
        while not self._stop:
            try:
                await self._sync_sessions()
            except Exception as e:
                print('Error syncing sessions:', e)
                traceback.print_exc()
            await asyncio.sleep(20)

    async def _sync_sessions(self):
        docs = await sessions_col.find().to_list(length=500)
        desired = {str(d['_id']): d for d in docs}
        for sid, doc in desired.items():
            if sid not in self.running_clients:
                await self._start_session_client(sid, doc)
        for sid in list(self.running_clients.keys()):
            if sid not in desired:
                client = self.running_clients.pop(sid)
                try:
                    await client.stop()
                except Exception:
                    pass
                if sid in self.client_tasks:
                    task = self.client_tasks.pop(sid)
                    task.cancel()

    async def _start_session_client(self, sid, doc):
        enc = doc['encrypted_value']
        val = fernet.decrypt(enc.encode()).decode()
        stype = doc['type']
        name = f'sess-{sid[:8]}'
        API_ID = int(os.environ.get('TG_API_ID')) if os.environ.get('TG_API_ID') else None
        API_HASH = os.environ.get('TG_API_HASH')
        if stype == 'bot':
            client = Client(name, bot_token=val)
        else:
            client = Client(name, api_id=API_ID, api_hash=API_HASH, session_string=val)

        async def on_message(c, m):
            try:
                conf = await configs.find_one({'_id':'global'}) or {}
                sources = [s['channel_id'] for s in conf.get('sources', [])]
                target = conf.get('target')
                if not target:
                    return
                if m.chat.id not in sources:
                    return
                key = f'{m.chat.id}:{m.message_id}'
                existed = await forwarded.find_one({'_id': key})
                if existed:
                    return
                await self._attempt_forward(c, m, target['channel_id'], key)
            except Exception as e:
                print('on_message handler error', e)
                traceback.print_exc()

        client.add_handler(client.create_handler(on_message))

        await client.start()
        self.running_clients[sid] = client
        print('Started session client', sid)
        await session_logs.update_one({'_id': sid}, {'$set': {'started_at': datetime.utcnow(), 'last_seen': datetime.utcnow(), 'errors': 0, 'success': 0}}, upsert=True)

    async def _attempt_forward(self, client, message, target_chat_id, key):
        attempt = 0
        backoff = INITIAL_BACKOFF
        while attempt < MAX_RETRIES:
            try:
                await client.copy_message(chat_id=target_chat_id, from_chat_id=message.chat.id, message_id=message.message_id)
                await forwarded.insert_one({'_id': key, 'source_chat': message.chat.id, 'source_msg': message.message_id, 'forwarded_at': datetime.utcnow()})
                await session_logs.update_one({'_id': str(client.session_name)}, {'$inc': {'success': 1}, '$set': {'last_forwarded': datetime.utcnow()}}, upsert=True)
                return
            except errors.RPCError as e:
                code_name = e.__class__.__name__
                attempt += 1
                await session_logs.update_one({'_id': str(client.session_name)}, {'$inc': {'errors': 1}, '$set': {'last_error': f"{code_name}: {str(e)}", 'last_error_at': datetime.utcnow()}}, upsert=True)
                if isinstance(e, errors.FloodWait):
                    wait = getattr(e, 'value', None) or 30
                    print(f'FloodWait for {wait}s — scheduling retry')
                    await asyncio.sleep(wait)
                    continue
                if isinstance(e, (errors.RetryAfter, errors.MessageTooLong)):
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                print('Non-fatal RPCError, enqueueing for later:', e)
                await self.queue.put({'client_name': client.session_name, 'message': {'chat_id': message.chat.id, 'message_id': message.message_id}, 'target': target_chat_id, 'key': key, 'attempts': attempt})
                return
            except Exception as e:
                attempt += 1
                await session_logs.update_one({'_id': str(client.session_name)}, {'$inc': {'errors': 1}, '$set': {'last_error': str(e), 'last_error_at': datetime.utcnow()}}, upsert=True)
                print('Forward attempt failed:', e)
                await asyncio.sleep(backoff)
                backoff *= 2
        print('Max retries reached, enqueueing for background retry')
        await self.queue.put({'client_name': client.session_name, 'message': {'chat_id': message.chat.id, 'message_id': message.message_id}, 'target': target_chat_id, 'key': key, 'attempts': attempt})

    async def _process_queue(self):
        while True:
            try:
                job = await self.queue.get()
                attempts = job.get('attempts', 0)
                if attempts >= MAX_RETRIES:
                    print('Dropping job after many attempts', job)
                    continue
                client_name = job['client_name']
                client = None
                for c in self.running_clients.values():
                    if getattr(c, 'session_name', '') == client_name:
                        client = c
                        break
                if not client:
                    await asyncio.sleep(5)
                    await self.queue.put(job)
                    continue
                try:
                    await client.copy_message(chat_id=job['target'], from_chat_id=job['message']['chat_id'], message_id=job['message']['message_id'])
                    await forwarded.insert_one({'_id': job['key'], 'source_chat': job['message']['chat_id'], 'source_msg': job['message']['message_id'], 'forwarded_at': datetime.utcnow()})
                    await session_logs.update_one({'_id': client.session_name}, {'$inc': {'success': 1}, '$set': {'last_forwarded': datetime.utcnow()}}, upsert=True)
                except Exception as e:
                    job['attempts'] = attempts + 1
                    print('Queue job failed, requeueing', e)
                    await session_logs.update_one({'_id': client.session_name}, {'$inc': {'errors': 1}, '$set': {'last_error': str(e), 'last_error_at': datetime.utcnow()}}, upsert=True)
                    await asyncio.sleep(2 ** attempts)
                    await self.queue.put(job)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print('Queue processor error', e)
                traceback.print_exc()
                await asyncio.sleep(2)
