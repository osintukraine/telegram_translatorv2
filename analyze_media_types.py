#!/usr/bin/env python3
"""
Analyze what media types are being received and currently skipped.
Run this to understand what "Unsupported media" actually means.
"""

from collections import Counter
from telethon import TelegramClient
from telethon.tl.types import MessageMediaWebPage
import yaml
import os
from dotenv import load_dotenv

load_dotenv()

# Load config
with open('config.yml', 'rb') as f:
    config = yaml.safe_load(f)
with open('channels.yml', 'rb') as f:
    channels = yaml.safe_load(f)

client = TelegramClient(config["session_name"], config["api_id"], config["api_hash"])
client.start()

media_types = Counter()
webpage_examples = []

print("Scanning recent messages for media types...")
print("This will check the last 50 messages from each monitored channel.\n")

# Check Ukraine channels
for channel_id in channels["ukraine_channel_ids"][:5]:  # Just check first 5 to be quick
    try:
        async for message in client.iter_messages(channel_id, limit=50):
            if message.media:
                media_type = type(message.media).__name__
                media_types[media_type] += 1

                if isinstance(message.media, MessageMediaWebPage):
                    webpage_examples.append({
                        'channel': channel_id,
                        'msg_id': message.id,
                        'text': message.message[:100] if message.message else '[No text]',
                        'url': message.media.webpage.url if hasattr(message.media.webpage, 'url') else 'N/A'
                    })
    except Exception as e:
        print(f"Couldn't check channel {channel_id}: {e}")

print("\n" + "="*60)
print("MEDIA TYPES FOUND")
print("="*60)
for media_type, count in media_types.most_common():
    status = "✓ Forwarded" if media_type not in ["MessageMediaWebPage"] else "✗ SKIPPED"
    print(f"{status:15} {media_type:30} ({count} messages)")

if webpage_examples:
    print("\n" + "="*60)
    print("WEBPAGE EXAMPLES (Currently Skipped!)")
    print("="*60)
    for ex in webpage_examples[:3]:
        print(f"\nChannel: {ex['channel']}, Message: {ex['msg_id']}")
        print(f"Text: {ex['text']}")
        print(f"URL: {ex['url']}")

print("\n" + "="*60)
print("RECOMMENDATION")
print("="*60)
print("MessageMediaWebPage messages contain:")
print("  - Regular text content")
print("  - Link preview/embed")
print("")
print("These should be forwarded as TEXT-ONLY messages!")
print("The link preview is just visual, the important content is the text.")

client.disconnect()
