import sqlite3
from telethon import TelegramClient, events
from telethon.tl.types import InputChannel
from dotenv import load_dotenv
import os
import deepl
import logging
import yaml
import html
import re

# Load environment variables from .env
load_dotenv()

DEEPL_AUTH_KEY = os.getenv("DEEPL_AUTH_KEY")
translator = deepl.Translator(DEEPL_AUTH_KEY)

# Set up logging
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s', level=logging.INFO)
logging.getLogger('telethon').setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Additional loggers for debugging
seq_matcher_logger = logging.getLogger('seq_matcher')
seq_matcher_logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler('seq_matcher_logs.log')
seq_matcher_logger.addHandler(file_handler)

store_msg_logger = logging.getLogger('store_message')
store_msg_logger.setLevel(logging.DEBUG)
store_msg_file_handler = logging.FileHandler('store_message_logs.log')
store_msg_logger.addHandler(store_msg_file_handler)

# Load credentials and channels from config files
with open('config.yml', 'rb') as f:
    config = yaml.safe_load(f)
with open('channels.yml', 'rb') as f:
    channels = yaml.safe_load(f)

# Initialize Telegram client
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

# SQLite Database setup
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

# Check if message has already been processed
def is_message_seen(channel_id, message_id):
    cursor.execute("SELECT * FROM messages WHERE channel_id = ? AND message_id = ?", (channel_id, message_id))
    result = cursor.fetchone()
    return bool(result)

# Store processed message
def store_message(channel_id, message_id, content, link, date):
    cursor.execute("INSERT INTO messages (channel_id, message_id, content, link, date) VALUES (?, ?, ?, ?, ?)",
                   (channel_id, message_id, content, link, date))
    conn.commit()
    store_msg_logger.debug(f"Stored message from channel: {channel_id}, message_id: {message_id}, link: {link}")

# Prefabricate the message to send
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
            f'{link} ↩</p></p>')
    else:
        message = (
            f'<p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n'
            f'{link} ↩</p>')

    # Trim message if it exceeds Telegram limits
    if len(message) >= 3980:
        formatting_chars_len = len(
            f'<p><p>{border}\n' + 
            f'<b>{html.escape(chat_name)}</b>\n' + 
            f'{border}\n\n</p>' + 
            f'<p>[TRANSLATED MESSAGE]\n' + 
            f'\n\n</p>' + 
            f'<p>{border}\n' + 
            f'{link} ↩</p></p>')
        desired_msg_len = 3980 - formatting_chars_len - 3
        translation = f'{translation[0:desired_msg_len]}...'
        message = (
            f'<p><p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n</p>'
            f'<p>[TRANSLATED MESSAGE]\n'
            f'{html.escape(translation)}\n\n</p>'
            f'<p>{border}\n'
            f'{link} ↩</p></p>')

    return message

# Event handlers
@client.on(events.NewMessage(chats=ukraine_channels_entities))
async def handle_ukraine_messages(event):
    chat = await event.get_chat()
    chat_name = chat.title or chat.username
    date = event.date
    message_id = event.id
    link = f't.me/{chat.username or f"c/{chat.id}"}/{message_id}'

    if event.message.photo:
        untranslated_msg = event.message.message or ""
        content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
        message = create_message(chat_name, untranslated_msg, content, link)
        await client.send_message(ukraine_news_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
        await client.send_message(ukr_photos_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
    elif event.message.document and re.search('video', event.message.media.document.mime_type):
        untranslated_msg = event.message.message or ""
        content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
        message = create_message(chat_name, untranslated_msg, content, link)
        await client.send_message(ukr_videos_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
    else:
        untranslated_msg = event.message.message or ""
        content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
        message = create_message(chat_name, untranslated_msg, content, link)
        await client.send_message(ukraine_news_channel, message, parse_mode='html', link_preview=False)

@client.on(events.NewMessage(chats=russia_channels_entities))
async def handle_russia_messages(event):
    chat = await event.get_chat()
    chat_name = chat.title or chat.username
    date = event.date
    message_id = event.id
    link = f't.me/{chat.username or f"c/{chat.id}"}/{message_id}'

    if event.message.photo:
        untranslated_msg = event.message.message or ""
        content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
        message = create_message(chat_name, untranslated_msg, content, link)
        await client.send_message(russia_news_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
        await client.send_message(rus_photos_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
    elif event.message.document and re.search('video', event.message.media.document.mime_type):
        untranslated_msg = event.message.message or ""
        content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
        message = create_message(chat_name, untranslated_msg, content, link)
        await client.send_message(rus_videos_channel, message, parse_mode='html', file=event.message.media, link_preview=False)
    else:
        untranslated_msg = event.message.message or ""
        content = translator.translate_text(untranslated_msg, target_lang="EN-US").text if untranslated_msg else ""
        message = create_message(chat_name, untranslated_msg, content, link)
        await client.send_message(russia_news_channel, message, parse_mode='html', link_preview=False)

# Run client
client.run_until_disconnected()
