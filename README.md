# Telegram Message Forwarder Bot

A simple Pyrogram-based userbot that forwards messages from multiple source channels to a target channel, logs them to MongoDB, and runs with Docker.

## Features

- ✅ Multiple source channels
- ✅ Forwards all messages (text/media)
- ✅ MongoDB logging
- ✅ Docker/Koyeb/Heroku ready

## Setup

1. Clone the repo
2. Copy `.env.example` to `.env` and fill your credentials
3. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4. Run:
    ```bash
    python bot.py
    ```

## Docker Deployment

```bash
docker build -t forwarder-bot .
docker run --env-file .env forwarder-bot
