#!/usr/bin/env python3
"""Debug script to check which channels are being found."""

from telethon import TelegramClient
import yaml

with open('config.yml', 'rb') as f:
    config = yaml.safe_load(f)
with open('channels.yml', 'rb') as f:
    channels = yaml.safe_load(f)

client = TelegramClient(config["session_name"], config["api_id"], config["api_hash"])
client.start()

all_dialog_ids = []
ukraine_found = []
russia_found = []

for d in client.iter_dialogs():
    all_dialog_ids.append(d.entity.id)
    if d.entity.id in channels["ukraine_channel_ids"]:
        ukraine_found.append(d.entity.id)
    if d.entity.id in channels["russian_channel_ids"]:
        russia_found.append(d.entity.id)

print(f"Total dialogs found: {len(all_dialog_ids)}")
print(f"Ukraine channels in config: {len(channels['ukraine_channel_ids'])}")
print(f"Ukraine channels found in dialogs: {len(ukraine_found)}")
print(f"Russia channels in config: {len(channels['russian_channel_ids'])}")
print(f"Russia channels found in dialogs: {len(russia_found)}")
print(f"\nMissing Ukraine channels: {len(channels['ukraine_channel_ids']) - len(ukraine_found)}")
print(f"Missing Russia channels: {len(channels['russian_channel_ids']) - len(russia_found)}")

client.disconnect()
