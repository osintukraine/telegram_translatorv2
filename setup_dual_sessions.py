#!/usr/bin/env python3
"""
Setup script to create or verify dual session files for Ukraine and Russia accounts.

Run this to:
1. Create ukraine_session.session (login with Ukraine account)
2. Create russia_session.session (login with Russia account)
3. Verify which channels each session can access
"""

import yaml
from telethon import TelegramClient

# Load config
with open('config-dual.yml', 'r') as f:
    config = yaml.safe_load(f)

with open('channels.yml', 'r') as f:
    channels = yaml.safe_load(f)

def setup_session(session_name, api_id, api_hash, expected_channels, channel_type):
    """Setup and verify a session."""
    print(f"\n{'='*60}")
    print(f"Setting up {channel_type} session: {session_name}")
    print(f"{'='*60}")

    client = TelegramClient(session_name, api_id, api_hash)
    client.start()

    print(f"✓ Connected as {session_name}")

    # Check which channels are accessible
    accessible = []
    dialogs = list(client.iter_dialogs())
    dialog_ids = {d.entity.id for d in dialogs}

    for channel_id in expected_channels:
        if channel_id in dialog_ids:
            accessible.append(channel_id)

    print(f"\n{channel_type} Channels:")
    print(f"  Expected: {len(expected_channels)}")
    print(f"  Accessible: {len(accessible)}")
    print(f"  Missing: {len(expected_channels) - len(accessible)}")

    if len(accessible) < len(expected_channels):
        missing = set(expected_channels) - set(accessible)
        print(f"\n⚠️  Missing {len(missing)} channels:")
        for cid in list(missing)[:5]:
            print(f"    {cid}")
        if len(missing) > 5:
            print(f"    ... and {len(missing) - 5} more")

    client.disconnect()
    return len(accessible), len(expected_channels)

print("\n" + "="*60)
print("DUAL SESSION SETUP")
print("="*60)
print("\nThis will create two session files:")
print("  1. ukraine_session.session - for Ukraine channels")
print("  2. russia_session.session - for Russia channels")
print("\nYou will need to login with each account separately.")
input("\nPress Enter to continue...")

# Setup Ukraine session
ukraine_ok, ukraine_total = setup_session(
    config['ukraine_session_name'],
    config['ukraine_api_id'],
    config['ukraine_api_hash'],
    channels['ukraine_channel_ids'],
    "Ukraine"
)

# Setup Russia session
russia_ok, russia_total = setup_session(
    config['russia_session_name'],
    config['russia_api_id'],
    config['russia_api_hash'],
    channels['russian_channel_ids'],
    "Russia"
)

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
print(f"Ukraine: {ukraine_ok}/{ukraine_total} channels accessible")
print(f"Russia:  {russia_ok}/{russia_total} channels accessible")

if ukraine_ok < ukraine_total or russia_ok < russia_total:
    print(f"\n⚠️  Some channels are not accessible.")
    print("   You may need to join missing channels with each account.")
else:
    print(f"\n✓ All channels accessible! Ready to run dual-session listener.")

print(f"\nSession files created:")
print(f"  - {config['ukraine_session_name']}.session")
print(f"  - {config['russia_session_name']}.session")
print(f"\n✓ Setup complete!")
