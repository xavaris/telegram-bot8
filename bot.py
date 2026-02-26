# ================= Część 1 z 6 =================
# INFRASTRUCTURE + ENV VALIDATION + HARDENED SQLITE + ERROR HANDLER

import os
import sys
import logging
import signal
import sqlite3
from typing import List, Optional
from contextlib import contextmanager
from telegram.ext import Application

# ============================================================
# LOGGING (Railway compatible – stdout)
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("MARKET_BOT")

# ============================================================
# ENV VALIDATION (FAIL FAST)
# ============================================================

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

# MULTI ADMIN
ADMIN_IDS: List[int] = [
    int(x.strip())
    for x in require_env("ADMIN_IDS").split(",")
    if x.strip().isdigit()
]

# Bootstrap lists (optional ENV)
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

logger.info("ENV loaded successfully")
logger.info(f"Admins: {ADMIN_IDS}")
logger.info(f"Bootstrap vendors: {BOOTSTRAP_VENDORS}")
logger.info(f"Bootstrap VIP: {BOOTSTRAP_VIP}")

# ============================================================
# SQLITE HARDENED LAYER
# ============================================================

DB_PATH = "market.db"


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
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("Database error", exc_info=e)
        raise
    finally:
        conn.close()


# ============================================================
# DATABASE INIT (TABLES + SAFE MIGRATION STYLE)
# ============================================================

def init_db():
    with db_cursor() as cur:

        # VENDORS
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

        # COOLDOWNS
        cur.execute("""
        CREATE TABLE IF NOT EXISTS cooldowns (
            user_id INTEGER PRIMARY KEY,
            last_post INTEGER
        )
        """)

        # INTERESTS
        cur.execute("""
        CREATE TABLE IF NOT EXISTS interests (
            message_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY(message_id, user_id)
        )
        """)

        # AUDIT LOG
        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            username TEXT,
            timestamp INTEGER,
            metadata TEXT
        )
        """)

    logger.info("Database initialized (WAL mode active)")


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

async def global_error_handler(update, context):
    logger.exception(
        "Unhandled exception occurred",
        exc_info=context.error
    )


# ============================================================
# GRACEFUL SHUTDOWN (Railway SIGTERM safe)
# ============================================================

def setup_signal_handlers(application: Application):

    def shutdown_handler(signum, frame):
        logger.warning(f"Received shutdown signal: {signum}")
        try:
            application.stop()
        except Exception as e:
            logger.exception("Error during shutdown", exc_info=e)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)


# ============================================================
# APPLICATION FACTORY
# ============================================================

def create_application() -> Application:
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(global_error_handler)
    setup_signal_handlers(app)
    return app
    # ================= Część 2 z 6 =================
# ROLE MANAGER + COOLDOWN + AUDIT LOG + BOOTSTRAP + RATE LIMIT

import re
import time
from datetime import datetime
from typing import Optional, Tuple

# ============================================================
# USERNAME VALIDATION (ANTI-INJECTION)
# ============================================================

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{5,32}$")


def validate_username(username: str) -> bool:
    if not username:
        return False
    username = username.replace("@", "")
    return bool(USERNAME_REGEX.fullmatch(username))


# ============================================================
# AUDIT LOG
# ============================================================

def log_action(action: str, username: str, metadata: str = ""):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO audit_log(action, username, timestamp, metadata)
            VALUES (?, ?, ?, ?)
        """, (
            action,
            username,
            int(time.time()),
            metadata
        ))


# ============================================================
# ROLE MANAGER
# ============================================================

class RoleManager:

    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in ADMIN_IDS

    @staticmethod
    def get_vendor(username: str) -> Optional[Tuple]:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM vendors WHERE username=?", (username.lower(),))
            return cur.fetchone()

    @staticmethod
    def is_vendor(username: str) -> bool:
        row = RoleManager.get_vendor(username)
        return bool(row and row[1] in ("vendor", "vip"))

    @staticmethod
    def is_vip(username: str) -> bool:
        row = RoleManager.get_vendor(username)
        return bool(row and row[1] == "vip")

    @staticmethod
    def add_vendor(username: str, role: str = "vendor"):
        if not validate_username(username):
            return False

        with db_cursor() as cur:
            cur.execute("""
                INSERT OR IGNORE INTO vendors
                (username, role, added_at)
                VALUES (?, ?, ?)
            """, (
                username.lower(),
                role,
                datetime.now().strftime("%d.%m.%Y")
            ))

        log_action("add_vendor", username, role)
        return True

    @staticmethod
    def remove_vendor(username: str):
        with db_cursor() as cur:
            cur.execute("DELETE FROM vendors WHERE username=?", (username.lower(),))
        log_action("remove_vendor", username)

    @staticmethod
    def set_vip(username: str):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET role='vip', auto_enabled=0
                WHERE username=?
            """, (username.lower(),))
        log_action("make_vip", username)

    @staticmethod
    def remove_vip(username: str):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET role='vendor', auto_enabled=0
                WHERE username=?
            """, (username.lower(),))
        log_action("remove_vip", username)

    @staticmethod
    def increment_posts(username: str):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET posts = posts + 1
                WHERE username=?
            """, (username.lower(),))

    @staticmethod
    def update_last_content(username: str, content: str):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET last_content=?
                WHERE username=?
            """, (content, username.lower()))

    @staticmethod
    def get_last_content(username: str) -> Optional[str]:
        with db_cursor() as cur:
            cur.execute("""
                SELECT last_content FROM vendors
                WHERE username=?
            """, (username.lower(),))
            row = cur.fetchone()
            return row[0] if row else None

    @staticmethod
    def update_interest_total(username: str, increment: int = 1):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET interest_total = interest_total + ?
                WHERE username=?
            """, (increment, username.lower()))


# ============================================================
# COOLDOWN SYSTEM
# ============================================================

def get_last_post(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT last_post FROM cooldowns WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0


def set_last_post(user_id: int):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO cooldowns(user_id, last_post)
            VALUES(?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET last_post=excluded.last_post
        """, (user_id, int(time.time())))


def remove_cooldown(user_id: int):
    with db_cursor() as cur:
        cur.execute("DELETE FROM cooldowns WHERE user_id=?", (user_id,))


# ============================================================
# BOOTSTRAP ROLES FROM ENV
# ============================================================

def bootstrap_roles():
    for username in BOOTSTRAP_VENDORS:
        RoleManager.add_vendor(username, role="vendor")

    for username in BOOTSTRAP_VIP:
        RoleManager.add_vendor(username, role="vip")

    logger.info("Bootstrap roles completed")


# ============================================================
# RATE LIMIT (ANTI-FLOOD)
# ============================================================

USER_RATE_LIMIT = {}  # user_id -> timestamp
RATE_LIMIT_SECONDS = 2


def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    last = USER_RATE_LIMIT.get(user_id, 0)

    if now - last < RATE_LIMIT_SECONDS:
        return False

    USER_RATE_LIMIT[user_id] = now
    return True
    # ================= Część 3 z 6 =================
# ULTRA DETECTION ENGINE (HARDENED + CONTEXT SAFE)

import unicodedata
import difflib
import re

# ============================================================
# FULL CHAR MAP
# ============================================================

CHAR_MAP = {
    "a": "@",
    "c": "©",
    "e": "€",
    "i": "l",
    "s": "$",
    "t": "τ",
    "u": "Ц",
    "o": "Ø",
    "p": "₱",
    "w": "₩",
    "x": "Ж",
    "y": "¥",
    "z": "Ƶ",
}

REVERSE_MAP = {v.lower(): k for k, v in CHAR_MAP.items()}

DIGIT_TO_LETTER = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t"
}

ZERO_WIDTH_PATTERN = re.compile(r"[\u200B-\u200D\uFEFF\u2060]")

# ============================================================
# HOMOGLYPH BASIC NORMALIZATION (CYRILLIC → LATIN)
# ============================================================

HOMOGLYPH_MAP = {
    "а": "a",  # cyrylica
    "о": "o",
    "е": "e",
    "р": "p",
    "с": "c",
    "х": "x",
    "у": "y",
    "і": "i",
    "ӏ": "l"
}

# ============================================================
# ULTRA CATEGORIES
# ============================================================

ULTRA_CATEGORIES = {
    "💎": ["mewa", "ice", "kryx", "kryształ", "krystal", "crystal"],
    "🌿": ["weed", "buch", "jazz", "jaaz", "zioło", "trawa"],
    "❄": ["3cmc", "4mmc", "feta"],
    "🍫": ["hasz", "haszysz", "hash"],
    "🧂": ["koks", "koko", "kokos", "cocaine"],
    "💊": ["clony", "clonozepan", "xanax", "medikinet", "pixy", "pigle", "piguły"]
}

# Whitelist kontekstowa (zapobiega false positive)
SAFE_CONTEXT = [
    "ice cream",
    "crystal clear",
    "weed control",
    "hashmap",
    "feta cheese"
]

# ============================================================
# NORMALIZATION PIPELINE
# ============================================================

def normalize_ultra(text: str) -> str:
    text = ZERO_WIDTH_PATTERN.sub("", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    # homoglyph replace
    text = "".join(HOMOGLYPH_MAP.get(c, c) for c in text)

    # digit → letter
    for d, l in DIGIT_TO_LETTER.items():
        text = text.replace(d, l)

    # reverse char map
    text = "".join(REVERSE_MAP.get(c.lower(), c) for c in text)

    return text.lower()


# ============================================================
# FUZZY MATCH
# ============================================================

def dynamic_threshold(word: str) -> float:
    l = len(word)
    if l <= 4:
        return 0.9
    elif l <= 7:
        return 0.8
    return 0.75


def fuzzy_match(word: str, keyword: str) -> bool:
    ratio = difflib.SequenceMatcher(None, word, keyword).ratio()
    return ratio >= dynamic_threshold(keyword)


# ============================================================
# CONTEXT CHECK
# ============================================================

def is_safe_context(text: str) -> bool:
    lowered = text.lower()
    for phrase in SAFE_CONTEXT:
        if phrase in lowered:
            return True
    return False


def looks_like_listing(text: str) -> bool:
    # Minimalny próg ogłoszeniowy
    if len(text.split()) < 2:
        return False

    if re.search(r"\b(g|ml|tabs|szt)\b", text.lower()):
        return True

    if re.search(r"#(gdy|gda|sopt)", text.lower()):
        return True

    if len(text) > 15:
        return True

    return False


# ============================================================
# MAIN DETECTION FUNCTION
# ============================================================

def ultra_detect(text: str, listing_mode: bool = True):
    """
    listing_mode=True → używane tylko w WTS/WTB/WTT
    """

    if not listing_mode:
        return "📦", text

    if is_safe_context(text):
        return "📦", text

    if not looks_like_listing(text):
        return "📦", text

    normalized = normalize_ultra(text)

    tokens = re.findall(r"\b[a-z0-9]+\b", normalized)
    original_tokens = re.findall(r"\b\S+\b", text)

    detected_emoji = None
    masked_words = []
    matched_indexes = set()

    for idx, token in enumerate(tokens):
        for emoji, keywords in ULTRA_CATEGORIES.items():
            for key in keywords:
                if fuzzy_match(token, key):
                    detected_emoji = emoji
                    matched_indexes.add(idx)
                    break

    # rebuild masked text
    for idx, original in enumerate(original_tokens):
        if idx in matched_indexes:
            masked = "".join(
                CHAR_MAP.get(c.lower(), c)
                for c in original
            )
            masked_words.append(masked)
        else:
            masked_words.append(original)

    if not detected_emoji:
        detected_emoji = "📦"

    return detected_emoji, " ".join(masked_words)
    # ================= Część 4 z 6 =================
# HARDCORE PRICE DETECTOR v3 (ANTI-BYPASS + LOW FALSE POSITIVE)

import re

# ============================================================
# CURRENCY PATTERNS
# ============================================================

CURRENCY_PATTERNS = [
    r"\bzł\b",
    r"\bpln\b",
    r"\beur\b",
    r"\busd\b",
    r"€",
    r"\$"
]

# ============================================================
# WORD NUMBERS (PL + ENG BASIC)
# ============================================================

WORD_NUMBERS = [
    "sto", "dwiescie", "trzysta", "czterysta",
    "piecset", "szescset", "siedemset",
    "osiemset", "dziewiecset",
    "tysiac", "tysiace",
    "hundred", "thousand"
]

# ============================================================
# NORMALIZE (REUSE ULTRA PIPELINE)
# ============================================================

def normalize_price_text(text: str) -> str:
    return normalize_ultra(text)


# ============================================================
# EXCEPTION PRODUCTS
# ============================================================

def remove_exceptions(text: str) -> str:
    return re.sub(r"\b(3cmc|4mmc)\b", "", text)


# ============================================================
# PATTERN DETECTORS
# ============================================================

def contains_currency(text: str) -> bool:
    for pattern in CURRENCY_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def contains_price_range(text: str) -> bool:
    # 100-300
    return bool(re.search(r"\b\d{2,}\s*[-]\s*\d{2,}\b", text))


def contains_quantity_price(text: str) -> bool:
    # 1g 200
    return bool(re.search(r"\b\d+\s*(g|ml|tabs|szt)\s*\d{2,}\b", text))


def contains_spaced_number(text: str) -> bool:
    # 2 0 0
    return bool(re.search(r"\b\d\s+\d\s+\d\b", text))


def contains_broken_number(text: str) -> bool:
    # 2-0-0 / 2.0.0 / 2_0_0
    return bool(re.search(r"\b\d(?:[\-._/]\d){2,}\b", text))


def contains_word_number(text: str) -> bool:
    for word in WORD_NUMBERS:
        if word in text:
            return True
    return False


def contains_standalone_large_number(text: str) -> bool:
    """
    Blokujemy liczby >= 2 cyfry tylko jeśli:
    - nie są rokiem (np. 2024)
    - nie są procentem (99%)
    - nie są jednostką (12g)
    """
    matches = re.findall(r"\b\d{2,}\b", text)

    for m in matches:
        number = int(m)

        # dozwolone lata 1900–2099
        if 1900 <= number <= 2099:
            continue

        # jeśli po liczbie jest % → OK
        if re.search(rf"\b{m}%", text):
            continue

        # jeśli po liczbie jest jednostka → OK
        if re.search(rf"\b{m}(g|ml|tabs|szt)\b", text):
            continue

        return True

    return False


# ============================================================
# MAIN DETECTOR
# ============================================================

def hardcore_price_detect(text: str) -> bool:
    """
    True  → wykryto cenę (blokuj)
    False → OK
    """

    normalized = normalize_price_text(text)
    normalized = remove_exceptions(normalized)

    if contains_currency(normalized):
        return True

    if contains_price_range(normalized):
        return True

    if contains_quantity_price(normalized):
        return True

    if contains_spaced_number(normalized):
        return True

    if contains_broken_number(normalized):
        return True

    if contains_word_number(normalized):
        return True

    if contains_standalone_large_number(normalized):
        return True

    return False
    # ================= Część 5 z 6 =================
# FLOW + LAYOUT + ATOMIC INTEREST SYSTEM (RACE SAFE)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import html
import time

# ============================================================
# CITY DETECTION
# ============================================================

CITY_KEYWORDS = {
    "#GDY": ["gdy", "gdynia"],
    "#GDA": ["gda", "gdansk"],
    "#SOPT": ["sop", "sopot"]
}


def detect_city(text: str) -> str:
    normalized = normalize_ultra(text)
    for tag, keywords in CITY_KEYWORDS.items():
        for k in keywords:
            if k in normalized:
                return tag
    return "#3CITY"


# ============================================================
# SAFE CAPTION BUILDER
# ============================================================

def build_caption(role: str,
                  title: str,
                  username: str,
                  content: str,
                  city: str,
                  interest_count: int) -> str:

    safe_username = html.escape(username)
    safe_content = content  # content already masked, do not escape emoji

    header = f"{title} MARKET"

    if role == "vip":
        header = "✨💎 VIP MARKET 💎✨"
    elif role == "vendor":
        header = "💎 WTS MARKET 💎"

    caption = (
        f"<b>{header}</b>\n\n"
        f"<b>👤 @{safe_username}</b>\n"
        f"<b>📍 {city}</b>\n\n"
        "<code>───────────────</code>\n"
        f"{safe_content}\n"
        "<code>───────────────</code>\n\n"
        f"<b>🔥 INTEREST: {interest_count}</b>"
    )

    return caption


# ============================================================
# ATOMIC INTEREST SYSTEM
# ============================================================

async def handle_interest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id
    message_id = query.message.message_id

    if not check_rate_limit(user_id):
        await query.answer("Zwolnij 😄", show_alert=False)
        return

    # Atomic insert
    with db_cursor() as cur:
        cur.execute("""
            INSERT OR IGNORE INTO interests(message_id, user_id)
            VALUES (?, ?)
        """, (message_id, user_id))

        cur.execute("""
            SELECT COUNT(*) FROM interests WHERE message_id=?
        """, (message_id,))
        count = cur.fetchone()[0]

    # Rebuild caption safely
    original_caption = query.message.caption

    # extract role/username/city/content from message
    # rebuild minimalistically by replacing interest only
    # safer: rebuild entirely using stored message fields

    # fallback: replace only interest line safely
    new_caption = re.sub(
        r"🔥 INTEREST: \d+",
        f"🔥 INTEREST: {count}",
        original_caption
    )

    try:
        await query.message.edit_caption(
            caption=new_caption,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]
            ])
        )
    except Exception as e:
        logger.warning("Interest caption update failed")

    await query.answer("Zainteresowano!")

    # Optional: update vendor interest_total
    # (requires storing vendor mapping message→username if needed)


# ============================================================
# WTS FLOW
# ============================================================

async def handle_wts(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not check_rate_limit(user.id):
        return

    if not user.username:
        await update.message.reply_text("Ustaw username.")
        return

    username = user.username.lower()

    if not RoleManager.is_vendor(username):
        await update.message.reply_text("Tylko vendor.")
        return

    role = "vip" if RoleManager.is_vip(username) else "vendor"

    cooldown_limit = 3 * 60 * 60 if role == "vip" else 6 * 60 * 60
    last = get_last_post(user.id)

    if time.time() - last < cooldown_limit:
        await update.message.reply_text("Cooldown aktywny.")
        return

    text = update.message.text

    # PRICE CHECK
    if hardcore_price_detect(text):
        await update.message.reply_text("❌ Zakaz cen.")
        return

    # ULTRA DETECT
    emoji, masked = ultra_detect(text, listing_mode=True)

    city = detect_city(text)

    caption = build_caption(
        role=role,
        title="WTS",
        username=username,
        content=f"{emoji} {masked}",
        city=city,
        interest_count=0
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]
    ])

    msg = await context.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=WTS_TOPIC,
        photo=LOGO_URL,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

    # VIP PIN
    if role == "vip":
        try:
            await context.bot.pin_chat_message(GROUP_ID, msg.message_id)
        except Exception:
            logger.warning("Pin failed")

    RoleManager.increment_posts(username)
    RoleManager.update_last_content(username, text)
    set_last_post(user.id)

    log_action("publish_wts", username)

    # AUTO DELETE 48H
    async def delete_later(ctx):
        try:
            await ctx.bot.delete_message(GROUP_ID, msg.message_id)
        except Exception:
            logger.warning("Auto delete failed")

    context.application.job_queue.run_once(delete_later, 172800)

    await update.message.reply_text("Opublikowano.")


# ============================================================
# WTB / WTT FLOW
# ============================================================

async def handle_wtb_wtt(update: Update,
                         context: ContextTypes.DEFAULT_TYPE,
                         type_: str):

    user = update.effective_user

    if not check_rate_limit(user.id):
        return

    text = html.escape(update.message.text)

    emoji, masked = ultra_detect(text, listing_mode=True)
    city = detect_city(text)

    caption = build_caption(
        role="user",
        title=type_,
        username=user.username or "USER",
        content=f"{emoji} {masked}",
        city=city,
        interest_count=0
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]
    ])

    msg = await context.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=WTB_TOPIC if type_ == "WTB" else WTT_TOPIC,
        photo=LOGO_URL,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

    log_action(f"publish_{type_.lower()}", user.username or "USER")

    async def delete_later(ctx):
        try:
            await ctx.bot.delete_message(GROUP_ID, msg.message_id)
        except Exception:
            logger.warning("Auto delete failed")

    context.application.job_queue.run_once(delete_later, 172800)

    await update.message.reply_text("Dodano ogłoszenie.")
                             # ================= Część 6 z 6 =================
# VIP ENTERPRISE SCHEDULER + VENDOR PANEL + ADMIN + MAIN

from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import time

# ============================================================
# VIP SCHEDULER (PER USER, NO DUPLICATION)
# ============================================================

VIP_JOB_PREFIX = "vip_auto_"


def vip_job_name(username: str) -> str:
    return f"{VIP_JOB_PREFIX}{username}"


def schedule_vip(application, username: str, interval: int = 21600):
    """
    interval domyślnie 6h
    """

    job_name = vip_job_name(username)

    # sprawdź czy job istnieje
    for job in application.job_queue.jobs():
        if job.name == job_name:
            return

    async def vip_callback(ctx):
        vendor = RoleManager.get_vendor(username)
        if not vendor:
            return

        role = vendor[1]
        auto_enabled = vendor[5]
        last_content = vendor[4]

        if role != "vip" or not auto_enabled or not last_content:
            return

        emoji, masked = ultra_detect(last_content, listing_mode=True)
        city = detect_city(last_content)

        caption = build_caption(
            role="vip",
            title="WTS",
            username=username,
            content=f"{emoji} {masked}",
            city=city,
            interest_count=0
        )

        msg = await ctx.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=caption,
            parse_mode="HTML"
        )

        try:
            await ctx.bot.pin_chat_message(GROUP_ID, msg.message_id)
        except Exception:
            logger.warning("VIP pin failed")

        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET last_auto_post=?
                WHERE username=?
            """, (int(time.time()), username))

    application.job_queue.run_repeating(
        vip_callback,
        interval=interval,
        first=interval,
        name=job_name
    )

    logger.info(f"VIP scheduler started for {username}")


def remove_vip_job(application, username: str):
    job_name = vip_job_name(username)
    for job in application.job_queue.jobs():
        if job.name == job_name:
            job.schedule_removal()
            logger.info(f"VIP scheduler removed for {username}")


def restore_vip_jobs(application):
    with db_cursor() as cur:
        cur.execute("""
            SELECT username FROM vendors
            WHERE role='vip' AND auto_enabled=1
        """)
        rows = cur.fetchall()

    for (username,) in rows:
        schedule_vip(application, username)


# ============================================================
# VENDOR PANEL
# ============================================================

async def cmd_panel(update, context):
    user = update.effective_user

    if not user.username:
        return

    username = user.username.lower()

    if not RoleManager.is_vendor(username):
        return

    role = "vip" if RoleManager.is_vip(username) else "vendor"

    buttons = [
        [InlineKeyboardButton("🔁 REPOST", callback_data="REPOST")],
        [InlineKeyboardButton("✏ EDIT", callback_data="EDIT")],
        [InlineKeyboardButton("📊 STATS", callback_data="STATS")]
    ]

    if role == "vip":
        buttons.append(
            [InlineKeyboardButton("🤖 AUTO ON/OFF", callback_data="AUTO_TOGGLE")]
        )

    await update.message.reply_text(
        "Panel Vendor:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def panel_callback(update, context):
    query = update.callback_query
    user = query.from_user

    if not user.username:
        return

    username = user.username.lower()

    if not RoleManager.is_vendor(username):
        await query.answer("Brak dostępu.")
        return

    await query.answer()

    if query.data == "REPOST":
        last_content = RoleManager.get_last_content(username)
        if not last_content:
            await query.edit_message_text("Brak ostatniego ogłoszenia.")
            return

        await handle_wts(update, context)

    elif query.data == "STATS":
        vendor = RoleManager.get_vendor(username)
        posts = vendor[3]
        interest_total = vendor[7]

        text = (
            f"📊 Posty: {posts}\n"
            f"🔥 Łączne interest: {interest_total}"
        )

        await query.edit_message_text(text)

    elif query.data == "AUTO_TOGGLE":
        if not RoleManager.is_vip(username):
            return

        vendor = RoleManager.get_vendor(username)
        auto_enabled = vendor[5]

        if auto_enabled:
            with db_cursor() as cur:
                cur.execute("""
                    UPDATE vendors
                    SET auto_enabled=0
                    WHERE username=?
                """, (username,))
            remove_vip_job(context.application, username)
            await query.edit_message_text("AUTO OFF")
        else:
            with db_cursor() as cur:
                cur.execute("""
                    UPDATE vendors
                    SET auto_enabled=1
                    WHERE username=?
                """, (username,))
            schedule_vip(context.application, username)
            await query.edit_message_text("AUTO ON")


# ============================================================
# ADMIN COMMANDS
# ============================================================

async def cmd_addvendor(update, context):
    if not RoleManager.is_admin(update.effective_user.id):
        return

    if not context.args:
        return

    username = context.args[0].replace("@", "").lower()
    RoleManager.add_vendor(username)
    await update.message.reply_text("Vendor dodany.")


async def cmd_removevendor(update, context):
    if not RoleManager.is_admin(update.effective_user.id):
        return

    if not context.args:
        return

    username = context.args[0].replace("@", "").lower()
    RoleManager.remove_vendor(username)
    await update.message.reply_text("Vendor usunięty.")


async def cmd_makevip(update, context):
    if not RoleManager.is_admin(update.effective_user.id):
        return

    if not context.args:
        return

    username = context.args[0].replace("@", "").lower()
    RoleManager.set_vip(username)
    await update.message.reply_text("Nadano VIP.")


async def cmd_removevip(update, context):
    if not RoleManager.is_admin(update.effective_user.id):
        return

    if not context.args:
        return

    username = context.args[0].replace("@", "").lower()
    RoleManager.remove_vip(username)
    await update.message.reply_text("VIP usunięty.")


# ============================================================
# MAIN
# ============================================================

def main():
    init_db()
    bootstrap_roles()

    app = create_application()

    # FLOW HANDLERS
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wts))
    app.add_handler(CallbackQueryHandler(handle_interest, pattern="INTEREST"))
    app.add_handler(CallbackQueryHandler(panel_callback))

    # PANEL
    app.add_handler(CommandHandler("panel", cmd_panel))

    # ADMIN
    app.add_handler(CommandHandler("addvendor", cmd_addvendor))
    app.add_handler(CommandHandler("removevendor", cmd_removevendor))
    app.add_handler(CommandHandler("makevip", cmd_makevip))
    app.add_handler(CommandHandler("removevip", cmd_removevip))

    restore_vip_jobs(app)

    logger.info("Bot started (Production Ready)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
