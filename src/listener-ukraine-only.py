"""
Ukraine-only Telegram listener.
Routes through dedicated IP/VPN for Ukraine account.
"""

import sqlite3
import asyncio
from functools import partial
from telethon import TelegramClient, events
from telethon.tl.types import InputChannel, MessageMediaWebPage
from telethon.errors import FloodWaitError, ChannelPrivateError
from dotenv import load_dotenv
import os
import deepl
import deepl.exceptions
import logging
import yaml
import html
import re
from datetime import datetime

# Load environment variables
load_dotenv()

DEEPL_AUTH_KEY = os.getenv("DEEPL_AUTH_KEY")
translator = deepl.Translator(DEEPL_AUTH_KEY)

# Logging setup
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s', level=logging.INFO)
logging.getLogger('telethon').setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Load config
with open('config-dual.yml', 'rb') as f:
    config = yaml.safe_load(f)
with open('channels.yml', 'rb') as f:
    channels = yaml.safe_load(f)

# Create Ukraine client only
client = TelegramClient(
    config["ukraine_session_name"],
    config["ukraine_api_id"],
    config["ukraine_api_hash"]
)
client.start()
logger.info('[UKRAINE CLIENT] Connected')

# Define channel entities
ukraine_channels_entities = []
for d in client.iter_dialogs():
    if d.entity.id in channels["ukraine_channel_ids"]:
        ukraine_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))

# Output channels
ukraine_news_channel = channels['output_channel_ids'][0]
ukr_photos_channel = channels['output_channel_ids'][2]
ukr_videos_channel = channels['output_channel_ids'][4]

# Database and helper functions (same as dual-session)
def get_db_connection():
    conn = sqlite3.connect('src/messages.db', timeout=10.0)
    return conn

def init_database():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            date TIMESTAMP NOT NULL,
            content TEXT,
            link TEXT,
            UNIQUE(channel_id, message_id)
        )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON messages(date DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel ON messages(channel_id)')
        conn.commit()
    finally:
        conn.close()

def is_message_seen(channel_id, message_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM messages WHERE channel_id = ? AND message_id = ? LIMIT 1", (channel_id, message_id))
        return cursor.fetchone() is not None
    finally:
        conn.close()

def store_message(channel_id, message_id, content, link, date):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO messages (channel_id, message_id, content, link, date) VALUES (?, ?, ?, ?, ?)",
                      (channel_id, message_id, content, link, date))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to store message: {e}")
    finally:
        conn.close()

init_database()

async def translate_async(text, target_lang="EN-US"):
    if not text:
        return ""
    loop = asyncio.get_event_loop()
    try:
        translation = await loop.run_in_executor(None, partial(translator.translate_text, text, target_lang=target_lang))
        return translation.text
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return "[Translation failed]"

async def send_with_retry(channel_id, message, file=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            await client.send_message(channel_id, message, parse_mode='html', file=file, link_preview=False)
            return True
        except FloodWaitError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = min(e.seconds, 60)
            logger.warning(f"Rate limited, waiting {wait_time}s")
            await asyncio.sleep(wait_time)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)

def create_message(chat_name, untranslated_msg, translation, link):
    border = '<br>'
    if translation:
        message = f'<p><p>{border}\n<b>{html.escape(chat_name)}</b>\n{border}\n\n</p><p>[TRANSLATED MESSAGE]\n{html.escape(translation)}\n\n</p><p>{border}\n{html.escape(link)} ↩</p></p>'
    else:
        message = f'<p>{border}\n<b>{html.escape(chat_name)}</b>\n{border}\n\n{html.escape(link)} ↩</p>'
    if len(message) >= 3980:
        translation = f'{translation[:3700]}...'
        message = f'<p><p>{border}\n<b>{html.escape(chat_name)}</b>\n{border}\n\n</p><p>[TRANSLATED MESSAGE]\n{html.escape(translation)}\n\n</p><p>{border}\n{html.escape(link)} ↩</p></p>'
    return message

async def handle_message(event, news_channel, photos_channel, videos_channel):
    try:
        chat = await event.get_chat()
        chat_name = chat.title or chat.username
        date = event.date
        message_id = event.id
        link = f't.me/{chat.username or f"c/{chat.id}"}/{message_id}'

        logger.info(f"Received Ukraine message: Channel {chat.id}, Message ID {message_id}")

        if is_message_seen(chat.id, message_id):
            logger.debug(f"Skipping duplicate: {chat.id}/{message_id}")
            return

        untranslated_msg = event.message.message or ""

        if event.message.media:
            if isinstance(event.message.media, MessageMediaWebPage):
                logger.warning(f"Unsupported media: {chat.id}/{message_id}")
                return

            content = await translate_async(untranslated_msg) if untranslated_msg else ""
            message = create_message(chat_name, untranslated_msg, content, link)

            if event.message.photo:
                await send_with_retry(news_channel, message, file=event.message.media)
                await send_with_retry(photos_channel, message, file=event.message.media)
            elif event.message.document:
                mime_type = event.message.media.document.mime_type
                if re.search('video', mime_type):
                    await send_with_retry(videos_channel, message, file=event.message.media)
                else:
                    await send_with_retry(news_channel, message, file=event.message.media)
        else:
            content = await translate_async(untranslated_msg) if untranslated_msg else ""
            message = create_message(chat_name, untranslated_msg, content, link)
            await send_with_retry(news_channel, message)

        store_message(chat.id, message_id, untranslated_msg, link, date)

    except Exception as e:
        logger.error(f"Failed to process Ukraine message: {e}", exc_info=True)

@client.on(events.NewMessage(chats=ukraine_channels_entities))
async def handle_ukraine_messages(event):
    await handle_message(event, ukraine_news_channel, ukr_photos_channel, ukr_videos_channel)

logger.info(f"Ukraine listener monitoring {len(ukraine_channels_entities)} channels")
client.run_until_disconnected()
