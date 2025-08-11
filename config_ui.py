import os
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from motor.motor_asyncio import AsyncIOMotorClient
from cryptography.fernet import Fernet

MONGO_URI = os.environ.get('MONGO_URI')
FERNET_KEY = os.environ.get('FERNET_KEY')
ADMIN_IDS = set(int(x) for x in os.environ.get('ADMIN_IDS','').split(',') if x.strip())
TG_API_ID = os.environ.get('TG_API_ID')
TG_API_HASH = os.environ.get('TG_API_HASH')

if not FERNET_KEY:
    raise RuntimeError('FERNET_KEY env var required in production')

fernet = Fernet(FERNET_KEY.encode())

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo.get_default_database()
configs = db['configs']
sessions_col = db['sessions']
tmp_states = db['tmp_states']

PAGE_SIZE = 6

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('➕ Add Source', callback_data='cfg:add_source')],
        [InlineKeyboardButton('🎯 Set Target', callback_data='cfg:set_target')],
        [InlineKeyboardButton('🔑 Sessions', callback_data='cfg:sessions')],
        [InlineKeyboardButton('📋 View Config', callback_data='cfg:list:0')],
    ])

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton('Cancel', callback_data='cfg:cancel')]])

def paginated_kb(items, prefix, page):
    kb = []
    start = page*PAGE_SIZE
    for i, item in enumerate(items[start:start+PAGE_SIZE], start=start):
        kb.append([InlineKeyboardButton(item['title'], callback_data=f'{prefix}:view:{i}')])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton('◀ Prev', callback_data=f'{prefix}:page:{page-1}'))
    if start+PAGE_SIZE < len(items):
        nav.append(InlineKeyboardButton('Next ▶', callback_data=f'{prefix}:page:{page+1}'))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton('Back', callback_data='cfg:back')])
    return InlineKeyboardMarkup(kb)

def register_handlers(app: Client):

    @app.on_message(filters.command('config') & filters.user(list(ADMIN_IDS)))
    async def cmd_config(_, msg: Message):
        await msg.reply_text('Bot Config Panel — choose action:', reply_markup=main_kb(), quote=True)

    @app.on_callback_query(filters.regex(r'^cfg:'))
    async def cfg_callbacks(_, cq: CallbackQuery):
        parts = cq.data.split(':')
        action = parts[1]
        user_id = cq.from_user.id
        if user_id not in ADMIN_IDS:
            await cq.answer('Only admins allowed.', show_alert=True)
            return

        if action == 'add_source':
            await cq.message.edit_text('Add source — forward a message from the channel OR send @username/id.',
                                       reply_markup=InlineKeyboardMarkup([
                                           [InlineKeyboardButton('Forward msg', callback_data='flow:source:forward')],
                                           [InlineKeyboardButton('Type id/username', callback_data='flow:source:type')],
                                           [InlineKeyboardButton('Back', callback_data='cfg:back')]
                                       ]))
        elif action == 'set_target':
            await cq.message.edit_text('Set target — forward a message from the target OR send @username/id.',
                                       reply_markup=InlineKeyboardMarkup([
                                           [InlineKeyboardButton('Forward msg', callback_data='flow:target:forward')],
                                           [InlineKeyboardButton('Type id/username', callback_data='flow:target:type')],
                                           [InlineKeyboardButton('Back', callback_data='cfg:back')]
                                       ]))
        elif action == 'sessions':
            await cq.message.edit_text('Sessions panel', reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('➕ Add Session', callback_data='flow:session:add')],
                [InlineKeyboardButton('📋 List Sessions', callback_data='flow:session:list:0')],
                [InlineKeyboardButton('Back', callback_data='cfg:back')]
            ]))
        elif action == 'list':
            page = int(parts[2]) if len(parts) > 2 else 0
            conf = await configs.find_one({'_id': 'global'}) or {}
            sources = conf.get('sources', [])
            await cq.message.edit_text('Sources list:', reply_markup=paginated_kb(sources, 'src', page))
        elif action == 'back':
            await cq.message.edit_text('Bot Config Panel — choose action:', reply_markup=main_kb())
        elif action == 'cancel':
            await cq.message.edit_text('Cancelled.', reply_markup=main_kb())
        else:
            await cq.answer()

    @app.on_callback_query(filters.regex(r'^flow:'))
    async def flow_start(_, cq: CallbackQuery):
        _, kind, method = cq.data.split(':')
        await cq.answer()
        if method == 'forward':
            await cq.message.edit_text('Now forward a message from the channel (one message).', reply_markup=cancel_kb())
            await tmp_states.update_one({'user_id': cq.from_user.id}, {'$set': {'mode': f'{kind}_await_forward', 'started_at': datetime.utcnow()}}, upsert=True)
        elif method == 'type':
            await cq.message.edit_text('Send the channel username (e.g. @channel) or numeric id now.', reply_markup=cancel_kb())
            await tmp_states.update_one({'user_id': cq.from_user.id}, {'$set': {'mode': f'{kind}_await_type', 'started_at': datetime.utcnow()}}, upsert=True)
        elif kind == 'session' and method == 'add':
            await cq.message.edit_text('Send: `bot <BOT_TOKEN>` OR `user <SESSION_STRING>`', reply_markup=cancel_kb())
            await tmp_states.update_one({'user_id': cq.from_user.id}, {'$set': {'mode': 'session_await_value', 'started_at': datetime.utcnow()}}, upsert=True)
        elif kind == 'session' and method == 'list':
            page = int(method := cq.data.split(':')[-1]) if cq.data.count(':')>=3 else 0
            docs = await sessions_col.find().to_list(length=200)
            if not docs:
                await cq.message.edit_text('No sessions stored.', reply_markup=main_kb())
                return
            start = page*PAGE_SIZE
            kb = []
            for i, d in enumerate(docs[start:start+PAGE_SIZE], start=start):
                title = d.get('name') or f"session-{i}"
                kb.append([InlineKeyboardButton(f"{title} ({d.get('type')})", callback_data=f'sess:view:{i}')])
            nav = []
            if page>0:
                nav.append(InlineKeyboardButton('◀ Prev', callback_data=f'sess:page:{page-1}'))
            if start+PAGE_SIZE < len(docs):
                nav.append(InlineKeyboardButton('Next ▶', callback_data=f'sess:page:{page+1}'))
            if nav: kb.append(nav)
            kb.append([InlineKeyboardButton('Back', callback_data='cfg:back')])
            await cq.message.edit_text('Sessions:', reply_markup=InlineKeyboardMarkup(kb))
        else:
            await cq.answer()

    @app.on_callback_query(filters.regex(r'^(src|sess):'))
    async def list_actions(_, cq: CallbackQuery):
        parts = cq.data.split(':')
        prefix = parts[0]
        act = parts[1]
        user_id = cq.from_user.id
        if user_id not in ADMIN_IDS:
            await cq.answer('Admins only', show_alert=True)
            return
        if prefix == 'src':
            if act == 'page':
                page = int(parts[2])
                conf = await configs.find_one({'_id': 'global'}) or {}
                sources = conf.get('sources', [])
                await cq.message.edit_text('Sources list:', reply_markup=paginated_kb(sources, 'src', page))
                return
            if act == 'view':
                index = int(parts[2])
                conf = await configs.find_one({'_id': 'global'}) or {}
                sources = conf.get('sources', [])
                if index <0 or index >= len(sources):
                    await cq.answer('Invalid index', show_alert=True)
                    return
                s = sources[index]
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Remove', callback_data=f'src:remove:{index}')],
                    [InlineKeyboardButton('Back', callback_data='cfg:back')]
                ])
                await cq.message.edit_text(f"Source:\n• {s.get('title')} — `{s.get('channel_id')}`", reply_markup=kb)
                return
            if act == 'remove':
                index = int(parts[2])
                conf = await configs.find_one({'_id':'global'}) or {}
                sources = conf.get('sources', [])
                if index<0 or index>=len(sources):
                    await cq.answer('Invalid index', show_alert=True)
                    return
                removed = sources.pop(index)
                await configs.update_one({'_id':'global'},{'$set':{'sources':sources}},upsert=True)
                await cq.message.edit_text(f"Removed source {removed.get('title')} ({removed.get('channel_id')})", reply_markup=main_kb())
                return
        elif prefix == 'sess':
            if act == 'page':
                page = int(parts[2])
                docs = await sessions_col.find().to_list(length=500)
                start = page*PAGE_SIZE
                kb = []
                for i,d in enumerate(docs[start:start+PAGE_SIZE], start=start):
                    kb.append([InlineKeyboardButton(d.get('name') or f'session-{i}', callback_data=f'sess:view:{i}')])
                nav = []
                if page>0: nav.append(InlineKeyboardButton('◀ Prev', callback_data=f'sess:page:{page-1}'))
                if start+PAGE_SIZE < len(docs): nav.append(InlineKeyboardButton('Next ▶', callback_data=f'sess:page:{page+1}'))
                if nav: kb.append(nav)
                kb.append([InlineKeyboardButton('Back', callback_data='cfg:back')])
                await cq.message.edit_text('Sessions:', reply_markup=InlineKeyboardMarkup(kb))
                return
            if act == 'view':
                idx = int(parts[2])
                docs = await sessions_col.find().to_list(length=500)
                if idx<0 or idx>=len(docs):
                    await cq.answer('Invalid', show_alert=True); return
                d = docs[idx]
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Remove', callback_data=f'sess:remove:{idx}')],
                    [InlineKeyboardButton('Back', callback_data='cfg:back')]
                ])
                await cq.message.edit_text(f"Session:\n• {d.get('name')} — {d.get('type')}", reply_markup=kb)
                return
            if act == 'remove':
                idx = int(parts[2])
                docs = await sessions_col.find().to_list(length=500)
                if idx<0 or idx>=len(docs):
                    await cq.answer('Invalid', show_alert=True); return
                doc = docs[idx]
                await sessions_col.delete_one({'_id': doc['_id']})
                await cq.message.edit_text('Session removed.', reply_markup=main_kb())
                return

    @app.on_message(filters.private & filters.user(list(ADMIN_IDS)))
    async def admin_response(_, msg: Message):
        state = await tmp_states.find_one({'user_id': msg.from_user.id})
        if not state: return
        mode = state.get('mode')

        if mode == 'source_await_forward' and msg.forward_from_chat:
            ch = msg.forward_from_chat
            channel_id = ch.id
            title = getattr(ch, 'title', getattr(ch, 'username', str(channel_id)))
            await configs.update_one({'_id':'global'},{'$push':{'sources':{'channel_id':channel_id,'title':title,'added_by':msg.from_user.id,'added_at':datetime.utcnow()}}},upsert=True)
            await msg.reply_text(f'Added source `{channel_id}` — {title}', quote=True)
            await tmp_states.delete_one({'user_id':msg.from_user.id})
            return

        if mode == 'target_await_forward' and msg.forward_from_chat:
            ch = msg.forward_from_chat
            channel_id = ch.id
            title = getattr(ch, 'title', getattr(ch, 'username', str(channel_id)))
            await configs.update_one({'_id':'global'},{'$set':{'target':{'channel_id':channel_id,'title':title,'set_by':msg.from_user.id,'set_at':datetime.utcnow()}}},upsert=True)
            await msg.reply_text(f'Target set to `{channel_id}` — {title}', quote=True)
            await tmp_states.delete_one({'user_id':msg.from_user.id})
            return

        if mode == 'source_await_type' and msg.text:
            txt = msg.text.strip()
            try:
                ch = await app.get_chat(txt)
                title = ch.title or ch.username or str(txt)
                real_id = ch.id
            except Exception:
                title = txt
                real_id = int(txt) if txt.lstrip('-').isdigit() else txt
            await configs.update_one({'_id':'global'},{'$push':{'sources':{'channel_id':real_id,'title':title,'added_by':msg.from_user.id,'added_at':datetime.utcnow()}}},upsert=True)
            await msg.reply_text(f'Added source `{real_id}` — {title}', quote=True)
            await tmp_states.delete_one({'user_id':msg.from_user.id})
            return

        if mode == 'target_await_type' and msg.text:
            txt = msg.text.strip()
            try:
                ch = await app.get_chat(txt)
                title = ch.title or ch.username or str(txt)
                real_id = ch.id
            except Exception:
                title = txt
                real_id = int(txt) if txt.lstrip('-').isdigit() else txt
            await configs.update_one({'_id':'global'},{'$set':{'target':{'channel_id':real_id,'title':title,'set_by':msg.from_user.id,'set_at':datetime.utcnow()}}},upsert=True)
            await msg.reply_text(f'Target set `{real_id}` — {title}', quote=True)
            await tmp_states.delete_one({'user_id':msg.from_user.id})
            return

        if mode == 'session_await_value' and msg.text:
            parts = msg.text.strip().split(None,1)
            if len(parts)<2:
                await msg.reply_text('Invalid format. Use `bot <TOKEN>` or `user <SESSION_STRING>`', quote=True); return
            stype,value = parts[0].lower(), parts[1].strip()
            if stype not in ('bot','user'):
                await msg.reply_text("Type must be 'bot' or 'user'", quote=True); return
            await msg.reply_text('Validating session...', quote=True)
            ok=False
            info=None
            temp=None
            try:
                if stype=='bot':
                    temp = Client('tmp-bot', bot_token=value)
                else:
                    if not TG_API_ID or not TG_API_HASH:
                        await msg.reply_text('Server missing TG_API_ID/TG_API_HASH', quote=True)
                        await tmp_states.delete_one({'user_id':msg.from_user.id}); return
                    temp = Client('tmp-user', api_id=int(TG_API_ID), api_hash=TG_API_HASH, session_string=value)
                await temp.__aenter__()
                who = await temp.get_me()
                info = who
                ok=True
            except Exception as e:
                await msg.reply_text(f'Validation failed: {e}', quote=True)
                ok=False
            finally:
                if temp:
                    try: await temp.__aexit__(None,None,None)
                    except: pass
            if not ok:
                await tmp_states.delete_one({'user_id':msg.from_user.id}); return
            enc = fernet.encrypt(value.encode()).decode()
            doc = {'name':getattr(info,'username',getattr(info,'first_name','unknown')),'type':'bot' if stype=='bot' else 'user','identifier':getattr(info,'id',None) or getattr(info,'username',''),'encrypted_value':enc,'added_by':msg.from_user.id,'added_at':datetime.utcnow()}
            await sessions_col.insert_one(doc)
            await msg.reply_text(f"Session stored for `{doc['name']}` ({doc['type']}).", quote=True)
            await tmp_states.delete_one({'user_id':msg.from_user.id})
            return

        if msg.text and msg.text.strip().lower()=='cancel':
            await msg.reply_text('Cancelled.', quote=True)
            await tmp_states.delete_one({'user_id':msg.from_user.id}); return

        return
