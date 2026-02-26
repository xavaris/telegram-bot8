# ============================================================
# FAZA 1/15 – HARDENED INFRASTRUCTURE & FAIL-FAST ENV
# ============================================================

import os
import sys
import signal
import logging
from dataclasses import dataclass
from typing import List


# ============================================================
# LOGGING (Railway stdout only)
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("MARKET_BOT")


# ============================================================
# ENV HELPERS (FAIL FAST)
# ============================================================

def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.critical(f"Missing required ENV variable: {name}")
        raise RuntimeError(f"Missing required ENV variable: {name}")
    return value.strip()


def _require_int_env(name: str) -> int:
    raw = _require_env(name)
    try:
        return int(raw)
    except ValueError:
        logger.critical(f"ENV variable {name} must be integer")
        raise RuntimeError(f"ENV variable {name} must be integer")


def _optional_list_env(name: str) -> List[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


# ============================================================
# CONFIG DATACLASS
# ============================================================

@dataclass(frozen=True)
class Config:
    token: str
    group_id: int
    wts_topic: int
    wtb_topic: int
    wtt_topic: int
    logo_url: str
    bot_username: str
    admin_ids: List[int]
    bootstrap_vendors: List[str]
    bootstrap_vip: List[str]


# ============================================================
# LOAD CONFIG
# ============================================================

def load_config() -> Config:
    token = _require_env("KEY")
    group_id = _require_int_env("GROUP_ID")
    wts_topic = _require_int_env("WTS")
    wtb_topic = _require_int_env("WTB")
    wtt_topic = _require_int_env("WTT")
    logo_url = _require_env("LOGO_URL")
    bot_username = _require_env("BOT_USERNAME")

    raw_admins = _optional_list_env("ADMIN_IDS")
    admin_ids: List[int] = []

    for entry in raw_admins:
        try:
            admin_ids.append(int(entry))
        except ValueError:
            raise RuntimeError("ADMIN_IDS must contain only integers")

    bootstrap_vendors = [v.lower() for v in _optional_list_env("VENDORS")]
    bootstrap_vip = [v.lower() for v in _optional_list_env("VIP_VENDORS")]

    # --- sanity checks ---
    if len(token) < 30:
        raise RuntimeError("Invalid Telegram bot token")

    if not str(group_id).startswith("-100"):
        raise RuntimeError("GROUP_ID must start with -100")

    logger.info("ENV validated successfully")

    return Config(
        token=token,
        group_id=group_id,
        wts_topic=wts_topic,
        wtb_topic=wtb_topic,
        wtt_topic=wtt_topic,
        logo_url=logo_url,
        bot_username=bot_username,
        admin_ids=admin_ids,
        bootstrap_vendors=bootstrap_vendors,
        bootstrap_vip=bootstrap_vip,
    )


# ============================================================
# GRACEFUL SHUTDOWN
# ============================================================

def setup_signal_handlers(stop_callback):

    def shutdown_handler(signum, frame):
        logger.warning(f"Shutdown signal received: {signum}")
        try:
            stop_callback()
        except Exception:
            logger.exception("Shutdown error")

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)


# ============================================================
# INFRA ENTRYPOINT
# ============================================================

def initialize_infrastructure() -> Config:
    config = load_config()
    logger.info("Infrastructure initialized (Phase 1 ready)")
    return config
    # ============================================================
# FAZA 2/15 – HARDENED SQLITE WAL LAYER
# ============================================================

import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "/data/market.db"


# ============================================================
# CONNECTION FACTORY (WAL + HARDENING)
# ============================================================

def create_connection():
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        isolation_level=None,  # autocommit off handled manually
    )

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA temp_store=MEMORY;")

    return conn


# ============================================================
# ATOMIC CURSOR CONTEXT
# ============================================================

@contextmanager
def db_cursor():
    conn = create_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN")
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Database transaction failed")
        raise
    finally:
        cursor.close()
        conn.close()


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_database():

    os.makedirs("/data", exist_ok=True)

    with db_cursor() as cur:

        # Vendors
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            added_at INTEGER,
            posts INTEGER DEFAULT 0,
            last_content TEXT,
            auto_enabled INTEGER DEFAULT 0,
            last_auto_post INTEGER DEFAULT 0,
            interest_total INTEGER DEFAULT 0
        )
        """)

        # Cooldowns
        cur.execute("""
        CREATE TABLE IF NOT EXISTS cooldowns (
            user_id INTEGER PRIMARY KEY,
            last_post INTEGER
        )
        """)

        # Interests
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

        # Indexes for performance
        cur.execute("CREATE INDEX IF NOT EXISTS idx_vendors_role ON vendors(role);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cooldowns_user ON cooldowns(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_interests_message ON interests(message_id);")

    logger.info("Database initialized (WAL + indexes ready)")


# ============================================================
# INTEGRITY CHECK
# ============================================================

def verify_database():
    with db_cursor() as cur:
        cur.execute("PRAGMA integrity_check;")
        result = cur.fetchone()
        if result[0] != "ok":
            raise RuntimeError("Database integrity check failed")

    logger.info("Database integrity verified")
    # ============================================================
# FAZA 3/15 – ROLE ENGINE + BOOTSTRAP SYSTEM
# ============================================================

def normalize_username(username: str) -> str:
    if not username:
        return ""
    return username.strip().lower()


class RoleManager:

    # ================= ADMIN =================

    @staticmethod
    def is_admin(user_id: int, config) -> bool:
        return user_id in config.admin_ids


    # ================= VENDOR FETCH =================

    @staticmethod
    def get_vendor(username: str):
        username = normalize_username(username)
        if not username:
            return None

        with db_cursor() as cur:
            cur.execute(
                "SELECT * FROM vendors WHERE username=?",
                (username,)
            )
            return cur.fetchone()


    @staticmethod
    def is_vendor(username: str) -> bool:
        vendor = RoleManager.get_vendor(username)
        return bool(vendor and vendor[1] in ("vendor", "vip"))


    @staticmethod
    def is_vip(username: str) -> bool:
        vendor = RoleManager.get_vendor(username)
        return bool(vendor and vendor[1] == "vip")


    # ================= ADD / REMOVE =================

    @staticmethod
    def add_vendor(username: str, role: str = "vendor"):
        username = normalize_username(username)
        if not username:
            return

        with db_cursor() as cur:
            cur.execute("""
                INSERT OR IGNORE INTO vendors(
                    username,
                    role,
                    added_at
                )
                VALUES (?, ?, ?)
            """, (
                username,
                role,
                int(time.time())
            ))


    @staticmethod
    def remove_vendor(username: str):
        username = normalize_username(username)
        if not username:
            return

        with db_cursor() as cur:
            cur.execute(
                "DELETE FROM vendors WHERE username=?",
                (username,)
            )


    @staticmethod
    def set_vip(username: str):
        username = normalize_username(username)
        if not username:
            return

        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET role='vip'
                WHERE username=?
            """, (username,))


    @staticmethod
    def remove_vip(username: str):
        username = normalize_username(username)
        if not username:
            return

        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET role='vendor',
                    auto_enabled=0
                WHERE username=?
            """, (username,))


# ============================================================
# BOOTSTRAP SYSTEM
# ============================================================

def bootstrap_roles(config):

    # Vendors
    for username in config.bootstrap_vendors:
        RoleManager.add_vendor(username, "vendor")

    # VIP
    for username in config.bootstrap_vip:
        RoleManager.add_vendor(username, "vip")

    logger.info("Bootstrap roles applied")
    # ============================================================
# FAZA 4/15 – PRODUCTION STATE MACHINE (FSM ENGINE)
# ============================================================

def init_state(context):
    """
    Inicjalizuje strukturę FSM tylko raz.
    """
    if "fsm_initialized" not in context.user_data:
        context.user_data["mode"] = None
        context.user_data["wts_total"] = 0
        context.user_data["wts_products"] = []
        context.user_data["pending_text"] = None
        context.user_data["city"] = None
        context.user_data["admin_action"] = None
        context.user_data["edit_mode"] = False
        context.user_data["fsm_initialized"] = True


def reset_state(context):
    """
    Czyści TYLKO dane flow.
    Nie usuwa flagi inicjalizacji.
    """
    context.user_data["mode"] = None
    context.user_data["wts_total"] = 0
    context.user_data["wts_products"] = []
    context.user_data["pending_text"] = None
    context.user_data["city"] = None
    context.user_data["admin_action"] = None
    context.user_data["edit_mode"] = False


# ============================================================
# MODE CONTROL
# ============================================================

def set_mode(context, mode: str):
    context.user_data["mode"] = mode


def get_mode(context):
    return context.user_data.get("mode")


# ============================================================
# WTS FLOW CONTROL
# ============================================================

def set_wts_count(context, count: int):

    try:
        count = int(count)
    except Exception:
        count = 1

    if count < 1:
        count = 1

    if count > 10:
        count = 10

    context.user_data["wts_total"] = count
    context.user_data["wts_products"] = []


def add_wts_product(context, product: str):

    products = context.user_data.get("wts_products")

    if products is None:
        context.user_data["wts_products"] = []
        products = context.user_data["wts_products"]

    products.append(product)


def is_wts_complete(context) -> bool:

    total = context.user_data.get("wts_total", 0)
    products = context.user_data.get("wts_products", [])

    try:
        total = int(total)
    except Exception:
        return False

    if total <= 0:
        return False

    return len(products) >= total


def get_next_wts_step(context) -> int:
    products = context.user_data.get("wts_products", [])
    return len(products) + 1


# ============================================================
# WTB / WTT TEXT STORAGE
# ============================================================

def store_pending_text(context, text: str):
    context.user_data["pending_text"] = text


def get_pending_text(context):
    return context.user_data.get("pending_text")


# ============================================================
# EDIT MODE CONTROL
# ============================================================

def enable_edit_mode(context):
    context.user_data["edit_mode"] = True


def disable_edit_mode(context):
    context.user_data["edit_mode"] = False


def is_edit_mode(context) -> bool:
    return context.user_data.get("edit_mode", False)


# ============================================================
# ADMIN FLOW CONTROL
# ============================================================

def set_admin_action(context, action: str):
    context.user_data["admin_action"] = action


def get_admin_action(context):
    return context.user_data.get("admin_action")


def clear_admin_action(context):
    context.user_data["admin_action"] = None
    # ============================================================
# FAZA 5/15 – ULTRA DETECTION ENGINE (HARDENED)
# ============================================================

import re
import unicodedata
import difflib


# ============================================================
# ZERO WIDTH + NORMALIZATION
# ============================================================

ZERO_WIDTH_PATTERN = re.compile(r"[\u200B-\u200D\uFEFF\u2060]")


def normalize_unicode(text: str) -> str:
    if not text:
        return ""
    text = ZERO_WIDTH_PATTERN.sub("", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


# ============================================================
# HOMOGLYPH NORMALIZATION
# ============================================================

HOMOGLYPH_MAP = {
    "а": "a", "о": "o", "е": "e",
    "р": "p", "с": "c", "х": "x",
    "у": "y", "і": "i", "ӏ": "l"
}


def normalize_homoglyphs(text: str) -> str:
    return "".join(HOMOGLYPH_MAP.get(c, c) for c in text)


# ============================================================
# DIGIT SPOOF NORMALIZATION
# ============================================================

DIGIT_TO_LETTER = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t"
}


def normalize_digits(text: str) -> str:
    for digit, letter in DIGIT_TO_LETTER.items():
        text = text.replace(digit, letter)
    return text


# ============================================================
# CATEGORY MAP
# ============================================================

ULTRA_CATEGORIES = {
    "💎": ["mewa", "kryx", "kryształ", "krystal", "crystal"],
    "🌿": ["weed", "buch", "ziolo", "trawa"],
    "❄": ["3cmc", "4mmc", "feta"],
    "🍫": ["hasz", "hash", "haszysz"],
    "🧂": ["koks", "kokaina", "cocaine"],
    "💊": ["xanax", "clony", "pixy", "medikinet"]
}

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

def normalize_for_detection(text: str) -> str:
    text = normalize_unicode(text)
    text = normalize_homoglyphs(text)
    text = normalize_digits(text)
    return text.lower()


# ============================================================
# FUZZY MATCH WITH DYNAMIC THRESHOLD
# ============================================================

def dynamic_threshold(word: str) -> float:
    length = len(word)
    if length <= 4:
        return 0.9
    if length <= 7:
        return 0.8
    return 0.75


def fuzzy_match(word: str, keyword: str) -> bool:
    ratio = difflib.SequenceMatcher(None, word, keyword).ratio()
    return ratio >= dynamic_threshold(keyword)


# ============================================================
# ULTRA DETECT MAIN
# ============================================================

def ultra_detect(text: str, listing_mode: bool = True):

    if not text:
        return "📦", ""

    if not listing_mode:
        return "📦", text

    lowered = text.lower()

    for safe_phrase in SAFE_CONTEXT:
        if safe_phrase in lowered:
            return "📦", text

    normalized = normalize_for_detection(text)

    tokens = re.findall(r"\b[a-z0-9]+\b", normalized)
    original_tokens = re.findall(r"\b\S+\b", text)

    matched_indexes = set()
    detected_emoji = None

    for idx, token in enumerate(tokens):
        for emoji, keywords in ULTRA_CATEGORIES.items():
            for keyword in keywords:
                if fuzzy_match(token, keyword):
                    matched_indexes.add(idx)
                    detected_emoji = emoji
                    break

    masked_tokens = []

    for idx, original in enumerate(original_tokens):
        if idx in matched_indexes:
            masked = "".join(
                "*" if c.isalnum() else c
                for c in original
            )
            masked_tokens.append(masked)
        else:
            masked_tokens.append(original)

    if not detected_emoji:
        detected_emoji = "📦"

    return detected_emoji, " ".join(masked_tokens)
    # ============================================================
# FAZA 6/15 – HARDCORE PRICE DETECTOR (ANTI-BYPASS)
# ============================================================

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
    "tysiac", "tysiace",
    "hundred", "thousand"
]


def hardcore_price_detect(text: str) -> bool:

    if not text:
        return False

    normalized = normalize_for_detection(text)

    # Ignore chemical names
    normalized = re.sub(r"\b(3cmc|4mmc)\b", "", normalized)

    # Direct currency match
    for pattern in CURRENCY_PATTERNS:
        if re.search(pattern, normalized):
            return True

    # Digit separated by spaces (1 0 0)
    if re.search(r"\b\d\s+\d\s+\d\b", normalized):
        return True

    # Range patterns (100-200, 100/200, 100_200)
    if re.search(r"\b\d{2,}\s*[-_/]\s*\d{2,}\b", normalized):
        return True

    # Continuous number with separators (10.00, 10,00)
    if re.search(r"\b\d+[.,]\d+\b", normalized):
        return True

    # Word numbers
    for word in WORD_NUMBERS:
        if word in normalized:
            return True

    # Standalone numbers >= 2 digits
    numbers = re.findall(r"\b\d{2,}\b", normalized)

    for number_str in numbers:
        number = int(number_str)

        # Ignore years
        if 1900 <= number <= 2099:
            continue

        # Ignore grams / ml / tabs
        if re.search(rf"\b{number_str}(g|ml|tabs|szt)\b", normalized):
            continue

        # Ignore percentages
        if re.search(rf"\b{number_str}%\b", normalized):
            continue

        return True

    return False
    # ============================================================
# FAZA 7/15 – CALLBACK ROUTER (DETERMINISTIC)
# ============================================================

async def callback_router(update, context):

if check_callback_rate_limit(user.id):
    return
    
    if not update.callback_query:
        return

    query = update.callback_query
    user = query.from_user

    await query.answer()

    init_state(context)

    data = query.data

    # ========================================================
    # MENU RESET
    # ========================================================

    if data == "MENU":
        reset_state(context)
        await query.edit_message_text(
            "Menu:",
            reply_markup=build_main_menu(user)
        )
        return

    # ========================================================
    # WTS START
    # ========================================================

    if data == "WTS":

        if not user.username:
            await query.edit_message_text("Ustaw username w Telegramie.")
            return

        if not RoleManager.is_vendor(user.username):
            await query.edit_message_text("Brak dostępu.")
            return

        set_mode(context, "WTS_SELECT_COUNT")

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

    # ========================================================
    # WTS COUNT SELECTED
    # ========================================================

    if data.startswith("WTS_COUNT_"):

        try:
            count = int(data.split("_")[2])
        except Exception:
            count = 1

        set_wts_count(context, count)
        set_mode(context, "WTS_INPUT")

        await query.edit_message_text(
            "Podaj produkt 1:"
        )
        return

    # ========================================================
    # WTB START
    # ========================================================

    if data == "WTB":

        set_mode(context, "WTB")

        await query.edit_message_text(
            "Wpisz treść ogłoszenia WTB:"
        )
        return

    # ========================================================
    # WTT START
    # ========================================================

    if data == "WTT":

        set_mode(context, "WTT")

        await query.edit_message_text(
            "Wpisz treść ogłoszenia WTT:"
        )
        return
        # ============================================================
# FAZA 8/15 – MESSAGE ROUTER (FINAL FSM LOGIC)
# ============================================================

async def message_router(update, context):

    if not update.message:
        return

    init_state(context)

    text = update.message.text.strip()
    mode = get_mode(context)

    # ========================================================
    # ========================= WTS ==========================
    # ========================================================

    if mode == "WTS_INPUT":

        if hardcore_price_detect(text):
            await update.message.reply_text("❌ Zakaz cen.")
            return

        emoji, masked = ultra_detect(text, listing_mode=True)
        add_wts_product(context, f"{emoji} {masked}")

        if not is_wts_complete(context):
            next_step = get_next_wts_step(context)
            await update.message.reply_text(f"Podaj produkt {next_step}:")
            return

        set_mode(context, "WTS_CITY")
        await update.message.reply_text("Podaj miasto (GDA, GDY, SOP):")
        return


    if mode == "WTS_CITY":

        city = text.upper()

        if city not in ["GDA", "GDY", "SOP"]:
            await update.message.reply_text("Podaj poprawne miasto (GDA, GDY, SOP).")
            return

        context.user_data["city"] = city

        try:
            await publish_wts(update, context)
            await update.message.reply_text("Opublikowano.")
        except Exception:
            logger.exception("WTS publish error")
            await update.message.reply_text("Błąd publikacji.")

        reset_state(context)
        return


    # ========================================================
    # ====================== WTB / WTT =======================
    # ========================================================

    if mode in ["WTB", "WTT"]:

        if hardcore_price_detect(text):
            await update.message.reply_text("❌ Zakaz cen.")
            return

        if check_wtx_rate_limit(update.effective_user.id):
    await update.message.reply_text("Odczekaj chwilę przed kolejnym ogłoszeniem.")
    return

        store_pending_text(context, text)
        set_mode(context, "WTX_CITY")

        await update.message.reply_text("Podaj miasto (GDA, GDY, SOP):")
        return


    if mode == "WTX_CITY":

        city = text.upper()

        if city not in ["GDA", "GDY", "SOP"]:
            await update.message.reply_text("Podaj poprawne miasto (GDA, GDY, SOP).")
            return

        context.user_data["city"] = city

        try:
            await publish_wtx(update, context)
            await update.message.reply_text("Opublikowano.")
        except Exception:
            logger.exception("WTX publish error")
            await update.message.reply_text("Błąd publikacji.")

        reset_state(context)
        return
        # ============================================================
# FAZA 9/15 – PUBLISH ENGINE (FORUM SAFE)
# ============================================================

async def safe_send_photo(context, chat_id, topic_id, caption):

    if not caption:
        raise RuntimeError("Empty caption")

    if not LOGO_URL:
        raise RuntimeError("LOGO_URL not configured")

    try:
        return await context.bot.send_photo(
            chat_id=chat_id,
            message_thread_id=topic_id,
            photo=LOGO_URL,
            caption=caption,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception("Telegram send_photo failed")
        raise e


# ============================================================
# WTS PUBLISH
# ============================================================

async def publish_wts(update, context):

    user = update.effective_user

    if not user or not user.username:
        raise RuntimeError("User has no username")

    products = context.user_data.get("wts_products", [])
    city = context.user_data.get("city")

    if not products:
        raise RuntimeError("No products to publish")

    if not city:
        raise RuntimeError("City missing")

    products_text = "\n".join(products)

    caption = (
        f"<b>💎 WTS MARKET</b>\n\n"
        f"<b>@{user.username}</b>\n"
        f"<b>📍 {city}</b>\n\n"
        f"{products_text}"
    )

    await safe_send_photo(
        context,
        GROUP_ID,
        WTS_TOPIC,
        caption
    )


# ============================================================
# WTB / WTT PUBLISH
# ============================================================

async def publish_wtx(update, context):

    user = update.effective_user

    if not user or not user.username:
        raise RuntimeError("User has no username")

    text = get_pending_text(context)
    city = context.user_data.get("city")
    mode = get_mode(context)

    if not text:
        raise RuntimeError("No text to publish")

    if not city:
        raise RuntimeError("City missing")

    topic = WTB_TOPIC if mode == "WTB" else WTT_TOPIC

    caption = (
        f"<b>{mode} MARKET</b>\n\n"
        f"<b>@{user.username}</b>\n"
        f"<b>📍 {city}</b>\n\n"
        f"{text}"
    )

    await safe_send_photo(
        context,
        GROUP_ID,
        topic,
        caption
    )
    # ============================================================
# FAZA 10/15 – INTEREST ENGINE (ATOMIC & SAFE)
# ============================================================

import re


async def handle_interest(update, context):

    if not update.callback_query:
        return

    query = update.callback_query
    user = query.from_user
    message = query.message

    await query.answer()

    if not message or not message.caption:
        return

    caption = message.caption

    # Extract vendor username from caption
    match = re.search(r"<b>@([a-zA-Z0-9_]+)</b>", caption)
    if not match:
        return

    vendor_username = match.group(1).lower()

    try:
        with db_cursor() as cur:

            # Try insert new interest (atomic)
            cur.execute("""
                INSERT OR IGNORE INTO interests(
                    message_id,
                    user_id,
                    vendor_username
                )
                VALUES (?, ?, ?)
            """, (
                message.message_id,
                user.id,
                vendor_username
            ))

            # Check if row inserted
            if cur.rowcount == 1:
                # Only increment if new interest
                cur.execute("""
                    UPDATE vendors
                    SET interest_total = interest_total + 1
                    WHERE username=?
                """, (vendor_username,))

            # Get real interest count
            cur.execute("""
                SELECT COUNT(*) FROM interests
                WHERE message_id=?
            """, (message.message_id,))
            count = cur.fetchone()[0]

        # Update caption safely
        new_caption = re.sub(
            r"🔥 INTEREST:\s*\d+",
            f"🔥 INTEREST: {count}",
            caption
        )

        try:
            await message.edit_caption(
                caption=new_caption,
                parse_mode="HTML",
                reply_markup=message.reply_markup
            )
        except Exception:
            logger.exception("Failed to edit interest caption")

    except Exception:
        logger.exception("Interest transaction failed")
        # ============================================================
# FAZA 11/15 – VIP AUTO SYSTEM (RESILIENT)
# ============================================================

VIP_JOB_PREFIX = "vip_auto_"


def vip_job_name(username: str) -> str:
    return f"{VIP_JOB_PREFIX}{username}"


def remove_vip_job(application, username: str):

    name = vip_job_name(username)

    for job in application.job_queue.jobs():
        if job.name == name:
            job.schedule_removal()


def schedule_vip_job(application, username: str, interval: int = 21600):

    name = vip_job_name(username)

    # Prevent duplicate jobs
    for job in application.job_queue.jobs():
        if job.name == name:
            return

    async def vip_callback(context):

        vendor = RoleManager.get_vendor(username)
        if not vendor:
            return

        role = vendor[1]
        auto_enabled = vendor[5]
        last_content = vendor[4]

        if role != "vip":
            return

        if not auto_enabled:
            return

        if not last_content:
            return

        try:
            # Reset interest counter inside caption
            caption = re.sub(
                r"🔥 INTEREST:\s*\d+",
                "🔥 INTEREST: 0",
                last_content
            )

            msg = await context.bot.send_photo(
                chat_id=GROUP_ID,
                message_thread_id=WTS_TOPIC,
                photo=LOGO_URL,
                caption=caption,
                parse_mode="HTML"
            )

            try:
                await context.bot.pin_chat_message(
                    GROUP_ID,
                    msg.message_id
                )
            except Exception:
                logger.warning("Pin failed (non-critical)")

            with db_cursor() as cur:
                cur.execute("""
                    UPDATE vendors
                    SET last_auto_post=?
                    WHERE username=?
                """, (int(time.time()), username))

        except Exception:
            logger.exception("VIP auto post failed")

    application.job_queue.run_repeating(
        vip_callback,
        interval=interval,
        first=interval,
        name=name
    )


def restore_vip_jobs(application):

    with db_cursor() as cur:
        cur.execute("""
            SELECT username
            FROM vendors
            WHERE role='vip'
            AND auto_enabled=1
        """)
        rows = cur.fetchall()

    for (username,) in rows:
        schedule_vip_job(application, username)

    logger.info("VIP auto jobs restored")
    # ============================================================
# FAZA 12/15 – ADMIN ENGINE (COMMANDS + PANEL)
# ============================================================

# =========================
# ADMIN COMMANDS
# =========================

async def cmd_addvendor(update, context):
    user = update.effective_user

    if not RoleManager.is_admin(user.id, CONFIG):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /addvendor username")
        return

    username = normalize_username(context.args[0])
    RoleManager.add_vendor(username, "vendor")

    log_admin_action("ADD_VENDOR", username)

    await update.message.reply_text(f"Dodano vendora: @{username}")


async def cmd_removevendor(update, context):
    user = update.effective_user

    if not RoleManager.is_admin(user.id, CONFIG):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /removevendor username")
        return

    username = normalize_username(context.args[0])
    RoleManager.remove_vendor(username)

    log_admin_action("REMOVE_VENDOR", username)

    await update.message.reply_text(f"Usunięto vendora: @{username}")


async def cmd_makevip(update, context):
    user = update.effective_user

    if not RoleManager.is_admin(user.id, CONFIG):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /makevip username")
        return

    username = normalize_username(context.args[0])
    RoleManager.set_vip(username)

    log_admin_action("MAKE_VIP", username)

    await update.message.reply_text(f"Ustawiono VIP: @{username}")


async def cmd_removevip(update, context):
    user = update.effective_user

    if not RoleManager.is_admin(user.id, CONFIG):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /removevip username")
        return

    username = normalize_username(context.args[0])

    RoleManager.remove_vip(username)
    remove_vip_job(context.application, username)

    log_admin_action("REMOVE_VIP", username)

    await update.message.reply_text(f"Odebrano VIP: @{username}")


async def cmd_resetcooldown(update, context):
    user = update.effective_user

    if not RoleManager.is_admin(user.id, CONFIG):
        return

    with db_cursor() as cur:
        cur.execute("DELETE FROM cooldowns")

    log_admin_action("RESET_COOLDOWN", "ALL")

    await update.message.reply_text("Cooldowny wyczyszczone.")


# ============================================================
# ADMIN PANEL CALLBACK
# ============================================================

async def admin_panel(update, context):

    query = update.callback_query
    user = query.from_user

    await query.answer()

    if not RoleManager.is_admin(user.id, CONFIG):
        await query.edit_message_text("Brak dostępu.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ ADD VENDOR", callback_data="ADMIN_ADD")],
        [InlineKeyboardButton("➖ REMOVE VENDOR", callback_data="ADMIN_REMOVE")],
        [InlineKeyboardButton("👑 MAKE VIP", callback_data="ADMIN_MAKEVIP")],
        [InlineKeyboardButton("❌ REMOVE VIP", callback_data="ADMIN_REMVIP")],
        [InlineKeyboardButton("🔄 RESET COOLDOWN", callback_data="ADMIN_RMCD")],
        [InlineKeyboardButton("⬅ MENU", callback_data="MENU")],
    ]

    await query.edit_message_text(
        "Admin panel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_callback(update, context):

    query = update.callback_query
    user = query.from_user

    await query.answer()

    if not RoleManager.is_admin(user.id, CONFIG):
        return

    action = query.data
    set_admin_action(context, action)

    await query.edit_message_text("Podaj @username:")


async def admin_text_handler(update, context):

    action = get_admin_action(context)
    if not action:
        return

    username = normalize_username(update.message.text.replace("@", ""))

    if not username:
        clear_admin_action(context)
        return

    if action == "ADMIN_ADD":
        RoleManager.add_vendor(username)

    elif action == "ADMIN_REMOVE":
        RoleManager.remove_vendor(username)

    elif action == "ADMIN_MAKEVIP":
        RoleManager.set_vip(username)

    elif action == "ADMIN_REMVIP":
        RoleManager.remove_vip(username)
        remove_vip_job(context.application, username)

    elif action == "ADMIN_RMCD":
        with db_cursor() as cur:
            cur.execute("DELETE FROM cooldowns")

    log_admin_action(action, username)

    clear_admin_action(context)

    await update.message.reply_text("Wykonano.")


# ============================================================
# ADMIN AUDIT LOG
# ============================================================

def log_admin_action(action: str, username: str):

    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO audit_log(
                action,
                username,
                timestamp,
                metadata
            )
            VALUES (?, ?, ?, ?)
        """, (
            action,
            username,
            int(time.time()),
            ""
        ))
        # ============================================================
# FAZA 14/15 – APPLICATION FACTORY + HANDLER ORDER
# ============================================================

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)


async def global_error_handler(update, context):
    logger.exception("Unhandled exception", exc_info=context.error)


def create_application(config):

    app = Application.builder().token(config.token).build()

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    app.add_error_handler(global_error_handler)

    # ========================================================
    # COMMANDS
    # ========================================================

    app.add_handler(CommandHandler("addvendor", cmd_addvendor))
    app.add_handler(CommandHandler("removevendor", cmd_removevendor))
    app.add_handler(CommandHandler("makevip", cmd_makevip))
    app.add_handler(CommandHandler("removevip", cmd_removevip))
    app.add_handler(CommandHandler("resetcooldown", cmd_resetcooldown))

    # ========================================================
    # CALLBACKS (SPECIFIC → GENERAL)
    # ========================================================

    app.add_handler(CallbackQueryHandler(handle_interest, pattern="^INTEREST$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^ADMIN$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^ADMIN_"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^PANEL_"))
    app.add_handler(CallbackQueryHandler(callback_router))

    # ========================================================
    # MESSAGE HANDLERS
    # ========================================================

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    return app


# ============================================================
# MAIN ENTRYPOINT
# ============================================================

def main():

    global CONFIG
    CONFIG = initialize_infrastructure()

    init_database()
    verify_database()

    bootstrap_roles(CONFIG)

    app = create_application(CONFIG)

    # Restore VIP auto jobs
    restore_vip_jobs(app)

    # Graceful shutdown
    setup_signal_handlers(app.stop)

    logger.info("MARKET BOT – PHASE 14 INITIALIZED")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
