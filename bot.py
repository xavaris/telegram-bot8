# ============================================================
# CZĘŚĆ 1/12 – INFRASTRUCTURE CORE + ENV + DATABASE (WAL)
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
from contextlib import contextmanager
from typing import List, Optional, Tuple, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# LOGGING (Railway stdout)
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("MARKET_BOT")

# ============================================================
# ENV – FAIL FAST
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

# ============================================================
# DATABASE – Persistent Volume + WAL
# ============================================================

DB_PATH = "/data/market.db"


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


def init_db():
    os.makedirs("/data", exist_ok=True)

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
            vendor_username TEXT,
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

        cur.execute("""
        CREATE TABLE IF NOT EXISTS wtb_wtt_cooldown (
            user_id INTEGER PRIMARY KEY,
            last_post INTEGER
        )
        """)

    logger.info("Database initialized (WAL + Persistent Volume ready)")
    # ============================================================
# CZĘŚĆ 2/12 – NORMALIZATION + ULTRA DETECTION ENGINE
# ============================================================

# ============================================================
# ZERO WIDTH + UNICODE NORMALIZATION
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
# MASKOWANIE TYLKO WYKRYTYCH SŁÓW
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
# FUZZY MATCH – DYNAMIC THRESHOLD
# ============================================================

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


# ============================================================
# ULTRA DETECT (MASKOWANIE + EMOJI)
# ============================================================

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
# CZĘŚĆ 3/12 – HARDCORE PRICE ENGINE + ROLE SYSTEM + COOLDOWN
# ============================================================

# ============================================================
# HARDCORE PRICE DETECTOR
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
# ROLE ENGINE
# ============================================================

class RoleManager:

    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in ADMIN_IDS

    @staticmethod
    def get_vendor(username: str):
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
                INSERT OR IGNORE INTO vendors(username, role, added_at)
                VALUES (?, ?, ?)
            """, (username.lower(), role, time.strftime("%d.%m.%Y")))

    @staticmethod
    def remove_vendor(username: str):
        with db_cursor() as cur:
            cur.execute("DELETE FROM vendors WHERE username=?", (username.lower(),))

    @staticmethod
    def set_vip(username: str):
        with db_cursor() as cur:
            cur.execute("UPDATE vendors SET role='vip' WHERE username=?", (username.lower(),))


def bootstrap_roles():
    for u in BOOTSTRAP_VENDORS:
        RoleManager.add_vendor(u, "vendor")
    for u in BOOTSTRAP_VIP:
        RoleManager.add_vendor(u, "vip")


# ============================================================
# WTS COOLDOWN SYSTEM
# ============================================================

def get_last_post(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT last_post FROM cooldowns WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0


def set_last_post(user_id: int):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO cooldowns(user_id,last_post)
            VALUES (?,?)
            ON CONFLICT(user_id)
            DO UPDATE SET last_post=excluded.last_post
        """, (user_id, int(time.time())))


# ============================================================
# WTB/WTT COOLDOWN SYSTEM
# ============================================================

WTB_WTT_COOLDOWN = 1800


def get_wtb_wtt_last(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT last_post FROM wtb_wtt_cooldown WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0


def set_wtb_wtt_last(user_id: int):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO wtb_wtt_cooldown(user_id,last_post)
            VALUES (?,?)
            ON CONFLICT(user_id)
            DO UPDATE SET last_post=excluded.last_post
        """, (user_id, int(time.time())))
        # ============================================================
# CZĘŚĆ 4/12 – STATE MANAGEMENT + MENU + START + CITY DETECT
# ============================================================

def reset_state(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()


def init_state(context: ContextTypes.DEFAULT_TYPE):
    if "initialized" not in context.user_data:
        context.user_data.update({
            "mode": None,
            "wts_total": 0,
            "wts_products": [],
            "city": None,
            "temp_listing": None,
            "admin_action": None,
            "edit_mode": False,
            "initialized": True
        })


def build_main_menu(user):
    keyboard = []
    row = []

    if user.username and RoleManager.is_vendor(user.username.lower()):
        row.append(InlineKeyboardButton("💼 WTS", callback_data="WTS"))

    row.append(InlineKeyboardButton("🛒 WTB", callback_data="WTB"))
    row.append(InlineKeyboardButton("🔁 WTT", callback_data="WTT"))
    keyboard.append(row)

    if user.username and RoleManager.is_vendor(user.username.lower()):
        keyboard.append([InlineKeyboardButton("📊 PANEL", callback_data="PANEL")])

    if RoleManager.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙ ADMIN PANEL", callback_data="ADMIN")])

    return InlineKeyboardMarkup(keyboard)


def back_button():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅ MENU", callback_data="MENU")]]
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_state(context)
    init_state(context)

    await update.message.reply_text(
        "Menu:",
        reply_markup=build_main_menu(update.effective_user),
    )


CITY_KEYWORDS = {
    "GDY": ["gdynia", "gdy", "#gdy"],
    "GDA": ["gdansk", "gdańsk", "gda", "#gda"],
    "SOP": ["sopot", "sop", "#sop"],
}


def detect_city(text: str) -> Optional[str]:
    normalized = normalize_for_detection(text)

    for city, keywords in CITY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in normalized:
                return city

    return None
    # ============================================================
# CZĘŚĆ 5/12 – CALLBACK ROUTER (WTS / WTB / WTT ENTRY FLOW)
# ============================================================

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user
    await query.answer()

    init_state(context)

    # ================= MENU =================
    if query.data == "MENU":
        reset_state(context)
        init_state(context)
        await query.edit_message_text(
            "Menu:",
            reply_markup=build_main_menu(user),
        )
        return

    # ================= PANEL =================
    if query.data == "PANEL":
        await panel_callback(update, context)
        return

    # ================= ADMIN PANEL =================
    if query.data == "ADMIN":
        await admin_panel(update, context)
        return

    # ================= WTS START =================
    if query.data == "WTS":

        if not user.username or not RoleManager.is_vendor(user.username.lower()):
            await query.edit_message_text("Brak dostępu.")
            return

        role = "vip" if RoleManager.is_vip(user.username.lower()) else "vendor"
        cooldown_limit = 3 * 3600 if role == "vip" else 6 * 3600

        if time.time() - get_last_post(user.id) < cooldown_limit:
            await query.edit_message_text(
                "Cooldown aktywny.",
                reply_markup=back_button(),
            )
            return

        context.user_data["mode"] = "WTS_COUNT"

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
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # ================= WTS COUNT =================
    if query.data.startswith("WTS_COUNT_"):

        try:
            count = int(query.data.split("_")[2])
        except Exception:
            await query.edit_message_text("Błąd wyboru.")
            return

        if count < 1 or count > 10:
            await query.edit_message_text("Niepoprawna liczba.")
            return

        context.user_data["mode"] = "WTS_INPUT"
        context.user_data["wts_total"] = count
        context.user_data["wts_products"] = []

        await query.edit_message_text(
            "Podaj produkt 1:",
            reply_markup=back_button(),
        )
        return

    # ================= WTB / WTT START =================
    if query.data in ("WTB", "WTT"):

        context.user_data["mode"] = query.data

        await query.edit_message_text(
            f"Wpisz treść ogłoszenia {query.data}:",
            reply_markup=back_button(),
        )
        return

    # ================= CITY SELECT (WTS + WTB/WTT) =================
    if query.data.startswith("CITY_"):

        city = query.data.replace("CITY_", "")
        context.user_data["city"] = city

        if context.user_data.get("mode") == "WTS_INPUT":
            await finalize_wts(update, context)
            return

        if context.user_data.get("mode") in ("WTB", "WTT"):
            await publish_wtb_wtt(update, context)
            return
            # ============================================================
# CZĘŚĆ 6/12 – MESSAGE ROUTER (WTS FLOW + WTB/WTT FLOW)
# ============================================================

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    init_state(context)

    user = update.effective_user
    text = update.message.text

    # ================= ADMIN FLOW =================
    if context.user_data.get("admin_action"):
        await admin_text_handler(update, context)
        return

    # ================= EDIT FLOW =================
    if context.user_data.get("edit_mode"):
        await edit_handler(update, context)
        return

    # ================= WTS INPUT =================
    if context.user_data.get("mode") == "WTS_INPUT":

        if hardcore_price_detect(text):
            await update.message.reply_text(
                "❌ Zakaz podawania cen.",
                reply_markup=back_button(),
            )
            return

        emoji, masked = ultra_detect(text, listing_mode=True)
        context.user_data["wts_products"].append(f"{emoji} {masked}")

        if len(context.user_data["wts_products"]) < context.user_data["wts_total"]:
            next_step = len(context.user_data["wts_products"]) + 1
            await update.message.reply_text(
                f"Podaj produkt {next_step}:",
                reply_markup=back_button(),
            )
            return

        combined = " ".join(context.user_data["wts_products"])
        detected_city = detect_city(combined)

        if detected_city:
            context.user_data["city"] = detected_city
            await finalize_wts(update, context)
            return

        keyboard = [
            [
                InlineKeyboardButton("GDY", callback_data="CITY_GDY"),
                InlineKeyboardButton("GDA", callback_data="CITY_GDA"),
                InlineKeyboardButton("SOP", callback_data="CITY_SOP"),
            ],
            [InlineKeyboardButton("⬅ MENU", callback_data="MENU")],
        ]

        await update.message.reply_text(
            "Wybierz miasto:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # ================= WTB / WTT =================
    if context.user_data.get("mode") in ("WTB", "WTT"):

        mode = context.user_data["mode"]

        if hardcore_price_detect(text):
            await update.message.reply_text("❌ Zakaz cen.")
            return

        last = get_wtb_wtt_last(user.id)
        remaining = WTB_WTT_COOLDOWN - (int(time.time()) - last)

        if remaining > 0:
            await update.message.reply_text(
                f"⏳ Poczekaj {remaining} sekund przed kolejnym ogłoszeniem."
            )
            return

        emoji, masked = ultra_detect(text, listing_mode=True)
        detected_city = detect_city(text)

        context.user_data["temp_listing"] = {
            "mode": mode,
            "emoji": emoji,
            "masked": masked,
        }

        if detected_city:
            context.user_data["city"] = detected_city
            await publish_wtb_wtt(update, context)
            return

        keyboard = [
            [
                InlineKeyboardButton("GDY", callback_data="CITY_GDY"),
                InlineKeyboardButton("GDA", callback_data="CITY_GDA"),
                InlineKeyboardButton("SOP", callback_data="CITY_SOP"),
            ],
            [InlineKeyboardButton("⬅ MENU", callback_data="MENU")],
        ]

        await update.message.reply_text(
            "Wybierz miasto:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return
        # ============================================================
# CZĘŚĆ 7/12 – FINALIZE WTS + PUBLISH WTB/WTT
# ============================================================

def safe_caption(text: str) -> str:
    return text[:1000]


async def finalize_wts(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user.username:
        return

    username = user.username.lower()
    vendor = RoleManager.get_vendor(username)

    if not vendor:
        return

    role = vendor[1]
    city = context.user_data.get("city") or "3CITY"
    content = "\n".join(context.user_data.get("wts_products", []))

    if role == "vip":
        caption = (
            "╔════════════════════╗\n"
            "║   👑 VIP EXCLUSIVE  ║\n"
            "╚════════════════════╝\n\n"
            f"<b>@{html.escape(username)}</b>\n"
            f"<b>📍 {city}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"{content}\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "<b>🔥 INTEREST: 0</b>"
        )
    else:
        caption = (
            "<b>💎 MARKET LISTING</b>\n\n"
            f"<b>@{html.escape(username)}</b>\n"
            f"<b>📍 {city}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"{content}\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "<b>🔥 INTEREST: 0</b>"
        )

    try:
        msg = await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=safe_caption(caption),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]]
            ),
        )
    except Exception:
        logger.exception("WTS publish failed")
        return

    if role == "vip":
        try:
            await context.bot.pin_chat_message(GROUP_ID, msg.message_id)
        except Exception:
            logger.exception("VIP pin failed")

    with db_cursor() as cur:
        cur.execute("""
            UPDATE vendors
            SET posts = posts + 1,
                last_content = ?
            WHERE username=?
        """, (caption, username))

    set_last_post(user.id)
    schedule_auto_delete(context, msg.message_id)
    reset_state(context)

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text="Opublikowano.",
            reply_markup=build_main_menu(user),
        )
    except Exception:
        pass


async def publish_wtb_wtt(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    data = context.user_data.get("temp_listing")

    if not data:
        return

    mode = data["mode"]
    emoji = data["emoji"]
    masked = data["masked"]
    city = context.user_data.get("city") or "3CITY"

    if mode == "WTB":
        title = "🛒 MARKET BUY REQUEST"
        topic = WTB_TOPIC
    else:
        title = "🔁 MARKET TRADE OFFER"
        topic = WTT_TOPIC

    caption = (
        f"<b>{title}</b>\n\n"
        f"<b>📍 {city}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} {masked}\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    try:
        msg = await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=topic,
            photo=LOGO_URL,
            caption=safe_caption(caption),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("WTB/WTT publish failed")
        return

    set_wtb_wtt_last(user.id)
    schedule_auto_delete(context, msg.message_id)
    reset_state(context)

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text="Opublikowano.",
            reply_markup=build_main_menu(user),
        )
    except Exception:
        pass
        # ============================================================
# CZĘŚĆ 7/12 – FINALIZE WTS + PUBLISH WTB/WTT
# ============================================================

def safe_caption(text: str) -> str:
    return text[:1000]


async def finalize_wts(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user.username:
        return

    username = user.username.lower()
    vendor = RoleManager.get_vendor(username)

    if not vendor:
        return

    role = vendor[1]
    city = context.user_data.get("city") or "3CITY"
    content = "\n".join(context.user_data.get("wts_products", []))

    if role == "vip":
        caption = (
            "╔════════════════════╗\n"
            "║   👑 VIP EXCLUSIVE  ║\n"
            "╚════════════════════╝\n\n"
            f"<b>@{html.escape(username)}</b>\n"
            f"<b>📍 {city}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"{content}\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "<b>🔥 INTEREST: 0</b>"
        )
    else:
        caption = (
            "<b>💎 MARKET LISTING</b>\n\n"
            f"<b>@{html.escape(username)}</b>\n"
            f"<b>📍 {city}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"{content}\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "<b>🔥 INTEREST: 0</b>"
        )

    try:
        msg = await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=safe_caption(caption),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]]
            ),
        )
    except Exception:
        logger.exception("WTS publish failed")
        return

    if role == "vip":
        try:
            await context.bot.pin_chat_message(GROUP_ID, msg.message_id)
        except Exception:
            logger.exception("VIP pin failed")

    with db_cursor() as cur:
        cur.execute("""
            UPDATE vendors
            SET posts = posts + 1,
                last_content = ?
            WHERE username=?
        """, (caption, username))

    set_last_post(user.id)
    schedule_auto_delete(context, msg.message_id)
    reset_state(context)

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text="Opublikowano.",
            reply_markup=build_main_menu(user),
        )
    except Exception:
        pass


async def publish_wtb_wtt(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    data = context.user_data.get("temp_listing")

    if not data:
        return

    mode = data["mode"]
    emoji = data["emoji"]
    masked = data["masked"]
    city = context.user_data.get("city") or "3CITY"

    if mode == "WTB":
        title = "🛒 MARKET BUY REQUEST"
        topic = WTB_TOPIC
    else:
        title = "🔁 MARKET TRADE OFFER"
        topic = WTT_TOPIC

    caption = (
        f"<b>{title}</b>\n\n"
        f"<b>📍 {city}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} {masked}\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    try:
        msg = await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=topic,
            photo=LOGO_URL,
            caption=safe_caption(caption),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("WTB/WTT publish failed")
        return

    set_wtb_wtt_last(user.id)
    schedule_auto_delete(context, msg.message_id)
    reset_state(context)

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text="Opublikowano.",
            reply_markup=build_main_menu(user),
        )
    except Exception:
        pass
        # ============================================================
# CZĘŚĆ 8/12 – INTEREST SYSTEM (WTS ONLY) + AUTO DELETE
# ============================================================

INTEREST_RATE_LIMIT: Dict[int, float] = {}


def schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, message_id: int):

    async def delete_job(ctx: ContextTypes.DEFAULT_TYPE):
        try:
            await ctx.bot.delete_message(GROUP_ID, message_id)
        except Exception:
            logger.exception("Auto delete failed")

    context.application.job_queue.run_once(
        delete_job,
        when=172800
    )


async def handle_interest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user
    message = query.message

    await query.answer()

    caption = message.caption or ""

    # Interest obsługiwany tylko dla WTS (musi zawierać @username)
    match = re.search(r"<b>@([a-zA-Z0-9_]+)</b>", caption)
    if not match:
        return

    vendor_username = match.group(1).lower()

    now = time.time()
    last_click = INTEREST_RATE_LIMIT.get(user.id, 0)

    if now - last_click < 3:
        return

    INTEREST_RATE_LIMIT[user.id] = now

    try:
        with db_cursor() as cur:

            cur.execute("""
                INSERT OR IGNORE INTO interests(message_id, user_id, vendor_username)
                VALUES (?, ?, ?)
            """, (message.message_id, user.id, vendor_username))

            inserted = cur.rowcount

            cur.execute("""
                SELECT COUNT(*) FROM interests
                WHERE message_id=?
            """, (message.message_id,))
            count = cur.fetchone()[0]

            if inserted:
                cur.execute("""
                    UPDATE vendors
                    SET interest_total = interest_total + 1
                    WHERE username=?
                """, (vendor_username,))

        new_caption = re.sub(
            r"🔥 INTEREST:\s*\d+",
            f"🔥 INTEREST: {count}",
            caption
        )

        await message.edit_caption(
            caption=new_caption,
            parse_mode=ParseMode.HTML,
        )

    except Exception:
        logger.exception("Interest handling error")
        # ============================================================
# CZĘŚĆ 10/12 – PANEL CALLBACK + EDIT HANDLER
# ============================================================

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

        cooldown_limit = 3 * 3600 if role == "vip" else 6 * 3600

        if time.time() - get_last_post(user.id) < cooldown_limit:
            await query.edit_message_text("Cooldown aktywny.")
            return

        try:
            msg = await context.bot.send_photo(
                chat_id=GROUP_ID,
                message_thread_id=WTS_TOPIC,
                photo=LOGO_URL,
                caption=safe_caption(last_content.replace("🔥 INTEREST:", "🔥 INTEREST: 0")),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔥 INTEREST", callback_data="INTEREST")]]
                ),
            )

            if role == "vip":
                await context.bot.pin_chat_message(GROUP_ID, msg.message_id)

            set_last_post(user.id)
            schedule_auto_delete(context, msg.message_id)

        except Exception:
            logger.exception("Repost failed")
            await query.edit_message_text("Błąd repostu.")
            return

        await query.edit_message_text(
            "Repost wykonany.",
            reply_markup=build_main_menu(user),
        )
        return

    # ================= EDIT =================
    if query.data == "PANEL_EDIT":
        context.user_data["edit_mode"] = True
        await query.edit_message_text(
            "Podaj nową treść ogłoszenia:",
            reply_markup=back_button(),
        )
        return

    # ================= STATS =================
    if query.data == "PANEL_STATS":

        posts = vendor[3]
        interest_total = vendor[7]

        await query.edit_message_text(
            f"📊 Posty: {posts}\n🔥 Łączne interest: {interest_total}",
            reply_markup=back_button(),
        )
        return

    # ================= VIP AUTO =================
    if query.data == "PANEL_AUTO" and role == "vip":

        try:
            with db_cursor() as cur:
                if auto_enabled:
                    cur.execute("""
                        UPDATE vendors SET auto_enabled=0
                        WHERE username=?
                    """, (username,))
                    remove_vip_job(context.application, username)
                    status = "AUTO OFF"
                else:
                    cur.execute("""
                        UPDATE vendors SET auto_enabled=1
                        WHERE username=?
                    """, (username,))
                    schedule_vip_job(context.application, username)
                    status = "AUTO ON"
        except Exception:
            logger.exception("VIP toggle failed")
            await query.edit_message_text("Błąd AUTO.")
            return

        await query.edit_message_text(
            status,
            reply_markup=build_main_menu(user),
        )
        return


async def edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("edit_mode"):
        return

    user = update.effective_user

    if not user.username:
        await update.message.reply_text("Brak username.")
        return

    username = user.username.lower()
    text = update.message.text

    if hardcore_price_detect(text):
        await update.message.reply_text("❌ Zakaz cen.")
        return

    emoji, masked = ultra_detect(text, listing_mode=True)
    city = detect_city(text)

    new_caption = (
        "<b>💎 MARKET LISTING</b>\n\n"
        f"<b>@{username}</b>\n"
        f"<b>📍 {city}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} {masked}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "<b>🔥 INTEREST: 0</b>"
    )

    try:
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET last_content=?, auto_enabled=0
                WHERE username=?
            """, (new_caption, username))

        remove_vip_job(context.application, username)

    except Exception:
        logger.exception("Edit update failed")
        await update.message.reply_text("Błąd edycji.")
        return

    context.user_data["edit_mode"] = False

    await update.message.reply_text(
        "Ogłoszenie zaktualizowane.\nAUTO wyłączone.",
        reply_markup=build_main_menu(user),
    )
    # ============================================================
# CZĘŚĆ 11/12 – ADMIN PANEL + ADMIN FLOW + COMMANDS
# ============================================================

# ================= ADMIN COMMANDS =================

async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not RoleManager.is_admin(user.id):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /addvendor @username")
        return

    username = context.args[0].replace("@", "").lower()
    RoleManager.add_vendor(username, "vendor")

    await update.message.reply_text(f"Dodano vendora: @{username}")


async def cmd_removevendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not RoleManager.is_admin(user.id):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /removevendor @username")
        return

    username = context.args[0].replace("@", "").lower()
    RoleManager.remove_vendor(username)

    await update.message.reply_text(f"Usunięto vendora: @{username}")


async def cmd_makevip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not RoleManager.is_admin(user.id):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /makevip @username")
        return

    username = context.args[0].replace("@", "").lower()
    RoleManager.set_vip(username)

    await update.message.reply_text(f"Nadano VIP: @{username}")


async def cmd_removevip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not RoleManager.is_admin(user.id):
        return

    if not context.args:
        await update.message.reply_text("Użycie: /removevip @username")
        return

    username = context.args[0].replace("@", "").lower()

    with db_cursor() as cur:
        cur.execute("""
            UPDATE vendors
            SET role='vendor', auto_enabled=0
            WHERE username=?
        """, (username,))

    await update.message.reply_text(f"Odebrano VIP: @{username}")


async def cmd_resetcooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not RoleManager.is_admin(user.id):
        return

    with db_cursor() as cur:
        cur.execute("DELETE FROM cooldowns")

    await update.message.reply_text("Cooldown zresetowany.")


# ================= ADMIN PANEL (INLINE) =================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
        [InlineKeyboardButton("🔄 RESET COOLDOWN", callback_data="ADMIN_RMCD")],
        [InlineKeyboardButton("⬅ MENU", callback_data="MENU")],
    ]

    await query.edit_message_text(
        "Admin panel:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not RoleManager.is_admin(user.id):
        return

    action = query.data
    context.user_data["admin_action"] = action

    await query.edit_message_text(
        "Podaj @username:",
        reply_markup=back_button(),
    )


async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    action = context.user_data.get("admin_action")
    if not action:
        return

    username = update.message.text.replace("@", "").strip().lower()

    if not username:
        context.user_data["admin_action"] = None
        await update.message.reply_text("Niepoprawny username.")
        return

    if action == "ADMIN_ADD":
        RoleManager.add_vendor(username, "vendor")

    elif action == "ADMIN_REMOVE":
        RoleManager.remove_vendor(username)

    elif action == "ADMIN_MAKEVIP":
        RoleManager.set_vip(username)

    elif action == "ADMIN_REMVIP":
        with db_cursor() as cur:
            cur.execute("""
                UPDATE vendors
                SET role='vendor', auto_enabled=0
                WHERE username=?
            """, (username,))
        remove_vip_job(context.application, username)

    elif action == "ADMIN_RMCD":
        with db_cursor() as cur:
            cur.execute("DELETE FROM cooldowns")

    context.user_data["admin_action"] = None

    await update.message.reply_text(
        "Wykonano.",
        reply_markup=build_main_menu(update.effective_user),
    )
    # ============================================================
# CZĘŚĆ 12/12 – SYSTEM POSTS + APPLICATION FACTORY + MAIN
# ============================================================

async def system_wts(ctx: ContextTypes.DEFAULT_TYPE):

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 NAPISZ DO ADMINA", url="https://t.me/8482440165")],
        [InlineKeyboardButton("💼 DODAJ OGŁOSZENIE", url=f"https://t.me/{BOT_USERNAME}")]
    ])

    try:
        await ctx.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            text="<b>🔥 CHCESZ ZOSTAĆ VENDOREM?</b>\nNapisz do admina.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception:
        logger.exception("System WTS post failed")


async def system_wtb(ctx: ContextTypes.DEFAULT_TYPE):

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 DODAJ OGŁOSZENIE", url=f"https://t.me/{BOT_USERNAME}")]
    ])

    try:
        await ctx.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=WTB_TOPIC,
            text="<b>🛒 CHCESZ COŚ KUPIĆ?</b>\nDodaj ogłoszenie teraz!",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception:
        logger.exception("System WTB post failed")


async def system_wtt(ctx: ContextTypes.DEFAULT_TYPE):

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 DODAJ OGŁOSZENIE", url=f"https://t.me/{BOT_USERNAME}")]
    ])

    try:
        await ctx.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=WTT_TOPIC,
            text="<b>🔁 CHCESZ COŚ WYMIENIĆ?</b>\nDodaj ogłoszenie teraz!",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception:
        logger.exception("System WTT post failed")


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

    app.add_error_handler(global_error_handler)
    setup_signal_handlers(app)

    return app


def main():

    init_db()
    bootstrap_roles()

    app = create_application()

    # ================= COMMANDS =================
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addvendor", cmd_addvendor))
    app.add_handler(CommandHandler("removevendor", cmd_removevendor))
    app.add_handler(CommandHandler("makevip", cmd_makevip))
    app.add_handler(CommandHandler("removevip", cmd_removevip))
    app.add_handler(CommandHandler("resetcooldown", cmd_resetcooldown))

    # ================= CALLBACKS =================
    app.add_handler(CallbackQueryHandler(handle_interest, pattern="^INTEREST$"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^PANEL"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^ADMIN$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^ADMIN_"))
    app.add_handler(CallbackQueryHandler(callback_router))

    # ================= MESSAGE ROUTER =================
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    # ================= SYSTEM POSTS (6H) =================
    if app.job_queue:
        app.job_queue.run_repeating(system_wts, interval=21600, first=60)
        app.job_queue.run_repeating(system_wtb, interval=21600, first=120)
        app.job_queue.run_repeating(system_wtt, interval=21600, first=180)

    # ================= RESTORE VIP AUTO =================
    restore_vip_jobs(app)

    logger.info("MARKET BOT FINAL STARTED")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
