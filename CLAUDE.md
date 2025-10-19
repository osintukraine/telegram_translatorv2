# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram message translator and forwarder application that monitors Ukrainian and Russian Telegram channels, translates messages to English using DeepL, and forwards them to categorized output channels (news, photos, videos) in near real-time. The project was developed to help follow Russian and Ukrainian-language Telegram posts about the war in Ukraine.

## Architecture

### Two-Process System (Orchestrated by Supervisor)

The application runs two separate processes simultaneously using supervisord:

1. **Telethon Listener** (`src/listener-db.py`): The main message processing service
   - Monitors configured Telegram channels using the Telethon library
   - Translates messages using DeepL API
   - Routes messages to appropriate output channels based on content type and source
   - Stores message metadata in SQLite to track processing
   - Logs to `/tmp/telethon_listener.out.log` and `/tmp/telethon_listener.err.log`

2. **Flask Web Server** (`app.py`): Log viewing interface
   - Provides a web UI at port 8080 for viewing real-time logs
   - Uses Server-Sent Events (SSE) to stream logs from the Telethon listener
   - Routes: `/` (index), `/logs` (log viewer UI), `/stream_logs` (SSE endpoint)

### Message Flow Architecture

The listener processes messages through two separate event handlers:

- `handle_ukraine_messages()`: Processes messages from Ukrainian channels
- `handle_russia_messages()`: Processes messages from Russian channels

Each handler:
1. Receives new message events from subscribed channels
2. Extracts message content and metadata (channel ID, message ID, date, link)
3. Translates text content using DeepL (target: EN-US)
4. Routes to appropriate output channels based on media type:
   - Text-only messages → news channel (ukraine_news_channel or russia_news_channel)
   - Photos → news channel + photos channel (ukr_photos_channel or rus_photos_channel)
   - Videos (documents with video MIME type) → videos channel (ukr_videos_channel or rus_videos_channel)
   - Other documents → news channel
   - Web page media → logged as unsupported
5. Stores message metadata in SQLite database

### Configuration Files

- `config.yml`: Telegram API credentials (api_id, api_hash, session_name)
- `channels.yml`: Channel ID mappings for input sources and output destinations
  - `ukraine_channel_ids`: List of Ukrainian source channels to monitor
  - `russian_channel_ids`: List of Russian source channels to monitor
  - `output_channel_ids`: 6 output channels in fixed order:
    - [0] ukraine_news_channel
    - [1] russia_news_channel
    - [2] ukr_photos_channel
    - [3] rus_photos_channel
    - [4] ukr_videos_channel
    - [5] rus_videos_channel
- `.env`: DeepL API key (DEEPL_AUTH_KEY)

### Data Persistence

- `messages.db`: SQLite database tracking processed messages
  - Schema: id, channel_id, message_id, date, content, link
  - Used for deduplication (though current code doesn't check before processing)
- `session_name.session`: Telegram authentication session file (persisted to avoid re-authentication)

### Logging Strategy

Multiple logging outputs for debugging and monitoring:
- Standard Python logging for info/warnings
- `seq_matcher_logs.log`: Debug logs for sequence matching (logger exists but not actively used in current code)
- `store_message_logs.log`: Debug logs for message storage operations
- `/tmp/telethon_listener.out.log`: Captured by Flask app for web viewing

## Development Commands

### Running Locally (Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp env-example .env
# Edit .env and add your DEEPL_AUTH_KEY

# Run the listener directly (for testing)
python src/listener-db.py

# Run the Flask app (separate terminal)
python app.py
```

### Docker Deployment (Production)

```bash
# Build the Docker image
docker build -t my_telegram_translator:v6 .

# Run with docker-compose
docker-compose up -d

# View logs
docker logs -f telegram_translator

# Stop the service
docker-compose down
```

The Dockerfile uses supervisord to run both processes. Mounted volumes persist:
- `./logs:/tmp` - Application logs
- `./src/messages.db:/app/src/messages.db` - Message database
- `./config.yml:/app/config.yml` - API credentials
- `./channels.yml:/app/channels.yml` - Channel configuration
- `./session_name.session:/app/session_name.session` - Telegram session

### Accessing the Log Viewer

When running (locally or Docker), access the web interface at:
- `http://localhost:8080/logs` - Real-time log streaming UI

## Important Implementation Details

### Channel ID Format
- Obtain channel IDs by forwarding a message from the channel to @userinfobot
- Remove the '-100' prefix from the ID before adding to channels.yml
- Channel IDs are integers, not strings (no quotes in YAML)

### Message Formatting
- Translated messages use HTML formatting with escape handling
- Messages include source channel name, translated content, and Telegram link
- Message length is capped at 3980 characters to stay within Telegram limits
- Border elements (`<br>`) separate sections

### Authentication Flow
- First run requires phone number and confirmation code from Telegram
- 2FA password if enabled on the account
- Session persists in `session_name.session` file
- The Telegram account must:
  - Have dialogs open with all input channels
  - Be an administrator on all output channels
  - Have dialogs open with all output channels

### Channel Entity Resolution
- On startup, the client iterates through all dialogs to match channel IDs
- Creates InputChannel entities with access_hash for Telethon operations
- If a channel ID is configured but no dialog exists, it won't be monitored

## Code Structure Notes

- The main application logic is in `src/listener-db.py` (despite the name, it's the production version)
- Both Ukraine and Russia handlers have nearly identical logic (potential refactoring opportunity)
- The `is_message_seen()` function exists but is not currently used to prevent duplicate processing
- Video detection uses regex search on MIME type (`re.search('video', mime_type)`)
- The DeepL translator is initialized globally with the API key from environment variables
