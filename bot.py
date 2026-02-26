# ============================================================
# FAZA 1/15 – INFRASTRUCTURE CORE (RAILWAY HARDENED)
# ============================================================

import os
import sys
import signal
import logging
import sqlite3
from contextlib import contextmanager
from typing import Optional

from telegram.ext import Application


# =========================
# LOGGING (stdout only)
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout
)

logger = logging.getLogger("MARKET_BOT")


# =========================
# ENV VALIDATION (FAIL FAST)
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

ADMIN_IDS = [
    int(x.strip())
    for x in require_env("ADMIN_IDS").split(",")
    if x.strip().isdigit()
]


# =========================
# DATABASE CONFIG (WAL + PERSISTENT)
# =========================

DB_DIR = "/data"
DB_PATH = os.path.join(DB_DIR, "market.db")


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


def ensure_data_dir():
    os.makedirs(DB_DIR, exist_ok=True)


# =========================
# GRACEFUL SHUTDOWN
# =========================

def setup_signal_handlers(application: Application):

    def shutdown_handler(signum, frame):
        logger.warning(f"Shutdown signal received: {signum}")
        try:
            application.stop()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)
    # ============================================================
# FAZA 2/15 – DATABASE SCHEMA & ATOMIC OPERATIONS
# ============================================================

import time


# =========================
# INIT DATABASE
# =========================

def init_db():

    ensure_data_dir()

    with db_cursor() as cur:

        # ===== VENDORS =====
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

        # ===== VENDOR COOLDOWN =====
        cur.execute("""
        CREATE TABLE IF NOT EXISTS cooldowns (
            user_id INTEGER PRIMARY KEY,
            last_post INTEGER
        )
        """)

        # ===== WTB/WTT COOLDOWN =====
        cur.execute("""
        CREATE TABLE IF NOT EXISTS wtb_wtt_cooldowns (
            user_id INTEGER PRIMARY KEY,
            last_post INTEGER
        )
        """)

        # ===== AUDIT LOG =====
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
# VENDOR POST UPDATE (ATOMIC)
# =========================

def update_vendor_post(username: str, content: str):

    with db_cursor() as cur:
        cur.execute("""
            UPDATE vendors
            SET posts = posts + 1,
                last_content = ?
            WHERE username = ?
        """, (content, username))


# =========================
# COOLDOWN HELPERS
# =========================

def get_vendor_last_post(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute(
            "SELECT last_post FROM cooldowns WHERE user_id=?",
            (user_id,)
        )
        row = cur.fetchone()
        return row[0] if row else 0


def set_vendor_last_post(user_id: int):
    now = int(time.time())
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO cooldowns(user_id, last_post)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET last_post=excluded.last_post
        """, (user_id, now))


def get_wtb_wtt_last(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute(
            "SELECT last_post FROM wtb_wtt_cooldowns WHERE user_id=?",
            (user_id,)
        )
        row = cur.fetchone()
        return row[0] if row else 0


def set_wtb_wtt_last(user_id: int):
    now = int(time.time())
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO wtb_wtt_cooldowns(user_id, last_post)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET last_post=excluded.last_post
        """, (user_id, now))


# =========================
# BOOTSTRAP ROLES
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

    with db_cursor() as cur:
        for u in BOOTSTRAP_VENDORS:
            cur.execute("""
                INSERT OR IGNORE INTO vendors(username, role, added_at)
                VALUES (?, 'vendor', ?)
            """, (u, time.strftime("%d.%m.%Y")))

        for u in BOOTSTRAP_VIP:
            cur.execute("""
                INSERT OR IGNORE INTO vendors(username, role, added_at)
                VALUES (?, 'vip', ?)
            """, (u, time.strftime("%d.%m.%Y")))

    logger.info("Bootstrap roles loaded")
# ============================================================
# FAZA 3/15 – STATE ENGINE (FINAL STABLE VERSION)
# ============================================================

def init_state(context):
    """
    Inicjalizuje state tylko jeśli nie istnieje.
    NIE nadpisuje istniejących danych.
    """
    if "state_initialized" not in context.user_data:
        context.user_data["mode"] = None
        context.user_data["wts_total"] = 0
        context.user_data["wts_products"] = []
        context.user_data["pending_text"] = None
        context.user_data["city"] = None
        context.user_data["admin_action"] = None
        context.user_data["edit_mode"] = False
        context.user_data["state_initialized"] = True


def reset_state(context):
    context.user_data["mode"] = None
    context.user_data["wts_total"] = 0
    context.user_data["wts_products"] = []
    context.user_data["pending_text"] = None
    context.user_data["city"] = None
    context.user_data["admin_action"] = None
    context.user_data["edit_mode"] = False


# =========================
# MODE CONTROL
# =========================

def set_mode(context, mode: str):
    context.user_data["mode"] = mode


def get_mode(context):
    return context.user_data.get("mode")


# =========================
# WTS FLOW CONTROL
# =========================

def set_wts_count(context, count: int):
    context.user_data["wts_total"] = int(count)
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

    return len(products) >= total and total > 0


def get_next_wts_step(context) -> int:
    products = context.user_data.get("wts_products", [])
    return len(products) + 1


# =========================
# PENDING TEXT (WTB/WTT)
# =========================

def store_pending_text(context, text: str):
    context.user_data["pending_text"] = text


def get_pending_text(context):
    return context.user_data.get("pending_text")


# =========================
# EDIT MODE
# =========================

def enable_edit_mode(context):
    context.user_data["edit_mode"] = True


def disable_edit_mode(context):
    context.user_data["edit_mode"] = False


def is_edit_mode(context) -> bool:
    return context.user_data.get("edit_mode", False)


# =========================
# ADMIN ACTION
# =========================

def set_admin_action(context, action: str):
    context.user_data["admin_action"] = action


def get_admin_action(context):
    return context.user_data.get("admin_action")


def clear_admin_action(context):
    context.user_data["admin_action"] = None
    
    # ============================================================
# FAZA 4/15 – ROLE & PERMISSION ENGINE
# ============================================================

# =========================
# ROLE MANAGER
# =========================

class RoleManager:

    @staticmethod
    def normalize_username(username: Optional[str]) -> Optional[str]:
        if not username:
            return None
        return username.lower().strip()

    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in ADMIN_IDS

    @staticmethod
    def get_vendor(username: Optional[str]):
        username = RoleManager.normalize_username(username)
        if not username:
            return None

        with db_cursor() as cur:
            cur.execute(
                "SELECT * FROM vendors WHERE username=?",
                (username,)
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
        username = RoleManager.normalize_username(username)
        if not username:
            return

        with db_cursor() as cur:
            cur.execute("""
                INSERT OR IGNORE INTO vendors(username, role, added_at)
                VALUES (?, ?, ?)
            """, (username, role, time.strftime("%d.%m.%Y")))

    @staticmethod
    def remove_vendor(username: str):
        username = RoleManager.normalize_username(username)
        if not username:
            return

        with db_cursor() as cur:
            cur.execute(
                "DELETE FROM vendors WHERE username=?",
                (username,)
            )

    @staticmethod
    def set_vip(username: str):
        username = RoleManager.normalize_username(username)
        if not username:
            return

        with db_cursor() as cur:
            cur.execute(
                "UPDATE vendors SET role='vip' WHERE username=?",
                (username,)
            )

    @staticmethod
    def downgrade_from_vip(username: str):
        username = RoleManager.normalize_username(username)
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
# FAZA 5/15 – DETECTION ENGINE (ULTRA + PRICE)
# ============================================================

import re
import unicodedata
import difflib
from typing import Tuple


# =========================
# NORMALIZATION
# =========================

ZERO_WIDTH_PATTERN = re.compile(r"[\u200B-\u200D\uFEFF\u2060]")


def normalize_unicode(text: str) -> str:
    text = ZERO_WIDTH_PATTERN.sub("", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


HOMOGLYPH_MAP = {
    "а": "a", "о": "o", "е": "e",
    "р": "p", "с": "c", "х": "x",
    "у": "y", "і": "i", "ӏ": "l"
}


def normalize_homoglyphs(text: str) -> str:
    return "".join(HOMOGLYPH_MAP.get(c, c) for c in text)


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


CHAR_MAP = {
    "a": "@", "c": "©", "e": "€",
    "i": "l", "s": "$", "t": "τ",
    "u": "Ц", "o": "Ø", "p": "₱",
    "w": "₩", "x": "Ж", "y": "¥",
    "z": "Ƶ",
}

REVERSE_MAP = {v.lower(): k for k, v in CHAR_MAP.items()}


def normalize_for_detection(text: str) -> str:
    text = normalize_unicode(text)
    text = normalize_homoglyphs(text)
    text = normalize_digits(text)
    text = "".join(REVERSE_MAP.get(c.lower(), c) for c in text)
    return text.lower()


# =========================
# ULTRA CATEGORY MAP
# =========================

ULTRA_CATEGORIES = {
    "💎": ["mewa", "ice", "kryx", "krysztal", "krystal", "crystal"],
    "🌿": ["weed", "buch", "jazz", "ziolo", "trawa"],
    "❄": ["3cmc", "4mmc"],
    "🍫": ["hasz", "haszysz", "hash"],
    "🧂": ["koks", "koko", "cocaine"],
    "💊": ["clony", "clonozepan", "xanax", "medikinet", "pixy"]
}

SAFE_CONTEXT = [
    "ice cream",
    "crystal clear",
    "weed control",
    "hashmap"
]


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


# =========================
# HARDCORE PRICE DETECTOR
# =========================

CURRENCY_PATTERNS = [
    r"\bzł\b", r"\bpln\b", r"\beur\b",
    r"\busd\b", r"€", r"\$"
]

WORD_NUMBERS = [
    "sto", "dwiescie", "trzysta",
    "czterysta", "piecset", "szescset",
    "tysiac", "hundred", "thousand"
]


def hardcore_price_detect(text: str) -> bool:

    normalized = normalize_for_detection(text)

    # wyjątek dla 3cmc/4mmc
    normalized = re.sub(r"\b(3cmc|4mmc)\b", "", normalized)

    for pattern in CURRENCY_PATTERNS:
        if re.search(pattern, normalized):
            return True

    if re.search(r"\b\d(?:[\-._/]\d){2,}\b", normalized):
        return True

    if re.search(r"\b\d\s+\d\s+\d\b", normalized):
        return True

    if re.search(r"\b\d{2,}\s*-\s*\d{2,}\b", normalized):
        return True

    for word in WORD_NUMBERS:
        if word in normalized:
            return True

    matches = re.findall(r"\b\d{2,}\b", normalized)

    for m in matches:
        number = int(m)

        if 1900 <= number <= 2099:
            continue

        if re.search(rf"\b{m}%", normalized):
            continue

        if re.search(rf"\b{m}(g|ml|tabs|szt)\b", normalized):
            continue

        return True

    return False
    # ============================================================
# FAZA 6/15 – FLOOD PROTECTION & ANTI-SPAM ENGINE
# ============================================================

GLOBAL_RATE_LIMIT_SECONDS = 3
VENDOR_COOLDOWN_VENDOR = 6 * 3600
VENDOR_COOLDOWN_VIP = 3 * 3600
WTB_WTT_COOLDOWN = 600  # 10 minut


# =========================
# GLOBAL BURST LIMITER
# =========================

_last_global_message_time = {}


def check_global_rate_limit(user_id: int) -> bool:
    now = int(time.time())
    last = _last_global_message_time.get(user_id, 0)

    if now - last < GLOBAL_RATE_LIMIT_SECONDS:
        return False

    _last_global_message_time[user_id] = now
    return True


# =========================
# VENDOR COOLDOWN CHECK
# =========================

def check_vendor_cooldown(user_id: int, username: str) -> bool:

    vendor = RoleManager.get_vendor(username)
    if not vendor:
        return False

    role = vendor[1]

    if role == "vip":
        limit = VENDOR_COOLDOWN_VIP
    else:
        limit = VENDOR_COOLDOWN_VENDOR

    last_post = get_vendor_last_post(user_id)

    return (int(time.time()) - last_post) >= limit


# =========================
# WTB/WTT COOLDOWN CHECK
# =========================

def check_wtb_wtt_cooldown(user_id: int) -> bool:

    last_post = get_wtb_wtt_last(user_id)

    return (int(time.time()) - last_post) >= WTB_WTT_COOLDOWN


# =========================
# DUPLICATE CONTENT GUARD
# =========================

_last_user_content = {}


def check_duplicate_content(user_id: int, text: str) -> bool:

    normalized = text.strip().lower()
    last = _last_user_content.get(user_id)

    if last == normalized:
        return False

    _last_user_content[user_id] = normalized
    return True
    # ============================================================
# FAZA 7/15 – LAYOUT ENGINE (STANDARD + VIP PREMIUM)
# ============================================================

def detect_city(text: str) -> str:
    normalized = normalize_for_detection(text)

    if "#gdy" in normalized or "gdynia" in normalized:
        return "GDY"
    if "#gda" in normalized or "gdansk" in normalized:
        return "GDA"
    if "#sop" in normalized or "sopot" in normalized:
        return "SOP"

    return "3CITY"


# =========================
# VENDOR STANDARD LAYOUT
# =========================

def build_vendor_layout(username: str, city: str, content: str) -> str:

    return (
        f"<b>💎 WTS MARKET 💎</b>\n\n"
        f"<b>@{username}</b>\n"
        f"<b>📍 {city}</b>\n\n"
        f"{content}\n\n"
        f"<b>🔥 INTEREST: 0</b>"
    )


# =========================
# VIP PREMIUM LAYOUT
# =========================

def build_vip_layout(username: str, city: str, content: str) -> str:

    return (
        f"<b>━━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>👑 PREMIUM VIP OFFER 👑</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<b>@{username}</b>\n"
        f"<b>📍 {city} | #VIP</b>\n\n"
        f"{content}\n\n"
        f"<b>🔥 INTEREST: 0</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━</b>"
    )


# =========================
# WTB LAYOUT
# =========================

def build_wtb_layout(city: str, content: str) -> str:

    return (
        f"<b>🛒 WTB MARKET 🛒</b>\n\n"
        f"{content}\n\n"
        f"<b>📍 {city} | #WTB</b>"
    )


# =========================
# WTT LAYOUT
# =========================

def build_wtt_layout(city: str, content: str) -> str:

    return (
        f"<b>🔁 WTT MARKET 🔁</b>\n\n"
        f"{content}\n\n"
        f"<b>📍 {city} | #WTT</b>"
    )
# ============================================================
# FAZA 8/15 – MESSAGE ROUTER + FINAL PUBLISH
# ============================================================

async def message_router(update, context):
    init_state(context)

    if not update.message:
        return

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
# PUBLISH – WTS
# ============================================================

async def publish_wts(update, context):

    user = update.effective_user

    if not user.username:
        raise Exception("User has no username")

    city = context.user_data.get("city")
    products = context.user_data.get("wts_products", [])

    if not products:
        raise Exception("No products in WTS publish")

    products_text = "\n".join(products)

    caption = (
        f"<b>💎 WTS MARKET</b>\n\n"
        f"<b>@{user.username}</b>\n"
        f"<b>📍 {city}</b>\n\n"
        f"{products_text}"
    )

    await context.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=WTS_TOPIC,
        photo=LOGO_URL,
        caption=caption,
        parse_mode="HTML"
    )



# ============================================================
# PUBLISH – WTB / WTT
# ============================================================

async def publish_wtx(update, context):

    user = update.effective_user

    if not user.username:
        raise Exception("User has no username")

    city = context.user_data.get("city")
    text = get_pending_text(context)
    mode = get_mode(context)

    if not text:
        raise Exception("No text for WTB/WTT")

    topic = WTB_TOPIC if mode == "WTB" else WTT_TOPIC

    caption = (
        f"<b>{mode} MARKET</b>\n\n"
        f"<b>@{user.username}</b>\n"
        f"<b>📍 {city}</b>\n\n"
        f"{text}"
    )

    await context.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=topic,
        photo=LOGO_URL,
        caption=caption,
        parse_mode="HTML"
    )
        # ============================================================
# FAZA 9/15 – UNIFIED MESSAGE ROUTER
# ============================================================

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.strip()

    init_state(context)

    # ================= GLOBAL RATE LIMIT =================
    if not check_global_rate_limit(user.id):
        return

    # ================= ADMIN FLOW =================
    action = get_admin_action(context)
    if action:
        await handle_admin_text(update, context)
        return

    # ================= EDIT MODE =================
    if is_edit_mode(context):
        await handle_edit_text(update, context)
        return

    mode = get_mode(context)

    # ================= WTS INPUT =================
    if mode == "WTS_INPUT":

        if hardcore_price_detect(text):
            await update.message.reply_text("❌ Zakaz podawania cen.")
            return

        emoji, masked = ultra_detect(text, listing_mode=True)

        add_wts_product(context, f"{emoji} {masked}")

        if not is_wts_complete(context):
            next_step = get_next_wts_step(context)
            await update.message.reply_text(
                f"Podaj produkt {next_step}:"
            )
            return

        # wszystkie produkty podane → pytanie o miasto
        set_mode(context, "WTS_CITY")

        await update.message.reply_text(
            "Podaj miasto (np. GDA, GDY, SOP) lub użyj #gda:"
        )
        return

    # ================= WTS CITY =================
    if mode == "WTS_CITY":

        city = detect_city(text)
        context.user_data["city"] = city

        await finalize_wts_post(update, context)
        return

    # ================= WTB INPUT =================
    if mode == "WTB_INPUT":

        if hardcore_price_detect(text):
            await update.message.reply_text("❌ Zakaz cen.")
            return

        if not check_duplicate_content(user.id, text):
            await update.message.reply_text("Duplikat treści.")
            return

        store_pending_text(context, text)

        detected_city = detect_city(text)

        if detected_city != "3CITY":
            context.user_data["city"] = detected_city
            await finalize_simple_post(update, context, "WTB")
            return

        set_mode(context, "WTB_CITY")

        await update.message.reply_text(
            "Podaj miasto (np. GDA, GDY, SOP):"
        )
        return

    # ================= WTT INPUT =================
    if mode == "WTT_INPUT":

        if hardcore_price_detect(text):
            await update.message.reply_text("❌ Zakaz cen.")
            return

        if not check_duplicate_content(user.id, text):
            await update.message.reply_text("Duplikat treści.")
            return

        store_pending_text(context, text)

        detected_city = detect_city(text)

        if detected_city != "3CITY":
            context.user_data["city"] = detected_city
            await finalize_simple_post(update, context, "WTT")
            return

        set_mode(context, "WTT_CITY")

        await update.message.reply_text(
            "Podaj miasto (np. GDA, GDY, SOP):"
        )
        return

    # ================= WTB CITY =================
    if mode == "WTB_CITY":

        context.user_data["city"] = detect_city(text)
        await finalize_simple_post(update, context, "WTB")
        return

    # ================= WTT CITY =================
    if mode == "WTT_CITY":

        context.user_data["city"] = detect_city(text)
        await finalize_simple_post(update, context, "WTT")
        return
        # ============================================================
# FAZA 10/15 – FINALIZATION ENGINE
# ============================================================

async def finalize_wts_post(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user.username:
        await update.message.reply_text("Brak username.")
        reset_state(context)
        return

    username = user.username.lower()
    vendor = RoleManager.get_vendor(username)

    if not vendor:
        await update.message.reply_text("Brak dostępu.")
        reset_state(context)
        return

    role = vendor[1]

    city = context.user_data.get("city", "3CITY")
    content = "\n".join(context.user_data.get("wts_products", []))

    if role == "vip":
        caption = build_vip_layout(username, city, content)
    else:
        caption = build_vendor_layout(username, city, content)

    try:
        msg = await update.message.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception("Publish WTS failed")
        await update.message.reply_text("Błąd publikacji.")
        reset_state(context)
        return

    update_vendor_post(username, caption)
    set_vendor_last_post(user.id)

    if role == "vip":
        try:
            await update.message.bot.pin_chat_message(
                GROUP_ID,
                msg.message_id
            )
        except Exception:
            pass

    reset_state(context)

    await update.message.reply_text("Opublikowano.")


async def finalize_simple_post(update: Update,
                               context: ContextTypes.DEFAULT_TYPE,
                               mode: str):

    user = update.effective_user
    text = get_pending_text(context)
    city = context.user_data.get("city", "3CITY")

    if not text:
        reset_state(context)
        return

    if mode == "WTB":
        caption = build_wtb_layout(city, text)
        topic = WTB_TOPIC
    else:
        caption = build_wtt_layout(city, text)
        topic = WTT_TOPIC

    try:
        await update.message.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=topic,
            photo=LOGO_URL,
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        logger.exception("Publish WTB/WTT failed")
        await update.message.reply_text("Błąd publikacji.")
        reset_state(context)
        return

    set_wtb_wtt_last(user.id)

    reset_state(context)

    await update.message.reply_text("Opublikowano.")
                                   # ============================================================
# FAZA 11/15 – VENDOR PANEL + VIP AUTO SYSTEM
# ============================================================

from telegram.ext import Application


# =========================
# VENDOR PANEL
# =========================

async def open_vendor_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user

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
        "Panel vendora:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# PANEL CALLBACK HANDLER
# =========================

async def handle_panel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user
    data = query.data

    await query.answer()

    if not user.username:
        return

    username = user.username.lower()

    vendor = RoleManager.get_vendor(username)
    if not vendor:
        return

    role = vendor[1]
    last_content = vendor[4]

    # REPOST
    if data == "PANEL_REPOST":

        if not last_content:
            await query.edit_message_text("Brak ostatniego ogłoszenia.")
            return

        if not check_vendor_cooldown(user.id, username):
            await query.edit_message_text("Cooldown aktywny.")
            return

        msg = await query.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=last_content,
            parse_mode=ParseMode.HTML
        )

        set_vendor_last_post(user.id)

        if role == "vip":
            try:
                await query.bot.pin_chat_message(
                    GROUP_ID,
                    msg.message_id
                )
            except Exception:
                pass

        await query.edit_message_text("Repost wykonany.")
        return

    # EDIT
    if data == "PANEL_EDIT":
        enable_edit_mode(context)
        await query.edit_message_text("Podaj nową treść ogłoszenia:")
        return

    # STATS
    if data == "PANEL_STATS":

        posts = vendor[3]
        interest_total = vendor[7]

        await query.edit_message_text(
            f"📊 Posty: {posts}\n🔥 Łączne interest: {interest_total}"
        )
        return

    # VIP AUTO
    if data == "PANEL_AUTO" and role == "vip":

        auto_enabled = vendor[5]

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

        await query.edit_message_text(status)
        return


# =========================
# EDIT HANDLER
# =========================

async def handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user.username:
        return

    username = user.username.lower()
    text = update.message.text

    if hardcore_price_detect(text):
        await update.message.reply_text("❌ Zakaz cen.")
        return

    emoji, masked = ultra_detect(text, listing_mode=True)
    city = detect_city(text)

    caption = build_vendor_layout(username, city, f"{emoji} {masked}")

    with db_cursor() as cur:
        cur.execute("""
            UPDATE vendors
            SET last_content=?, auto_enabled=0
            WHERE username=?
        """, (caption, username))

    disable_edit_mode(context)

    await update.message.reply_text("Ogłoszenie zaktualizowane.")


# =========================
# VIP AUTO SYSTEM
# =========================

VIP_JOB_PREFIX = "vip_auto_"


def vip_job_name(username: str) -> str:
    return f"{VIP_JOB_PREFIX}{username}"


def remove_vip_job(application: Application, username: str):
    name = vip_job_name(username)
    for job in application.job_queue.jobs():
        if job.name == name:
            job.schedule_removal()


def schedule_vip_job(application: Application,
                     username: str,
                     interval: int = 21600):

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

        msg = await ctx.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=last_content,
            parse_mode=ParseMode.HTML
        )

        try:
            await ctx.bot.pin_chat_message(
                GROUP_ID,
                msg.message_id
            )
        except Exception:
            pass

    application.job_queue.run_repeating(
        vip_callback,
        interval=interval,
        first=interval,
        name=name
    )


def restore_vip_jobs(application: Application):

    with db_cursor() as cur:
        cur.execute("""
            SELECT username FROM vendors
            WHERE role='vip' AND auto_enabled=1
        """)
        rows = cur.fetchall()

    for (username,) in rows:
        schedule_vip_job(application, username)
        # ============================================================
# FAZA 12/15 – ADMIN SYSTEM (COMMAND + CALLBACK SAFE)
# ============================================================

from telegram.ext import CommandHandler


# =========================
# ADMIN PANEL (CALLBACK)
# =========================

async def open_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user

    if not RoleManager.is_admin(user.id):
        await query.edit_message_text("Brak dostępu.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ ADD VENDOR", callback_data="ADMIN_ADD")],
        [InlineKeyboardButton("➖ REMOVE VENDOR", callback_data="ADMIN_REMOVE")],
        [InlineKeyboardButton("👑 MAKE VIP", callback_data="ADMIN_MAKEVIP")],
        [InlineKeyboardButton("❌ REMOVE VIP", callback_data="ADMIN_REMOVEVIP")],
        [InlineKeyboardButton("🔄 RESET COOLDOWN", callback_data="ADMIN_RESETCD")],
        [InlineKeyboardButton("⬅ MENU", callback_data="MENU")]
    ]

    await query.edit_message_text(
        "Admin panel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# ADMIN CALLBACK HANDLER
# =========================

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user
    data = query.data

    await query.answer()

    if not RoleManager.is_admin(user.id):
        return

    if data.startswith("ADMIN_"):
        set_admin_action(context, data)
        await query.edit_message_text("Podaj @username:")
        return


# =========================
# ADMIN TEXT HANDLER
# =========================

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    action = get_admin_action(context)
    if not action:
        return

    username = update.message.text.replace("@", "").strip().lower()

    if not username:
        clear_admin_action(context)
        await update.message.reply_text("Niepoprawny username.")
        return

    if action == "ADMIN_ADD":
        RoleManager.add_vendor(username, "vendor")

    elif action == "ADMIN_REMOVE":
        RoleManager.remove_vendor(username)

    elif action == "ADMIN_MAKEVIP":
        RoleManager.set_vip(username)

    elif action == "ADMIN_REMOVEVIP":
        RoleManager.downgrade_from_vip(username)

    elif action == "ADMIN_RESETCD":
        with db_cursor() as cur:
            cur.execute("DELETE FROM cooldowns")

    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO audit_log(action, username, timestamp, metadata)
            VALUES (?, ?, ?, ?)
        """, (
            action,
            username,
            int(time.time()),
            ""
        ))

    clear_admin_action(context)

    await update.message.reply_text("Wykonano.")


# =========================
# COMMAND VERSION (SAFETY BACKUP)
# =========================

async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not RoleManager.is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /addvendor username")
        return

    username = context.args[0].replace("@", "").lower()
    RoleManager.add_vendor(username, "vendor")

    await update.message.reply_text("Dodano vendora.")


async def cmd_makevip(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not RoleManager.is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /makevip username")
        return

    username = context.args[0].replace("@", "").lower()
    RoleManager.set_vip(username)

    await update.message.reply_text("Nadano VIP.")
# ============================================================
# FAZA 13/15 – APPLICATION WIRING (FIXED VERSION)
# ============================================================

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# START COMMAND
# =========================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    reset_state(context)

    await update.message.reply_text(
        "Menu:",
        reply_markup=build_main_menu(update.effective_user)
    )


# =========================
# MAIN MENU BUILDER
# =========================

def build_main_menu(user):

    keyboard = []
    row = []

    username = user.username.lower() if user.username else ""

    if username and RoleManager.is_vendor(username):
        row.append(InlineKeyboardButton("💼 WTS", callback_data="WTS"))

    row.append(InlineKeyboardButton("🛒 WTB", callback_data="WTB"))
    row.append(InlineKeyboardButton("🔁 WTT", callback_data="WTT"))

    keyboard.append(row)

    if username and RoleManager.is_vendor(username):
        keyboard.append([
            InlineKeyboardButton("📊 PANEL", callback_data="PANEL")
        ])

    if RoleManager.is_admin(user.id):
        keyboard.append([
            InlineKeyboardButton("⚙ ADMIN PANEL", callback_data="ADMIN")
        ])

    return InlineKeyboardMarkup(keyboard)


# =========================
# GLOBAL ERROR HANDLER
# =========================

async def global_error_handler(update, context):
    logger.exception("Unhandled exception", exc_info=context.error)


# =========================
# CREATE APPLICATION
# =========================

def create_application() -> Application:

    app = Application.builder().token(TOKEN).build()

    # ===== ERROR HANDLER =====
    app.add_error_handler(global_error_handler)

    # ===== COMMANDS =====
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addvendor", cmd_addvendor))
    app.add_handler(CommandHandler("makevip", cmd_makevip))

    # ===== CALLBACKS =====
    app.add_handler(
        CallbackQueryHandler(handle_panel_action, pattern="^PANEL_")
    )

    app.add_handler(
        CallbackQueryHandler(handle_admin_callback, pattern="^ADMIN_")
    )

    app.add_handler(
        CallbackQueryHandler(guarded_callback_router)
    )

    # ===== MESSAGE ROUTER =====
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            guarded_message_router
        )
    )

    # ===== RESTORE VIP AUTO =====
    restore_vip_jobs(app)

    return app
    
    # ============================================================
# FAZA 14/15 – RUNTIME GUARDS & STABILITY LAYER
# ============================================================

def safe_username(user) -> str:
    if not user:
        return ""
    if not user.username:
        return ""
    return user.username.lower()


def trace_mode(context, label: str):
    mode = context.user_data.get("mode")
    logger.info(f"[TRACE] {label} | mode={mode}")


async def safe_send_message(bot, chat_id, text, **kwargs):
    try:
        return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except Exception:
        logger.exception("safe_send_message failed")
        return None


async def safe_send_photo(bot, chat_id, photo, caption, **kwargs):
    try:
        return await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            **kwargs
        )
    except Exception:
        logger.exception("safe_send_photo failed")
        return None


async def guarded_message_router(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):

    try:
        await message_router(update, context)
    except Exception:
        logger.exception("CRITICAL message_router failure")
        try:
            await update.message.reply_text(
                "Wystąpił błąd. Spróbuj ponownie."
            )
        except Exception:
            pass
        reset_state(context)


async def guarded_callback_router(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):

    try:
        await callback_router(update, context)
    except Exception:
        logger.exception("CRITICAL callback_router failure")
        try:
            await update.callback_query.answer(
                "Błąd systemu",
                show_alert=True
            )
        except Exception:
            pass
        reset_state(context)
        # ============================================================
# FAZA 15/15 – MAIN ENTRY + FINAL INTEGRATION
# ============================================================

def main():

    logger.info("=== STARTING MARKET BOT (PRODUCTION BUILD) ===")

    # ===== INIT DATABASE =====
    init_db()
    bootstrap_roles()

    # ===== CREATE APPLICATION =====
    app = create_application()

    # ===== PODMIANA ROUTERÓW NA GUARDED =====
    app.handlers.clear()

    # COMMANDS
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addvendor", cmd_addvendor))
    app.add_handler(CommandHandler("makevip", cmd_makevip))

    # CALLBACKS
    app.add_handler(CallbackQueryHandler(handle_panel_action, pattern="^PANEL_"))
    app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^ADMIN_"))
    app.add_handler(CallbackQueryHandler(guarded_callback_router))

    # MESSAGE ROUTER (JEDEN)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, guarded_message_router)
    )

    # ERROR HANDLER
    app.add_error_handler(global_error_handler)

    # SIGNAL HANDLERS
    setup_signal_handlers(app)

    # VIP AUTO RESTORE
    restore_vip_jobs(app)

    logger.info("=== MARKET BOT READY ===")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()




