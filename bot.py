# MARKETPLACE PREMIUM ULTRA v99999.9099999
# python-telegram-bot v20+

import os
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")

GROUP_ID = int(os.getenv("GROUP_ID"))
TOPIC_ID_WTB = int(os.getenv("TOPIC_ID_WTB"))
TOPIC_ID_WTT = int(os.getenv("TOPIC_ID_WTT"))
TOPIC_ID_WTS = int(os.getenv("TOPIC_ID_WTS"))

ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOGO_URL = os.getenv("LOGO_URL")
MAX_DAILY = int(os.getenv("MAX_DAILY", "3"))

VENDORS = set(os.getenv("VENDOR_NAME", "").lower().split(","))

TZ = pytz.timezone("Europe/Warsaw")

# ================= MEMORY =================

steps = {}
saved_templates = {}
vendor_stats = {}
blacklist = set()
offer_id = 1000

# ================= MAPA LITER =================

CHAR_MAP = {
    "a":"@","b":"ß","c":"¢","d":"Ð","e":"3","f":"₣","g":"6",
    "h":"Ħ","i":"1","j":"ʝ","k":"Ҡ","l":"Ł","m":"₥","n":"И",
    "o":"Ø","p":"₱","q":"Ǫ","r":"Я","s":"$","t":"7",
    "u":"Ц","v":"√","w":"₩","x":"Ж","y":"¥","z":"Ƶ"
}

def encode(t):
    return "".join(CHAR_MAP.get(c.lower(), c.upper()) for c in t)

# ================= EMOJI =================

PRODUCT_EMOJI = {
    "buch":"🌿","weed":"🌿",
    "koks":"✉️","kokaina":"✉️","cola":"✉️",
    "crystal":"💎","mefedron":"💎",
    "xanax":"💊","mdma":"🍬","lsd":"🧠",
    "hasz":"🟫","speed":"⚡"
}

def emoji(t):
    for k,v in PRODUCT_EMOJI.items():
        if k in t.lower():
            return v
    return "📦"

def now():
    return datetime.now(TZ).strftime("%H:%M")

# ================= TEMPLATES =================

def render(products, user, style, topic):
    global offer_id
    offer_id += 1

    items = "\n".join([f"• {emoji(p)} {encode(p)}" for p in products])

    tag = topic.upper()

    return f"""
<b>████████████████████</b>
<b>🔥 {tag} MARKET 🔥</b>
<b>████████████████████</b>

🆔 #{offer_id} | 🕒 {now()}

{items}

<b>@{user}</b>
"""

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = (update.effective_user.username or "").lower()

    if update.effective_user.id == ADMIN_ID:
        VENDORS.add(user)

    kb = [
        [InlineKeyboardButton("➕ NOWA OFERTA", callback_data="new")],
        [InlineKeyboardButton("📂 MOJE SZABLONY", callback_data="mytpl")]
    ]

    await update.message.reply_text(
        "🔥 MARKETPLACE PREMIUM ULTRA 🔥",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= BUTTONS =================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    user = (q.from_user.username or "").lower()

    # -------- NEW --------

    if q.data == "new":

        rows = [
            [InlineKeyboardButton("🟢 WTB", callback_data="topic_wtb")],
            [InlineKeyboardButton("🔵 WTT", callback_data="topic_wtt")]
        ]

        if user in VENDORS:
            rows.append([InlineKeyboardButton("🔴 WTS", callback_data="topic_wts")])

        await q.message.reply_text(
            "📌 Wybierz temat:",
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # -------- TOPIC --------

    if q.data.startswith("topic_"):

        topic = q.data.split("_")[1]

        if topic == "wts" and user not in VENDORS:
            await q.message.reply_text("❌ WTS tylko dla vendorów.")
            return

        steps[uid] = {
            "topic": topic,
            "items": []
        }

        await q.message.reply_text("Ile produktów? (1-10)")
        return

    # -------- SEND QTY --------

    if q.data == "send":

        topic_map = {
            "wtb": TOPIC_ID_WTB,
            "wtt": TOPIC_ID_WTT,
            "wts": TOPIC_ID_WTS
        }

        ad = render(
            steps[uid]["items"],
            user,
            0,
            steps[uid]["topic"]
        )

        await context.bot.send_photo(
            GROUP_ID,
            LOGO_URL,
            caption=ad,
            parse_mode="HTML",
            message_thread_id=topic_map[steps[uid]["topic"]]
        )

        await q.message.reply_text("✅ OPUBLIKOWANO")
        steps.pop(uid)
        return

    # -------- TEMPLATES --------

    if q.data == "mytpl":

        rows = [
            [InlineKeyboardButton(f"SZABLON {i+1}", callback_data=f"use_{i}")]
            for i in range(len(saved_templates.get(user, [])))
        ]

        await q.message.reply_text(
            "Twoje szablony:",
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if q.data.startswith("use_"):

        idx = int(q.data[4:])
        items = saved_templates[user][idx]

        ad = render(items, user, 0, "wts")

        await context.bot.send_photo(
            GROUP_ID,
            LOGO_URL,
            caption=ad,
            parse_mode="HTML",
            message_thread_id=TOPIC_ID_WTS
        )
        return

# ================= COLLECT =================

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id
    text = update.message.text

    if uid not in steps:
        return

    if "qty" not in steps[uid]:

        qty = int(text)
        steps[uid]["qty"] = qty
        await update.message.reply_text("Podaj produkt 1")
        return

    steps[uid]["items"].append(text)

    if len(steps[uid]["items"]) < steps[uid]["qty"]:
        await update.message.reply_text(
            f"Podaj produkt {len(steps[uid]['items'])+1}"
        )
    else:
        ad = render(
            steps[uid]["items"],
            update.effective_user.username,
            0,
            steps[uid]["topic"]
        )

        await update.message.reply_text(
            ad,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ PUBLIKUJ", callback_data="send")]]
            )
        )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND, start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect))
    print("🔥 MARKETPLACE PREMIUM ULTRA v99999.9099999 ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
