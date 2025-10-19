"""
Dual-session Telegram listener that uses separate accounts for Ukraine and Russia channels.

This allows you to:
- Use one Telegram account (with access to Ukraine channels) for Ukraine monitoring
- Use another Telegram account (with access to Russia channels) for Russia monitoring
- Split API quota across two accounts
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

# Debug loggers
seq_matcher_logger = logging.getLogger('seq_matcher')
seq_matcher_logger.setLevel(logging.DEBUG)
seq_matcher_logger.addHandler(logging.FileHandler('seq_matcher_logs.log'))

store_msg_logger = logging.getLogger('store_message')
store_msg_logger.setLevel(logging.DEBUG)
store_msg_logger.addHandler(logging.FileHandler('store_message_logs.log'))

# Load dual-session config
with open('config-dual.yml', 'rb') as f:
    config = yaml.safe_load(f)
with open('channels.yml', 'rb') as f:
    channels = yaml.safe_load(f)

# Create TWO Telegram clients - one for Ukraine, one for Russia
ukraine_client = TelegramClient(
    config["ukraine_session_name"],
    config["ukraine_api_id"],
    config["ukraine_api_hash"]
)
ukraine_client.start()
logger.info('[Ukraine Client] Connected')

russia_client = TelegramClient(
    config["russia_session_name"],
    config["russia_api_id"],
    config["russia_api_hash"]
)
russia_client.start()
logger.info('[Russia Client] Connected')

# Define channel entities for UKRAINE client
ukraine_channels_entities = []
output_channels_entities_ukraine = []

for d in ukraine_client.iter_dialogs():
    if d.entity.id in channels["ukraine_channel_ids"]:
        ukraine_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))
    if d.entity.id in channels["output_channel_ids"]:
        output_channels_entities_ukraine.append(InputChannel(d.entity.id, d.entity.access_hash))

# Define channel entities for RUSSIA client
russia_channels_entities = []
output_channels_entities_russia = []

for d in russia_client.iter_dialogs():
    if d.entity.id in channels["russian_channel_ids"]:
        russia_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))
    if d.entity.id in channels["output_channel_ids"]:
        output_channels_entities_russia.append(InputChannel(d.entity.id, d.entity.access_hash))

# Output channels (same IDs, but accessed through different clients)
ukraine_news_channel = channels['output_channel_ids'][0]
russia_news_channel = channels['output_channel_ids'][1]
ukr_photos_channel = channels['output_channel_ids'][2]
rus_photos_channel = channels['output_channel_ids'][3]
ukr_videos_channel = channels['output_channel_ids'][4]
rus_videos_channel = channels['output_channel_ids'][5]

# Database helper functions with proper connection management
def get_db_connection():
    """Get a new database connection with proper settings."""
    conn = sqlite3.connect('src/messages.db', timeout=10.0)
    return conn

def init_database():
    """Initialize database schema with indexes and constraints."""
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
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON messages(date DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel ON messages(channel_id)')
        conn.commit()
        logger.info("Database initialized successfully")
    finally:
        conn.close()

def is_message_seen(channel_id, message_id):
    """Check if a message has been processed before."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM messages WHERE channel_id = ? AND message_id = ? LIMIT 1",
            (channel_id, message_id)
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()

def store_message(channel_id, message_id, content, link, date):
    """Store message in database with proper connection management."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO messages (channel_id, message_id, content, link, date) VALUES (?, ?, ?, ?, ?)",
            (channel_id, message_id, content, link, date)
        )
        conn.commit()
        store_msg_logger.debug(f"Stored message: Channel {channel_id}, Message ID {message_id}")
    except Exception as e:
        logger.error(f"Failed to store message {channel_id}/{message_id}: {e}", exc_info=True)
    finally:
        conn.close()

# Initialize database on startup
init_database()

async def translate_async(text, target_lang="EN-US"):
    """
    Translate text asynchronously using thread pool executor.

    This prevents blocking the event loop while waiting for DeepL API.
    """
    if not text:
        return ""

    loop = asyncio.get_event_loop()
    try:
        # Run blocking translation in thread pool
        translation = await loop.run_in_executor(
            None,
            partial(translator.translate_text, text, target_lang=target_lang)
        )
        return translation.text
    except deepl.exceptions.QuotaExceededException:
        logger.error("DeepL quota exceeded")
        return "[Translation unavailable: quota exceeded]"
    except deepl.exceptions.AuthorizationException:
        logger.error("DeepL authorization failed - check API key")
        return "[Translation unavailable: auth error]"
    except deepl.exceptions.DeepLException as e:
        logger.error(f"DeepL error: {e}")
        return "[Translation failed]"
    except Exception as e:
        logger.error(f"Unexpected translation error: {e}", exc_info=True)
        return "[Translation error]"

async def send_with_retry(client, channel_id, message, file=None, max_retries=3):
    """
    Send message with exponential backoff retry logic.

    Handles rate limiting and temporary failures gracefully.
    """
    for attempt in range(max_retries):
        try:
            await client.send_message(
                channel_id,
                message,
                parse_mode='html',
                file=file,
                link_preview=False
            )
            return True
        except FloodWaitError as e:
            if attempt == max_retries - 1:
                logger.error(f"Rate limited after {max_retries} attempts, giving up")
                raise
            wait_time = min(e.seconds, 60)  # Cap at 60 seconds
            logger.warning(f"Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(wait_time)
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Send failed after {max_retries} attempts: {e}")
                raise
            logger.warning(f"Send failed (attempt {attempt + 1}/{max_retries}): {e}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s

def create_message(chat_name, untranslated_msg, translation, link):
    """Create formatted HTML message for Telegram forwarding."""
    border = '<br>'
    if translation:
        message = (
            f'<p><p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n</p>'
            f'<p>[TRANSLATED MESSAGE]\n'
            f'{html.escape(translation)}\n\n</p>'
            f'<p>{border}\n'
            f'{html.escape(link)} ↩</p></p>'
        )
    else:
        message = (
            f'<p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n'
            f'{html.escape(link)} ↩</p>'
        )

    # Handle truncation if message is too long
    if len(message) >= 3980:
        translation = f'{translation[:3700]}...'
        message = (
            f'<p><p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n</p>'
            f'<p>[TRANSLATED MESSAGE]\n'
            f'{html.escape(translation)}\n\n</p>'
            f'<p>{border}\n'
            f'{html.escape(link)} ↩</p></p>'
        )
    return message

async def handle_message(event, client, news_channel, photos_channel, videos_channel, country_name):
    """
    Generic message handler for Ukraine and Russia channels.

    This consolidates the duplicate logic from both handlers with full error handling.
    """
    try:
        chat = await event.get_chat()
        chat_name = chat.title or chat.username
        date = event.date
        message_id = event.id
        link = f't.me/{chat.username or f"c/{chat.id}"}/{message_id}'

        logger.info(f"Received {country_name} message: Channel {chat.id}, Message ID {message_id}")

        # Check for duplicates before processing
        if is_message_seen(chat.id, message_id):
            logger.debug(f"Skipping duplicate message: {chat.id}/{message_id}")
            return

        untranslated_msg = event.message.message or ""

        # Handle media messages
        if event.message.media:
            if isinstance(event.message.media, MessageMediaWebPage):
                logger.warning(f"Unsupported media: Channel {chat.id}, Message ID {message_id}")
                return

            # Translate text if present (async, non-blocking)
            content = await translate_async(untranslated_msg) if untranslated_msg else ""
            message = create_message(chat_name, untranslated_msg, content, link)

            if event.message.photo:
                # Send to both news and photos channels
                await send_with_retry(client, news_channel, message, file=event.message.media)
                await send_with_retry(client, photos_channel, message, file=event.message.media)
            elif event.message.document:
                mime_type = event.message.media.document.mime_type
                if re.search('video', mime_type):
                    # Send videos to video channel
                    await send_with_retry(client, videos_channel, message, file=event.message.media)
                else:
                    # Send other documents to news channel
                    await send_with_retry(client, news_channel, message, file=event.message.media)
        else:
            # Text-only message
            content = await translate_async(untranslated_msg) if untranslated_msg else ""
            message = create_message(chat_name, untranslated_msg, content, link)
            await send_with_retry(client, news_channel, message)

        # Store after successful processing
        store_message(chat.id, message_id, untranslated_msg, link, date)

    except ChannelPrivateError:
        logger.error(f"Lost access to channel {event.chat_id}")
    except FloodWaitError as e:
        logger.warning(f"Rate limited for {e.seconds} seconds on channel {event.chat_id}")
    except Exception as e:
        logger.error(
            f"Failed to process {country_name} message {event.chat_id}/{event.id}: {e}",
            exc_info=True
        )

# Ukraine handler - uses ukraine_client
@ukraine_client.on(events.NewMessage(chats=ukraine_channels_entities))
async def handle_ukraine_messages(event):
    """Handle incoming messages from Ukraine channels using Ukraine account."""
    await handle_message(
        event,
        client=ukraine_client,
        news_channel=ukraine_news_channel,
        photos_channel=ukr_photos_channel,
        videos_channel=ukr_videos_channel,
        country_name="Ukraine"
    )

# Russia handler - uses russia_client
@russia_client.on(events.NewMessage(chats=russia_channels_entities))
async def handle_russia_messages(event):
    """Handle incoming messages from Russia channels using Russia account."""
    await handle_message(
        event,
        client=russia_client,
        news_channel=russia_news_channel,
        photos_channel=rus_photos_channel,
        videos_channel=rus_videos_channel,
        country_name="Russia"
    )

# Run both clients
async def main():
    logger.info("=" * 60)
    logger.info("DUAL-SESSION TELEGRAM LISTENER")
    logger.info("=" * 60)
    logger.info(f"Ukraine account monitoring {len(ukraine_channels_entities)} channels")
    logger.info(f"Russia account monitoring {len(russia_channels_entities)} channels")
    logger.info("=" * 60)

    # Run both clients concurrently
    await asyncio.gather(
        ukraine_client.run_until_disconnected(),
        russia_client.run_until_disconnected()
    )

if __name__ == '__main__':
    asyncio.run(main())
