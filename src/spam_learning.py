"""
Self-learning spam filter system.

Extracts patterns from user feedback (false positives/negatives)
and uses them to improve future spam detection.
"""

import sqlite3
import re
import json
from typing import List, Tuple, Dict
from collections import Counter
import logging

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect('src/messages.db', timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def extract_ngrams(text: str, n: int = 3) -> List[str]:
    """Extract n-grams (word sequences) from text, preserving case."""
    words = re.findall(r'\b\w+\b', text)  # Preserve original case
    if len(words) < n:
        return []
    return [' '.join(words[i:i+n]) for i in range(len(words) - n + 1)]


def extract_patterns_from_message(content: str, channel_id: int) -> Dict[str, List[str]]:
    """
    Extract learnable patterns from a message.

    Returns dict with pattern types:
    - trigram: [3-word phrases]
    - named_entity: [capitalized words/phrases]

    NOTE: Channel-level whitelisting is NOT used to avoid missing
    actual spam from mixed-content channels in war coverage context.
    """
    patterns = {
        'trigram': [],
        'named_entity': []
    }

    # Extract trigrams (3-word sequences)
    trigrams = extract_ngrams(content, n=3)

    # Filter out generic trigrams - keep only meaningful ones
    # Common stop words to avoid (Russian and English)
    stop_words = {
        'the', 'and', 'or', 'but', 'for', 'with', 'this', 'that',
        'в', 'и', 'на', 'с', 'по', 'из', 'к', 'от', 'за', 'о', 'для',
        'что', 'как', 'это', 'был', 'была', 'были'
    }

    meaningful_trigrams = []
    for trigram in trigrams:
        words = trigram.split()
        # Skip if all words are stop words or too short
        if len(words) == 3 and not all(word in stop_words or len(word) < 3 for word in words):
            # Prefer trigrams with at least one capitalized word or number
            if any(word[0].isupper() or word.isdigit() for word in words if word):
                meaningful_trigrams.append(trigram)

    patterns['trigram'] = meaningful_trigrams[:10]  # Keep top 10 most specific

    # Extract named entities (capitalized words/phrases in Cyrillic or Latin)
    # Match: Минюст, СВО, Ministry of Justice, NATO, etc.
    # Minimum 2 characters to avoid single letters
    named_entities = re.findall(r'\b[А-ЯЁA-Z][а-яёa-z]{1,}(?:\s+[А-ЯЁA-Z][а-яёa-z]+)*\b', content)

    # Filter out common single words that aren't actually entities
    common_starts = {'The', 'A', 'An', 'In', 'On', 'At', 'To', 'For', 'With'}
    filtered_entities = [e for e in named_entities if e not in common_starts and len(e) > 2]

    patterns['named_entity'] = list(set(filtered_entities))[:8]  # Keep top 8 unique

    return patterns


def add_learned_pattern(pattern_type: str, pattern_value: str, action: str) -> None:
    """
    Add or update a learned pattern in the database.

    Args:
        pattern_type: 'channel', 'trigram', or 'named_entity'
        pattern_value: The actual pattern value
        action: 'whitelist' (not spam) or 'blacklist' (is spam)
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Try to insert, or update confidence if exists
        cursor.execute('''
            INSERT INTO learned_patterns (pattern_type, pattern_value, action, confidence)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(pattern_type, pattern_value, action)
            DO UPDATE SET
                confidence = confidence + 1,
                last_seen = CURRENT_TIMESTAMP
        ''', (pattern_type, pattern_value, action))
        conn.commit()
        logger.info(f"Learned pattern: {pattern_type}={pattern_value} (action={action})")
    finally:
        conn.close()


def check_learned_patterns(content: str, channel_id: int) -> Tuple[bool, str]:
    """
    Check if message matches any learned whitelist patterns.

    Uses content-based patterns (named entities, trigrams) only.
    Channel-level whitelisting is NOT used to avoid missing spam
    from mixed-content channels.

    Returns:
        (should_whitelist, reason) - True if message should bypass spam filter
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # NOTE: Channel whitelisting intentionally disabled for war coverage context
        # Check named entity whitelist
        named_entities = re.findall(r'\b[А-ЯЁA-Z][а-яёa-z]+(?:\s+[А-ЯЁA-Z][а-яёa-z]+)*\b', content)
        for entity in named_entities:
            cursor.execute('''
                SELECT confidence FROM learned_patterns
                WHERE pattern_type = 'named_entity'
                AND pattern_value = ?
                AND action = 'whitelist'
                AND confidence > 0
            ''', (entity,))
            entity_match = cursor.fetchone()
            if entity_match and entity_match['confidence'] >= 2:  # Require confidence >= 2
                return True, f"Trusted entity: {entity} (confidence: {entity_match['confidence']})"

        # Check trigram whitelist (least specific, require higher confidence)
        trigrams = extract_ngrams(content, n=3)
        for trigram in trigrams[:20]:  # Check top 20 trigrams
            cursor.execute('''
                SELECT confidence FROM learned_patterns
                WHERE pattern_type = 'trigram'
                AND pattern_value = ?
                AND action = 'whitelist'
                AND confidence > 0
            ''', (trigram,))
            trigram_match = cursor.fetchone()
            if trigram_match and trigram_match['confidence'] >= 3:  # Require confidence >= 3
                return True, f"Trusted phrase pattern (confidence: {trigram_match['confidence']})"

        return False, ""
    finally:
        conn.close()


def learn_from_false_positive(spam_id: int, should_forward: bool = False) -> Dict:
    """
    Learn patterns from a false positive spam detection.

    Args:
        spam_id: ID from spam_filtered table
        should_forward: Whether to re-forward the message

    Returns:
        Dict with learned patterns and recovery info
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Get the spam message details
        cursor.execute('''
            SELECT channel_id, message_id, content_preview, link
            FROM spam_filtered
            WHERE id = ?
        ''', (spam_id,))
        spam_msg = cursor.fetchone()

        if not spam_msg:
            return {'error': 'Spam message not found'}

        # Extract patterns
        patterns = extract_patterns_from_message(
            spam_msg['content_preview'],
            spam_msg['channel_id']
        )

        # Add patterns to whitelist
        learned_count = 0
        for pattern_type, pattern_values in patterns.items():
            for pattern_value in pattern_values:
                if pattern_value:  # Skip empty patterns
                    add_learned_pattern(pattern_type, pattern_value, 'whitelist')
                    learned_count += 1

        # Record recovery
        cursor.execute('''
            INSERT INTO spam_recovered (spam_id, forwarded, learned_patterns_json)
            VALUES (?, ?, ?)
        ''', (spam_id, should_forward, json.dumps(patterns)))
        conn.commit()

        return {
            'success': True,
            'learned_patterns': patterns,
            'learned_count': learned_count,
            'spam_id': spam_id,
            'should_forward': should_forward
        }
    finally:
        conn.close()


def get_learned_patterns_summary() -> Dict:
    """Get summary of all learned patterns."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Get whitelist patterns by type
        cursor.execute('''
            SELECT pattern_type, COUNT(*) as count, SUM(confidence) as total_confidence
            FROM learned_patterns
            WHERE action = 'whitelist' AND confidence > 0
            GROUP BY pattern_type
        ''')
        pattern_stats = [dict(row) for row in cursor.fetchall()]

        # Get top patterns by confidence
        cursor.execute('''
            SELECT pattern_type, pattern_value, confidence, last_seen
            FROM learned_patterns
            WHERE action = 'whitelist' AND confidence > 0
            ORDER BY confidence DESC
            LIMIT 20
        ''')
        top_patterns = [dict(row) for row in cursor.fetchall()]

        # Get recovery count
        cursor.execute('SELECT COUNT(*) as count FROM spam_recovered')
        recovery_count = cursor.fetchone()['count']

        return {
            'pattern_stats': pattern_stats,
            'top_patterns': top_patterns,
            'total_recovered': recovery_count
        }
    finally:
        conn.close()


def delete_learned_pattern(pattern_id: int) -> bool:
    """Delete a learned pattern by ID."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM learned_patterns WHERE id = ?', (pattern_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
