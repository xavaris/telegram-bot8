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

BOT_USERNAME = "ogloszeniovybot"  # zmień jeśli inna nazwa

# ================= DATABASE =================
conn = sqlite3.connect("market.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS vendors (
    username TEXT PRIMARY KEY,
    added_at TEXT,
    city TEXT,
    options TEXT
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
    "a": "@", "e": "3", "i": "1", "o": "0",
    "s": "$", "t": "7", "z": "2", "u": "Ц", "c": "©"
}

PRODUCT_EMOJI = {
    "3cmc": "💎", "4mmc": "💎", "mmc": "💎", "cmc": "💎",
    "weed": "🌿", "koks": "❄️", "buch": "🔥",
    "xanax": "💊", "lsd": "🧪"
}

# ================= UTIL =================
def smart_mask_caps(text: str) -> str:
    return "".join(CHAR_MAP.get(c.lower(), c) for c in text).upper()

def get_product_emoji(name: str) -> str:
    for key, emoji in PRODUCT_EMOJI.items():
        if key in name.lower():
            return emoji
    return "📦"

def contains_price(text: str) -> bool:
    patterns = [
        r"\b\d+\s?(zł|pln|usd|eur|\$|€)\b",
        r"\b\d+\b\s?(zł|pln|usd|eur|\$|€)"
    ]
    return any(re.search(p, text.lower()) for p in patterns)

# ================= DB HELPERS =================
def get_vendor(username):
    cursor.execute("SELECT * FROM vendors WHERE username=?", (username,))
    return cursor.fetchone()

def add_vendor(username):
    if get_vendor(username):
        return False
    now = datetime.now().strftime("%d.%m.%Y")
    cursor.execute("INSERT INTO vendors VALUES(?,?,?,?)",
                   (username, now, None, None))
    conn.commit()
    return True

def remove_vendor(username):
    cursor.execute("DELETE FROM vendors WHERE username=?", (username,))
    conn.commit()

def list_vendors():
    cursor.execute("SELECT username, added_at FROM vendors")
    return cursor.fetchall()

def update_vendor_settings(username, city, options):
    cursor.execute(
        "UPDATE vendors SET city=?, options=? WHERE username=?",
        (city, ",".join(options), username)
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

# ================= TEMPLATE =================
def premium_template(title, username, content, vendor_data, city, options):

    badge = ""
    if vendor_data:
        badge = f"👑 VERIFIED VENDOR\n🗓 OD: {vendor_data[1]}\n\n"

    option_text = ""
    if options:
        option_text = "  |  " + "  ".join(options)

    profile = f"👤 {username}  |  📍 {city}{option_text}  |  #3CITY"

    hashtag = ""
    if title == "WTB":
        hashtag = "\n#WTB"
    if title == "WTT":
        hashtag = "\n#WTT"

    return (
        f"💎 {title} MARKET\n\n"
        f"{badge}"
        f"{profile}\n\n"
        "────────────\n"
        f"{content}\n"
        "────────────"
        f"{hashtag}\n\n"
        "⚡ OFFICIAL MARKETPLACE"
    )

# ================= ADMIN COMMANDS =================
async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("UŻYJ: /addvendor @username")
        return
    username = context.args[0].replace("@","").lower()
    if add_vendor(username):
        await update.message.reply_text("VENDOR DODANY.")
    else:
        await update.message.reply_text("TEN VENDOR JUŻ ISTNIEJE.")

async def cmd_removevendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("UŻYJ: /removevendor @username")
        return
    username = context.args[0].replace("@","").lower()
    remove_vendor(username)
    await update.message.reply_text("VENDOR USUNIĘTY.")

async def cmd_listvendors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    vendors = list_vendors()
    text = "\n".join([f"@{v[0]} | OD {v[1]}" for v in vendors]) or "BRAK"
    await update.message.reply_text(text)

# ================= AUTO SYSTEM =================
async def auto_messages(context: ContextTypes.DEFAULT_TYPE):

    keyboard_wts = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 NAPISZ DO ADMINA", url="https://t.me/burwusovy")],
        [InlineKeyboardButton("💼 DODAJ OGŁOSZENIE",
                              url=f"https://t.me/{BOT_USERNAME}?start=1")]
    ])

    await context.bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=WTS_TOPIC,
        text="🔥 CHCESZ ZOSTAĆ VENDOREM?\nVENDOR JEST DARMOWY (OKRES TESTOWY)",
        reply_markup=keyboard_wts
    )

    keyboard_general = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 DODAJ OGŁOSZENIE",
                              url=f"https://t.me/{BOT_USERNAME}?start=1")]
    ])

    await context.bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=WTB_TOPIC,
        text="🛒 CHCESZ COŚ KUPIĆ?",
        reply_markup=keyboard_general
    )

    await context.bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=WTT_TOPIC,
        text="🔁 CHCESZ COŚ WYMIENIĆ?",
        reply_markup=keyboard_general
    )
    # ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    keyboard = [[
        InlineKeyboardButton("🛒 WTB", callback_data="WTB"),
        InlineKeyboardButton("💼 WTS", callback_data="WTS"),
        InlineKeyboardButton("🔁 WTT", callback_data="WTT"),
    ]]

    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙ ADMIN PANEL", callback_data="ADMIN")])

    await update.message.reply_text(
        "WYBIERZ TYP OGŁOSZENIA:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= ADMIN PANEL INLINE =================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("➕ DODAJ VENDORA", callback_data="ADD_VENDOR")],
        [InlineKeyboardButton("➖ USUŃ VENDORA", callback_data="REMOVE_VENDOR")],
        [InlineKeyboardButton("📋 LISTA VENDORÓW", callback_data="LIST_VENDOR")],
        [InlineKeyboardButton("❌ USUŃ COOLDOWN", callback_data="CLEAR_CD")]
    ]
    await query.edit_message_text("PANEL ADMINA:",
                                  reply_markup=InlineKeyboardMarkup(keyboard))

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
        await query.edit_message_text("COOLDOWNY USUNIĘTE.")
        return

    if query.data == "LIST_VENDOR" and user.id == ADMIN_ID:
        vendors = list_vendors()
        text = "\n".join([f"@{v[0]} | OD {v[1]}" for v in vendors]) or "BRAK"
        await query.edit_message_text(text)
        return

    if query.data in ["ADD_VENDOR", "REMOVE_VENDOR"] and user.id == ADMIN_ID:
        context.user_data["admin_action"] = query.data
        await query.edit_message_text("PODAJ @USERNAME:")
        return

    # ================= WTS =================
    if query.data == "WTS":
        if not user.username:
            await query.edit_message_text("USTAW USERNAME NA TELEGRAMIE.")
            return

        vendor = get_vendor(user.username.lower())
        if not vendor:
            await query.edit_message_text("TYLKO VENDOR.")
            return

        if time.time() - get_last_post(user.id) < 6*60*60:
            await query.edit_message_text("COOLDOWN 6H.")
            return

        context.user_data["vendor"] = vendor

        # pytanie o domyślne ustawienia
        if vendor[2]:
            keyboard = [
                [InlineKeyboardButton("✅ UŻYJ DOMYŚLNYCH", callback_data="USE_DEFAULT")],
                [InlineKeyboardButton("⚙️ ZMIEŃ", callback_data="CHANGE_SETTINGS")]
            ]
            await query.edit_message_text(
                "UŻYĆ ZAPISANYCH USTAWIEŃ?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        await ask_product_count(query)
        return

    if query.data == "USE_DEFAULT":
        await ask_product_count(query)
        return

    if query.data == "CHANGE_SETTINGS":
        context.user_data["vendor"] = None
        await ask_product_count(query)
        return

    if query.data.startswith("CNT_"):
        context.user_data["wts_total"] = int(query.data.split("_")[1])
        context.user_data["wts_products"] = []
        await query.edit_message_text("PODAJ PRODUKT 1:")
        return

    # CITY
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
            "WYBIERZ OPCJE (MOŻESZ DWIE):",
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
        await query.edit_message_text("NAPISZ TREŚĆ:")
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
            await update.message.reply_text("DODANO.")
        else:
            remove_vendor(username)
            await update.message.reply_text("USUNIĘTO.")
        context.user_data.clear()
        return

    # WTS PRODUCTS FLOW
    if "wts_total" in context.user_data:
        if contains_price(text):
            await update.message.reply_text("ZAKAZ CEN.")
            return

        context.user_data["wts_products"].append(text)

        if len(context.user_data["wts_products"]) < context.user_data["wts_total"]:
            await update.message.reply_text(
                f"PODAJ PRODUKT {len(context.user_data['wts_products'])+1}:"
            )
            return

        keyboard = [
            [InlineKeyboardButton("GDY", callback_data="CITY_GDY")],
            [InlineKeyboardButton("GDA", callback_data="CITY_GDA")],
            [InlineKeyboardButton("SOP", callback_data="CITY_SOP")]
        ]

        await update.message.reply_text(
            "WYBIERZ MIASTO:",
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
            "WYBIERZ MIASTO:",
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
        "ILE PRODUKTÓW?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= PUBLISH =================
async def publish(update, context):
    user = update.callback_query.from_user
    vendor = get_vendor(user.username.lower()) if user.username else None

    city_map = {
        "CITY_GDY": "#GDY",
        "CITY_GDA": "#GDA",
        "CITY_SOP": "#SOPT"
    }

    option_map = {
        "OPT_DOLOT": "✈️ DOLOT",
        "OPT_UBER": "🚗 UBER PAKA"
    }

    city = city_map.get(context.user_data.get("city"))
    options = [
        option_map[o] for o in context.user_data.get("options", [])
        if o in option_map
    ]

    if "wts_products" in context.user_data:
        content = "\n".join(
            f"{get_product_emoji(p)} {smart_mask_caps(p)}"
            for p in context.user_data["wts_products"]
        )
        title = "WTS"
        topic = WTS_TOPIC
        set_last_post(user.id)

        if user.username:
            update_vendor_settings(
                user.username.lower(),
                city,
                context.user_data.get("options", [])
            )
    else:
        content = smart_mask_caps(context.user_data["content"])
        title = context.user_data["type"]
        topic = WTB_TOPIC if title == "WTB" else WTT_TOPIC

    await update.get_bot().send_photo(
        chat_id=GROUP_ID,
        message_thread_id=topic,
        photo=LOGO_URL,
        caption=premium_template(
            title,
            f"@{user.username}".upper(),
            content,
            vendor,
            city,
            options
        )
    )

    context.user_data.clear()


# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addvendor", cmd_addvendor))
    app.add_handler(CommandHandler("removevendor", cmd_removevendor))
    app.add_handler(CommandHandler("listvendors", cmd_listvendors))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(auto_messages, interval=43200, first=60)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
