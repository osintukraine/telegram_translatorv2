# Duplicate Detection Analysis

## Current Architecture

**Source:** 254 channels (92 Ukraine + 162 Russia) from various sources
**Destination:** 6 output channels you control:
- `ukraine_news_channel` - Ukrainian text messages
- `russia_news_channel` - Russian text messages
- `ukr_photos_channel` - Ukrainian photos
- `rus_photos_channel` - Russian photos
- `ukr_videos_channel` - Ukrainian videos
- `rus_videos_channel` - Russian videos

**Archival:** Use `tg-archive` to archive just these 6 channels (instead of 254!)

---

## Current Duplicate Detection

```python
# Check BEFORE processing
if is_message_seen(source_channel_id, message_id):
    return  # Skip

# Process and forward...

# Store AFTER forwarding
store_message(source_channel_id, message_id, content, link, date)
```

**Database Schema:**
```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,      -- Source channel ID
    message_id INTEGER NOT NULL,      -- Original message ID from source
    date TIMESTAMP NOT NULL,
    content TEXT,
    link TEXT,
    UNIQUE(channel_id, message_id)    -- Prevents DB-level duplicates
)
```

---

## Issues with Current Approach

### 1. **Race Condition** (LOW RISK)
If two identical messages arrive before first one stores:
```
Time 0ms:  Message A arrives -> is_message_seen() = False
Time 5ms:  Message A duplicate arrives -> is_message_seen() = False (not stored yet)
Time 100ms: First message stores
Time 105ms: Duplicate stores (UNIQUE constraint prevents, but message already forwarded)
```

**Likelihood:** Very low - Telegram doesn't typically send true duplicates simultaneously
**Impact:** Duplicate in output channels

### 2. **Partial Failure** (MEDIUM RISK)
If forwarding succeeds but storing fails:
```
1. is_message_seen() = False (not in DB)
2. Forward to output channels ✓
3. store_message() fails ✗ (disk full, permissions, etc.)
4. On restart: is_message_seen() = False (still not in DB)
5. Forward again = DUPLICATE
```

**Likelihood:** Medium - can happen with disk issues, crashes during store
**Impact:** Duplicate in output channels on every restart

### 3. **Store After Forward** (CURRENT ISSUE)
Messages stored AFTER forwarding means:
- If forward fails, message not stored, will retry (GOOD)
- If forward succeeds but store fails, will retry forward (BAD - duplicate)

---

## Scenarios Where Duplicates Can Occur

### Scenario A: Listener Crash Between Forward & Store
```
1. Message arrives from channel 1234, message ID 5678
2. Forward to ukraine_news_channel ✓
3. **CRASH** (process killed, out of memory, etc.)
4. store_message() never called
5. Restart listener
6. Same message triggers again (not in DB)
7. Forward again = DUPLICATE
```

### Scenario B: Database Write Failure
```
1. Message forwarded successfully ✓
2. store_message() called
3. Database locked/full/permission error ✗
4. Exception caught and logged, but message not stored
5. Next restart: message re-processes = DUPLICATE
```

### Scenario C: Telegram Re-Delivery
Telegram might re-deliver messages in some edge cases:
- After reconnection
- During catch-up after offline period
- Network issues

Current code handles this ✓ (if store succeeded the first time)

---

## Solutions

### Option 1: Store BEFORE Forward (Idempotent) ⭐ RECOMMENDED

```python
async def handle_message(event, ...):
    # ... get message details ...

    # Store FIRST (marks as "processing")
    try:
        store_message(chat.id, message_id, untranslated_msg, link, date)
    except sqlite3.IntegrityError:
        # Already stored = already processed (or in-progress)
        logger.debug(f"Duplicate message: {chat.id}/{message_id}")
        return
    except Exception as e:
        logger.error(f"Failed to store message: {e}")
        # Don't forward if we can't track it
        return

    # Now forward (we know it's tracked in DB)
    try:
        # ... translate and forward ...
    except Exception as e:
        logger.error(f"Forward failed: {e}")
        # Message is in DB, won't retry (idempotent)
        # Could add a "forwarded" flag to retry failed forwards
```

**Pros:**
- Idempotent: If forward fails, we don't retry (no duplicates)
- Race-proof: UNIQUE constraint prevents concurrent duplicates
- Crash-proof: Even if crash during forward, won't re-forward

**Cons:**
- If forward fails permanently, message lost (stored but not forwarded)
- Could be mitigated with a "forwarded" status column

### Option 2: Add "Forwarded" Status Column

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    date TIMESTAMP NOT NULL,
    content TEXT,
    link TEXT,
    forwarded BOOLEAN DEFAULT 0,  -- New column
    forward_attempts INTEGER DEFAULT 0,  -- Retry tracking
    last_error TEXT,
    UNIQUE(channel_id, message_id)
)
```

```python
def mark_as_forwarded(channel_id, message_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE messages SET forwarded = 1 WHERE channel_id = ? AND message_id = ?",
            (channel_id, message_id)
        )
        conn.commit()
    finally:
        conn.close()

async def handle_message(event, ...):
    # Check if already forwarded
    if is_message_forwarded(chat.id, message_id):
        return

    # Store with forwarded=0
    store_message(chat.id, message_id, ...)

    # Forward
    try:
        await send_with_retry(...)
        mark_as_forwarded(chat.id, message_id)
    except Exception as e:
        # Logged but not marked forwarded
        # Will retry on next startup
```

**Pros:**
- Can retry failed forwards
- Tracks forwarding status separately
- No lost messages

**Cons:**
- More complex
- More database operations

### Option 3: Atomic Transaction with Lock

```python
async def handle_message(event, ...):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # BEGIN TRANSACTION
        cursor.execute("BEGIN EXCLUSIVE")

        # Check and insert atomically
        cursor.execute("SELECT 1 FROM messages WHERE channel_id = ? AND message_id = ?",
                      (chat.id, message_id))
        if cursor.fetchone():
            conn.rollback()
            return  # Already processed

        # Insert immediately
        cursor.execute("INSERT INTO messages (...) VALUES (...)")

        # COMMIT before forwarding
        conn.commit()

    finally:
        conn.close()

    # Now forward (already marked as processed)
    await send_with_retry(...)
```

**Pros:**
- Atomic check-and-insert
- Prevents races

**Cons:**
- Exclusive locks can cause contention
- Still has "stored but not forwarded" issue

---

## Recommendation

**Use Option 1 with monitoring:**

1. **Store before forward** (prevents duplicates)
2. **Monitor failed forwards** (add metrics)
3. **Add manual retry** script for failed forwards

This gives you:
- ✅ Zero duplicates in output channels
- ✅ Simple implementation
- ✅ Race-condition proof
- ✅ Crash-proof
- ⚠️ Possible lost messages (but rare, and monitorable)

If you want **zero lost messages**, use Option 2 (status column).

---

## Migration Plan

To move to Option 1:

```python
# Just swap the order
async def handle_message(event, news_channel, photos_channel, videos_channel, country_name):
    try:
        chat = await event.get_chat()
        # ... setup ...

        # NEW: Store FIRST (idempotent marker)
        try:
            store_message(chat.id, message_id, untranslated_msg, link, date)
        except sqlite3.IntegrityError:
            logger.debug(f"Duplicate: {chat.id}/{message_id}")
            return
        except Exception as e:
            logger.error(f"Storage failed: {e}")
            return  # Don't forward if can't track

        # OLD: Remove is_message_seen() check (redundant now)
        # if is_message_seen(...): return

        # Translate and forward...
        # ... (no change) ...

        # OLD: Remove store_message() at end (already stored)

    except Exception as e:
        logger.error(...)
```

**Testing:**
1. Deploy new version
2. Send test message
3. Kill process during forward
4. Restart
5. Verify message NOT re-forwarded (✓ no duplicate)

---

## Current vs Proposed

| Scenario | Current | Option 1 | Option 2 |
|----------|---------|----------|----------|
| Normal operation | ✅ No dupe | ✅ No dupe | ✅ No dupe |
| Crash during forward | ❌ Duplicate | ✅ No dupe | ✅ No dupe |
| Store failure | ❌ Duplicate | ✅ No dupe | ✅ No dupe |
| Forward failure | ✅ Retry | ❌ Lost | ✅ Retry |
| Race condition | ⚠️ Possible | ✅ Prevented | ✅ Prevented |

---

## Your Call

Which approach feels right?

1. **Option 1**: Simple, zero duplicates, rare message loss
2. **Option 2**: Complex, zero duplicates, zero loss
3. **Keep current**: Simple, rare duplicates on crash

I'd recommend **Option 1** for your use case since:
- Duplicates are worse than rare losses (you're archiving)
- Failures are rare with proper error handling
- Can always add Option 2 later if needed
