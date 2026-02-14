import os
import asyncio
from datetime import datetime
import pytz
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ===================== CONFIG =====================

BOT_TOKEN = os.getenv("BOT_TOKEN")

GROUP_ID = -1003831965198
TOPIC_ID = 42

# Vendorzy wpisani w Railway:
# VENDOR_NAME=nick1,nick2,nick3
VENDOR_NAMES = os.getenv("VENDOR_NAME", "").lower().split(",")

MAX_PER_DAY = 2

poland = pytz.timezone("Europe/Warsaw")

# ===================== MEMORY =====================

user_steps = {}
daily_count = {}
last_ads = {}

# ===================== MAPA ZAMIANY =====================

MAP = {
    "a":"@", "e":"3", "i":"!", "o":"0", "s":"$", "b":"8",
    "k":"X", "m":"M", "t":"7", "l":"1", "g":"6", "r":"2",
    "c":"(", "h":"#"
}

def encode(text):
    out = ""
    for c in text.lower():
        out += MAP.get(c, c)
    return out.upper()

# ===================== FORMAT =====================

FRAMES = [
"╔════════════════════╗\n{c}\n╚════════════════════╝",
"┏━━━━━━━━━━━━━━━━━━━━┓\n{c}\n┗━━━━━━━━━━━━━━━━━━━━┛",
"╭────────────────────╮\n{c}\n╰────────────────────╯"
]

EMOJIS = ["🔥","💣","🚀","⚡","💥","👑"]

def build_ad(products, user):
    emoji = EMOJIS[hash(user)%len(EMOJIS)]
    frame = FRAMES[hash(user)%len(FRAMES)]

    now = datetime.now(poland).strftime("%H:%M")

    items = "\n".join([f"• {encode(p)}" for p in products])

    body = f"""
{emoji}  O F F E R T A  {emoji}

{items}

───────────────
📩 @{user}
🕒 {now}
───────────────
"""

    return frame.format(c=body.strip())

# ===================== /START =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    if not user or user.lower() not in VENDOR_NAMES:
        await update.message.reply_text("❌ Nie jesteś na liście vendorów.")
        return

    kb = [[InlineKeyboardButton(str(i), callback_data=f"qty_{i}") for i in range(1,6)],
          [InlineKeyboardButton(str(i), callback_data=f"qty_{i}") for i in range(6,11)]]

    await update.message.reply_text("Ile produktów?", reply_markup=InlineKeyboardMarkup(kb))

# ===================== BUTTONS =====================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("qty_"):
        qty = int(q.data.split("_")[1])
        user_steps[q.from_user.id] = {"qty":qty, "items":[]}
        await q.message.reply_text("Podaj nazwę produktu 1:")
        return

    if q.data == "send_yes":
        data = user_steps[q.from_user.id]
        ad = build_ad(data["items"], q.from_user.username)

        msg = await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=TOPIC_ID,
            text=ad
        )

        if q.from_user.id in last_ads:
            try:
                await context.bot.delete_message(GROUP_ID, last_ads[q.from_user.id])
            except:
                pass

        last_ads[q.from_user.id] = msg.message_id

        today = datetime.now(poland).date()
        daily_count.setdefault(q.from_user.id, {"date":today,"count":0})

        daily_count[q.from_user.id]["count"] += 1

        await q.message.reply_text("✅ Opublikowano.")
        user_steps.pop(q.from_user.id)

    if q.data == "send_no":
        user_steps.pop(q.from_user.id)
        await q.message.reply_text("Anulowano. /start")

# ===================== COLLECT TEXT =====================

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_steps:
        return

    data = user_steps[uid]
    data["items"].append(update.message.text)

    if len(data["items"]) < data["qty"]:
        await update.message.reply_text(f"Podaj nazwę produktu {len(data['items'])+1}:")
    else:
        ad = build_ad(data["items"], update.effective_user.username)

        kb = [[
            InlineKeyboardButton("✅ WYŚLIJ", callback_data="send_yes"),
            InlineKeyboardButton("❌ ANULUJ", callback_data="send_no")
        ]]

        await update.message.reply_text(
            f"Tak będzie wyglądało Twoje ogłoszenie:\n\n{ad}",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# ===================== MAIN =====================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect))

    print("BOT READY")
    app.run_polling()

if __name__ == "__main__":
    main()
