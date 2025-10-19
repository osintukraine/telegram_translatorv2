#!/usr/bin/env python3
"""Test script to verify database schema is correct."""

import sqlite3
from datetime import datetime

def test_database_schema():
    """Test that database schema matches code expectations."""
    print("Testing database schema...")

    # Connect to database (same path as listener-db.py uses)
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()

    # Test 1: Insert a message (what store_message does)
    test_channel_id = 99999
    test_message_id = 88888
    try:
        cursor.execute(
            'INSERT OR IGNORE INTO messages (channel_id, message_id, content, link, date) VALUES (?, ?, ?, ?, ?)',
            (test_channel_id, test_message_id, 'Test content', 'https://t.me/test', datetime.now())
        )
        conn.commit()
        print("✅ Test 1: Insert message - PASSED")
    except Exception as e:
        print(f"❌ Test 1: Insert message - FAILED: {e}")
        conn.close()
        return False

    # Test 2: Query message (what is_message_seen does)
    try:
        cursor.execute('SELECT * FROM messages WHERE channel_id = ? AND message_id = ?', (test_channel_id, test_message_id))
        result = cursor.fetchone()
        if result:
            print("✅ Test 2: Query message - PASSED")
        else:
            print("❌ Test 2: Query message - FAILED: No result found")
            conn.close()
            return False
    except Exception as e:
        print(f"❌ Test 2: Query message - FAILED: {e}")
        conn.close()
        return False

    # Test 3: Check unique constraint (prevent duplicates)
    try:
        cursor.execute(
            'INSERT INTO messages (channel_id, message_id, content, link, date) VALUES (?, ?, ?, ?, ?)',
            (test_channel_id, test_message_id, 'Duplicate', 'https://t.me/test2', datetime.now())
        )
        conn.commit()
        print("❌ Test 3: Unique constraint - FAILED: Allowed duplicate")
        conn.close()
        return False
    except sqlite3.IntegrityError:
        print("✅ Test 3: Unique constraint - PASSED (correctly rejected duplicate)")

    # Cleanup test data
    cursor.execute('DELETE FROM messages WHERE channel_id = ?', (test_channel_id,))
    conn.commit()
    print("✅ Cleanup: Test data removed")

    # Show final state
    cursor.execute('SELECT COUNT(*) FROM messages')
    count = cursor.fetchone()[0]
    print(f"\n📊 Database ready. Current message count: {count}")

    conn.close()
    print("\n✅ All schema tests PASSED!")
    return True

if __name__ == '__main__':
    test_database_schema()
