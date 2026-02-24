import os
import re
import sqlite3
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# ================= DATABASE =================
conn = sqlite3.connect("market.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS vendors (
    username TEXT PRIMARY KEY,
    added_at TEXT
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
    "e": "3",
    "i": "1",
    "o": "0",
    "s": "$",
    "t": "7",
    "z": "2",
    "u": "Ц",
    "c": "©",
}

def smart_mask_caps(text: str) -> str:
    return "".join(CHAR_MAP.get(c.lower(), c) for c in text).upper()

def contains_price(text: str) -> bool:
    text = text.lower()
    patterns = [
        r"\b\d+\s?(zł|pln|usd|eur|\$|€)\b",
        r"\b\d+\b\s?(zł|pln|usd|eur|\$|€)"
    ]
    return any(re.search(p, text) for p in patterns)

# ================= DB HELPERS =================
def is_vendor(username):
    cursor.execute("SELECT 1 FROM vendors WHERE username=?", (username,))
    return cursor.fetchone() is not None

def add_vendor(username):
    now = datetime.now().strftime("%d.%m.%Y")
    cursor.execute("INSERT OR IGNORE INTO vendors VALUES(?, ?)", (username, now))
    conn.commit()

def remove_vendor(username):
    cursor.execute("DELETE FROM vendors WHERE username=?", (username,))
    conn.commit()

def get_vendor_date(username):
    cursor.execute("SELECT added_at FROM vendors WHERE username=?", (username,))
    row = cursor.fetchone()
    return row[0] if row else None

def get_last_post(user_id):
    cursor.execute("SELECT last_post FROM cooldowns WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def set_last_post(user_id):
    cursor.execute("""
        INSERT INTO cooldowns(user_id, last_post)
        VALUES(?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET last_post=excluded.last_post
    """, (user_id, int(time.time())))
    conn.commit()

def clear_all_cooldowns():
    cursor.execute("DELETE FROM cooldowns")
    conn.commit()

# ================= TEMPLATE =================
def premium_template(title, username, content, verified, vendor_date):
    header = (
        "━━━━━━━━━━━━━━━━━━\n"
        f"        💎 {title} MARKET\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    vendor_block = ""
    if verified and vendor_date:
        vendor_block = (
            "👑 VERIFIED VENDOR\n"
            f"🗓 VENDOR OD: {vendor_date}\n\n"
        )

    body = (
        f"        👤 {username}\n\n"
        f"{content}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ OFFICIAL MARKETPLACE SYSTEM\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    return header + vendor_block + body

# ================= AUTO POSTS =================
async def auto_messages(context: ContextTypes.DEFAULT_TYPE):

    keyboard_wts = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 NAPISZ DO ADMINA", url="https://t.me/burwusovy")],
        [InlineKeyboardButton("💼 DODAJ OGŁOSZENIE", url="https://t.me/ogloszeniovybot?start=1")]
    ])

    await context.bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=WTS_TOPIC,
        text=(
            "🔥 CHCESZ ZOSTAĆ VENDOREM?\n"
            "VENDOR JEST OBECNIE DARMOWY (OKRES TESTOWY)\n\n"
            "JESTEŚ JUŻ VENDOREM?"
        ),
        reply_markup=keyboard_wts
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "📩 DODAJ OGŁOSZENIE",
            url="https://t.me/ogloszeniovybot?start=1"
        )
    ]])

    text = "🛒 CHCESZ COŚ KUPIĆ LUB WYMIENIĆ?"

    await context.bot.send_message(GROUP_ID, text=text, message_thread_id=WTB_TOPIC, reply_markup=keyboard)
    await context.bot.send_message(GROUP_ID, text=text, message_thread_id=WTT_TOPIC, reply_markup=keyboard)

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

    await update.message.reply_text("WYBIERZ TYP OGŁOSZENIA:", reply_markup=InlineKeyboardMarkup(keyboard))

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    # ADMIN
    if query.data == "ADMIN" and user.id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("➕ DODAJ VENDORA", callback_data="ADD")],
            [InlineKeyboardButton("➖ USUŃ VENDORA", callback_data="REMOVE")],
            [InlineKeyboardButton("📋 LISTA", callback_data="LIST")],
            [InlineKeyboardButton("❌ USUŃ COOLDOWN", callback_data="CLEAR_CD")]
        ]
        await query.edit_message_text("PANEL ADMINA:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data == "CLEAR_CD" and user.id == ADMIN_ID:
        clear_all_cooldowns()
        await query.edit_message_text("COOLDOWNY USUNIĘTE.")
        return

    if query.data == "LIST":
        cursor.execute("SELECT username, added_at FROM vendors")
        rows = cursor.fetchall()
        text = "\n".join(f"@{r[0]} | OD {r[1]}" for r in rows) or "BRAK"
        await query.edit_message_text(text)
        return

    if query.data in ["ADD", "REMOVE"]:
        context.user_data["admin_action"] = query.data
        await query.edit_message_text("PODAJ @USERNAME:")
        return

    # WTS
    if query.data == "WTS":
        username = user.username.lower() if user.username else None

        if user.id != ADMIN_ID and (not username or not is_vendor(username)):
            await query.edit_message_text("TYLKO VENDOR MOŻE PUBLIKOWAĆ WTS.")
            return

        if time.time() - get_last_post(user.id) < 6*60*60:
            await query.edit_message_text("COOLDOWN 6H.")
            return

        keyboard = []
        row = []
        for i in range(1, 11):
            row.append(InlineKeyboardButton(f"📦 {i}", callback_data=f"CNT_{i}"))
            if i % 5 == 0:
                keyboard.append(row)
                row = []

        await query.edit_message_text("ILE PRODUKTÓW?", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("CNT_"):
        context.user_data["wts_total"] = int(query.data.split("_")[1])
        context.user_data["wts_products"] = []
        await query.edit_message_text("PODAJ PRODUKT 1:")
        return

    if query.data in ["WTB", "WTT"]:
        context.user_data["type"] = query.data
        context.user_data["topic"] = WTB_TOPIC if query.data == "WTB" else WTT_TOPIC
        await query.edit_message_text("NAPISZ TREŚĆ:")
        return

# ================= MESSAGE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    text = update.message.text

    if user.id == ADMIN_ID and "admin_action" in context.user_data:
        username = text.replace("@", "").lower()
        if context.user_data["admin_action"] == "ADD":
            add_vendor(username)
            await update.message.reply_text("DODANO.")
        else:
            remove_vendor(username)
            await update.message.reply_text("USUNIĘTO.")
        context.user_data.clear()
        return

    if "wts_total" in context.user_data:
        if contains_price(text):
            await update.message.reply_text("ZAKAZ CEN.")
            return

        context.user_data["wts_products"].append(text)

        if len(context.user_data["wts_products"]) < context.user_data["wts_total"]:
            await update.message.reply_text(f"PODAJ PRODUKT {len(context.user_data['wts_products'])+1}:")
            return

        username_display = f"@{user.username}".upper()
        verified = is_vendor(user.username.lower()) if user.username else False
        vendor_date = get_vendor_date(user.username.lower()) if verified else None

        products_text = "\n".join(f"✓ {smart_mask_caps(p)}" for p in context.user_data["wts_products"])

        await update.get_bot().send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=premium_template("WTS", username_display, products_text, verified, vendor_date)
        )

        set_last_post(user.id)
        context.user_data.clear()
        await update.message.reply_text("OPUBLIKOWANO.")
        return

    if "topic" in context.user_data:
        username_display = f"@{user.username}".upper()
        await update.get_bot().send_photo(
            chat_id=GROUP_ID,
            message_thread_id=context.user_data["topic"],
            photo=LOGO_URL,
            caption=premium_template(
                context.user_data["type"],
                username_display,
                smart_mask_caps(text),
                False,
                None
            )
        )
        context.user_data.clear()
        await update.message.reply_text("OPUBLIKOWANO.")

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(auto_messages, interval=43200, first=10)

    print("FINAL COMPLETE VERSION RUNNING")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
