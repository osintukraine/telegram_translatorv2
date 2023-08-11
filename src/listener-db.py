import sqlite3
from difflib import SequenceMatcher
from telethon import TelegramClient, events
from telethon.tl.types import InputChannel
from googletrans import Translator
import logging
import yaml
import html
import re

# Logging as per docs
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s', level=logging.INFO)
logging.getLogger('telethon').setLevel(level=logging.INFO)
logger = logging.getLogger(__name__)
# Initialize the logger for sequence matcher
seq_matcher_logger = logging.getLogger('seq_matcher')
seq_matcher_logger.setLevel(logging.DEBUG)

# If you want to log to a separate file, uncomment and adjust the following lines:
file_handler = logging.FileHandler('seq_matcher_logs.log')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
seq_matcher_logger.addHandler(file_handler)


# Load credentials from config.yml
with open('config.yml', 'rb') as f:
    config = yaml.safe_load(f)

# Load channel ID's from channels.yml
with open('channels.yml', 'rb') as f:
    channels = yaml.safe_load(f)

# Create the client
client = TelegramClient(config["session_name"], config["api_id"], config["api_hash"])

# Connect the client
client.start()
print('[Telethon] Client is listening...')

# Create a translator instance
translator = Translator()

# Get input and output Channel entities from the channel ID's
preferred_channels_entities = []
rus_channels_entities = []
ukr_channels_entities = []
output_channels_entities = []

for d in client.iter_dialogs():
    if d.entity.id in channels["rus_channel_ids"]:
        rus_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))
    if d.entity.id in channels["ukr_channel_ids"]:
        ukr_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))
    if d.entity.id in channels["preferred_channel_ids"]:
        preferred_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))
    if d.entity.id in channels["output_channel_ids"]:
        output_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))
        
if not output_channels_entities:
    logger.error(f"[Telethon] Could not find any output channels in the user's dialogs")
if not rus_channels_entities and not ukr_channels_entities and not preferred_channels_entities:
    logger.error(f"[Telethon] Could not find any input channels in the user's dialogs")

# Log total number of input and output channels
num_input_channels = len(list(set(channels["ukr_channel_ids"] + channels["rus_channel_ids"] + channels["preferred_channel_ids"])))
num_output_channels = len(output_channels_entities)
print(f"[Telethon] Listening to {num_input_channels} {'channel' if num_input_channels == 1 else 'channels'}.")
print(f"[Telethon] Forwarding messages to {num_output_channels} {'channel' if num_output_channels == 1 else 'channels'}.")

# Output channels
preferred_channel = channels['output_channel_ids'][0]
rus_videos_channel = channels['output_channel_ids'][1]
rus_photos_channel = channels['output_channel_ids'][2]
ukr_videos_channel = channels['output_channel_ids'][3]
ukr_photos_channel = channels['output_channel_ids'][4]

# Get the title or username of the input channel
def get_channel_name(chat):
    if hasattr(chat, 'title'):
        return chat.title
    else:
        return chat.username

# Setup SQLite Database
conn = sqlite3.connect('messages.db')
cursor = conn.cursor()

# Create the messages table

cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER NOT NULL PRIMARY KEY,
    origin TEXT NOT NULL,
    type TEXT NOT NULL,
    date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    edit_date TIMESTAMP,
    content TEXT,
    link TEXT,
    reply_to INTEGER,
    user_id INTEGER,
    media_id INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(media_id) REFERENCES media(id)
)
''')


# Create the users table
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER NOT NULL PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    tags TEXT,
    avatar TEXT
)
''')

# Create the media table
cursor.execute('''
CREATE TABLE IF NOT EXISTS media (
    id INTEGER NOT NULL PRIMARY KEY,
    type TEXT,
    url TEXT,
    title TEXT,
    description TEXT,
    thumb TEXT
)
''')

conn.commit()


def is_message_seen(origin, link, content):
    cursor.execute("SELECT * FROM messages WHERE origin = ? AND (content = ? OR link = ?)", (origin, content, link))
    result = cursor.fetchone()
    if result:
        stored_msg = result[2]
        matcher = SequenceMatcher(None, stored_msg, content)
        if matcher.ratio() > 0.9:  # adjust the threshold as needed
            print(f"Duplicate message detected: {link}. Similarity ratio: {matcher.ratio()}")
            return True
    return False

def store_message(origin, link, content, date):
    cursor.execute("INSERT INTO messages (origin, date, content, link) VALUES (?, ?, ?, ?)", (origin, date, content, link))
    conn.commit()


# Listen for new messages from my preferred channels
@client.on(events.NewMessage(chats=preferred_channels_entities))
async def handler(e):
    chat = await e.get_chat()
    chat_name = get_channel_name(chat)
    if chat.username:
        link = f't.me/{chat.username}/{e.id}'
    else:
        link = f't.me/c/{chat.id}/{e.id}'

    untranslated_msg = e.message.message

    # Check if message has been seen using sequence matcher
    if is_message_seen ("preferred", link, untranslated_msg):
        print(f"Message {link} has already been seen. Not forwarding.")
    return

    # Translate with Google Translator (source language is auto-detected; output language is English)
    content = translator.translate(untranslated_msg)
    if content.text:
        translation = content.text
    else:
        translation = ''

    # Translator mistranslates 'Тривога!' as 'Anxiety' (in this context); change to 'Alert!'
    translated_msg = translation.replace('Anxiety!', 'Alert!')
    
    # Escape input text since using html parsing
    message_id = e.id
    border = '<br>'
    if translation:
        message = (
            f'<p><p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n</p>'
            f'<p>[TRANSLATED MESSAGE]\n'
            f'{html.escape(translated_msg)}\n\n</p>'
            f'<p>{border}\n'
            f'{link}/{message_id} ↩</p></p>') 
    else:
        message = (
            f'<p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n'
            f'{link}/{message_id} ↩</p>') 

    # Message length limit appears to be around 3980 characters; must trim longer messages or they cannot be sent
    if len(message) >= 3980:
        formatting_chars_len = len(
            f'<p><p>{border}\n' + 
            f'<b>{html.escape(chat_name)}</b>\n' + 
            f'{border}\n\n</p>' + 
            f'<p>[TRANSLATED MESSAGE]\n' + 
            f'\n\n</p>' + 
            f'<p>{border}\n' + 
            f'{link}/{message_id} ↩</p></p>')
        
        # Subtract 3 for ellipsis
        desired_msg_len = 3980 - formatting_chars_len - 3
        translated_msg = f'{translated_msg[0:desired_msg_len]}...'
        message = (
            f'<p><p>{border}\n'
            f'<b>{html.escape(chat_name)}</b>\n'
            f'{border}\n\n</p>'
            f'<p>[TRANSLATED MESSAGE]\n'
            f'{html.escape(translated_msg)}\n\n</p>'
            f'<p>{border}\n'
            f'{link}/{message_id} ↩</p></p>') 

    if chat.username not in ['uavideos', 'uaphotos', 'amplifyukraine', 'telehunt_video', 'telehunt_news', 'telehunt_watch', 'telehunt_broadcast']:
        try:
            await client.send_message(preferred_channel, message, link_preview=False, parse_mode='html')
        except Exception as exc:
            print('[Telethon] Error while sending message!')
            print(exc)

    # Store the seen message
    store_message("preferred", link, untranslated_msg, date)

# Listen for new Russian video messages
@client.on(events.NewMessage(chats=rus_channels_entities, func=lambda e: hasattr(e.media, 'document')))
async def handler(e):
    video = e.message.media.document
    if hasattr(video, 'mime_type') and bool(re.search('video', video.mime_type)):
        content = translator.translate(e.message.message)
        if content.text:
            translation = content.text
        else:
            translation = ''
        
        chat = await e.get_chat()
        chat_name = get_channel_name(chat)

        if chat.username:
            link = f't.me/{chat.username}'
        else:
            link = f't.me/c/{chat.id}'
        
        message_id = e.id
        untranslated_msg = e.message.message

        # Check if message has been seen using sequence matcher
        if is_message_seen("rus_video", link, untranslated_msg):
            print(f"Message {link}/{message_id} has already been seen. Not forwarding.")
            return

        # Escape input text since using html parsing
        border = '<br>'
        if translation:
            message = (
                f'<p><p>{link}/{message_id} ↩\n\n'
                f'{border}\n'
                f'<p><b>{html.escape(chat_name)}</b>\n</p>'
                f'{border}\n\n</p>'
                f'<p>[TRANSLATED MESSAGE]\n'
                f'{html.escape(translation)}</p></p>'
                f'{border}\n</p>')
        else:
            message = (
                f'<p>{link}/{message_id} ↩\n\n' 
                f'{border}\n'
                f'<b>{html.escape(chat_name)}</b>\n'
                f'{border}</p>')

        # Video message length limit appears to be around 1024 characters; must trim longer messages or they cannot be sent
        if len(message) >= 1024:
            formatting_chars_len = len(
                f'<p><p>{link}/{message_id} ↩\n\n'
                f'{border}\n'
                f'<p><b>{html.escape(chat_name)}</b>\n</p>'
                f'{border}\n\n</p>'
                f'<p>[TRANSLATED MESSAGE]\n'
                f'\n\n</p>'
                f'{border}\n</p>')
            
            desired_msg_len = (1024 - formatting_chars_len - 6) // 2
            translated_msg = f'{translation[0:desired_msg_len]}...'
            untranslated_msg = f'{untranslated_msg[0:desired_msg_len]}...'
            message = (
                f'<p><p>{link}/{message_id} ↩\n\n'
                f'{border}\n'
                f'<p><b>{html.escape(chat_name)}</b>\n</p>'
                f'{border}\n\n</p>'
                f'<p>[TRANSLATED MESSAGE]\n'
                f'{html.escape(translated_msg)}\n\n</p>'
                f'{border}\n</p>')
            
        try:
            await client.send_message(rus_videos_channel, message, parse_mode='html', file=e.media, link_preview=False)
        except Exception as exc:
            print('[Telethon] Error while forwarding video message!')
            print(exc)
            print(e.message)

        # Store the seen message
        store_message("rus_video", link, untranslated_msg, date)

# Listen for new Russian photo messages
@client.on(events.NewMessage(chats=rus_channels_entities, func=lambda e: hasattr(e.media, 'photo')))
async def handler(e):
    chat = await e.get_chat()
    chat_name = get_channel_name(chat)

    if chat.username:
        link = f't.me/{chat.username}'
    else:
        link = f't.me/c/{chat.id}'
    
    message_id = e.id
    untranslated_msg = e.message.message

    # Check if message has been seen using sequence matcher
    if is_message_seen("rus_photo", link, untranslated_msg):
        print(f"Message {link}/{message_id} has already been seen. Not forwarding.")
        return

    border = '<br>'
    message = (
        f'<p>{link}/{message_id} ↩\n\n'
        f'{border}\n</p>'
        f'<b>{chat_name}</b>\n'
        f'{border}</p>')

    try:
        await client.send_message(rus_photos_channel, message, parse_mode='html', file=e.media, link_preview=False)
    except Exception as exc:
        print('[Telethon] Error while forwarding photo message!')
        print(exc)
        print(e.message)

    # Store the seen message
    store_message("rus_photo", link, untranslated_msg, date)

# Listen for new Ukrainian video messages
@client.on(events.NewMessage(chats=ukr_channels_entities, func=lambda e: hasattr(e.media, 'document')))
async def handler(e):
    video = e.message.media.document
    if hasattr(video, 'mime_type') and bool(re.search('video', video.mime_type)):
        content = translator.translate(e.message.message)
        if content.text:
            translation = content.text
        else:
            translation = ''
        
        chat = await e.get_chat()
        chat_name = get_channel_name(chat)

        if chat.username:
            link = f't.me/{chat.username}'
        else:
            link = f't.me/c/{chat.id}'
        
        message_id = e.id
        untranslated_msg = e.message.message

        # Check if message has been seen using sequence matcher
        if is_message_seen("ukr_video", link, untranslated_msg):
            print(f"Message {link}/{message_id} has already been seen. Not forwarding.")
            return

        # Escape input text since using html parsing
        border = '<br>'
        if translation:
            message = (
                f'<p><p>{link}/{message_id} ↩\n\n'
                f'{border}\n'
                f'<p><b>{html.escape(chat_name)}</b>\n</p>'
                f'{border}\n\n</p>'
                f'<p>[TRANSLATED MESSAGE]\n'
                f'{html.escape(translation)}</p></p>'
                f'{border}\n</p>')
        else:
            message = (
                f'<p>{link}/{message_id} ↩\n\n' 
                f'{border}\n'
                f'<b>{html.escape(chat_name)}</b>\n'
                f'{border}</p>')

        # Video message length limit appears to be around 1024 characters; must trim longer messages or they cannot be sent
        if len(message) >= 1024:
            formatting_chars_len = len(
                f'<p><p>{link}/{message_id} ↩\n\n'
                f'{border}\n'
                f'<p><b>{html.escape(chat_name)}</b>\n</p>'
                f'{border}\n\n</p>'
                f'<p>[TRANSLATED MESSAGE]\n'
                f'\n\n</p>'
                f'{border}\n')
            
            # Subtract 6 for ellipses; 
            desired_msg_len = (1024 - formatting_chars_len - 6) // 2
            translated_msg = f'{translation[0:desired_msg_len]}...'
            message = (
                f'<p><p>{link}/{message_id} ↩\n\n'
                f'{border}\n'
                f'<p><b>{html.escape(chat_name)}</b>\n</p>'
                f'{border}\n\n</p>'
                f'<p>[TRANSLATED MESSAGE]\n'
                f'{html.escape(translated_msg)}</p></p>'
                f'{border}\n</p>')                
            
        try:
            await client.send_message(ukr_videos_channel, message, parse_mode='html', file=e.media, link_preview=False)
        except Exception as exc:
            print('[Telethon] Error while forwarding video message!')
            print(exc)
            print(e.message)

        # Store the seen message
        store_message("ukr_video", link, untranslated_msg, date)

# Listen for new Ukrainian photo messages
@client.on(events.NewMessage(chats=ukr_channels_entities, func=lambda e: hasattr(e.media, 'photo')))
async def handler(e):
    chat = await e.get_chat()
    chat_name = get_channel_name(chat)

    if chat.username:
        link = f't.me/{chat.username}'
    else:
        link = f't.me/c/{chat.id}'
    
    message_id = e.id
    untranslated_msg = e.message.message

    # Check if message has been seen using sequence matcher
    if is_message_seen("ukr_photo", link, untranslated_msg):
        print(f"Message {link}/{message_id} has already been seen. Not forwarding.")
        return

    border = '<br>'
    message = (
        f'<p>{link}/{message_id} ↩\n\n'
        f'{border}\n</p>'
        f'<b>{chat_name}</b>\n'
        f'{border}</p>')

    try:
        await client.send_message(ukr_photos_channel, message, parse_mode='html', file=e.media, link_preview=False)
    except Exception as exc:
        print('[Telethon] Error while forwarding photo message!')
        print(exc)
        print(e.message)

    # Store the seen message
    store_message("ukr_photo", link, untranslated_msg, date)

# Run client until a keyboard interrupt (ctrl+C)
client.run_until_disconnected()
