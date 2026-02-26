# ================= Część 1 z 6 =================
# INFRA + DB + ROLE ENGINE + GLOBAL STATE CONTROL

import os
import sys
import logging
import signal
import sqlite3
import time
from contextlib import contextmanager
from typing import List, Optional, Tuple
from telegram.ext import Application

# ============================================================
# LOGGING (Railway stdout)
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("MARKET_BOT")

# ============================================================
# ENV FAIL-FAST
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

ADMIN_IDS: List[int] = [
    int(x.strip())
    for x in require_env("ADMIN_IDS").split(",")
    if x.strip().isdigit()
]

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

# ============================================================
# SQLITE (HARDENED WAL)
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
# DATABASE INIT
# ============================================================

def init_db():
    with db_cursor() as cur:

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

        cur.execute("""
        CREATE TABLE IF NOT EXISTS cooldowns (
            user_id INTEGER PRIMARY KEY,
            last_post INTEGER
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS interests (
            message_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY(message_id, user_id)
        )
        """)

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
# ROLE ENGINE
# ============================================================

class RoleManager:

    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in ADMIN_IDS

    @staticmethod
    def get_vendor(username: str) -> Optional[Tuple]:
        if not username:
            return None
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
        with db_cursor() as cur:
            cur.execute("""
                INSERT OR IGNORE INTO vendors
                (username, role, added_at)
                VALUES (?, ?, ?)
            """, (
                username.lower(),
                role,
                time.strftime("%d.%m.%Y")
            ))

    @staticmethod
    def set_vip(username: str):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET role='vip'
                WHERE username=?
            """, (username.lower(),))

    @staticmethod
    def remove_vendor(username: str):
        with db_cursor() as cur:
            cur.execute("DELETE FROM vendors WHERE username=?", (username.lower(),))


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


# ============================================================
# BOOTSTRAP ROLES
# ============================================================

def bootstrap_roles():
    for username in BOOTSTRAP_VENDORS:
        RoleManager.add_vendor(username, role="vendor")

    for username in BOOTSTRAP_VIP:
        RoleManager.add_vendor(username, role="vip")

    logger.info("Bootstrap roles completed")


# ============================================================
# GLOBAL STATE CONTROL (ANTI-CHAOS)
# ============================================================

def reset_state(context):
    """
    Globalny reset wszystkich trybów
    """
    context.user_data.clear()


def init_user_state(context):
    if "initialized" not in context.user_data:
        context.user_data.update({
            "mode": None,
            "wts_step": None,
            "wts_total": 0,
            "wts_products": [],
            "city": None,
            "options": [],
            "admin_action": None,
            "edit_mode": False,
            "initialized": True
        })


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

async def global_error_handler(update, context):
    logger.exception("Unhandled exception", exc_info=context.error)


# ============================================================
# GRACEFUL SHUTDOWN
# ============================================================

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
# APPLICATION FACTORY
# ============================================================

def create_application() -> Application:
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(global_error_handler)
    setup_signal_handlers(app)
    return app
    # ================= Część 2 z 6 =================
# ULTRA DETECTION + HARDCORE PRICE DETECTOR (HARDENED)

import re
import unicodedata
import difflib

# ============================================================
# ZERO WIDTH + NORMALIZACJA UNICODE
# ============================================================

ZERO_WIDTH_PATTERN = re.compile(r"[\u200B-\u200D\uFEFF\u2060]")

def normalize_unicode(text: str) -> str:
    text = ZERO_WIDTH_PATTERN.sub("", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


# ============================================================
# HOMOGLYPH NORMALIZATION (CYRYLICA → ŁACINA)
# ============================================================

HOMOGLYPH_MAP = {
    "а": "a", "о": "o", "е": "e",
    "р": "p", "с": "c", "х": "x",
    "у": "y", "і": "i", "ӏ": "l"
}

def normalize_homoglyphs(text: str) -> str:
    return "".join(HOMOGLYPH_MAP.get(c, c) for c in text)


# ============================================================
# DIGIT → LETTER MAP
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
    for d, l in DIGIT_TO_LETTER.items():
        text = text.replace(d, l)
    return text


# ============================================================
# FULL CHAR MAP (MASKOWANIE)
# ============================================================

CHAR_MAP = {
    "a": "@", "c": "©", "e": "€",
    "i": "l", "s": "$", "t": "τ",
    "u": "Ц", "o": "Ø", "p": "₱",
    "w": "₩", "x": "Ж", "y": "¥",
    "z": "Ƶ",
}

REVERSE_MAP = {v.lower(): k for k, v in CHAR_MAP.items()}


# ============================================================
# ULTRA CATEGORY MAP
# ============================================================

ULTRA_CATEGORIES = {
    "💎": ["mewa", "ice", "kryx", "kryształ", "krystal", "crystal"],
    "🌿": ["weed", "buch", "jazz", "jaaz", "zioło", "trawa"],
    "❄": ["3cmc", "4mmc", "feta"],
    "🍫": ["hasz", "haszysz", "hash"],
    "🧂": ["koks", "koko", "kokos", "cocaine"],
    "💊": ["clony", "clonozepan", "xanax", "medikinet", "pixy", "pigle", "piguły"]
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
    return difflib.SequenceMatcher(None, word, keyword).ratio() >= dynamic_threshold(keyword)


# ============================================================
# ULTRA DETECTION (CONTEXT SAFE)
# ============================================================

def ultra_detect(text: str, listing_mode: bool = True):

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
# HARDCORE PRICE DETECTOR v3
# ============================================================

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
    normalized = re.sub(r"\b(3cmc|4mmc)\b", "", normalized)

    # currency
    for pattern in CURRENCY_PATTERNS:
        if re.search(pattern, normalized):
            return True

    # broken numbers 2-0-0 / 2.0.0
    if re.search(r"\b\d(?:[\-._/]\d){2,}\b", normalized):
        return True

    # spaced numbers
    if re.search(r"\b\d\s+\d\s+\d\b", normalized):
        return True

    # quantity + number
    if re.search(r"\b\d+\s*(g|ml|tabs|szt)\s*\d{2,}\b", normalized):
        return True

    # range 100-300
    if re.search(r"\b\d{2,}\s*-\s*\d{2,}\b", normalized):
        return True

    # word numbers
    for word in WORD_NUMBERS:
        if word in normalized:
            return True

    # standalone large number (z wyjątkami)
    matches = re.findall(r"\b\d{2,}\b", normalized)

    for m in matches:
        number = int(m)

        # allowed: 1900-2099
        if 1900 <= number <= 2099:
            continue

        if re.search(rf"\b{m}%", normalized):
            continue

        if re.search(rf"\b{m}(g|ml|tabs|szt)\b", normalized):
            continue

        return True

    return False
 # ================= Część 3 z 6 =================
# STATE MACHINE + WTS FLOW + WTB/WTT START

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import html
import time

# ============================================================
# MENU BUILDER
# ============================================================

def build_main_menu(user):
    keyboard = []

    is_vendor = user.username and RoleManager.is_vendor(user.username.lower())
    is_admin = RoleManager.is_admin(user.id)

    row = []
    if is_vendor:
        row.append(InlineKeyboardButton("💼 WTS", callback_data="WTS"))
    row.append(InlineKeyboardButton("🛒 WTB", callback_data="WTB"))
    row.append(InlineKeyboardButton("🔁 WTT", callback_data="WTT"))
    keyboard.append(row)

    if is_vendor:
        keyboard.append([InlineKeyboardButton("📊 PANEL", callback_data="PANEL")])

    if is_admin:
        keyboard.append([InlineKeyboardButton("⚙ ADMIN PANEL", callback_data="ADMIN")])

    return InlineKeyboardMarkup(keyboard)


def menu_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ MENU", callback_data="MENU")]
    ])


# ============================================================
# START
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_state(context)
    init_user_state(context)

    await update.message.reply_text(
        "Wybierz opcję:",
        reply_markup=build_main_menu(update.effective_user)
    )


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user
    await query.answer()

    init_user_state(context)

    # GLOBAL MENU RESET
    if query.data == "MENU":
        reset_state(context)
        init_user_state(context)
        await query.edit_message_text(
            "Menu główne:",
            reply_markup=build_main_menu(user)
        )
        return

    # ========================================================
    # WTB / WTT START (JUŻ WPIĘTE)
    # ========================================================

    if query.data == "WTB":
        context.user_data["mode"] = "WTB"
        await query.edit_message_text(
            "Wpisz treść ogłoszenia WTB:",
            reply_markup=menu_button()
        )
        return

    if query.data == "WTT":
        context.user_data["mode"] = "WTT"
        await query.edit_message_text(
            "Wpisz treść ogłoszenia WTT:",
            reply_markup=menu_button()
        )
        return

    # ========================================================
    # WTS START
    # ========================================================

    if query.data == "WTS":
        if not user.username or not RoleManager.is_vendor(user.username.lower()):
            await query.edit_message_text("Brak dostępu.")
            return

        role = "vip" if RoleManager.is_vip(user.username.lower()) else "vendor"
        cooldown_limit = 3*60*60 if role == "vip" else 6*60*60
        last = get_last_post(user.id)

        if time.time() - last < cooldown_limit:
            await query.edit_message_text("Cooldown aktywny.", reply_markup=menu_button())
            return

        context.user_data["mode"] = "WTS_SELECT_COUNT"

        keyboard = []
        row = []
        for i in range(1, 11):
            row.append(InlineKeyboardButton(str(i), callback_data=f"WTS_COUNT_{i}"))
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
    # SELECT COUNT
    # ========================================================

    if query.data.startswith("WTS_COUNT_"):
        count = int(query.data.split("_")[2])
        context.user_data["mode"] = "WTS_INPUT"
        context.user_data["wts_total"] = count
        context.user_data["wts_products"] = []
        context.user_data["wts_step"] = 1

        await query.edit_message_text(
            "Podaj produkt 1:",
            reply_markup=menu_button()
        )
        return

    # ========================================================
    # CITY SELECT
    # ========================================================

    if query.data.startswith("CITY_"):
        context.user_data["city"] = query.data.replace("CITY_", "")
        await ask_options(query, context)
        return

    # ========================================================
    # OPTIONS
    # ========================================================

    if query.data.startswith("OPT_"):
        option = query.data.replace("OPT_", "")
        options = context.user_data.get("options", [])

        if option == "BRAK":
            context.user_data["options"] = []
        else:
            if option not in options and len(options) < 2:
                options.append(option)
                context.user_data["options"] = options

        await ask_options(query, context)
        return

    if query.data == "OPT_DONE":
        await finalize_wts(update, context)
        return
# ============================================================
# FINALIZE WTS
# ============================================================

async def finalize_wts(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.callback_query.from_user
    username = user.username.lower()

    role = "vip" if RoleManager.is_vip(username) else "vendor"

    content = "\n".join(context.user_data["wts_products"])
    city = context.user_data.get("city", "3CITY")
    options = context.user_data.get("options", [])

    option_text = ""
    if options:
        option_text = "\n" + " | ".join(options)

    caption = (
        f"<b>{'✨💎 VIP MARKET 💎✨' if role=='vip' else '💎 WTS MARKET 💎'}</b>\n\n"
        f"<b>@{html.escape(username)}</b>\n"
        f"<b>📍 {city}</b>{option_text}\n\n"
        f"{content}\n\n"
        f"<b>🔥 INTEREST: 0</b>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]
    ])

    msg = await update.callback_query.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=WTS_TOPIC,
        photo=LOGO_URL,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

    if role == "vip":
        try:
            await update.callback_query.bot.pin_chat_message(GROUP_ID, msg.message_id)
        except:
            pass

    RoleManager.add_vendor(username)
    set_last_post(user.id)

    reset_state(context)

    await update.callback_query.edit_message_text(
        "Opublikowano.",
        reply_markup=build_main_menu(user)
    )
    # ================= Część 4 z 6 =================
# WTB / WTT + ATOMIC INTEREST SYSTEM

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

# ============================================================
# CITY AUTO DETECTION
# ============================================================

CITY_KEYWORDS = {
    "GDY": ["gdynia", "gdy"],
    "GDA": ["gdansk", "gdańsk", "gda"],
    "SOP": ["sopot", "sop"]
}


def detect_city(text: str) -> str:
    normalized = normalize_for_detection(text)

    for city, keywords in CITY_KEYWORDS.items():
        for k in keywords:
            if k in normalized:
                return city

    return "3CITY"


# ============================================================
# WTB / WTT START (callback_router extension)
# ============================================================

async def start_wtb_wtt(query, context, mode):

    context.user_data["mode"] = mode

    await query.edit_message_text(
        f"Wpisz treść ogłoszenia {mode}:",
        reply_markup=menu_button()
    )


# (dodać do callback_router w Części 3:)
# if query.data == "WTB": await start_wtb_wtt(query, context, "WTB")
# if query.data == "WTT": await start_wtb_wtt(query, context, "WTT")


# ============================================================
# MESSAGE ROUTER EXTENSION (WTB / WTT)
# ============================================================

async def handle_wtb_wtt(update, context):

    mode = context.user_data.get("mode")

    if mode not in ("WTB", "WTT"):
        return

    text = update.message.text

    emoji, masked = ultra_detect(text, listing_mode=True)
    city = detect_city(text)

    hashtag = "#WTB" if mode == "WTB" else "#WTT"

    caption = (
        f"<b>{mode} MARKET</b>\n\n"
        f"{emoji} {masked}\n\n"
        f"<b>📍 {city} | #3CITY</b>\n"
        f"<b>{hashtag}</b>\n\n"
        f"<b>🔥 INTEREST: 0</b>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]
    ])

    msg = await update.message.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=WTB_TOPIC if mode == "WTB" else WTT_TOPIC,
        photo=LOGO_URL,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

    schedule_auto_delete(context, msg.message_id)

    reset_state(context)

    await update.message.reply_text(
        "Opublikowano.",
        reply_markup=build_main_menu(update.effective_user)
    )


# ============================================================
# AUTO DELETE 48H
# ============================================================

def schedule_auto_delete(context, message_id: int):

    async def delete_job(ctx):
        try:
            await ctx.bot.delete_message(GROUP_ID, message_id)
        except Exception:
            pass

    context.application.job_queue.run_once(delete_job, 172800)


# ============================================================
# INTEREST SYSTEM (ATOMIC)
# ============================================================

async def handle_interest(update, context):

    query = update.callback_query
    user = query.from_user
    message = query.message

    await query.answer()

    try:
        with db_cursor() as cur:

            cur.execute("""
                INSERT OR IGNORE INTO interests(message_id, user_id)
                VALUES (?, ?)
            """, (message.message_id, user.id))

            cur.execute("""
                SELECT COUNT(*) FROM interests
                WHERE message_id=?
            """, (message.message_id,))
            count = cur.fetchone()[0]

        # Update caption safely
        new_caption = re.sub(
            r"🔥 INTEREST:\s*\d+",
            f"🔥 INTEREST: {count}",
            message.caption
        )

        await message.edit_caption(
            caption=new_caption,
            parse_mode=ParseMode.HTML,
            reply_markup=message.reply_markup
        )

    except Exception:
        pass
        # ================= Część 5 z 6 =================
# VENDOR PANEL + VIP PANEL + EDIT MODE

from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ============================================================
# PANEL HANDLER
# ============================================================

async def open_panel(update, context):
    user = update.effective_user

    if not user.username:
        return

    username = user.username.lower()

    if not RoleManager.is_vendor(username):
        await update.message.reply_text("Brak dostępu.")
        return

    is_vip = RoleManager.is_vip(username)

    keyboard = [
        [InlineKeyboardButton("🔁 REPOST", callback_data="PANEL_REPOST")],
        [InlineKeyboardButton("✏ EDIT", callback_data="PANEL_EDIT")],
        [InlineKeyboardButton("📊 STATS", callback_data="PANEL_STATS")]
    ]

    if is_vip:
        keyboard.append(
            [InlineKeyboardButton("🤖 AUTO ON/OFF", callback_data="PANEL_AUTO")]
        )

    keyboard.append([InlineKeyboardButton("⬅ MENU", callback_data="MENU")])

    await update.message.reply_text(
        "Panel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# PANEL CALLBACK
# ============================================================

EDIT_STATE = 100


async def panel_callback(update, context):

    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not user.username:
        return

    username = user.username.lower()

    if not RoleManager.is_vendor(username):
        await query.edit_message_text("Brak dostępu.")
        return

    vendor = RoleManager.get_vendor(username)
    last_content = vendor[4]
    role = vendor[1]

    # REPOST
    if query.data == "PANEL_REPOST":

        if not last_content:
            await query.edit_message_text("Brak ostatniego ogłoszenia.", reply_markup=menu_button())
            return

        cooldown_limit = 3*60*60 if role == "vip" else 6*60*60
        if time.time() - get_last_post(user.id) < cooldown_limit:
            await query.edit_message_text("Cooldown aktywny.", reply_markup=menu_button())
            return

        caption = last_content.replace("🔥 INTEREST:", "🔥 INTEREST: 0")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]
        ])

        msg = await query.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

        if role == "vip":
            try:
                await query.bot.pin_chat_message(GROUP_ID, msg.message_id)
            except:
                pass

        set_last_post(user.id)

        await query.edit_message_text(
            "Repost wykonany.",
            reply_markup=build_main_menu(user)
        )
        return

    # EDIT
    if query.data == "PANEL_EDIT":

        context.user_data["edit_mode"] = True

        await query.edit_message_text(
            "Podaj nową treść ogłoszenia:",
            reply_markup=menu_button()
        )
        return EDIT_STATE

    # STATS
    if query.data == "PANEL_STATS":

        posts = vendor[3]
        interest_total = vendor[7]

        await query.edit_message_text(
            f"📊 Posty: {posts}\n🔥 Łączne interest: {interest_total}",
            reply_markup=menu_button()
        )
        return

    # AUTO (VIP only)
    if query.data == "PANEL_AUTO":

        if role != "vip":
            return

        auto_enabled = vendor[5]

        with db_cursor() as cur:
            if auto_enabled:
                cur.execute("""
                    UPDATE vendors SET auto_enabled=0 WHERE username=?
                """, (username,))
                status = "AUTO OFF"
            else:
                cur.execute("""
                    UPDATE vendors SET auto_enabled=1 WHERE username=?
                """, (username,))
                status = "AUTO ON"

        await query.edit_message_text(status, reply_markup=menu_button())
        return


# ============================================================
# EDIT HANDLER
# ============================================================

async def edit_receive(update, context):

    if not context.user_data.get("edit_mode"):
        return ConversationHandler.END

    user = update.effective_user
    username = user.username.lower()
    text = update.message.text

    if hardcore_price_detect(text):
        await update.message.reply_text("❌ Zakaz cen.", reply_markup=menu_button())
        return EDIT_STATE

    emoji, masked = ultra_detect(text, listing_mode=True)

    city = detect_city(text)

    caption = (
        f"<b>💎 WTS MARKET 💎</b>\n\n"
        f"<b>@{username}</b>\n"
        f"<b>📍 {city}</b>\n\n"
        f"{emoji} {masked}\n\n"
        f"<b>🔥 INTEREST: 0</b>"
    )

    with db_cursor() as cur:
        cur.execute("""
            UPDATE vendors
            SET last_content=?, auto_enabled=0
            WHERE username=?
        """, (caption, username))

    context.user_data["edit_mode"] = False

    await update.message.reply_text(
        "Ogłoszenie zaktualizowane.\nAUTO wyłączone.",
        reply_markup=build_main_menu(user)
    )

    return ConversationHandler.END


# ============================================================
# EDIT CANCEL
# ============================================================

async def edit_cancel(update, context):
    reset_state(context)
    await update.message.reply_text(
        "Anulowano.",
        reply_markup=build_main_menu(update.effective_user)
    )
    return ConversationHandler.END
    # ================= Część 6 z 6 =================
# VIP SCHEDULER + ADMIN PANEL + MAIN

from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

# ============================================================
# VIP ENTERPRISE SCHEDULER
# ============================================================

VIP_JOB_PREFIX = "vip_auto_"


def vip_job_name(username: str) -> str:
    return f"{VIP_JOB_PREFIX}{username}"


def remove_vip_job(application, username: str):
    name = vip_job_name(username)
    for job in application.job_queue.jobs():
        if job.name == name:
            job.schedule_removal()


def schedule_vip(application, username: str, interval: int = 21600):

    name = vip_job_name(username)

    # dedupe
    for job in application.job_queue.jobs():
        if job.name == name:
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

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]
        ])

        msg = await ctx.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=last_content.replace("🔥 INTEREST:", "🔥 INTEREST: 0"),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

        try:
            await ctx.bot.pin_chat_message(GROUP_ID, msg.message_id)
        except:
            pass

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
        name=name
    )


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
# ADMIN PANEL
# ============================================================

async def admin_panel(update, context):

    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not RoleManager.is_admin(user.id):
        await query.edit_message_text("Brak dostępu.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ ADD VENDOR", callback_data="ADMIN_ADD")],
        [InlineKeyboardButton("➖ REMOVE VENDOR", callback_data="ADMIN_REMOVE")],
        [InlineKeyboardButton("👑 MAKE VIP", callback_data="ADMIN_MAKEVIP")],
        [InlineKeyboardButton("❌ REMOVE VIP", callback_data="ADMIN_REMVIP")],
        [InlineKeyboardButton("🔄 REMOVE COOLDOWN", callback_data="ADMIN_RMCD")],
        [InlineKeyboardButton("📦 BACKUP VENDORS", callback_data="ADMIN_BACKUP")],
        [InlineKeyboardButton("⬅ MENU", callback_data="MENU")]
    ]

    await query.edit_message_text(
        "Admin panel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# ADMIN CALLBACK
# ============================================================

async def admin_callback(update, context):

    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not RoleManager.is_admin(user.id):
        return

    action = query.data

    if action == "ADMIN_ADD":
        context.user_data["admin_action"] = "ADD"
        await query.edit_message_text("Podaj @username:", reply_markup=menu_button())
        return

    if action == "ADMIN_REMOVE":
        context.user_data["admin_action"] = "REMOVE"
        await query.edit_message_text("Podaj @username:", reply_markup=menu_button())
        return

    if action == "ADMIN_MAKEVIP":
        context.user_data["admin_action"] = "MAKEVIP"
        await query.edit_message_text("Podaj @username:", reply_markup=menu_button())
        return

    if action == "ADMIN_REMVIP":
        context.user_data["admin_action"] = "REMVIP"
        await query.edit_message_text("Podaj @username:", reply_markup=menu_button())
        return

    if action == "ADMIN_RMCD":
        context.user_data["admin_action"] = "RMCD"
        await query.edit_message_text("Podaj @username:", reply_markup=menu_button())
        return

    if action == "ADMIN_BACKUP":
        with db_cursor() as cur:
            cur.execute("SELECT username, role FROM vendors")
            rows = cur.fetchall()

        text = "\n".join([f"{u}:{r}" for u, r in rows])

        await query.edit_message_text(text or "Brak.", reply_markup=menu_button())
        return


# ============================================================
# ADMIN TEXT HANDLER
# ============================================================

async def admin_text(update, context):

    action = context.user_data.get("admin_action")
    if not action:
        return

    username = update.message.text.replace("@", "").lower()

    if action == "ADD":
        RoleManager.add_vendor(username, role="vendor")

    elif action == "REMOVE":
        RoleManager.remove_vendor(username)

    elif action == "MAKEVIP":
        RoleManager.set_vip(username)

    elif action == "REMVIP":
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors SET role='vendor', auto_enabled=0
                WHERE username=?
            """, (username,))

    elif action == "RMCD":
        with db_cursor() as cur:
            cur.execute("""
                DELETE FROM cooldowns
                WHERE user_id=(
                    SELECT user_id FROM cooldowns
                )
            """)

    context.user_data["admin_action"] = None

    await update.message.reply_text(
        "Wykonano.",
        reply_markup=build_main_menu(update.effective_user)
    )


# ============================================================
# MAIN
# ============================================================

def main():

    init_db()
    bootstrap_roles()

    app = create_application()

    # START
    app.add_handler(CommandHandler("start", cmd_start))

    # CALLBACKS
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^PANEL_"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^ADMIN$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^ADMIN_"))
    app.add_handler(CallbackQueryHandler(handle_interest, pattern="^INTEREST$"))

    # MESSAGE ROUTERS
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wtb_wtt))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text))

    # EDIT CONVERSATION
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(panel_callback, pattern="PANEL_EDIT")],
        states={
            EDIT_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_receive)]
        },
        fallbacks=[CommandHandler("cancel", edit_cancel)]
    )

    app.add_handler(edit_conv)

    restore_vip_jobs(app)

    logger.info("Market Bot 2.0 started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
