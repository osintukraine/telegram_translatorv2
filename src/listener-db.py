import sqlite3
from telethon import TelegramClient, events
from telethon.tl.types import InputChannel, MessageMediaWebPage
from dotenv import load_dotenv
import os
import deepl
import logging
import yaml
import html
import re

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

# Load config files
with open('config.yml', 'rb') as f:
    config = yaml.safe_load(f)
with open('channels.yml', 'rb') as f:
    channels = yaml.safe_load(f)

# Telegram client setup
client = TelegramClient(config["session_name"], config["api_id"], config["api_hash"])
client.start()
print('[Telethon] Client is listening...')

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

# SQLite database setup
conn = sqlite3.connect('messages.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER NOT NULL PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    content TEXT,
    link TEXT
)
''')
conn.commit()

def is_message_seen(channel_id, message_id):
    cursor.execute("SELECT * FROM messages WHERE channel_id = ? AND message_id = ?", (channel_id, message_id))
    return bool(cursor.fetchone())

def store_message(channel_id, message_id, content, link, date):
    cursor.execute("INSERT INTO messages (channel_id, message_id, content, link, date) VALUES (?, ?, ?, ?, ?)",
                   (channel_id, message_id, content, link, date))
    conn.commit()
    store_msg_logger.debug(f"Stored message: Channel {channel_id}, Message ID {message_id}, Link {link}")

def create_message(chat_name, untranslated_msg, translation, link):
    border = '<br>'
    if translation:
        message = (
            f'<p><p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n</p>'
            f'<p>[TRANSLATED MESSAGE]\n'
            f'{html.escape(translation)}\n\n</p>'
            f'<p>{border}\n'
            f'{link} ↩</p></p>'
        )
    else:
        message = (
            f'<p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n'
            f'{link} ↩</p>'
        )
    if len(message) >= 3980:
        translation = f'{translation[:3980]}...'
        message = (
            f'<p><p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n</p>'
            f'<p>[TRANSLATED MESSAGE]\n'
            f'{html.escape(translation)}\n\n</p>'
            f'<p>{border}\n'
            f'{link} ↩</p></p>'
        )
    return message

@client.on(events.NewMessage(chats=ukraine_channels_entities))
async def handle_ukraine_messages(event):
    chat = await event.get_chat()
    chat_name = chat.title or chat.username
    date = event.date
    message_id = event.id
    link = f't.me/{chat.username or f"c/{chat.id}"}/{message_id}'

    logger.info(f"Received Ukraine message: Channel {chat.id}, Message ID {message_id}")

    untranslated_msg = event.message.message or ""
    if event.message.media:
        if isinstance(event.message.media, MessageMediaWebPage):
            logger.warning(f"Unsupported media: Channel {chat.id}, Message ID {message_id}, Link {link}")
        elif event.message.photo:
            content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
            message = create_message(chat_name, untranslated_msg, content, link)
            await client.send_message(ukraine_news_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
            await client.send_message(ukr_photos_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
        elif event.message.document:
            mime_type = event.message.media.document.mime_type
            if re.search('video', mime_type):
                content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
                message = create_message(chat_name, untranslated_msg, content, link)
                await client.send_message(ukr_videos_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
            else:
                content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
                message = create_message(chat_name, untranslated_msg, content, link)
                await client.send_message(ukraine_news_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
    else:
        content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
        message = create_message(chat_name, untranslated_msg, content, link)
        await client.send_message(ukraine_news_channel, message, parse_mode='html', link_preview=False)

    store_message(chat.id, message_id, untranslated_msg, link, date)

@client.on(events.NewMessage(chats=russia_channels_entities))
async def handle_russia_messages(event):
    chat = await event.get_chat()
    chat_name = chat.title or chat.username
    date = event.date
    message_id = event.id
    link = f't.me/{chat.username or f"c/{chat.id}"}/{message_id}'

    logger.info(f"Received Russia message: Channel {chat.id}, Message ID {message_id}")

    untranslated_msg = event.message.message or ""
    if event.message.media:
        if isinstance(event.message.media, MessageMediaWebPage):
            logger.warning(f"Unsupported media: Channel {chat.id}, Message ID {message_id}, Link {link}")
        elif event.message.photo:
            content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
            message = create_message(chat_name, untranslated_msg, content, link)
            await client.send_message(russia_news_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
            await client.send_message(rus_photos_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
        elif event.message.document:
            mime_type = event.message.media.document.mime_type
            if re.search('video', mime_type):
                content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
                message = create_message(chat_name, untranslated_msg, content, link)
                await client.send_message(rus_videos_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
            else:
                content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
                message = create_message(chat_name, untranslated_msg, content, link)
                await client.send_message(russia_news_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
    else:
        content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
        message = create_message(chat_name, untranslated_msg, content, link)
        await client.send_message(russia_news_channel, message, parse_mode='html', link_preview=False)

    store_message(chat.id, message_id, untranslated_msg, link, date)

client.run_until_disconnected()
