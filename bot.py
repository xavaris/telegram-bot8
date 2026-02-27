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
TOKEN = os.getenv("KEY")
GROUP_ID = int(os.getenv("GROUP_ID"))
WTB_TOPIC = int(os.getenv("WTB"))
WTS_TOPIC = int(os.getenv("WTS"))
WTT_TOPIC = int(os.getenv("WTT"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOGO_URL = os.getenv("LOGO_URL")
BOT_USERNAME = os.getenv("BOT_USERNAME")

# ================= FAST POST MEMORY (DODANE) =================
last_ads = {}

# ================= DATABASE =================
conn = sqlite3.connect("market.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS vendors (
    username TEXT PRIMARY KEY,
    added_at TEXT,
    city TEXT,
    options TEXT,
    posts INTEGER DEFAULT 0
)
""")

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

product_groups = {

    # 🇵🇱 AMFETAMINA (POLSKA)
    "🇵🇱": [
        "feta", "amfa", "amfetamina",
        "polak",
        "krajowka", "krajowa", "krajuwa"
    ],

    # 💜 EKSTAZY
    "💜": [
        "pix", "pixy", "piksy", "piksi",
        "eksta", "exta", "extasy", "ecstasy",
        "mitsubishi", "lego", "superman",
        "rolls", "pharaoh", "tesla", "bluepunisher"
    ],

    # 💎 MEPH / CMC
    "💎": [
        "mewa", "3cmc", "4mmc", "cmc", "mmc",
        "kryx", "krysztal", "crystal", "ice",
        "mefedron", "mefa", "mef",
        "kamien", "bezwonny"
    ],

    # ❄️ KOKAINA
    "❄️": [
        "koks", "kokos", "koko",
        "coke", "cocaina", "kokaina",
        "biala", "bialy",
        "sniff", "kreska", "kreski"
    ],

    # 🌿 WEED
    "🌿": [
        "weed", "buch", "jazz",
        "trawa", "ziolo", "zielone",
        "buszek", "haze", "cali", "w33d"
    ],

    # 🍫 HASZ
    "🍫": [
        "hasz", "haszysz", "czekolada", "haszyk"
    ],

    # 🌙 NASENNE
    "🌙": [
        "zolpidem", "stilnox",
        "nasen", "sleep"
    ],

    # 💊 OPIOIDY
    "💊": [
        "dhc",
        "kodeina", "codeine",
        "opioid",
        "oxy", "oxycodone"
    ],

    # 💪 STERYDY
    "💪": [
        "testosteron", "test", "enan",
        "prop", "tren", "deca",
        "bold", "winstrol",
        "anavar", "oxandrolone",
        "dianabol", "meta"
    ],

    # 🧠 KETAMINA
    "🧠": [
        "keta", "ketamina", "ket"
    ],

    # 🍄 GRZYBY
    "🍄": [
        "grzyby", "grzybki", "grzyb",
        "lizy", "lysiczki"
    ],

    # 💨 VAPE
    "💨": [
        "vape", "vap", "liquid", "liq",
        "pod", "salt", "jednorazowka"
    ],

    # 🛢 CARTRIDGE
    "🛢": [
        "cart", "cartridge", "kartridz",
        "wklad"
    ],

    # 🧴 PERFUMY
    "🧴": [
        "perfumy", "perfum", "perfumka",
        "dior", "chanel", "gucci",
        "armani", "versace", "tom ford"
    ],

    # 🚬 E-PAPIEROSY
    "🚬": [
        "epapieros", "epapierosy"
    ],

    # ✨ BLINKERY
    "✨": [
        "blinker", "blink", "blinkery"
    ],

    # 💳 KARTY SIM
    "💳": [
        "sim", "starter", "kartasim",
        "startersim", "esim", "simki"
    ]
}
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
    cursor.execute("SELECT * FROM vendors WHERE username=?", (username,))
    return cursor.fetchone()

def add_vendor(username):
    if get_vendor(username):
        return False
    now = datetime.now().strftime("%d.%m.%Y")
    cursor.execute("INSERT INTO vendors VALUES(?,?,?,?,?)",
                   (username, now, None, None, 0))
    conn.commit()
    return True

def remove_vendor(username):
    cursor.execute("DELETE FROM vendors WHERE username=?", (username,))
    conn.commit()

def list_vendors():
    cursor.execute("SELECT username, added_at, posts FROM vendors")
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
    """,(user_id,int(time.time())))
    conn.commit()

def clear_all_cooldowns():
    cursor.execute("DELETE FROM cooldowns")
    conn.commit()
    # ================= PREMIUM TEMPLATE =================
def premium_template(title, username, content, vendor_data, city, options):

    badge = ""
    if vendor_data:
        badge = (
            "<b>👑 VERIFIED VENDOR</b>\n"
            f"<b>🗓 OD:</b> {vendor_data[1]}\n"
            f"<b>📊 OGŁOSZEŃ:</b> {vendor_data[4]}\n\n"
        )

    option_text = ""
    if options:
        option_text = " | " + " | ".join(options)

    profile = f"<b>👤 {username}</b>\n<b>📍 {city}{option_text} | #3CITY</b>"

    hashtag = ""
    if title == "WTB":
        hashtag = "\n<b>#WTB</b>"
    if title == "WTT":
        hashtag = "\n<b>#WTT</b>"

    return (
        f"<b>       💎 {title} MARKET 💎</b>\n\n"
        f"{badge}"
        f"{profile}\n\n"
        "<code>───────────────</code>\n"
        f"<b>{content}</b>\n"
        "<code>───────────────</code>"
        f"{hashtag}\n\n"
        "<b>⚡ OFFICIAL MARKETPLACE</b>"
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

    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙ ADMIN PANEL", callback_data="ADMIN")])

    await update.message.reply_text(
        "<b>WYBIERZ TYP OGŁOSZENIA:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= ADMIN COMMANDS =================
async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("<b>UŻYJ:</b> /addvendor @username", parse_mode="HTML")
        return
    username = context.args[0].replace("@", "").lower()
    if add_vendor(username):
        await update.message.reply_text("<b>VENDOR DODANY.</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("<b>VENDOR JUŻ ISTNIEJE.</b>", parse_mode="HTML")


# ================= NOWA KOMENDA: ADD MULTIPLE =================
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

        try:
            if add_vendor(username):
                added.append(username)
            else:
                skipped.append(username)
        except:
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
        await update.message.reply_text("<b>UŻYJ:</b> /removevendor @username", parse_mode="HTML")
        return
    username = context.args[0].replace("@", "").lower()
    remove_vendor(username)
    await update.message.reply_text("<b>VENDOR USUNIĘTY.</b>", parse_mode="HTML")


async def cmd_listvendors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    vendors = list_vendors()
    if not vendors:
        await update.message.reply_text("<b>BRAK VENDORÓW.</b>", parse_mode="HTML")
        return
    text = ""
    for v in vendors:
        text += f"<b>@{v[0]}</b> | OD {v[1]} | OGŁOSZEŃ: {v[2]}\n"
    await update.message.reply_text(text, parse_mode="HTML")
    # ================= ADMIN PANEL INLINE =================
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

# ================= CALLBACK HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    # ADMIN PANEL
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
            text += f"<b>@{v[0]}</b> | OD {v[1]} | OGŁOSZEŃ: {v[2]}\n"
        await query.edit_message_text(text or "<b>BRAK.</b>", parse_mode="HTML")
        return

    if query.data in ["ADD_VENDOR", "REMOVE_VENDOR"] and user.id == ADMIN_ID:
        context.user_data["admin_action"] = query.data
        await query.edit_message_text("<b>PODAJ @USERNAME:</b>", parse_mode="HTML")
        return

    # ================= FAST POST =================
    if query.data == "FAST_POST":
        data = last_ads.get(user.id)
        if not data:
            await query.edit_message_text("<b>BRAK ZAPISANEGO OGŁOSZENIA.</b>", parse_mode="HTML")
            return

        context.user_data["wts_products"] = data["products"]
        context.user_data["city"] = data["city"]
        context.user_data["options"] = data["options"]

        await publish(update, context)
        return

    if query.data == "NEW_WTS":
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

            context.user_data.pop("selecting_sim_network")
            context.user_data.pop("pending_sim_product")
            context.user_data.pop("selected_networks")

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

        else:
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

        if time.time() - get_last_post(user.id) < 6*60*60:
            await query.edit_message_text("<b>COOLDOWN 6H.</b>", parse_mode="HTML")
            return

        context.user_data["vendor"] = vendor

        keyboard = []

        if user.id in last_ads:
            keyboard.append([
                InlineKeyboardButton("🚀 POST (Wyślij to samo)", callback_data="FAST_POST")
            ])

        keyboard.append([
            InlineKeyboardButton("➕ NOWE OGŁOSZENIE", callback_data="NEW_WTS")
        ])

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

    if query.data in ["CITY_GDY", "CITY_GDA", "CITY_SOP"]:
        context.user_data["city"] = query.data
        context.user_data["options"] = []
        keyboard = [
            [InlineKeyboardButton("✈️ DOLOT", callback_data="OPT_DOLOT")],
            [InlineKeyboardButton("🚗 UBER PAKA", callback_data="OPT_UBER")],
            [InlineKeyboardButton("❌ BRAK", callback_data="OPT_BRAK")],
            [InlineKeyboardButton("✅ PUBLIKUJ", callback_data="OPT_DONE")]
        ]
        await query.edit_message_text(
            "<b>WYBIERZ OPCJE:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if query.data in ["OPT_DOLOT", "OPT_UBER"]:
        if query.data not in context.user_data["options"]:
            context.user_data["options"].append(query.data)
        return

    if query.data == "OPT_BRAK":
        context.user_data["options"] = []
        return

    if query.data == "OPT_DONE":
        await publish(update, context)
        return

    # ================= WTB / WTT =================
    if query.data in ["WTB", "WTT"]:
        context.user_data["type"] = query.data
        await query.edit_message_text("<b>NAPISZ TREŚĆ:</b>", parse_mode="HTML")
        return
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

      # ================= WTS PRODUCTS =================
    if "wts_total" in context.user_data:

        if contains_price_hardcore(text):
            await update.message.reply_text("<b>❌ ZAKAZ PODAWANIA CEN.</b>", parse_mode="HTML")
            return

        # 🔥 JEŚLI TO SIM → WYBÓR SIECI
        if get_product_emoji(text) == "💳":

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

    # WTB / WTT TEXT
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
async def ask_product_count(query):
    keyboard = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(str(i), callback_data=f"CNT_{i}"))
        if i % 5 == 0:
            keyboard.append(row)
            row = []
    await query.edit_message_text(
        "<b>ILE PRODUKTÓW?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ================= PUBLISH =================
async def publish(update, context):
    user = update.callback_query.from_user

    city_map = {
        "CITY_GDY": "#GDY",
        "CITY_GDA": "#GDA",
        "CITY_SOP": "#SOP"
    }

    option_map = {
        "OPT_DOLOT": "#DOLOT",
        "OPT_UBER": "#UBERPAKA"
    }

    city = city_map.get(context.user_data.get("city"))
    options_raw = context.user_data.get("options", [])

    # ================= WTS =================
    if "wts_products" in context.user_data:

        vendor = get_vendor(user.username.lower()) if user.username else None

        content = "\n".join(
            f"{get_product_emoji(p)} {smart_mask_caps(p)}"
            for p in context.user_data["wts_products"]
        )

        title = "WTS"
        topic = WTS_TOPIC

        set_last_post(user.id)

        if user.username:
            increment_posts(user.username.lower())

        last_ads[user.id] = {
            "products": context.user_data.get("wts_products"),
            "city": context.user_data.get("city"),
            "options": context.user_data.get("options")
        }

        caption = premium_template(
            title,
            f"@{user.username}".upper() if user.username else "BRAK USERNAME",
            content,
            vendor,
            city,
            [
                option_map[o] for o in options_raw if o in option_map
            ]
        )

        reply_markup = None

    # ================= WTB / WTT =================
    else:

        content = smart_mask_caps(context.user_data["content"])
        title = context.user_data["type"]
        topic = WTB_TOPIC if title == "WTB" else WTT_TOPIC

        hashtags = []

        if city:
            hashtags.append(city)

        if title == "WTB":
            hashtags.append("#KUPIE")
        else:
            hashtags.append("#WYMIANA")

        for o in options_raw:
            if o in option_map:
                hashtags.append(option_map[o])

        hashtag_line = " ".join(hashtags)

        # 🔥 WYŚWIETLANIE USERNAME
        if user.username:
            user_display = f"@{user.username}"
            contact_url = f"https://t.me/{user.username}"
        else:
            user_display = f"ID: {user.id}"
            contact_url = f"tg://user?id={user.id}"

        caption = (
            f"<b>🚨🚨 {title} ALERT 🚨🚨</b>\n\n"
            f"<b>👤 {user_display}</b>\n\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"<b>🔥 {content} 🔥</b>\n\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"{hashtag_line}\n\n"
            f"<b>⚡ MARKETPLACE</b>"
        )

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 KONTAKT", url=contact_url)]
        ])

    msg = await update.get_bot().send_photo(
        chat_id=GROUP_ID,
        message_thread_id=topic,
        photo=LOGO_URL,
        caption=caption,
        parse_mode="HTML",
        reply_markup=reply_markup
    )

    async def delete_later(ctx):
        try:
            await ctx.bot.delete_message(GROUP_ID, msg.message_id)
        except:
            pass

    context.application.job_queue.run_once(delete_later, 172800)

    context.user_data.clear()
    
# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addvendor", cmd_addvendor))
    app.add_handler(CommandHandler("addvendors", cmd_addvendors))  # NOWE
    app.add_handler(CommandHandler("removevendor", cmd_removevendor))
    app.add_handler(CommandHandler("listvendors", cmd_listvendors))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(auto_messages, interval=21600, first=60)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()




