#!/usr/bin/env python3
"""Find which Ukraine channels are missing from dialogs."""

from telethon import TelegramClient
import yaml

with open('config.yml', 'rb') as f:
    config = yaml.safe_load(f)
with open('channels.yml', 'rb') as f:
    channels = yaml.safe_load(f)

client = TelegramClient(config["session_name"], config["api_id"], config["api_hash"])
client.start()

# Get all dialog IDs
dialog_ids = set()
for d in client.iter_dialogs():
    dialog_ids.add(d.entity.id)

# Find missing Ukraine channels
ukraine_ids = set(channels["ukraine_channel_ids"])
missing = ukraine_ids - dialog_ids

print(f"Missing Ukraine channel IDs ({len(missing)}):")
for channel_id in sorted(missing):
    print(f"  {channel_id}")

print(f"\nTo fix: The Telegram account needs to join/have dialogs with these {len(missing)} channels")

client.disconnect()
