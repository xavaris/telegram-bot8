# ============================================================
# Część 1 z 15 – Infrastruktura i Runtime Core
# ============================================================

import os
import re
import sys
import time
import html
import signal
import logging
import sqlite3
import unicodedata
import difflib
from typing import Dict, List, Optional, Tuple
from contextlib import contextmanager

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# LOGGING (Railway stdout)
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("MARKET_BOT")

# =========================
# ENV – FAIL FAST
# =========================

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required ENV variable: {name}")
    return value


TOKEN = require_env("KEY")
GROUP_ID = int(require_env("GROUP_ID"))
WTS_TOPIC = int(require_env("WTS"))
WTB_TOPIC = int(require_env("WTB"))
WTT_TOPIC = int(require_env("WTT"))
LOGO_URL = require_env("LOGO_URL")
BOT_USERNAME = require_env("BOT_USERNAME")

ADMIN_IDS: List[int] = [
    int(x.strip())
    for x in require_env("ADMIN_IDS").split(",")
    if x.strip().isdigit()
]

# =========================
# Persistent Volume (Railway)
# =========================

DATA_DIR = "/data"
DB_PATH = os.path.join(DATA_DIR, "market.db")

os.makedirs(DATA_DIR, exist_ok=True)

# =========================
# Global Runtime Limits
# =========================

VENDOR_COOLDOWN_STANDARD = 6 * 3600
VENDOR_COOLDOWN_VIP = 3 * 3600
WTB_WTT_COOLDOWN = 900  # 15 min
AUTO_DELETE_SECONDS = 172800  # 48h

# =========================
# Global Memory Rate Limits
# =========================

INTEREST_RATE_LIMIT: Dict[int, float] = {}
GLOBAL_POST_RATE_LIMIT: Dict[int, float] = {}
DUPLICATE_CACHE: Dict[int, str] = {}
# ============================================================
# Część 2 z 15 – Warstwa Bazy Danych (SQLite WAL Hardened)
# ============================================================

# =========================
# DATABASE CONNECTION (WAL + Hardened)
# =========================

def create_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def db_cursor():
    conn = create_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Database error")
        raise
    finally:
        conn.close()


# =========================
# DATABASE SCHEMA INIT
# =========================

def init_db():

    with db_cursor() as cur:

        # Vendors
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            added_at TEXT,
            posts INTEGER DEFAULT 0,
            last_content TEXT,
            auto_enabled INTEGER DEFAULT 0,
            last_auto_post INTEGER DEFAULT 0,
            interest_total INTEGER DEFAULT 0
        )
        """)

        # Vendor cooldown (WTS)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS cooldowns (
            user_id INTEGER PRIMARY KEY,
            last_post INTEGER
        )
        """)

        # WTB/WTT cooldown
        cur.execute("""
        CREATE TABLE IF NOT EXISTS wtb_wtt_cooldown (
            user_id INTEGER PRIMARY KEY,
            last_post INTEGER
        )
        """)

        # Interest (WTS only)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS interests (
            message_id INTEGER,
            user_id INTEGER,
            vendor_username TEXT,
            PRIMARY KEY(message_id, user_id)
        )
        """)

        # Audit log
        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            username TEXT,
            timestamp INTEGER,
            metadata TEXT
        )
        """)

    logger.info("Database initialized (WAL + Persistent Volume ready)")


# =========================
# COOLDOWN HELPERS
# =========================

def get_vendor_last_post(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT last_post FROM cooldowns WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0


def set_vendor_last_post(user_id: int):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO cooldowns(user_id, last_post)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET last_post=excluded.last_post
        """, (user_id, int(time.time())))


def get_wtb_wtt_last(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT last_post FROM wtb_wtt_cooldown WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0


def set_wtb_wtt_last(user_id: int):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO wtb_wtt_cooldown(user_id, last_post)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET last_post=excluded.last_post
        """, (user_id, int(time.time())))
        # ============================================================
# Część 3 z 15 – Role Engine + Bootstrap
# ============================================================

# =========================
# ROLE MANAGER
# =========================

class RoleManager:

    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in ADMIN_IDS

    @staticmethod
    def get_vendor(username: Optional[str]):
        if not username:
            return None
        with db_cursor() as cur:
            cur.execute(
                "SELECT * FROM vendors WHERE username=?",
                (username.lower(),)
            )
            return cur.fetchone()

    @staticmethod
    def is_vendor(username: Optional[str]) -> bool:
        row = RoleManager.get_vendor(username)
        return bool(row and row[1] in ("vendor", "vip"))

    @staticmethod
    def is_vip(username: Optional[str]) -> bool:
        row = RoleManager.get_vendor(username)
        return bool(row and row[1] == "vip")

    @staticmethod
    def add_vendor(username: str, role: str = "vendor"):
        with db_cursor() as cur:
            cur.execute("""
                INSERT OR IGNORE INTO vendors(username, role, added_at)
                VALUES (?, ?, ?)
            """, (
                username.lower(),
                role,
                time.strftime("%Y-%m-%d %H:%M:%S")
            ))

    @staticmethod
    def remove_vendor(username: str):
        with db_cursor() as cur:
            cur.execute(
                "DELETE FROM vendors WHERE username=?",
                (username.lower(),)
            )

    @staticmethod
    def set_vip(username: str):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET role='vip'
                WHERE username=?
            """, (username.lower(),))

    @staticmethod
    def remove_vip(username: str):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET role='vendor',
                    auto_enabled=0
                WHERE username=?
            """, (username.lower(),))


# =========================
# BOOTSTRAP ROLES (ENV)
# =========================

BOOTSTRAP_VENDORS = [
    x.strip().lower()
    for x in os.getenv("VENDORS", "").split(",")
    if x.strip()
]

BOOTSTRAP_VIP = [
    x.strip().lower()
    for x in os.getenv("VIP_VENDORS", "").split(",")
    if x.strip()
]


def bootstrap_roles():

    for username in BOOTSTRAP_VENDORS:
        RoleManager.add_vendor(username, "vendor")

    for username in BOOTSTRAP_VIP:
        RoleManager.add_vendor(username, "vip")

    logger.info("Bootstrap roles loaded")
    # ============================================================
# Część 4 z 15 – State Machine Core (User Flow Engine)
# ============================================================

# =========================
# STATE INITIALIZATION
# =========================

def reset_state(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()


def init_state(context: ContextTypes.DEFAULT_TYPE):
    if "initialized" not in context.user_data:
        context.user_data.update({
            "mode": None,                 # WTS / WTB / WTT
            "wts_total": 0,               # liczba produktów
            "wts_products": [],           # lista produktów
            "city": None,                 # wykryte / wybrane miasto
            "temp_listing": None,         # WTB/WTT cache
            "edit_mode": False,           # czy w trybie edycji
            "admin_action": None,         # aktualna akcja admina
            "initialized": True
        })


# =========================
# FLOW CONSTANTS
# =========================

FLOW_NONE = None
FLOW_WTS_COUNT = "WTS_COUNT"
FLOW_WTS_INPUT = "WTS_INPUT"
FLOW_WTB = "WTB"
FLOW_WTT = "WTT"


# =========================
# SAFE MODE SWITCHER
# =========================

def set_mode(context: ContextTypes.DEFAULT_TYPE, mode: Optional[str]):
    context.user_data["mode"] = mode


def get_mode(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    return context.user_data.get("mode")


# =========================
# DUPLICATE PROTECTION CACHE
# =========================

def is_duplicate_post(user_id: int, content: str) -> bool:
    previous = DUPLICATE_CACHE.get(user_id)
    if previous and previous == content:
        return True
    DUPLICATE_CACHE[user_id] = content
    return False


# =========================
# GLOBAL POST RATE LIMIT
# =========================

GLOBAL_RATE_SECONDS = 3


def is_global_rate_limited(user_id: int) -> bool:
    now = time.time()
    last = GLOBAL_POST_RATE_LIMIT.get(user_id, 0)

    if now - last < GLOBAL_RATE_SECONDS:
        return True

    GLOBAL_POST_RATE_LIMIT[user_id] = now
    return False
    # ============================================================
# Część 5 z 15 – Detection Engine (Ultra Normalize + Anti-Evasion)
# ============================================================

# =========================
# ZERO WIDTH + UNICODE NORMALIZATION
# =========================

ZERO_WIDTH_PATTERN = re.compile(r"[\u200B-\u200D\uFEFF\u2060]")


def normalize_unicode(text: str) -> str:
    text = ZERO_WIDTH_PATTERN.sub("", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


# =========================
# HOMOGLYPH NORMALIZATION
# =========================

HOMOGLYPH_MAP = {
    "а": "a", "о": "o", "е": "e",
    "р": "p", "с": "c", "х": "x",
    "у": "y", "і": "i", "ӏ": "l"
}


def normalize_homoglyphs(text: str) -> str:
    return "".join(HOMOGLYPH_MAP.get(c, c) for c in text)


# =========================
# DIGIT → LETTER MAP
# =========================

DIGIT_TO_LETTER = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t"
}


def normalize_digits(text: str) -> str:
    for d, l in DIGIT_TO_LETTER.items():
        text = text.replace(d, l)
    return text


# =========================
# MASK MAP (ONLY FOR DETECTED WORDS)
# =========================

CHAR_MAP = {
    "a": "@", "c": "©", "e": "€",
    "i": "l", "s": "$", "t": "τ",
    "u": "Ц", "o": "Ø", "p": "₱",
    "w": "₩", "x": "Ж", "y": "¥",
    "z": "Ƶ",
}

REVERSE_MAP = {v.lower(): k for k, v in CHAR_MAP.items()}


# =========================
# ULTRA CATEGORY MAP
# =========================

ULTRA_CATEGORIES = {
    "💎": ["mewa", "ice", "kryx", "kryształ", "krystal", "crystal"],
    "🌿": ["weed", "buch", "jazz", "jaaz", "ziolo", "trawa"],
    "❄": ["3cmc", "4mmc", "feta"],
    "🍫": ["hasz", "haszysz", "hash"],
    "🧂": ["koks", "koko", "kokos", "cocaine"],
    "💊": ["clony", "clonozepan", "xanax", "medikinet", "pixy", "pigle", "piguly"]
}

SAFE_CONTEXT = [
    "ice cream",
    "crystal clear",
    "weed control",
    "hashmap",
    "feta cheese"
]


# =========================
# NORMALIZATION PIPELINE
# =========================

def normalize_for_detection(text: str) -> str:
    text = normalize_unicode(text)
    text = normalize_homoglyphs(text)
    text = normalize_digits(text)
    text = "".join(REVERSE_MAP.get(c.lower(), c) for c in text)
    return text.lower()


# =========================
# FUZZY MATCH
# =========================

def dynamic_threshold(word: str) -> float:
    l = len(word)
    if l <= 4:
        return 0.9
    elif l <= 7:
        return 0.8
    return 0.75


def fuzzy_match(word: str, keyword: str) -> bool:
    return (
        difflib.SequenceMatcher(None, word, keyword).ratio()
        >= dynamic_threshold(keyword)
    )


# =========================
# ULTRA DETECT
# =========================

def ultra_detect(text: str, listing_mode: bool = True) -> Tuple[str, str]:

    if not listing_mode:
        return "📦", text

    lowered = text.lower()

    for phrase in SAFE_CONTEXT:
        if phrase in lowered:
            return "📦", text

    normalized = normalize_for_detection(text)

    tokens = re.findall(r"\b[a-z0-9]+\b", normalized)
    original_tokens = re.findall(r"\b\S+\b", text)

    matched_indexes = set()
    detected_emoji = None

    for idx, token in enumerate(tokens):
        for emoji, keywords in ULTRA_CATEGORIES.items():
            for key in keywords:
                if fuzzy_match(token, key):
                    detected_emoji = emoji
                    matched_indexes.add(idx)
                    break

    masked_tokens = []

    for idx, original in enumerate(original_tokens):
        if idx in matched_indexes:
            masked = "".join(
                CHAR_MAP.get(c.lower(), c)
                for c in original
            )
            masked_tokens.append(masked)
        else:
            masked_tokens.append(original)

    if not detected_emoji:
        detected_emoji = "📦"

    return detected_emoji, " ".join(masked_tokens)
    # ============================================================
# Część 5 z 15 – Detection Engine (Ultra Normalize + Anti-Evasion)
# ============================================================

# =========================
# ZERO WIDTH + UNICODE NORMALIZATION
# =========================

ZERO_WIDTH_PATTERN = re.compile(r"[\u200B-\u200D\uFEFF\u2060]")


def normalize_unicode(text: str) -> str:
    text = ZERO_WIDTH_PATTERN.sub("", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


# =========================
# HOMOGLYPH NORMALIZATION
# =========================

HOMOGLYPH_MAP = {
    "а": "a", "о": "o", "е": "e",
    "р": "p", "с": "c", "х": "x",
    "у": "y", "і": "i", "ӏ": "l"
}


def normalize_homoglyphs(text: str) -> str:
    return "".join(HOMOGLYPH_MAP.get(c, c) for c in text)


# =========================
# DIGIT → LETTER MAP
# =========================

DIGIT_TO_LETTER = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t"
}


def normalize_digits(text: str) -> str:
    for d, l in DIGIT_TO_LETTER.items():
        text = text.replace(d, l)
    return text


# =========================
# MASK MAP (ONLY FOR DETECTED WORDS)
# =========================

CHAR_MAP = {
    "a": "@", "c": "©", "e": "€",
    "i": "l", "s": "$", "t": "τ",
    "u": "Ц", "o": "Ø", "p": "₱",
    "w": "₩", "x": "Ж", "y": "¥",
    "z": "Ƶ",
}

REVERSE_MAP = {v.lower(): k for k, v in CHAR_MAP.items()}


# =========================
# ULTRA CATEGORY MAP
# =========================

ULTRA_CATEGORIES = {
    "💎": ["mewa", "ice", "kryx", "kryształ", "krystal", "crystal"],
    "🌿": ["weed", "buch", "jazz", "jaaz", "ziolo", "trawa"],
    "❄": ["3cmc", "4mmc", "feta"],
    "🍫": ["hasz", "haszysz", "hash"],
    "🧂": ["koks", "koko", "kokos", "cocaine"],
    "💊": ["clony", "clonozepan", "xanax", "medikinet", "pixy", "pigle", "piguly"]
}

SAFE_CONTEXT = [
    "ice cream",
    "crystal clear",
    "weed control",
    "hashmap",
    "feta cheese"
]


# =========================
# NORMALIZATION PIPELINE
# =========================

def normalize_for_detection(text: str) -> str:
    text = normalize_unicode(text)
    text = normalize_homoglyphs(text)
    text = normalize_digits(text)
    text = "".join(REVERSE_MAP.get(c.lower(), c) for c in text)
    return text.lower()


# =========================
# FUZZY MATCH
# =========================

def dynamic_threshold(word: str) -> float:
    l = len(word)
    if l <= 4:
        return 0.9
    elif l <= 7:
        return 0.8
    return 0.75


def fuzzy_match(word: str, keyword: str) -> bool:
    return (
        difflib.SequenceMatcher(None, word, keyword).ratio()
        >= dynamic_threshold(keyword)
    )


# =========================
# ULTRA DETECT
# =========================

def ultra_detect(text: str, listing_mode: bool = True) -> Tuple[str, str]:

    if not listing_mode:
        return "📦", text

    lowered = text.lower()

    for phrase in SAFE_CONTEXT:
        if phrase in lowered:
            return "📦", text

    normalized = normalize_for_detection(text)

    tokens = re.findall(r"\b[a-z0-9]+\b", normalized)
    original_tokens = re.findall(r"\b\S+\b", text)

    matched_indexes = set()
    detected_emoji = None

    for idx, token in enumerate(tokens):
        for emoji, keywords in ULTRA_CATEGORIES.items():
            for key in keywords:
                if fuzzy_match(token, key):
                    detected_emoji = emoji
                    matched_indexes.add(idx)
                    break

    masked_tokens = []

    for idx, original in enumerate(original_tokens):
        if idx in matched_indexes:
            masked = "".join(
                CHAR_MAP.get(c.lower(), c)
                for c in original
            )
            masked_tokens.append(masked)
        else:
            masked_tokens.append(original)

    if not detected_emoji:
        detected_emoji = "📦"

    return detected_emoji, " ".join(masked_tokens)
    # ============================================================
# Część 6 z 15 – Hardcore Price Engine (Anti-Price System)
# ============================================================

# =========================
# PRICE DETECTION PATTERNS
# =========================

CURRENCY_PATTERNS = [
    r"\bzł\b",
    r"\bpln\b",
    r"\beur\b",
    r"\busd\b",
    r"€",
    r"\$"
]

WORD_NUMBERS = [
    "sto", "dwiescie", "trzysta",
    "czterysta", "piecset", "szescset",
    "tysiac", "hundred", "thousand"
]


# =========================
# HARDCORE PRICE DETECTOR
# =========================

def hardcore_price_detect(text: str) -> bool:

    normalized = normalize_for_detection(text)

    # wyjątek dla nazw typu 3cmc / 4mmc
    normalized = re.sub(r"\b(3cmc|4mmc)\b", "", normalized)

    # 1️⃣ Waluty
    for pattern in CURRENCY_PATTERNS:
        if re.search(pattern, normalized):
            return True

    # 2️⃣ Rozbite liczby 2-0-0 / 2_0_0
    if re.search(r"\b\d(?:[\-._/]\d){2,}\b", normalized):
        return True

    # 3️⃣ Spaced digits 2 0 0
    if re.search(r"\b\d\s+\d\s+\d\b", normalized):
        return True

    # 4️⃣ Zakresy 100-300
    if re.search(r"\b\d{2,}\s*-\s*\d{2,}\b", normalized):
        return True

    # 5️⃣ Liczebniki słowne
    for word in WORD_NUMBERS:
        if word in normalized:
            return True

    # 6️⃣ Standalone numbers
    matches = re.findall(r"\b\d{2,}\b", normalized)

    for m in matches:
        number = int(m)

        # wyjątek: lata
        if 1900 <= number <= 2099:
            continue

        # wyjątek: procent
        if re.search(rf"\b{m}%", normalized):
            continue

        # wyjątek: gramatura
        if re.search(rf"\b{m}(g|ml|tabs|szt)\b", normalized):
            continue

        return True

    return False
    # ============================================================
# Część 7 z 15 – Flood Protection & Advanced Rate Limiting
# ============================================================

# =========================
# VENDOR COOLDOWN CHECK
# =========================

def is_vendor_on_cooldown(user_id: int, is_vip: bool) -> bool:
    last_post = get_vendor_last_post(user_id)
    now = int(time.time())

    cooldown = (
        VENDOR_COOLDOWN_VIP if is_vip else VENDOR_COOLDOWN_STANDARD
    )

    return now - last_post < cooldown


# =========================
# WTB/WTT COOLDOWN CHECK
# =========================

def is_wtb_wtt_on_cooldown(user_id: int) -> bool:
    last_post = get_wtb_wtt_last(user_id)
    now = int(time.time())

    return now - last_post < WTB_WTT_COOLDOWN


# =========================
# ADVANCED DUPLICATE DETECTION
# =========================

def is_similar_duplicate(user_id: int, content: str) -> bool:
    """
    Sprawdza:
    1. Exact duplicate
    2. Fuzzy similarity > 0.92
    """

    previous = DUPLICATE_CACHE.get(user_id)

    if not previous:
        DUPLICATE_CACHE[user_id] = content
        return False

    # Exact
    if previous == content:
        return True

    # Fuzzy similarity
    ratio = difflib.SequenceMatcher(None, previous, content).ratio()

    if ratio > 0.92:
        return True

    DUPLICATE_CACHE[user_id] = content
    return False


# =========================
# GLOBAL POST SPAM PROTECTION
# =========================

GLOBAL_SPAM_LIMIT = 5
GLOBAL_SPAM_WINDOW = 10  # seconds

GLOBAL_ACTIVITY_LOG: Dict[int, List[int]] = {}


def is_globally_spamming(user_id: int) -> bool:
    now = int(time.time())

    history = GLOBAL_ACTIVITY_LOG.get(user_id, [])

    # keep only recent timestamps
    history = [t for t in history if now - t < GLOBAL_SPAM_WINDOW]

    history.append(now)
    GLOBAL_ACTIVITY_LOG[user_id] = history

    return len(history) > GLOBAL_SPAM_LIMIT
    # ============================================================
# Część 8 z 15 – State Machine Core (User Flow Engine)
# ============================================================

# =========================
# STATE INITIALIZATION
# =========================

def reset_state(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()


def init_state(context: ContextTypes.DEFAULT_TYPE):
    if "initialized" not in context.user_data:
        context.user_data.update({
            "mode": None,
            "wts_step": 0,
            "wts_total": 0,
            "wts_products": [],
            "city": None,
            "pending_text": None,
            "edit_mode": False,
            "admin_action": None,
            "initialized": True
        })


# =========================
# MODE HELPERS
# =========================

def set_mode(context: ContextTypes.DEFAULT_TYPE, mode: str):
    context.user_data["mode"] = mode


def get_mode(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    return context.user_data.get("mode")


# =========================
# WTS FLOW STATE HELPERS
# =========================

def start_wts_flow(context: ContextTypes.DEFAULT_TYPE, total_products: int):
    context.user_data["mode"] = "WTS_INPUT"
    context.user_data["wts_total"] = total_products
    context.user_data["wts_step"] = 1
    context.user_data["wts_products"] = []


def add_wts_product(context: ContextTypes.DEFAULT_TYPE, product_line: str):
    context.user_data["wts_products"].append(product_line)
    context.user_data["wts_step"] += 1


def is_wts_complete(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return len(context.user_data["wts_products"]) >= context.user_data["wts_total"]


def get_next_wts_step(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.user_data["wts_step"]


# =========================
# WTB/WTT FLOW STATE HELPERS
# =========================

def start_simple_post_flow(context: ContextTypes.DEFAULT_TYPE, mode: str):
    context.user_data["mode"] = mode
    context.user_data["pending_text"] = None
    context.user_data["city"] = None


def store_pending_text(context: ContextTypes.DEFAULT_TYPE, text: str):
    context.user_data["pending_text"] = text


def get_pending_text(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    return context.user_data.get("pending_text")


# =========================
# EDIT MODE STATE
# =========================

def enable_edit_mode(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["edit_mode"] = True


def disable_edit_mode(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["edit_mode"] = False


def is_edit_mode(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get("edit_mode", False)


# =========================
# ADMIN MODE STATE
# =========================

def set_admin_action(context: ContextTypes.DEFAULT_TYPE, action: str):
    context.user_data["admin_action"] = action


def clear_admin_action(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["admin_action"] = None


def get_admin_action(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    return context.user_data.get("admin_action")
    # ============================================================
# Część 9 z 15 – Menu Builder + Premium Layout System
# ============================================================

# =========================
# MAIN MENU BUILDER
# =========================

def build_main_menu(user):

    keyboard = []
    row = []

    username = user.username.lower() if user.username else None
    is_vendor = username and RoleManager.is_vendor(username)
    is_vip = username and RoleManager.is_vip(username)

    # ===== WTS only for vendors =====
    if is_vendor:
        if is_vip:
            row.append(InlineKeyboardButton("💎 WTS PREMIUM", callback_data="WTS"))
        else:
            row.append(InlineKeyboardButton("💼 WTS", callback_data="WTS"))

    row.append(InlineKeyboardButton("🛒 WTB", callback_data="WTB"))
    row.append(InlineKeyboardButton("🔁 WTT", callback_data="WTT"))

    keyboard.append(row)

    # ===== Vendor Panel =====
    if is_vendor:
        if is_vip:
            keyboard.append([
                InlineKeyboardButton("👑 VIP PANEL", callback_data="PANEL")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("📊 PANEL", callback_data="PANEL")
            ])

    # ===== Admin Panel =====
    if RoleManager.is_admin(user.id):
        keyboard.append([
            InlineKeyboardButton("⚙ ADMIN PANEL", callback_data="ADMIN")
        ])

    return InlineKeyboardMarkup(keyboard)


# =========================
# BACK BUTTON
# =========================

def back_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ MENU", callback_data="MENU")]
    ])


# =========================
# PREMIUM LAYOUT BUILDER
# =========================

def build_wts_caption(
    username: str,
    role: str,
    city: str,
    content: str
) -> str:

    username_safe = html.escape(username)

    if role == "vip":
        return (
            f"<b>💎💎💎 WTS PREMIUM MARKET 💎💎💎</b>\n\n"
            f"<b>👑 VIP VENDOR</b>\n"
            f"<b>@{username_safe}</b>\n"
            f"<b>📍 {city}</b>\n\n"
            f"{content}\n\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<b>🔥 VERIFIED PREMIUM SELLER</b>"
        )

    else:
        return (
            f"<b>💎 WTS MARKET 💎</b>\n\n"
            f"<b>@{username_safe}</b>\n"
            f"<b>📍 {city}</b>\n\n"
            f"{content}"
        )


# =========================
# WTB/WTT CAPTION BUILDER
# =========================

def build_simple_caption(
    mode: str,
    city: str,
    content: str
) -> str:

    return (
        f"<b>{mode} MARKET</b>\n\n"
        f"{content}\n\n"
        f"<b>📍 {city} | #3CITY</b>"
    )
    # ============================================================
# Część 10 z 15 – Callback Router (WTS / WTB / WTT Entry Logic)
# ============================================================

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user
    await query.answer()

    init_state(context)

    # ================= MENU RESET =================
    if query.data == "MENU":
        reset_state(context)
        init_state(context)
        await query.edit_message_text(
            "Menu:",
            reply_markup=build_main_menu(user)
        )
        return

    # ================= PANEL OPEN =================
    if query.data == "PANEL":

        if not user.username:
            await query.edit_message_text("Brak username.")
            return

        username = user.username.lower()

        if not RoleManager.is_vendor(username):
            await query.edit_message_text("Brak dostępu.")
            return

        vendor = RoleManager.get_vendor(username)
        role = vendor[1]
        auto_enabled = vendor[5]

        keyboard = [
            [InlineKeyboardButton("🔁 REPOST", callback_data="PANEL_REPOST")],
            [InlineKeyboardButton("✏ EDYTUJ", callback_data="PANEL_EDIT")],
            [InlineKeyboardButton("📊 STATYSTYKI", callback_data="PANEL_STATS")]
        ]

        if role == "vip":
            label = "🤖 AUTO OFF" if auto_enabled else "🤖 AUTO ON"
            keyboard.append([InlineKeyboardButton(label, callback_data="PANEL_AUTO")])

        keyboard.append([InlineKeyboardButton("⬅ MENU", callback_data="MENU")])

        await query.edit_message_text(
            "Panel:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= ADMIN PANEL =================
    if query.data == "ADMIN":

        if not RoleManager.is_admin(user.id):
            await query.edit_message_text("Brak dostępu.")
            return

        keyboard = [
            [InlineKeyboardButton("➕ ADD VENDOR", callback_data="ADMIN_ADD")],
            [InlineKeyboardButton("➖ REMOVE VENDOR", callback_data="ADMIN_REMOVE")],
            [InlineKeyboardButton("👑 MAKE VIP", callback_data="ADMIN_MAKEVIP")],
            [InlineKeyboardButton("❌ REMOVE VIP", callback_data="ADMIN_REMVIP")],
            [InlineKeyboardButton("🔄 REMOVE COOLDOWN", callback_data="ADMIN_RMCD")],
            [InlineKeyboardButton("⬅ MENU", callback_data="MENU")]
        ]

        await query.edit_message_text(
            "Admin Panel:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= WTS START =================
    if query.data == "WTS":

        if not user.username:
            await query.edit_message_text("Brak username.")
            return

        username = user.username.lower()

        if not RoleManager.is_vendor(username):
            await query.edit_message_text("Brak dostępu.")
            return

        is_vip = RoleManager.is_vip(username)

        if is_vendor_on_cooldown(user.id, is_vip):
            await query.edit_message_text(
                "Cooldown aktywny.",
                reply_markup=back_button()
            )
            return

        keyboard = []
        row = []

        for i in range(1, 11):
            row.append(
                InlineKeyboardButton(str(i), callback_data=f"WTS_COUNT_{i}")
            )
            if i % 5 == 0:
                keyboard.append(row)
                row = []

        keyboard.append([InlineKeyboardButton("⬅ MENU", callback_data="MENU")])

        await query.edit_message_text(
            "Ile produktów?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= WTS COUNT SELECT =================
    if query.data.startswith("WTS_COUNT_"):

        count = int(query.data.split("_")[2])

        start_wts_flow(context, count)

        await query.edit_message_text(
            "Podaj produkt 1:",
            reply_markup=back_button()
        )
        return

    # ================= WTB START =================
    if query.data == "WTB":

        if is_wtb_wtt_on_cooldown(user.id):
            await query.edit_message_text(
                "Cooldown aktywny.",
                reply_markup=back_button()
            )
            return

        start_simple_post_flow(context, "WTB")

        await query.edit_message_text(
            "Wpisz treść ogłoszenia WTB:",
            reply_markup=back_button()
        )
        return

    # ================= WTT START =================
    if query.data == "WTT":

        if is_wtb_wtt_on_cooldown(user.id):
            await query.edit_message_text(
                "Cooldown aktywny.",
                reply_markup=back_button()
            )
            return

        start_simple_post_flow(context, "WTT")

        await query.edit_message_text(
            "Wpisz treść ogłoszenia WTT:",
            reply_markup=back_button()
        )
        return

    # ================= ADMIN ACTION SELECT =================
    if query.data.startswith("ADMIN_"):
        set_admin_action(context, query.data)
        await query.edit_message_text(
            "Podaj @username:",
            reply_markup=back_button()
        )
        return
        # ============================================================
# Część 11 z 15 – Message Router (WTS Flow + WTB/WTT Flow)
# ============================================================

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    init_state(context)

    user = update.effective_user
    text = update.message.text.strip()

    if not text:
        return

    # ================= GLOBAL SPAM PROTECTION =================
    if is_globally_spamming(user.id):
        await update.message.reply_text("Zbyt wiele akcji. Zwolnij.")
        return

    # ================= ADMIN FLOW =================
    if get_admin_action(context):
        return  # obsłużone w admin_text_handler

    # ================= EDIT MODE =================
    if is_edit_mode(context):
        return  # obsłużone w edit_handler

    mode = get_mode(context)

    # ============================================================
    # ===================== WTS FLOW =============================
    # ============================================================

    if mode == "WTS_INPUT":

        if hardcore_price_detect(text):
            await update.message.reply_text(
                "❌ Zakaz podawania cen.",
                reply_markup=back_button()
            )
            return

        emoji, masked = ultra_detect(text, listing_mode=True)
        line = f"{emoji} {masked}"

        add_wts_product(context, line)

        if not is_wts_complete(context):
            next_step = get_next_wts_step(context)
            await update.message.reply_text(
                f"Podaj produkt {next_step}:",
                reply_markup=back_button()
            )
            return

        # wszystkie produkty podane
        combined = " ".join(context.user_data["wts_products"])
        city = detect_city(combined)

        context.user_data["city"] = city

        await finalize_wts_post(update, context)
        return

    # ============================================================
    # ===================== WTB / WTT FLOW =======================
    # ============================================================

    if mode in ("WTB", "WTT"):

        if hardcore_price_detect(text):
            await update.message.reply_text("❌ Zakaz cen.")
            return

        if is_similar_duplicate(user.id, text):
            await update.message.reply_text("Duplikat ogłoszenia.")
            return

        store_pending_text(context, text)

        city = detect_city(text)

        if city != "3CITY":
            context.user_data["city"] = city
            await finalize_simple_post(update, context)
            return

        # jeśli nie wykryto miasta — pytamy
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("GDY", callback_data="CITY_GDY"),
                InlineKeyboardButton("GDA", callback_data="CITY_GDA"),
                InlineKeyboardButton("SOP", callback_data="CITY_SOP"),
            ],
            [InlineKeyboardButton("⬅ MENU", callback_data="MENU")]
        ])

        await update.message.reply_text(
            "Wybierz miasto:",
            reply_markup=keyboard
        )
        return
        # ============================================================
# Część 12 z 15 – Finalize Posts (WTS + WTB/WTT) + City Callback
# ============================================================

# =========================
# FINALIZE WTS POST
# =========================

async def finalize_wts_post(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user.username:
        await update.message.reply_text("Brak username.")
        return

    username = user.username.lower()
    vendor = RoleManager.get_vendor(username)

    if not vendor:
        await update.message.reply_text("Brak dostępu.")
        return

    role = vendor[1]
    city = context.user_data.get("city", "3CITY")

    content = "\n".join(context.user_data["wts_products"])

    caption = build_wts_caption(
        username=username,
        role=role,
        city=city,
        content=content
    )

    await update.message.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=WTS_TOPIC,
        photo=LOGO_URL,
        caption=caption,
        parse_mode=ParseMode.HTML
    )

    update_vendor_post(username, caption)
    set_vendor_last_post(user.id)

    reset_state(context)

    await update.message.reply_text(
        "Opublikowano.",
        reply_markup=build_main_menu(user)
    )


# =========================
# FINALIZE SIMPLE POST (WTB / WTT)
# =========================

async def finalize_simple_post(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    mode = get_mode(context)
    text = get_pending_text(context)
    city = context.user_data.get("city", "3CITY")

    emoji, masked = ultra_detect(text, listing_mode=True)

    caption = build_simple_caption(
        mode=mode,
        city=city,
        content=f"{emoji} {masked}"
    )

    topic = WTB_TOPIC if mode == "WTB" else WTT_TOPIC

    await update.message.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=topic,
        photo=LOGO_URL,
        caption=caption,
        parse_mode=ParseMode.HTML
    )

    set_wtb_wtt_last(user.id)

    reset_state(context)

    await update.message.reply_text(
        "Opublikowano.",
        reply_markup=build_main_menu(user)
    )


# ============================================================
# CITY CALLBACK HANDLER (WTB/WTT CITY SELECTION)
# ============================================================

async def city_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user

    await query.answer()

    if not query.data.startswith("CITY_"):
        return

    city = query.data.replace("CITY_", "")
    context.user_data["city"] = city

    mode = get_mode(context)

    if mode in ("WTB", "WTT"):
        await finalize_simple_post(update, context)
        return

    if mode == "WTS_INPUT":
        await finalize_wts_post(update, context)
        return
        # ============================================================
# Część 13 z 15 – Vendor Panel + VIP Auto System
# ============================================================

# =========================
# PANEL CALLBACK HANDLER
# =========================

async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user

    await query.answer()

    if not user.username:
        await query.edit_message_text("Brak username.")
        return

    username = user.username.lower()

    if not RoleManager.is_vendor(username):
        await query.edit_message_text("Brak dostępu.")
        return

    vendor = RoleManager.get_vendor(username)
    role = vendor[1]
    last_content = vendor[4]
    auto_enabled = vendor[5]

    # ================= REPOST =================
    if query.data == "PANEL_REPOST":

        if not last_content:
            await query.edit_message_text("Brak ostatniego ogłoszenia.")
            return

        is_vip = role == "vip"

        if is_vendor_on_cooldown(user.id, is_vip):
            await query.edit_message_text("Cooldown aktywny.")
            return

        await query.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=last_content,
            parse_mode=ParseMode.HTML
        )

        set_vendor_last_post(user.id)

        await query.edit_message_text(
            "Repost wykonany.",
            reply_markup=build_main_menu(user)
        )
        return

    # ================= EDIT =================
    if query.data == "PANEL_EDIT":
        enable_edit_mode(context)
        await query.edit_message_text(
            "Podaj nową treść ogłoszenia:",
            reply_markup=back_button()
        )
        return

    # ================= STATS =================
    if query.data == "PANEL_STATS":
        posts = vendor[3]
        interest_total = vendor[7]

        await query.edit_message_text(
            f"📊 Posty: {posts}\n⭐ Statystyki aktywności: {interest_total}",
            reply_markup=back_button()
        )
        return

    # ================= VIP AUTO =================
    if query.data == "PANEL_AUTO" and role == "vip":

        with db_cursor() as cur:
            if auto_enabled:
                cur.execute(
                    "UPDATE vendors SET auto_enabled=0 WHERE username=?",
                    (username,)
                )
                remove_vip_job(context.application, username)
                status = "AUTO OFF"
            else:
                cur.execute(
                    "UPDATE vendors SET auto_enabled=1 WHERE username=?",
                    (username,)
                )
                schedule_vip_job(context.application, username)
                status = "AUTO ON"

        await query.edit_message_text(
            status,
            reply_markup=build_main_menu(user)
        )


# ============================================================
# VIP AUTO SYSTEM
# ============================================================

VIP_JOB_PREFIX = "vip_auto_"


def vip_job_name(username: str) -> str:
    return f"{VIP_JOB_PREFIX}{username}"


def remove_vip_job(application: Application, username: str):
    name = vip_job_name(username)
    for job in application.job_queue.jobs():
        if job.name == name:
            job.schedule_removal()


def schedule_vip_job(application: Application, username: str, interval: int = 21600):

    name = vip_job_name(username)

    for job in application.job_queue.jobs():
        if job.name == name:
            return

    async def vip_callback(ctx: ContextTypes.DEFAULT_TYPE):

        vendor = RoleManager.get_vendor(username)

        if not vendor:
            return

        role = vendor[1]
        auto_enabled = vendor[5]
        last_content = vendor[4]

        if role != "vip" or not auto_enabled or not last_content:
            return

        await ctx.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=last_content,
            parse_mode=ParseMode.HTML
        )

        with db_cursor() as cur:
            cur.execute(
                "UPDATE vendors SET last_auto_post=? WHERE username=?",
                (int(time.time()), username)
            )

    application.job_queue.run_repeating(
        vip_callback,
        interval=interval,
        first=interval,
        name=name
    )


def restore_vip_jobs(application: Application):

    with db_cursor() as cur:
        cur.execute(
            "SELECT username FROM vendors WHERE role='vip' AND auto_enabled=1"
        )
        rows = cur.fetchall()

    for (username,) in rows:
        schedule_vip_job(application, username)
        # ============================================================
# Część 14 z 15 – Admin Text Flow + Edit Handler
# ============================================================

# =========================
# ADMIN TEXT HANDLER
# =========================

async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    action = get_admin_action(context)

    if not action:
        return

    user = update.effective_user

    if not RoleManager.is_admin(user.id):
        clear_admin_action(context)
        return

    username = update.message.text.replace("@", "").strip().lower()

    if not username:
        clear_admin_action(context)
        await update.message.reply_text(
            "Niepoprawny username.",
            reply_markup=build_main_menu(user)
        )
        return

    if action == "ADMIN_ADD":
        RoleManager.add_vendor(username, "vendor")

    elif action == "ADMIN_REMOVE":
        RoleManager.remove_vendor(username)

    elif action == "ADMIN_MAKEVIP":
        RoleManager.set_vip(username)

    elif action == "ADMIN_REMVIP":
        with db_cursor() as cur:
            cur.execute(
                "UPDATE vendors SET role='vendor', auto_enabled=0 WHERE username=?",
                (username,)
            )
        remove_vip_job(context.application, username)

    elif action == "ADMIN_RMCD":
        with db_cursor() as cur:
            cur.execute("DELETE FROM cooldowns")

    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log(action, username, timestamp, metadata) VALUES (?, ?, ?, ?)",
            (action, username, int(time.time()), "")
        )

    clear_admin_action(context)

    await update.message.reply_text(
        "Wykonano.",
        reply_markup=build_main_menu(user)
    )


# ============================================================
# EDIT HANDLER
# ============================================================

async def edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_edit_mode(context):
        return

    user = update.effective_user

    if not user.username:
        disable_edit_mode(context)
        await update.message.reply_text("Brak username.")
        return

    text = update.message.text.strip()

    if hardcore_price_detect(text):
        await update.message.reply_text("❌ Zakaz cen.")
        return

    emoji, masked = ultra_detect(text, listing_mode=True)
    city = detect_city(text)

    username = user.username.lower()
    vendor = RoleManager.get_vendor(username)

    if not vendor:
        disable_edit_mode(context)
        return

    role = vendor[1]

    caption = build_wts_caption(
        username=username,
        role=role,
        city=city,
        content=f"{emoji} {masked}"
    )

    update_vendor_post(username, caption)

    if role == "vip":
        remove_vip_job(context.application, username)

        with db_cursor() as cur:
            cur.execute(
                "UPDATE vendors SET auto_enabled=0 WHERE username=?",
                (username,)
            )

    disable_edit_mode(context)

    await update.message.reply_text(
        "Ogłoszenie zaktualizowane.",
        reply_markup=build_main_menu(user)
    )
    # ============================================================
# Część 15 z 15 – Application Wiring + Startup + Final Integrity Guard
# ============================================================

async def global_error_handler(update, context):
    logger.exception("Unhandled exception", exc_info=context.error)


def setup_signal_handlers(application: Application):

    def shutdown_handler(signum, frame):
        logger.warning(f"Shutdown signal received: {signum}")
        try:
            application.stop()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)


def create_application() -> Application:

    app = Application.builder().token(TOKEN).build()

    # Global error handler
    app.add_error_handler(global_error_handler)

    # Signal handlers (Railway safe)
    setup_signal_handlers(app)

    return app


def main():

    # ================= INIT CORE =================
    init_db()
    bootstrap_roles()

    app = create_application()

    # ================= COMMANDS =================
    app.add_handler(CommandHandler("start", cmd_start))

    # ================= CALLBACK HANDLERS =================
    app.add_handler(CallbackQueryHandler(city_callback, pattern="^CITY_"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^PANEL"))
    app.add_handler(CallbackQueryHandler(callback_router))
    
    # ================= MESSAGE HANDLERS =================
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, edit_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    # ================= VIP RESTORE =================
    try:
        restore_vip_jobs(app)
    except Exception:
        logger.exception("VIP restore failed")

    logger.info("MARKET BOT – ENTERPRISE FINAL BUILD STARTED")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
