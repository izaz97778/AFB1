import uvloop
import asyncio
import logging
import re
from os import environ
from pyrogram import Client, filters
from motor.motor_asyncio import AsyncIOMotorClient

# Setup fast asyncio event loop
uvloop.install()

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# Regex for numeric Telegram IDs (with optional negative)
id_pattern = re.compile(r"^-?\d+$")

# Load env vars
SESSION = environ.get("SESSION", "")
API_ID = int(environ.get("API_ID", "0"))
API_HASH = environ.get("API_HASH", "")
TARGET_CHANNEL = int(environ.get("TARGET_CHANNEL", "0"))
SOURCE_CHANNELS = [
    int(ch) if id_pattern.match(ch) else ch
    for ch in environ.get("SOURCE_CHANNELS", "").split()
]
MONGO_URI = environ.get("MONGO_URI", "")

# MongoDB init
mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo.forwarderbot

# Create Pyrogram client
app = Client(name=SESSION, session_string=SESSION, api_id=API_ID, api_hash=API_HASH)

# Bot startup
async def start_bot():
    await app.start()
    user = await app.get_me()
    logging.info(f"Logged in as: {user.first_name} (@{user.username}) [ID: {user.id}]")
    logging.info(f"Listening to: {SOURCE_CHANNELS} → Forwarding to: {TARGET_CHANNEL}")
    await asyncio.Event().wait()

# Message forward handler
@app.on_message(filters.chat(SOURCE_CHANNELS))
async def forward_messages(client, message):
    try:
        sent = await message.copy(TARGET_CHANNEL)
        logging.info(f"✅ Forwarded [{message.chat.id}] {message.id} → {TARGET_CHANNEL}")

        await db.messages.insert_one({
            "chat_id": message.chat.id,
            "message_id": message.id,
            "forwarded_id": sent.id,
            "date": message.date.isoformat(),
            "text": message.text or message.caption,
            "media_type": message.media,
        })

    except Exception as e:
        logging.error(f"❌ Failed to forward message {message.id} from {message.chat.id}: {e}")

# Start the bot
app.run(start_bot())
