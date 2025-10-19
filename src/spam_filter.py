"""
Spam detection for Telegram messages.

Filters two types of unwanted content:
1. Financial spam (donation requests, bank cards, payment links)
2. Off-topic content (not related to Ukraine/Russia war)
"""

import re
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


# Bank card number patterns (various formats)
CARD_NUMBER_PATTERNS = [
    r'\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b',  # 1234 5678 9012 3456 or 1234567890123456
    r'\b\d{4}-\d{4}-\d{4}-\d{4}\b',         # 1234-5678-9012-3456
]

# Payment/donation links
PAYMENT_DOMAINS = [
    r'monobank\.ua',
    r'privat24\.ua',
    r'send\.monobank',
    r'wayforpay',
    r'fondy\.eu',
    r'paypal\.me',
    r'patreon\.com',
    r'buymeacoffee',
    r'kofi\.com',
    r'donationalerts',
    r'donatepay',
]

# Donation keywords (multi-language)
# NOTE: These are SPECIFIC phrases, not generic words like "help" or "support"
DONATION_KEYWORDS = [
    # Ukrainian - SPECIFIC donation language
    r'\bдонат',
    r'\bпідтримайте канал',
    r'\bпідтримайте автор',
    r'\bзбір коштів',
    r'\bзбір на ',  # "fundraising for"
    r'\bперерахувати',  # transfer (money)
    r'\bреквізити',  # bank details
    r'\bякщо хочете підтримати',
    r'\bбуду вдячн',
    r'\bбуду радий',
    r'\bскинуть',  # chip in

    # Russian - SPECIFIC donation language
    r'\bдонат',
    r'\bподдержите канал',
    r'\bподдержите автор',
    r'\bсбор средств',
    r'\bсбор на ',  # "fundraising for"
    r'\bперечислить',  # transfer (money)
    r'\bреквизиты',  # bank details (plural)
    r'\bесли хотите поддержать',
    r'\bбуду благодарен',
    r'\bбуду рад',
    r'\bскинуть',  # chip in
    r'\bвыделить.*руб',  # allocate X rubles

    # English - SPECIFIC donation language
    r'\bdonat',
    r'\bsupport us',
    r'\bsupport.{0,10}channel',  # support the/our/this channel
    r'\bfundraising',
    r'\btip jar',
    r'\bcontribut',
    r'\bif you want to support',
]

# Military unit indicators (WHITELIST for fundraising)
# If message mentions these + donation, it's LEGITIMATE military fundraising
# NOTE: Only specific unit names and fundraising items, NOT general war terms
MILITARY_UNIT_KEYWORDS = [
    # Ukrainian military units
    r'\bзсу',  # Armed Forces of Ukraine
    r'\bвсу',  # same
    r'\bбригад',  # brigade
    r'\bбатальйон',  # battalion
    r'\bполк',  # regiment
    r'\bрота',  # company
    r'\bвзвод',  # platoon
    r'\bпідрозділ',  # unit
    r'\bтро',  # Territorial Defense
    r'\bазов',  # Azov
    r'\bкракен',  # Kraken
    r'\bда винчі',  # Da Vinci Wolves
    r'\bвовки',  # Wolves
    r'\bшторм',  # Storm

    # Russian military (for balance)
    r'\bвс рф',
    r'\bвагнер',
    r'\bчвк',

    # Fundraising equipment (specific items)
    r'\bдрон',  # drone
    r'\bбпла',  # UAV
    r'\bквадрокоптер',
    r'\bмавік',  # Mavic
    r'\bброн',  # armor
    r'\bгенератор',  # generator
    r'\bрації',  # radios
    r'\bтепловізор',  # thermal imager

    # English/transliterated
    r'\bbrigade',
    r'\bbattalion',
    r'\bregiment',
    r'\bdrone',
    r'\buav',
    r'\bmavic',
]

# Off-topic keywords (NOT related to Ukraine/Russia war)
OFF_TOPIC_KEYWORDS = [
    # Israel/Palestine conflict
    r'\bisrael',
    r'\bpalestine',
    r'\bpalestinian',
    r'\bgaza',
    r'\bhamas',
    r'\bhezbollah',
    r'\bwest bank',

    # Iran
    r'\biran',
    r'\biranian',
    r'\btehran',

    # Other conflicts
    r'\bsyria',
    r'\byemen',
    r'\bafghanistan',
    r'\blibya',

    # Generic off-topic
    r'\bcrypto',
    r'\bbitcoin',
    r'\bnft',
]

# War-related keywords (ON-topic, Ukraine/Russia conflict)
WAR_RELATED_KEYWORDS = [
    # Ukrainian locations
    r'\bukrain',
    r'\bkyiv',
    r'\bkharkiv',
    r'\bdonbas',
    r'\bluhansk',
    r'\bdonetsk',
    r'\bcrimea',
    r'\bmariupol',
    r'\bzaporizhzhia',
    r'\bkherson',
    r'\bodesa',
    r'\blviv',
    r'\bdnipro',

    # Russian locations/forces
    r'\brussia',
    r'\bmoscow',
    r'\bkremlin',
    r'\bputin',
    r'\bwagner',
    r'\bchechen',
    r'\bсво',  # СВО - Special Military Operation (Russian term for the war)

    # Military/war terms (avoid overly generic terms)
    r'\barmy',
    r'\bmilitary',
    r'\bsoldier',
    r'\btank',
    r'\bmissile',
    r'\bdrone',
    # r'\battack',  # TOO GENERIC - matches "Israel attacks"
    r'\boffensive',
    r'\bfront[s\b]',  # front line
    r'\bbrigade',
    r'\bbattalion',
    r'\bartillery',
    r'\bshelling',
    r'\bbombardment',

    # Ukrainian/Russian language indicators
    r'\bукра[іи]',
    r'\bросі[ійя]',
    r'\bзсу',  # Ukrainian Armed Forces
    r'\bвсу',  # Russian Armed Forces
]


def is_financial_spam(text: str) -> Tuple[bool, str]:
    """
    Detect financial spam (donations, bank cards, payment links).

    EXCEPTION: Military unit fundraising is NOT spam.
    If message mentions military units + donations, it's legitimate.

    Returns:
        (is_spam, reason) - True if spam detected, with explanation
    """
    if not text:
        return False, ""

    text_lower = text.lower()

    # First, check if this is MILITARY fundraising (legitimate)
    military_matches = [kw for kw in MILITARY_UNIT_KEYWORDS if re.search(kw, text_lower, re.IGNORECASE)]
    if military_matches:
        # This is military fundraising - NOT spam!
        logger.debug(f"Military fundraising detected (allowed): {military_matches[:2]}")
        return False, ""

    # Check for bank card numbers
    for pattern in CARD_NUMBER_PATTERNS:
        if re.search(pattern, text):
            return True, "Bank card number detected"

    # Check for payment links
    for domain in PAYMENT_DOMAINS:
        if re.search(domain, text_lower):
            return True, f"Payment link detected: {domain}"

    # Check for donation keywords (need multiple to avoid false positives)
    donation_matches = sum(1 for kw in DONATION_KEYWORDS if re.search(kw, text_lower, re.IGNORECASE))
    if donation_matches >= 2:
        return True, f"Donation request detected ({donation_matches} keywords)"

    return False, ""


def is_off_topic(text: str) -> Tuple[bool, str]:
    """
    Detect off-topic content (not related to Ukraine/Russia war).

    Strategy:
    - If contains strong off-topic keywords (Israel, Gaza, Iran, Yemen) → check if ALSO has Ukraine/Russia keywords
    - If contains generic war terms ONLY (drone, attack, etc.) but NO Ukraine/Russia → likely off-topic
    - If contains Ukraine/Russia keywords → definitely on-topic
    - If no strong signal → assume on-topic (avoid false positives)

    Returns:
        (is_off_topic, reason) - True if off-topic detected, with explanation
    """
    if not text:
        return False, ""

    text_lower = text.lower()

    # Count off-topic and on-topic keywords
    off_topic_matches = [kw for kw in OFF_TOPIC_KEYWORDS if re.search(kw, text_lower, re.IGNORECASE)]
    war_related_matches = [kw for kw in WAR_RELATED_KEYWORDS if re.search(kw, text_lower, re.IGNORECASE)]

    # Strong location-based indicators (not just generic war terms)
    ukraine_russia_keywords = [
        r'\bukrain', r'\bkyiv', r'\brussia', r'\bmoscow', r'\bdonbas',
        r'\bcrimea', r'\bkharkiv', r'\bputin', r'\bзсу', r'\bвсу',
        r'\bукра', r'\bросі'
    ]
    specific_location_matches = [kw for kw in ukraine_russia_keywords if re.search(kw, text_lower, re.IGNORECASE)]

    # If has specific Ukraine/Russia locations, it's definitely on-topic
    if specific_location_matches:
        logger.debug(f"On-topic: found specific location keywords {specific_location_matches[:2]}")
        return False, ""

    # Special case: Iran + drone/missile could be about supplying Russia
    # Example: "Iran sends Shahed drones to Russia" = ON-topic
    iran_match = any(re.search(r'\biran', text_lower, re.IGNORECASE) for _ in [1])
    drone_missile_match = any(re.search(kw, text_lower, re.IGNORECASE)
                              for kw in [r'\bdrone', r'\bmissile', r'\bshahed', r'\bgeran'])
    if iran_match and drone_missile_match:
        logger.debug(f"On-topic: Iran + drone/missile (likely related to Russia supply)")
        return False, ""

    # If has off-topic keywords (Israel, Gaza, Yemen), filter it
    # But we already excluded Iran+drone above
    if len(off_topic_matches) >= 1:
        logger.debug(f"Off-topic: {off_topic_matches[:3]}, war terms: {war_related_matches[:3]}")
        return True, f"Off-topic content detected: {', '.join(off_topic_matches[:3])}"

    # Default to on-topic (avoid filtering too aggressively)
    return False, ""


def is_spam(text: str, link: str = "", channel_id: int = None) -> Tuple[bool, str]:
    """
    Main spam detection function with learned pattern checking.

    Checks learned whitelist patterns first, then financial spam and off-topic content.

    Args:
        text: Message content (original language)
        link: Message link (optional, for logging)
        channel_id: Channel ID (optional, for learned pattern matching)

    Returns:
        (is_spam, reason) - True if spam detected, with explanation
    """
    # Check learned whitelist patterns FIRST (bypass spam filter if trusted)
    if channel_id is not None:
        try:
            # Import here to avoid circular dependency
            import sys
            import os
            sys.path.insert(0, os.path.dirname(__file__))
            from spam_learning import check_learned_patterns

            should_whitelist, whitelist_reason = check_learned_patterns(text, channel_id)
            if should_whitelist:
                logger.info(f"Whitelisted by learned pattern: {whitelist_reason} - {link}")
                return False, ""  # NOT spam (learned pattern)
        except Exception as e:
            # Don't fail spam detection if learning system has issues
            logger.warning(f"Failed to check learned patterns: {e}")

    # Check financial spam (higher priority)
    is_financial, reason = is_financial_spam(text)
    if is_financial:
        logger.info(f"Financial spam detected: {reason} - {link}")
        return True, f"Financial spam: {reason}"

    # Check off-topic content
    is_offtopic, reason = is_off_topic(text)
    if is_offtopic:
        logger.info(f"Off-topic content detected: {reason} - {link}")
        return True, f"Off-topic: {reason}"

    return False, ""


# Example test cases
if __name__ == "__main__":
    # Test financial spam detection
    test_cases = [
        # Financial spam - should be FILTERED
        ("Donate to my card 5168 7521 4428 8613", True, "Bank card (personal)"),
        ("Support via https://send.monobank.ua/jar/5tHNLeyVqk", True, "Monobank link (personal)"),
        ("Донат на карту ПриватБанку\n5168752144288613", True, "Donation + card (personal)"),
        ("Підтримка каналу, реквізити: 5168 7521 4428 8613", True, "Channel support (personal)"),

        # Military fundraising - should NOT be filtered (LEGITIMATE)
        ("3-тя штурмова бригада потребує дронів. Збір коштів:\n5168 7521 4428 8613", False, "Military unit fundraising"),
        ("ЗСУ потребує допомоги. Донат: https://send.monobank.ua/jar/xyz", False, "Military fundraising with link"),
        ("Наш батальйон збирає на Мавік. Реквізити: 5168752144288613", False, "Battalion drone fundraising"),
        ("Підтримка бійців Азов. Карта: 5168 7521 4428 8613", False, "Azov unit support"),

        # War news - should NOT be spam
        ("Ukraine forces advanced near Bakhmut", False, "War news"),
        ("Russia launched missiles at Kyiv", False, "War news"),
        ("Fighting near the river bank of Dnipro", False, "River bank (not financial)"),

        # Off-topic - should be FILTERED
        ("Israel attacks Gaza again, Hamas responds", True, "Off-topic: Israel/Gaza"),
        ("Syria conflict escalates near Damascus", True, "Off-topic: Syria"),

        # Iran + drones = ON-topic (likely about supplying Russia)
        ("Iran sends Shahed drones to Russia for Ukraine war", False, "Iran drones (Russia supply)"),
        ("Geran-2 drones from Iran used in Ukraine", False, "Iran drones (on-topic)"),

        # Iran without drones = OFF-topic
        ("Iran protests continue in Tehran", True, "Off-topic: Iran (no drones)"),

        # Edge case: mentions both conflicts (should NOT be spam - has Ukraine keywords)
        ("Like in Gaza, Ukraine faces humanitarian crisis", False, "Has Ukraine keyword"),
    ]

    logging.basicConfig(level=logging.DEBUG)

    print("Spam Filter Test Results:")
    print("=" * 80)

    for text, expected_spam, description in test_cases:
        is_spam_result, reason = is_spam(text)
        status = "✅ PASS" if is_spam_result == expected_spam else "❌ FAIL"
        print(f"{status} | {description}")
        print(f"    Text: {text[:60]}...")
        print(f"    Result: {'SPAM' if is_spam_result else 'OK'} - {reason}")
        print()
