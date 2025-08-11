import os
import asyncio
from pyrogram import Client
from dotenv import load_dotenv
from config_ui import register_handlers
from forwarder import ForwardWorker

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_API_TOKEN")
API_ID = int(os.environ.get("TG_API_ID")) if os.environ.get("TG_API_ID") else None
API_HASH = os.environ.get("TG_API_HASH")

app = Client("cfg-bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)
register_handlers(app)

fw = ForwardWorker(app)

async def main():
    async with app:
        await fw.start()
        print("Bot and forward worker running — press Ctrl+C to stop.")
        await app.idle()

if __name__ == '__main__':
    asyncio.run(main())
