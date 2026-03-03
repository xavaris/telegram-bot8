import os
import re
import sqlite3
import time
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= ENV =================
# ================= ENV =================
TOKEN = os.getenv("KEY")
GROUP_ID = int(os.getenv("GROUP_ID"))
WTB_TOPIC = int(os.getenv("WTB"))
WTS_TOPIC = int(os.getenv("WTS"))
WTT_TOPIC = int(os.getenv("WTT"))
VIP_TOPIC = int(os.getenv("VIP_TOPIC"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOGO_URL = os.getenv("LOGO_URL")
VIP_LOGO_URL = os.getenv("VIP_LOGO_URL")
BOT_USERNAME = os.getenv("BOT_USERNAME")
VIP_GIF_URL = os.getenv("VIP_GIF_URL")

# ================= FAST POST MEMORY (DODANE) =================
last_ads = {}
# ================= GLOBAL CALLBACK LOCK =================
active_callbacks = set()

active_publications = set()

# ================= VIP AUTO LOCK =================
active_vip_auto = set()

# ================= DATABASE =================
DB_PATH = os.getenv("DB_PATH", "/data/market.db")

db_dir = os.path.dirname(DB_PATH)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS vendors (
    username TEXT PRIMARY KEY,
    added_at TEXT,
    city TEXT,
    options TEXT,
    posts INTEGER DEFAULT 0,
    vip INTEGER DEFAULT 0
)
""")

# Migracja dla istniejących baz (jeśli kolumna vip już jest, to poleci błąd -> ignorujemy)
try:
    cursor.execute("ALTER TABLE vendors ADD COLUMN vip INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS cooldowns (
    user_id INTEGER PRIMARY KEY,
    last_post INTEGER
)
""")

conn.commit()
# ================= LEET MAP =================
CHAR_MAP = {
    "a": "@",
    "e": "€",
    "i": "ı",
    "o": "0",
    "s": "$",
    "t": "τ",
    "z": "Ƶ",
    "u": "Ц",
    "c": "©"
}

REVERSE_LEET = {
    "@": "a",
    "€": "e",
    "ı": "i",
    "0": "o",
    "$": "s",
    "τ": "t",
    "2": "z",
    "ц": "u",
    "©": "c"
}

def smart_mask_caps(text: str) -> str:
    return "".join(CHAR_MAP.get(c.lower(), c) for c in text).upper()

def reverse_leet(text: str) -> str:
    result = ""
    for char in text.lower():
        result += REVERSE_LEET.get(char, char)
    return result

def normalize_text(text: str) -> str:
    text = reverse_leet(text)
    text = text.lower()
    text = text.replace("ł", "l").replace("ó", "o").replace("ą", "a")
    text = text.replace("ę", "e").replace("ś", "s").replace("ż", "z")
    text = text.replace("ź", "z").replace("ć", "c").replace("ń", "n")
    text = re.sub(r"[^a-z0-9]", "", text)
    return text

# ================= ULTRA PRODUCT DETECTION =================
# ================= ULTRA PRODUCT DETECTION =================

def get_product_emoji(name: str) -> str:
    normalized = normalize_text(name)

    product_groups = {

        "📑": [
            "recka", "recepty", "recepta", "recki"
        ],

        "💤": [
            "nasen", "zolpidem", "relanium",
        ],

        "🍁": [
            "klony", "clonozepan", "clony",
        ],
        
        "🇵🇱": [
            "feta", "polak", "krajowa", "ryba", "feciura"
        ],

        "💜": [
            "pix", "pixy", "piksy", "piksi",
            "eksta", "exta", "extasy", "ecstasy",
            "mitsubishi", "lego", "superman", "rolls",
            "pharaoh", "tesla", "bluepunisher", "cukierki"
        ],

        "💎": [
            "mewa", "3cmc", "4mmc", "cmc", "mmc",
            "kryx", "krysztal", "kryształ",
            "crystal", "ice",
            "mefedron", "mefa", "mef", "kamien", "kamień", "bezwonny",
            "m3ff", "ewa"
        ],

        "❄️": [
            "koks", "kokos", "koko",
            "koperta", "coke", "cocaina", "kokaina",
            "biała", "biala", "biały", "bialy",
            "sniff", "kreska", "kreski", "cocos",
            "cocoos", "koper", "k0k0", "c0c0", "k0per",
            "chrzan", 
            
        ],

        "🌿": [
            "weed", "buch", "jazz", "jaaz",
            "trawa", "ziolo", "zielone", "buszek", "haze", "cali"
        ],

        "🍫": [
            "hasz", "haszysz", "czekolada", "haszyk"
        ],

        "💊": [
            "xanax", "alpra", "alprazolam",
            "clonazepam", "rivotril", "diazepam",
            "tabs", "tabsy", "tabletki",
            "pigula", "piguły", "pigułki", "xani", "xanii"
        ],

        "💨": [
            "vape", "vap", "liquid", "liq",
            "pod", "salt", "jednorazowka"
        ],

        "🛢": [
            "cart", "cartridge", "kartridz",
            "wkład", "wklad", "thc cart"
        ],

        "🧴": [
            "perfumy", "perfum", "perfumka",
            "dior", "chanel", "gucci",
            "armani", "versace", "tom ford"
        ],

        "🚬": [
            "epapieros", "e-papieros",
            "epapierosy", "e-papierosy", "epety",
            "e-pety"
        ],

        "✨": [
            "blinker", "blink", "blinkery"
        ],

        "💳": [
            "sim", "starter", "karta sim", "karty sim",
            "starter sim", "esim", "simki"
        ]
    }

    for emoji, keywords in product_groups.items():
        for key in keywords:
            if key in normalized:
                return emoji

    return "📦"
    
    
# ================= ULTRA HARDCORE PRICE DETECTOR V3 =================
def contains_price_hardcore(text: str) -> bool:

    lines = text.split("\n")

    price_pattern_count = 0

    for line in lines:

        clean = reverse_leet(line.lower().strip())
        normalized = re.sub(r"[^a-z0-9\s\-:]", "", clean)

        # ===== WYJĄTKI PRODUKTOWE =====

        # 3cmc / 4mmc / 2cb
        if re.fullmatch(r"\d+(cmc|mmc|cb)", normalized):
            continue

        # dawki 250mg / 250 mg
        if re.search(r"\b\d+\s*mg\b", normalized):
            if not re.search(r"\b\d+\s*mg\b.*\b\d{2,5}\b", normalized):
                continue

        # ===== WYKRYWANIE ILOŚĆ - CENA =====

        # 1 - 50 / 2-100 / 5 - 200
        if re.search(r"\b\d+\s*[-:]\s*\d{2,5}\b", normalized):
            price_pattern_count += 1

        # 1 50
        if re.search(r"\b\d+\s+\d{2,5}\b", normalized):
            price_pattern_count += 1

        # 1g 50
        if re.search(r"\b\d+\s*(g|ml|szt|tabs)\s+\d{2,5}\b", normalized):
            price_pattern_count += 1

        # sama cena
        if re.fullmatch(r"\d{2,5}", normalized):
            price_pattern_count += 1

        # 200 zl
        if re.search(r"\b\d{2,5}\s*(zl|pln|usd|eur|\$|€)\b", normalized):
            price_pattern_count += 1

        # 1 5 0
        if re.search(r"\b\d\s\d\s\d\b", normalized):
            price_pattern_count += 1

    # 🔥 Jeśli wykryto 2 lub więcej wzorców cenowych → blokada
    if price_pattern_count >= 2:
        return True

    return False

# ================= DB HELPERS =================
def get_vendor(username):
    cursor.execute(
        "SELECT username, added_at, city, options, posts, vip FROM vendors WHERE username=?",
        (username,)
    )
    return cursor.fetchone()


def add_vendor(username):
    if get_vendor(username):
        return False
    now = datetime.now().strftime("%d.%m.%Y")
    cursor.execute(
        "INSERT INTO vendors (username, added_at, city, options, posts, vip) VALUES (?,?,?,?,?,?)",
        (username, now, None, None, 0, 0)
    )
    conn.commit()
    return True


def remove_vendor(username):
    cursor.execute("DELETE FROM vendors WHERE username=?", (username,))
    conn.commit()


def list_vendors():
    cursor.execute("SELECT username, added_at, posts, vip FROM vendors")
    return cursor.fetchall()


def update_vendor_settings(username, city, options):
    cursor.execute(
        "UPDATE vendors SET city=?, options=? WHERE username=?",
        (city, ",".join(options), username)
    )
    conn.commit()


def increment_posts(username):
    cursor.execute(
        "UPDATE vendors SET posts = posts + 1 WHERE username=?",
        (username,)
    )
    conn.commit()


def is_vip_vendor(username: str) -> bool:
    row = get_vendor(username)
    if not row:
        return False
    # row: (username, added_at, city, options, posts, vip)
    return bool(int(row[5]))


def set_vip_vendor(username: str, vip: bool = True) -> bool:
    if not get_vendor(username):
        return False
    cursor.execute(
        "UPDATE vendors SET vip=? WHERE username=?",
        (1 if vip else 0, username)
    )
    conn.commit()
    return True


def get_last_post(user_id):
    cursor.execute("SELECT last_post FROM cooldowns WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0


def set_last_post(user_id):
    cursor.execute("""
        INSERT INTO cooldowns(user_id,last_post)
        VALUES(?,?)
        ON CONFLICT(user_id)
        DO UPDATE SET last_post=excluded.last_post
    """, (user_id, int(time.time())))
    conn.commit()


def clear_all_cooldowns():
    cursor.execute("DELETE FROM cooldowns")
    conn.commit()
    


# ================= SUPER VIP TEMPLATE =================
def vip_template(username, content, vendor_data, city, options, shop_link=None, legit_link=None):

    option_text = ""
    if options:
        option_text = " | " + " | ".join(options)

    # ===== GOLD LINKS SECTION =====
    links_block = ""
    if shop_link or legit_link:

        links_block = "\n"
        links_block += "✨ <b>PRIVATE ACCESS</b>\n"

        if shop_link:
            links_block += f'📸 <b><a href="{shop_link}">OFICJALNA GALERIA</a></b>\n'

        if legit_link:
            links_block += f'🛡 <b><a href="{legit_link}">GRUPA WERYFIKACYJNA</a></b>\n'

    return (
        "✨👑 <b>GOLD VENDOR COLLECTION</b> 👑✨\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🏛 <b>EXCLUSIVE VERIFIED SELLER</b>\n"
        f"🗓 <b>Member since:</b> {vendor_data[1]}\n"
        f"📊 <b>Published offers:</b> {vendor_data[4]}\n\n"

        f"👤 <b>@{username}</b>\n"
        f"📍 <b>{city}{option_text} | #3CITY</b>\n"
        f"{links_block}\n"

        "━━━━━━━━━━━━━━━━━━\n"
        f"{content}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "💫 <b>Premium Quality</b>\n"
        "⚜️ <b>Discretion • Reputation • Prestige</b>"
    )
    
# ================= AUTO SYSTEM =================
async def auto_messages(context: ContextTypes.DEFAULT_TYPE):

    # ===== WTS =====
    keyboard_wts = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📞 NAPISZ DO ADMINA",
                url=f"https://t.me/{os.getenv('ADMIN_USERNAME')}"
            )
        ],
        [
            InlineKeyboardButton(
                "💼 DODAJ OGŁOSZENIE",
                url=f"https://t.me/{BOT_USERNAME}?start=wts"
            )
        ]
    ])

    await context.bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=WTS_TOPIC,
        text="<b>🔥 CHCESZ ZOSTAĆ VENDOREM?</b>\nVENDOR JEST DARMOWY (OKRES TESTOWY)",
        parse_mode="HTML",
        reply_markup=keyboard_wts
    )

    # ===== WTB =====
    keyboard_wtb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛒 DODAJ OGŁOSZENIE",
                url=f"https://t.me/{BOT_USERNAME}?start=wtb"
            )
        ]
    ])

    await context.bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=WTB_TOPIC,
        text="<b>🔎 CHCESZ COŚ KUPIĆ?</b>\nDodaj ogłoszenie poniżej 👇",
        parse_mode="HTML",
        reply_markup=keyboard_wtb
    )

    # ===== WTT =====
    keyboard_wtt = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔁 DODAJ OGŁOSZENIE",
                url=f"https://t.me/{BOT_USERNAME}?start=wtt"
            )
        ]
    ])

    await context.bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=WTT_TOPIC,
        text="<b>🔁 CHCESZ COŚ WYMIENIĆ?</b>\nDodaj ogłoszenie poniżej 👇",
        parse_mode="HTML",
        reply_markup=keyboard_wtt
    )


# ================= VIP AUTO POST SYSTEM =================
async def vip_auto_post(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data

    username = data.get("username")
    ad_data = data.get("ad_data")

    if not username or not ad_data:
        return

    city_map = {
        "CITY_GDY": "#GDY",
        "CITY_GDA": "#GDA",
        "CITY_SOP": "#SOP"
    }

    option_map = {
        "OPT_DOLOT": "#DOLOT",
        "OPT_UBER": "#UBERPAKA",
        "OPT_H2H": "#H2H"
    }

    city = city_map.get(ad_data.get("city"))

    options = [
        option_map[o]
        for o in ad_data.get("options", [])
        if o in option_map
    ]

    content = "\n".join(
        f"{get_product_emoji(p)} {smart_mask_caps(p)}"
        for p in ad_data.get("products", [])
    )

    caption = vip_template(
        username=username,
        content=content,
        vendor_data=get_vendor(username),
        city=city,
        options=options,
        shop_link=ad_data.get("shop_link"),
        legit_link=ad_data.get("legit_link")
    )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 KONTAKT Z VENDOREM", url=f"https://t.me/{username}")]
    ])

    await context.bot.send_animation(
        chat_id=GROUP_ID,
        message_thread_id=VIP_TOPIC,
        animation=VIP_GIF_URL,
        caption=caption,
        parse_mode="HTML",
        reply_markup=reply_markup
    )
    
# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    args = context.args

    if args:
        if args[0] == "wts":
            context.user_data["type"] = "WTS"
        elif args[0] == "wtb":
            context.user_data["type"] = "WTB"
        elif args[0] == "wtt":
            context.user_data["type"] = "WTT"

    keyboard = [[
        InlineKeyboardButton("🛒 WTB", callback_data="WTB"),
        InlineKeyboardButton("💼 WTS", callback_data="WTS"),
        InlineKeyboardButton("🔁 WTT", callback_data="WTT"),
    ]]

    user = update.effective_user

    # ✅ VIP VENDOR przycisk (tylko jeśli vendor ma vip=1)
    if user.username and is_vip_vendor(user.username.lower()):
        keyboard.append([
            InlineKeyboardButton("💎 VIP VENDOR", callback_data="VIP_PANEL")
        ])

    # ✅ ADMIN PANEL (tylko dla admina)
    if user.id == ADMIN_ID:
        keyboard.append([
            InlineKeyboardButton("⚙ ADMIN PANEL", callback_data="ADMIN")
        ])

    await update.message.reply_text(
        "<b>WYBIERZ TYP OGŁOSZENIA:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= ADMIN COMMANDS =================
# ================= ADMIN COMMANDS =================

async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "<b>UŻYJ:</b> /addvendor @username",
            parse_mode="HTML"
        )
        return

    username = context.args[0].replace("@", "").strip().lower()

    if not re.fullmatch(r"[a-zA-Z0-9_]{5,32}", username):
        await update.message.reply_text("<b>❌ ZŁY USERNAME.</b>", parse_mode="HTML")
        return

    if add_vendor(username):
        await update.message.reply_text("<b>✅ VENDOR DODANY.</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("<b>⚠️ VENDOR JUŻ ISTNIEJE.</b>", parse_mode="HTML")


async def cmd_addvendors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "<b>UŻYJ:</b> /addvendors user1,user2,user3",
            parse_mode="HTML"
        )
        return

    raw = " ".join(context.args)
    usernames = re.split(r"[,\s]+", raw)

    added = []
    skipped = []

    for name in usernames:
        username = name.replace("@", "").strip().lower()

        if not re.fullmatch(r"[a-zA-Z0-9_]{5,32}", username):
            skipped.append(name)
            continue

        if add_vendor(username):
            added.append(username)
        else:
            skipped.append(username)

    msg = ""
    if added:
        msg += "✅ <b>DODANO:</b>\n" + "\n".join(f"@{u}" for u in added) + "\n\n"
    if skipped:
        msg += "⚠️ <b>POMINIĘTO:</b>\n" + "\n".join(f"@{u}" for u in skipped)

    await update.message.reply_text(msg or "<b>BRAK ZMIAN.</b>", parse_mode="HTML")


async def cmd_removevendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "<b>UŻYJ:</b> /removevendor @username",
            parse_mode="HTML"
        )
        return

    username = context.args[0].replace("@", "").strip().lower()

    if not get_vendor(username):
        await update.message.reply_text("<b>❌ Taki vendor nie istnieje.</b>", parse_mode="HTML")
        return

    remove_vendor(username)
    await update.message.reply_text("<b>🗑 VENDOR USUNIĘTY.</b>", parse_mode="HTML")


async def cmd_listvendors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    vendors = list_vendors()

    if not vendors:
        await update.message.reply_text("<b>BRAK VENDORÓW.</b>", parse_mode="HTML")
        return

    text = ""

    for v in vendors:
        vip_badge = " 💎VIP" if int(v[3]) == 1 else ""
        text += f"<b>@{v[0]}</b>{vip_badge} | OD {v[1]} | OGŁOSZEŃ: {v[2]}\n"

    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_setvip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "<b>UŻYJ:</b> /setvip @username",
            parse_mode="HTML"
        )
        return

    username = context.args[0].replace("@", "").strip().lower()

    if not re.fullmatch(r"[a-zA-Z0-9_]{5,32}", username):
        await update.message.reply_text("<b>❌ ZŁY USERNAME.</b>", parse_mode="HTML")
        return

    if not get_vendor(username):
        await update.message.reply_text("<b>❌ Vendor nie istnieje.</b>", parse_mode="HTML")
        return

    set_vip_vendor(username, True)

    await update.message.reply_text(
        f"<b>💎 VIP NADANY:</b> @{username}",
        parse_mode="HTML"
    )


async def cmd_unsetvip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "<b>UŻYJ:</b> /unsetvip @username",
            parse_mode="HTML"
        )
        return

    username = context.args[0].replace("@", "").strip().lower()

    if not re.fullmatch(r"[a-zA-Z0-9_]{5,32}", username):
        await update.message.reply_text("<b>❌ ZŁY USERNAME.</b>", parse_mode="HTML")
        return

    if not get_vendor(username):
        await update.message.reply_text("<b>❌ Vendor nie istnieje.</b>", parse_mode="HTML")
        return

    set_vip_vendor(username, False)

    await update.message.reply_text(
        f"<b>❌ VIP USUNIĘTY:</b> @{username}",
        parse_mode="HTML"
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    keyboard = [
        [InlineKeyboardButton("➕ DODAJ VENDORA", callback_data="ADD_VENDOR")],
        [InlineKeyboardButton("➖ USUŃ VENDORA", callback_data="REMOVE_VENDOR")],
        [InlineKeyboardButton("📋 LISTA VENDORÓW", callback_data="LIST_VENDOR")],
        [InlineKeyboardButton("❌ USUŃ COOLDOWN", callback_data="CLEAR_CD")]
    ]

    await query.edit_message_text(
        "<b>PANEL ADMINA</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def vip_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if not user.username or not is_vip_vendor(user.username.lower()):
        await query.edit_message_text("<b>BRAK DOSTĘPU.</b>", parse_mode="HTML")
        return

    vendor = get_vendor(user.username.lower())
    posts = vendor[4] if vendor else 0
    since = vendor[1] if vendor else "-"

    active_jobs = context.job_queue.get_jobs_by_name(f"vip_auto_{user.id}")
    auto_status = "🟢 AKTYWNY" if active_jobs else "🔴 WYŁĄCZONY"

    keyboard = [
        [InlineKeyboardButton("🚀 AUTO START (6H)", callback_data="VIP_AUTO_START")],
        [InlineKeyboardButton("🛑 AUTO STOP", callback_data="VIP_AUTO_STOP")],
        [InlineKeyboardButton("📊 MOJE STATY", callback_data="VIP_STATS")],
        [InlineKeyboardButton("⬅️ WSTECZ", callback_data="VIP_BACK_START")]
    ]

    await query.edit_message_text(
        f"<b>💎 VIP VENDOR PANEL</b>\n\n"
        f"<b>👤 @{user.username}</b>\n"
        f"<b>🗓 OD:</b> {since}\n"
        f"<b>📊 OGŁOSZEŃ:</b> {posts}\n\n"
        f"<b>AUTO POST:</b> {auto_status}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
# ================= CALLBACK HANDLER =================
# ================= CALLBACK HANDLER =================
# ================= CALLBACK HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user = query.from_user

    # 🔒 GLOBAL CALLBACK LOCK
    if user.id in active_callbacks:
        await query.answer()
        return

    active_callbacks.add(user.id)

    try:
        await query.answer()

        if query.data == "VIP_SKIP_SHOP":
            context.user_data.pop("awaiting_shop", None)
            context.user_data["awaiting_legit"] = True
    
            await query.edit_message_text(
                "<b>🔗 PODAJ LINK DO LEGIT CHECK (GRUPA TELEGRAM)</b>\n\n"
                "Np: https://t.me/twojagrupa\n"
                "Możesz też kliknąć POMIŃ.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏭ POMIŃ", callback_data="VIP_SKIP_LEGIT")]
                ])
            )
            return
    
    
        # ================= VIP SKIP LEGIT =================
        if query.data == "VIP_SKIP_LEGIT":
            context.user_data.pop("awaiting_legit", None)
            await finalize_publish(update, context)
        
            await query.edit_message_text(
                "<b>✅ OGŁOSZENIE OPUBLIKOWANE</b>",
                parse_mode="HTML"
            )
            return
            
        # ================= VIP PANEL =================
        if query.data == "VIP_PANEL":
            await vip_panel(update, context)
            return
    
        if query.data == "VIP_STATS":
            if not user.username or not is_vip_vendor(user.username.lower()):
                await query.edit_message_text("<b>BRAK DOSTĘPU.</b>", parse_mode="HTML")
                return
    
            vendor = get_vendor(user.username.lower())
            posts = vendor[4] if vendor else 0
            since = vendor[1] if vendor else "-"
    
            await query.edit_message_text(
                f"<b>📊 VIP STATY</b>\n\n"
                f"<b>👤 @{user.username}</b>\n"
                f"<b>🗓 OD:</b> {since}\n"
                f"<b>📊 OGŁOSZEŃ:</b> {posts}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ WSTECZ", callback_data="VIP_PANEL")]
                ])
            )
            return
    
        # ================= VIP AUTO START =================
        if query.data == "VIP_AUTO_START":

            if user.id in active_vip_auto:
                return

            active_vip_auto.add(user.id)

            try:

                if not user.username or not is_vip_vendor(user.username.lower()):
                    await query.answer("Brak dostępu.", show_alert=True)
                    return

                ad_data = last_ads.get(user.id)

                if not ad_data:
                    await query.answer("Najpierw opublikuj ogłoszenie.", show_alert=True)
                    return

                old_jobs = context.job_queue.get_jobs_by_name(f"vip_auto_{user.id}")
                for job in old_jobs:
                    job.schedule_removal()

                username = user.username.lower()

                city_map = {
                    "CITY_GDY": "#GDY",
                    "CITY_GDA": "#GDA",
                    "CITY_SOP": "#SOP"
                }

                option_map = {
                    "OPT_DOLOT": "#DOLOT",
                    "OPT_UBER": "#UBERPAKA",
                    "OPT_H2H": "#H2H"
                }

                city = city_map.get(ad_data.get("city"))

                options = [
                    option_map[o]
                    for o in ad_data.get("options", [])
                    if o in option_map
                ]

                content = "\n".join(
                    f"{get_product_emoji(p)} {smart_mask_caps(p)}"
                    for p in ad_data.get("products", [])
                )

                caption = vip_template(
                    username=username,
                    content=content,
                    vendor_data=get_vendor(username),
                    city=city,
                    options=options,
                    shop_link=ad_data.get("shop_link"),
                    legit_link=ad_data.get("legit_link")
                )

                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📩 KONTAKT Z VENDOREM", url=f"https://t.me/{username}")]
                ])

                await context.bot.send_animation(
                    chat_id=GROUP_ID,
                    message_thread_id=VIP_TOPIC,
                    animation=VIP_GIF_URL,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )

                context.job_queue.run_repeating(
                    vip_auto_post,
                    interval=21600,
                    first=21600,
                    name=f"vip_auto_{user.id}",
                    data={
                        "username": username,
                        "ad_data": ad_data
                    }
                )

                await query.answer("AUTO START WŁĄCZONY 🚀")
                await vip_panel(update, context)

            finally:
                active_vip_auto.discard(user.id)

            return


        # ================= VIP AUTO STOP =================
        if query.data == "VIP_AUTO_STOP":

            if not user.username or not is_vip_vendor(user.username.lower()):
                await query.answer("Brak dostępu.", show_alert=True)
                return

            jobs = context.job_queue.get_jobs_by_name(f"vip_auto_{user.id}")

            if not jobs:
                await query.answer("AUTO już wyłączony.", show_alert=True)
                await vip_panel(update, context)
                return

            for job in jobs:
                job.schedule_removal()

            await query.answer("AUTO STOP WYŁĄCZONY 🛑")
            await vip_panel(update, context)
            return
            
        # ================= VIP BACK =================
        if query.data == "VIP_BACK_START":
            keyboard = [[
                InlineKeyboardButton("🛒 WTB", callback_data="WTB"),
                InlineKeyboardButton("💼 WTS", callback_data="WTS"),
                InlineKeyboardButton("🔁 WTT", callback_data="WTT"),
            ]]
    
            if user.username and is_vip_vendor(user.username.lower()):
                keyboard.append([InlineKeyboardButton("💎 VIP VENDOR", callback_data="VIP_PANEL")])
    
            if user.id == ADMIN_ID:
                keyboard.append([InlineKeyboardButton("⚙ ADMIN PANEL", callback_data="ADMIN")])
    
            await query.edit_message_text(
                "<b>WYBIERZ TYP OGŁOSZENIA:</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        # ================= ADMIN PANEL =================
        if query.data == "ADMIN" and user.id == ADMIN_ID:
            await admin_panel(update, context)
            return
    
        if query.data == "CLEAR_CD" and user.id == ADMIN_ID:
            clear_all_cooldowns()
            await query.edit_message_text("<b>COOLDOWNY USUNIĘTE.</b>", parse_mode="HTML")
            return
    
        if query.data == "LIST_VENDOR" and user.id == ADMIN_ID:
            vendors = list_vendors()
            text = ""
            for v in vendors:
                vip_badge = " 💎VIP" if len(v) >= 4 and int(v[3]) == 1 else ""
                text += f"<b>@{v[0]}</b>{vip_badge} | OD {v[1]} | OGŁOSZEŃ: {v[2]}\n"
            await query.edit_message_text(text or "<b>BRAK.</b>", parse_mode="HTML")
            return
    
        if query.data in ["ADD_VENDOR", "REMOVE_VENDOR"] and user.id == ADMIN_ID:
            context.user_data["admin_action"] = query.data
            await query.edit_message_text("<b>PODAJ @USERNAME:</b>", parse_mode="HTML")
            return
    
        # ================= FAST POST =================
        # ================= FAST POST =================
        if query.data == "FAST_POST":

            if time.time() - get_last_post(user.id) < 6 * 60 * 60:
                await query.answer("COOLDOWN 6H.", show_alert=True)
                return

            data = last_ads.get(user.id)

            if not data:
                await query.edit_message_text(
                    "<b>BRAK ZAPISANEGO OGŁOSZENIA.</b>",
                    parse_mode="HTML"
                )
                return

            # 🔥 ODBUDOWUJEMY PEŁEN STAN WTS
            context.user_data["type"] = "WTS"
            context.user_data["wts_products"] = list(data.get("products", []))
            context.user_data["city"] = data.get("city")
            context.user_data["options"] = list(data.get("options", []))
            context.user_data["shop_link"] = data.get("shop_link")
            context.user_data["legit_link"] = data.get("legit_link")

            await finalize_publish(update, context)
    
            await query.edit_message_text(
                "<b>✅ OGŁOSZENIE OPUBLIKOWANE</b>",
                parse_mode="HTML"
            )
    
            return
    
        # ================= NOWE WTS =================
        if query.data == "NEW_WTS":
            if not user.username:
                await query.edit_message_text(
                    "<b>❌ Aby publikować WTS musisz ustawić @username.</b>",
                    parse_mode="HTML"
                )
                return
    
            context.user_data["vendor"] = get_vendor(user.username.lower())
            await ask_product_count(query)
            return
    
        # ================= SIM NETWORK SELECTION =================
        if query.data.startswith("NET_"):
            if not context.user_data.get("selecting_sim_network"):
                return
    
            network_map = {
                "NET_PLAY": "🟣 Play",
                "NET_ORANGE": "🟠 Orange",
                "NET_PLUS": "🟢 Plus",
                "NET_TMOBILE": "🔴 T-Mobile",
                "NET_HEYAH": "🔺 Heyah",
                "NET_NJU": "🟧 Nju Mobile",
                "NET_VIRGIN": "🟣 Virgin Mobile",
                "NET_LYCA": "🔵 LycaMobile",
                "NET_VIKINGS": "⚔️ Mobile Vikings",
                "NET_PREMIUM": "⭐ Premium Mobile",
                "NET_A2": "🅰️ A2Mobile",
                "NET_FAKT": "📰 Fakt Mobile",
                "NET_BIEDRONKA": "🛒 Biedronka Mobile"
            }
    
            if query.data == "NET_DONE":
                selected = context.user_data.get("selected_networks", [])
    
                if not selected:
                    await query.answer("Wybierz przynajmniej 1 sieć ❗", show_alert=True)
                    return
    
                product_name = context.user_data.get("pending_sim_product")
                network_text = " | ".join(selected)
    
                full_product = f"{product_name} | {network_text}"
                context.user_data["wts_products"].append(full_product)
    
                context.user_data.pop("selecting_sim_network", None)
                context.user_data.pop("pending_sim_product", None)
                context.user_data.pop("selected_networks", None)
    
                if len(context.user_data["wts_products"]) < context.user_data["wts_total"]:
                    await query.edit_message_text(
                        f"<b>PODAJ PRODUKT {len(context.user_data['wts_products'])+1}:</b>",
                        parse_mode="HTML"
                    )
                    return
    
                keyboard = [
                    [InlineKeyboardButton("GDY", callback_data="CITY_GDY")],
                    [InlineKeyboardButton("GDA", callback_data="CITY_GDA")],
                    [InlineKeyboardButton("SOP", callback_data="CITY_SOP")]
                ]
    
                await query.edit_message_text(
                    "<b>WYBIERZ MIASTO:</b>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
    
            network = network_map.get(query.data)
            if not network:
                return
    
            selected = context.user_data.get("selected_networks", [])
    
            if network in selected:
                selected.remove(network)
                await query.answer("Usunięto ❌")
            else:
                selected.append(network)
                await query.answer("Dodano ✅")
            return
    
        # ================= WTS =================
        if query.data == "WTS":
            if not user.username:
                await query.edit_message_text("<b>USTAW USERNAME.</b>", parse_mode="HTML")
                return
    
            vendor = get_vendor(user.username.lower())
            if not vendor:
                await query.edit_message_text("<b>TYLKO VENDOR.</b>", parse_mode="HTML")
                return
    
            if time.time() - get_last_post(user.id) < 6 * 60 * 60:
                await query.edit_message_text("<b>COOLDOWN 6H.</b>", parse_mode="HTML")
                return
    
            context.user_data["vendor"] = vendor
            keyboard = []
    
            if user.id in last_ads:
                keyboard.append([InlineKeyboardButton("🚀 POST (Wyślij to samo)", callback_data="FAST_POST")])
    
            keyboard.append([InlineKeyboardButton("➕ NOWE OGŁOSZENIE", callback_data="NEW_WTS")])
    
            await query.edit_message_text(
                "<b>PANEL WTS</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
        if query.data.startswith("CNT_"):
            context.user_data["wts_total"] = int(query.data.split("_")[1])
            context.user_data["wts_products"] = []
            await query.edit_message_text("<b>PODAJ PRODUKT 1:</b>", parse_mode="HTML")
            return
    
        # ================= CITY SELECTION =================
        if query.data in ["CITY_GDY", "CITY_GDA", "CITY_SOP"]:
            has_wts_flow = "wts_total" in context.user_data or "wts_products" in context.user_data
            has_text_flow = "type" in context.user_data and "content" in context.user_data
    
            if not has_wts_flow and not has_text_flow:
                await query.answer("To menu jest nieaktywne. Zacznij od /start.", show_alert=True)
                return
    
            context.user_data["city"] = query.data
            context.user_data["options"] = []
    
            keyboard = [
                [InlineKeyboardButton("✈️ DOLOT", callback_data="OPT_DOLOT")],
                [InlineKeyboardButton("🚗 UBER PAKA", callback_data="OPT_UBER")],
                [InlineKeyboardButton("🤝 H2H", callback_data="OPT_H2H")],
                [InlineKeyboardButton("❌ BRAK", callback_data="OPT_BRAK")],
                [InlineKeyboardButton("✅ PUBLIKUJ", callback_data="OPT_DONE")]
            ]
    
            await query.edit_message_text(
                "<b>WYBIERZ OPCJE:</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
        if query.data in ["OPT_DOLOT", "OPT_UBER", "OPT_H2H"]:
            if query.data not in context.user_data.get("options", []):
                context.user_data.setdefault("options", []).append(query.data)
            return
    
        if query.data == "OPT_BRAK":
            context.user_data["options"] = []
            return
    
        # ================= OPT DONE =================
        if query.data == "OPT_DONE":

            # 🔥 USUWAMY PRZYCISKI I POKAZUJEMY LOADING
            await query.edit_message_text(
                "<b>⏳ Publikuję ogłoszenie...</b>",
                parse_mode="HTML"
            )

            # 🔥 LINKI TYLKO DLA VIP WTS
            if (
                "wts_products" in context.user_data
                and user.username
                and is_vip_vendor(user.username.lower())
            ):
                context.user_data["awaiting_shop"] = True

                await query.edit_message_text(
                    "<b>🔗 PODAJ LINK DO SKLEPU (telegra.ph)</b>\n\n"
                    "Możesz też kliknąć POMIŃ.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⏭ POMIŃ", callback_data="VIP_SKIP_SHOP")]
                    ])
                )
                return

            await finalize_publish(update, context)

            # 🔥 EDYTUJEMY WIADOMOŚĆ NA SUKCES
            await query.edit_message_text(
                "<b>✅ OGŁOSZENIE OPUBLIKOWANE</b>",
                parse_mode="HTML"
            )

            return
    
        # ================= WTB / WTT =================
        if query.data in ["WTB", "WTT"]:
            if not user.username:
                await query.edit_message_text(
                    "<b>❌ Aby dodać ogłoszenie musisz ustawić @username w Telegramie.</b>",
                    parse_mode="HTML"
                )
                return
    
            context.user_data["type"] = query.data
            await query.edit_message_text("<b>NAPISZ TREŚĆ:</b>", parse_mode="HTML")

    finally:
        active_callbacks.discard(user.id)
    
# ================= MESSAGE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    text = update.message.text

    # ADMIN ACTION
    if user.id == ADMIN_ID and "admin_action" in context.user_data:
        username = text.replace("@", "").lower()
        if context.user_data["admin_action"] == "ADD_VENDOR":
            add_vendor(username)
            await update.message.reply_text("<b>DODANO.</b>", parse_mode="HTML")
        else:
            remove_vendor(username)
            await update.message.reply_text("<b>USUNIĘTO.</b>", parse_mode="HTML")
        context.user_data.clear()
        return
            # ================= VIP SHOP LINK =================
    if context.user_data.get("awaiting_shop"):
        link = text.strip()

        if not link.startswith("https://telegra.ph/"):
            await update.message.reply_text(
                "<b>❌ Link musi być z telegra.ph</b>",
                parse_mode="HTML"
            )
            return

        context.user_data["shop_link"] = link
        context.user_data.pop("awaiting_shop")

        context.user_data["awaiting_legit"] = True

        await update.message.reply_text(
            "<b>🔗 PODAJ LINK DO LEGIT CHECK (GRUPA TELEGRAM)</b>\n\n"
            "Np: https://t.me/twojagrupa\n"
            "Możesz też kliknąć POMIŃ.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ POMIŃ", callback_data="VIP_SKIP_LEGIT")]
            ])
        )
        return

    # ================= VIP LEGIT LINK =================
    if context.user_data.get("awaiting_legit"):
        link = text.strip()
    
        if not link.startswith("https://t.me/"):
            await update.message.reply_text(
                "<b>❌ Link musi być do grupy Telegram (https://t.me/...)</b>",
                parse_mode="HTML"
            )
            return
    
        context.user_data["legit_link"] = link
        context.user_data.pop("awaiting_legit")
    
        await finalize_publish(update, context)
    
        await update.message.reply_text(
            "<b>✅ OGŁOSZENIE OPUBLIKOWANE</b>",
            parse_mode="HTML"
        )
        return
    # ================= WTS PRODUCTS =================
    if "wts_total" in context.user_data:

        if contains_price_hardcore(text):
            await update.message.reply_text(
                "<b>❌ ZAKAZ PODAWANIA CEN.</b>",
                parse_mode="HTML"
            )
            return

        # 🔥 BEZPIECZNE SPRAWDZENIE EMOJI PRODUKTU
        try:
            product_emoji = get_product_emoji(text)
        except NameError:
            product_emoji = "📦"

        # 🔥 JEŚLI TO SIM → WYBÓR SIECI
        if product_emoji == "💳":

            context.user_data["selecting_sim_network"] = True
            context.user_data["pending_sim_product"] = text
            context.user_data["selected_networks"] = []

            keyboard = [
                [
                    InlineKeyboardButton("🟣 Play", callback_data="NET_PLAY"),
                    InlineKeyboardButton("🟠 Orange", callback_data="NET_ORANGE")
                ],
                [
                    InlineKeyboardButton("🟢 Plus", callback_data="NET_PLUS"),
                    InlineKeyboardButton("🔴 T-Mobile", callback_data="NET_TMOBILE")
                ],
                [
                    InlineKeyboardButton("🔺 Heyah", callback_data="NET_HEYAH"),
                    InlineKeyboardButton("🟧 Nju", callback_data="NET_NJU")
                ],
                [
                    InlineKeyboardButton("🟣 Virgin", callback_data="NET_VIRGIN"),
                    InlineKeyboardButton("🔵 Lyca", callback_data="NET_LYCA")
                ],
                [
                    InlineKeyboardButton("⚔️ Vikings", callback_data="NET_VIKINGS"),
                    InlineKeyboardButton("⭐ Premium", callback_data="NET_PREMIUM")
                ],
                [
                    InlineKeyboardButton("🅰️ A2Mobile", callback_data="NET_A2"),
                    InlineKeyboardButton("📰 Fakt Mobile", callback_data="NET_FAKT")
                ],
                [
                    InlineKeyboardButton("🛒 Biedronka Mobile", callback_data="NET_BIEDRONKA")
                ],
                [
                    InlineKeyboardButton("➡️ DALEJ", callback_data="NET_DONE")
                ]
            ]

            await update.message.reply_text(
                "<b>📡 WYBIERZ SIECI (MIN. 1):</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # NORMALNY PRODUKT
        context.user_data["wts_products"].append(text)

        if len(context.user_data["wts_products"]) < context.user_data["wts_total"]:
            await update.message.reply_text(
                f"<b>PODAJ PRODUKT {len(context.user_data['wts_products'])+1}:</b>",
                parse_mode="HTML"
            )
            return

        keyboard = [
            [InlineKeyboardButton("GDY", callback_data="CITY_GDY")],
            [InlineKeyboardButton("GDA", callback_data="CITY_GDA")],
            [InlineKeyboardButton("SOP", callback_data="CITY_SOP")]
        ]

        await update.message.reply_text(
            "<b>WYBIERZ MIASTO:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= WTB / WTT TEXT =================
    if "type" in context.user_data:
        context.user_data["content"] = text

        keyboard = [
            [InlineKeyboardButton("GDY", callback_data="CITY_GDY")],
            [InlineKeyboardButton("GDA", callback_data="CITY_GDA")],
            [InlineKeyboardButton("SOP", callback_data="CITY_SOP")]
        ]

        await update.message.reply_text(
            "<b>WYBIERZ MIASTO:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ================= ASK PRODUCT COUNT =================
# ================= ASK PRODUCT COUNT =================
async def ask_product_count(query):

    keyboard = [
        [
            InlineKeyboardButton("1", callback_data="CNT_1"),
            InlineKeyboardButton("2", callback_data="CNT_2"),
            InlineKeyboardButton("3", callback_data="CNT_3"),
            InlineKeyboardButton("4", callback_data="CNT_4"),
            InlineKeyboardButton("5", callback_data="CNT_5"),
        ],
        [
            InlineKeyboardButton("6", callback_data="CNT_6"),
            InlineKeyboardButton("7", callback_data="CNT_7"),
            InlineKeyboardButton("8", callback_data="CNT_8"),
            InlineKeyboardButton("9", callback_data="CNT_9"),
            InlineKeyboardButton("10", callback_data="CNT_10"),
        ]
    ]

    await query.edit_message_text(
        "<b>ILE PRODUKTÓW CHCESZ DODAĆ?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
# ================= FINALIZE PUBLISH =================
# ================= FINALIZE PUBLISH =================
async def finalize_publish(update, context):

    user = update.effective_user

    if not user:
        return

    if not user.username:
        await user.send_message("❌ Musisz mieć ustawiony @username.")
        return

    username = user.username.lower()

    if user.id in active_publications:
        return

    active_publications.add(user.id)

    try:
        print("=== FINALIZE START ===")

        city_map = {
            "CITY_GDY": "#GDY",
            "CITY_GDA": "#GDA",
            "CITY_SOP": "#SOP"
        }

        option_map = {
            "OPT_DOLOT": "#DOLOT",
            "OPT_UBER": "#UBERPAKA",
            "OPT_H2H": "#H2H"
        }

        city_key = context.user_data.get("city")
        city = city_map.get(city_key)

        options_raw = context.user_data.get("options", [])
        options = [option_map[o] for o in options_raw if o in option_map]

        post_type = context.user_data.pop("type", None)

        print("POST TYPE:", post_type)
        print("CITY:", city)
        print("OPTIONS:", options)

        if not city:
            await user.send_message("❌ Nie wybrano miasta.")
            return

        option_text = ""
        if options:
            option_text = " | " + " | ".join(options)

        # ================= WTS =================
        if "wts_products" in context.user_data:

            content_lines = []
            for p in context.user_data.get("wts_products", []):
                content_lines.append(f"{get_product_emoji(p)} {smart_mask_caps(p)}")

            content = "\n".join(content_lines)
            vendor_data = get_vendor(username)

            # ===== VIP =====
            if vendor_data and int(vendor_data[5]) == 1:

                if not VIP_GIF_URL:
                    await user.send_message("❌ VIP_GIF_URL nie ustawione w ENV.")
                    return

                caption = vip_template(
                    username=username,
                    content=content,
                    vendor_data=vendor_data,
                    city=city,
                    options=options,
                    shop_link=context.user_data.get("shop_link"),
                    legit_link=context.user_data.get("legit_link")
                )

                await context.bot.send_animation(
                    chat_id=GROUP_ID,
                    message_thread_id=WTS_TOPIC,
                    animation=VIP_GIF_URL,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📩 KONTAKT", url=f"https://t.me/{username}")]
                    ])
                )

            # ===== NORMAL =====
            else:

                since = vendor_data[1] if vendor_data else "-"
                posts = vendor_data[4] if vendor_data else 0

                caption = (
                    "💎 <b>WTS MARKET</b> 💎\n\n"
                    "📜 <b>VERIFIED VENDOR</b>\n"
                    f"📅 <b>OD:</b> {since}\n"
                    f"📊 <b>OGŁOSZEŃ:</b> {posts}\n\n"
                    f"👤 <b>@{username}</b>\n"
                    f"📍 <b>{city}{option_text} | #3CITY</b>\n\n"
                    "<code>──────────────────</code>\n"
                    f"{content}\n"
                    "<code>──────────────────</code>\n\n"
                    "⚡ <b>OFFICIAL MARKETPLACE</b>"
                )

                await context.bot.send_photo(
                    chat_id=GROUP_ID,
                    message_thread_id=WTS_TOPIC,
                    photo=LOGO_URL,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📩 KONTAKT", url=f"https://t.me/{username}")]
                    ])
                )

            # ===== ZAPIS WTS (VIP + NORMAL) =====
            last_ads[user.id] = {
                "products": list(context.user_data.get("wts_products", [])),
                "city": context.user_data.get("city"),
                "options": list(context.user_data.get("options", [])),
                "shop_link": context.user_data.get("shop_link"),
                "legit_link": context.user_data.get("legit_link"),
            }

            set_last_post(user.id)
            increment_posts(username)

        # ================= WTB =================
        elif post_type == "WTB":

            masked_content = smart_mask_caps(context.user_data.get("content", ""))

            caption = (
                "🛒 <b>WTB MARKET</b>\n\n"
                f"👤 <b>@{username}</b>\n"
                f"📍 <b>{city}{option_text} | #3CITY</b>\n\n"
                "<code>───────────────</code>\n"
                f"<b>{masked_content}</b>\n"
                "<code>───────────────</code>"
            )

            await context.bot.send_photo(
                chat_id=GROUP_ID,
                message_thread_id=WTB_TOPIC,
                photo=LOGO_URL,
                caption=caption,
                parse_mode="HTML"
            )

        # ================= WTT =================
        elif post_type == "WTT":

            masked_content = smart_mask_caps(context.user_data.get("content", ""))

            caption = (
                "🔁 <b>WTT MARKET</b>\n\n"
                f"👤 <b>@{username}</b>\n"
                f"📍 <b>{city}{option_text} | #3CITY</b>\n\n"
                "<code>───────────────</code>\n"
                f"<b>{masked_content}</b>\n"
                "<code>───────────────</code>"
            )

            await context.bot.send_photo(
                chat_id=GROUP_ID,
                message_thread_id=WTT_TOPIC,
                photo=LOGO_URL,
                caption=caption,
                parse_mode="HTML"
            )

        else:
            await user.send_message("❌ Nieznany typ ogłoszenia.")
            print("ERROR: post_type =", post_type)
            return

        context.user_data.clear()
        print("=== FINALIZE SUCCESS ===")

    except Exception as e:
        print("=== FINALIZE ERROR ===")
        print(e)
        await user.send_message(f"❌ Błąd publikacji:\n{e}")

    finally:
        active_publications.discard(user.id)
        
    
# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # ADMIN COMMANDS
    app.add_handler(CommandHandler("addvendor", cmd_addvendor))
    app.add_handler(CommandHandler("addvendors", cmd_addvendors))
    app.add_handler(CommandHandler("removevendor", cmd_removevendor))
    app.add_handler(CommandHandler("listvendors", cmd_listvendors))

    # VIP COMMANDS (ADMIN ONLY)
    app.add_handler(CommandHandler("setvip", cmd_setvip))
    app.add_handler(CommandHandler("unsetvip", cmd_unsetvip))

    # CALLBACKS + MESSAGES
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(auto_messages, interval=21600, first=60)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
    












































