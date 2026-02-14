import os
import random
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
TOPIC_ID = int(os.getenv("TOPIC_ID"))
VENDOR_NAMES = os.getenv("VENDOR_NAME", "").lower().split(",")

LOGO_URL = "https://dump.li/image/get/78f6f8dc8e370504.png"
MAX_DAILY = 2

# ================= MEMORY =================

daily_counter = {}
last_message_id = {}
offer_number = 1   # globalny licznik

# ================= MASKOWANIE =================

REPLACE_MAP = {
    "a": "Å",
    "e": "Ë",
    "i": "Ï",
    "o": "Ø",
    "u": "Ü",
    "s": "Ś",
    "c": "Ç",
}

def stylize(text):
    return "".join(REPLACE_MAP.get(c.lower(), c).upper() for c in text)

# ================= IKONY =================

ICONS = {
    "weed": "🌿",
    "buch": "🌿",
    "marihuana": "🌿",
    "koks": "❄️",
    "kokaina": "❄️",
    "xanax": "💊",
    "mdma": "💊",
    "lsd": "🧪"
}

def pick_icon(name):
    for k, v in ICONS.items():
        if k in name.lower():
            return v
    return "💎"

# ================= HELPERS =================

def is_vendor(user):
    return user.username and user.username.lower() in VENDOR_NAMES

def build_offer(username, products, number):
    now = datetime.datetime.now().strftime("%H:%M")

    text = f"""
        💥🔥💣 OSTATNIA SZANSA 💣🔥💥

           🆔 OFERTA #{number}
               ⏱ {now}

          🚨🔥 OFERTA 🔥🚨

"""

    for p in products:
        text += f"          {pick_icon(p)} {stylize(p)}\n"

    text += f"""

            📩 @{username}
         ⚠️ PISZ PO CENĘ
"""
    return text

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_vendor(update.message.from_user):
        await update.message.reply_text("❌ Nie masz uprawnień.")
        return

    keyboard = [[InlineKeyboardButton(str(i), callback_data=f"count_{i}")]
                for i in range(1,11)]

    await update.message.reply_text(
        "💥 Ile masz towarów? (1-10)",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= COUNT =================

async def choose_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data["count"] = int(q.data.split("_")[1])
    context.user_data["products"] = []

    await q.message.reply_text("Podaj nazwę towaru:")

# ================= COLLECT =================

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "count" not in context.user_data:
        return

    context.user_data["products"].append(update.message.text)

    if len(context.user_data["products"]) < context.user_data["count"]:
        await update.message.reply_text("Następny towar:")
        return

    preview = build_offer(
        update.message.from_user.username,
        context.user_data["products"],
        "PREVIEW"
    )

    await update.message.reply_text(
        "🔥 TAK BĘDZIE WYGLĄDAŁO TWOJE OGŁOSZENIE 🔥\n\n" + preview,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ WYŚLIJ", callback_data="send"),
             InlineKeyboardButton("❌ ANULUJ", callback_data="cancel")]
        ])
    )

# ================= SEND =================

async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global offer_number

    q = update.callback_query
    await q.answer()

    user = q.from_user.username.lower()
    today = datetime.date.today()

    if user not in daily_counter:
        daily_counter[user] = {"date": today, "count": 0}

    if daily_counter[user]["date"] != today:
        daily_counter[user] = {"date": today, "count": 0}

    if daily_counter[user]["count"] >= MAX_DAILY:
        await q.message.reply_text("⛔ Limit 2 ogłoszeń dziennie.")
        return

    daily_counter[user]["count"] += 1

    offer_number += 1

    text = build_offer(user, context.user_data["products"], offer_number)

    if user in last_message_id:
        try:
            await context.bot.delete_message(GROUP_ID, last_message_id[user])
        except:
            pass

    msg = await context.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=TOPIC_ID,
        photo=LOGO_URL,
        caption=text
    )

    last_message_id[user] = msg.message_id
    context.user_data.clear()

    await q.message.reply_text("✅ Ogłoszenie wysłane!")

# ================= CANCEL =================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await q.message.reply_text("Anulowano. /start")

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(choose_count, pattern="^count_"))
    app.add_handler(CallbackQueryHandler(publish, pattern="^send$"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect))

    print("🔥 MARKET BOT READY 🔥")
    app.run_polling()

if __name__ == "__main__":
    main()
