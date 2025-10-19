import sqlite3
import asyncio
import sys
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
from spam_filter import is_spam

# Load environment variables
load_dotenv()

DEEPL_AUTH_KEY = os.getenv("DEEPL_AUTH_KEY")
translator = deepl.Translator(DEEPL_AUTH_KEY)

# Unified logging setup - stdout only (supervisord captures to file for Flask)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Format for all log messages
formatter = logging.Formatter('[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s')

# Single handler: stdout (supervisord redirects to /tmp/telethon_listener.out.log)
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.DEBUG)
stdout_handler.setFormatter(formatter)
logger.addHandler(stdout_handler)

# Reduce noise from telethon library
logging.getLogger('telethon').setLevel(logging.WARNING)

# Load config files
with open('config.yml', 'rb') as f:
    config = yaml.safe_load(f)
with open('channels.yml', 'rb') as f:
    channels = yaml.safe_load(f)

# Telegram client setup
client = TelegramClient(config["session_name"], config["api_id"], config["api_hash"])
client.start()
logger.info('[Telethon] Client is listening...')

# Define channel entities
ukraine_channels_entities = []
russia_channels_entities = []
output_channels_entities = []

for d in client.iter_dialogs():
    if d.entity.id in channels["ukraine_channel_ids"]:
        ukraine_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))
    if d.entity.id in channels["russian_channel_ids"]:
        russia_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))
    if d.entity.id in channels["output_channel_ids"]:
        output_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))

# Output channels
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
        # Create spam tracking table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS spam_filtered (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            date TIMESTAMP NOT NULL,
            spam_type TEXT NOT NULL,
            reason TEXT,
            content_preview TEXT,
            content_translated TEXT,
            link TEXT,
            UNIQUE(channel_id, message_id)
        )
        ''')
        # Create learned patterns table (self-learning spam filter)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS learned_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT NOT NULL,
            pattern_value TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pattern_type, pattern_value, action)
        )
        ''')
        # Create spam recovery tracking table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS spam_recovered (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spam_id INTEGER NOT NULL,
            recovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            forwarded BOOLEAN DEFAULT 0,
            learned_patterns_json TEXT,
            FOREIGN KEY (spam_id) REFERENCES spam_filtered(id)
        )
        ''')
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON messages(date DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel ON messages(channel_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_spam_date ON spam_filtered(date DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_spam_type ON spam_filtered(spam_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_learned_patterns ON learned_patterns(pattern_type, action)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pattern_confidence ON learned_patterns(confidence DESC)')
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
        rows_affected = cursor.rowcount
        conn.commit()

        if rows_affected > 0:
            logger.debug(f"Stored new message: Channel {channel_id}, Message ID {message_id}")
        else:
            logger.debug(f"Duplicate message skipped: Channel {channel_id}, Message ID {message_id}")
    except Exception as e:
        logger.error(f"Failed to store message {channel_id}/{message_id}: {e}", exc_info=True)
    finally:
        conn.close()

def store_spam(channel_id, message_id, spam_type, reason, content, content_translated, link, date):
    """Store filtered spam message for metrics and analysis (with translation for dashboard review)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Truncate content preview to 200 chars
        content_preview = (content[:200] + '...') if len(content) > 200 else content
        # Truncate translation to 500 chars for dashboard readability
        translated_preview = (content_translated[:500] + '...') if content_translated and len(content_translated) > 500 else content_translated
        cursor.execute(
            "INSERT OR IGNORE INTO spam_filtered (channel_id, message_id, date, spam_type, reason, content_preview, content_translated, link) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (channel_id, message_id, date, spam_type, reason, content_preview, translated_preview, link)
        )
        conn.commit()
        logger.debug(f"Stored spam: {spam_type} - Channel {channel_id}, Message ID {message_id}")
    except Exception as e:
        logger.error(f"Failed to store spam record {channel_id}/{message_id}: {e}", exc_info=True)
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

async def send_with_retry(channel_id, message, file=None, max_retries=3):
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

async def handle_message(event, news_channel, photos_channel, videos_channel, country_name):
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

        # Check for spam (financial spam, off-topic content) with learned patterns
        is_spam_message, spam_reason = is_spam(untranslated_msg, link, channel_id=chat.id)
        if is_spam_message:
            logger.info(f"Skipping spam message: {spam_reason} - {link}")
            # Determine spam type from reason
            spam_type = "financial" if "Financial spam" in spam_reason else "off-topic"
            # Translate spam for dashboard review (during testing phase)
            spam_translation = await translate_async(untranslated_msg) if untranslated_msg else ""
            # Store spam for metrics (with translation)
            store_spam(chat.id, message_id, spam_type, spam_reason, untranslated_msg, spam_translation, link, date)
            # Also store as seen to avoid reprocessing
            store_message(chat.id, message_id, untranslated_msg, link, date)
            return

        # Handle media messages
        if event.message.media:
            if isinstance(event.message.media, MessageMediaWebPage):
                # Web page previews - forward as text-only message
                logger.debug(f"Web page preview: Channel {chat.id}, Message ID {message_id}")
                content = await translate_async(untranslated_msg) if untranslated_msg else ""
                message = create_message(chat_name, untranslated_msg, content, link)
                await send_with_retry(news_channel, message)
                store_message(chat.id, message_id, untranslated_msg, link, date)
                return

            # Translate text if present (async, non-blocking)
            content = await translate_async(untranslated_msg) if untranslated_msg else ""
            message = create_message(chat_name, untranslated_msg, content, link)

            if event.message.photo:
                # Send to both news and photos channels
                await send_with_retry(news_channel, message, file=event.message.media)
                await send_with_retry(photos_channel, message, file=event.message.media)
            elif event.message.document:
                mime_type = event.message.media.document.mime_type
                if re.search('video', mime_type):
                    # Send videos to video channel
                    await send_with_retry(videos_channel, message, file=event.message.media)
                else:
                    # Send other documents to news channel
                    await send_with_retry(news_channel, message, file=event.message.media)
            else:
                # Unknown media type - log it and forward as text
                media_type = type(event.message.media).__name__
                logger.warning(f"Unknown media type '{media_type}' from {chat.id}/{message_id} - forwarding text only")
                await send_with_retry(news_channel, message)
        else:
            # Text-only message
            content = await translate_async(untranslated_msg) if untranslated_msg else ""
            message = create_message(chat_name, untranslated_msg, content, link)
            await send_with_retry(news_channel, message)

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

@client.on(events.NewMessage(chats=ukraine_channels_entities))
async def handle_ukraine_messages(event):
    """Handle incoming messages from Ukraine channels."""
    await handle_message(
        event,
        news_channel=ukraine_news_channel,
        photos_channel=ukr_photos_channel,
        videos_channel=ukr_videos_channel,
        country_name="Ukraine"
    )

@client.on(events.NewMessage(chats=russia_channels_entities))
async def handle_russia_messages(event):
    """Handle incoming messages from Russia channels."""
    await handle_message(
        event,
        news_channel=russia_news_channel,
        photos_channel=rus_photos_channel,
        videos_channel=rus_videos_channel,
        country_name="Russia"
    )

# Run the client
logger.info("Starting Telegram client...")
logger.info(f"Monitoring {len(ukraine_channels_entities)} Ukraine channels")
logger.info(f"Monitoring {len(russia_channels_entities)} Russia channels")
client.run_until_disconnected()
