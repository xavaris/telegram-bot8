import os
from datetime import datetime
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
TOPIC_ID = int(os.getenv("TOPIC_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOGO_URL = os.getenv("LOGO_URL")
MAX_DAILY = int(os.getenv("MAX_DAILY", "2"))

VENDORS = set(os.getenv("VENDOR_NAME","").lower().split(","))

TZ = pytz.timezone("Europe/Warsaw")

# ================= MEMORY =================

steps = {}
daily = {}
last_ad = {}
blacklist = set()
offer_id = 1000
templates = {}   # uid -> list produktów

# ================= STYLING =================

CHAR_MAP = {"a":"@","e":"3","i":"1","o":"0","s":"$","t":"7"}

def encode_name(text):
    return "".join(CHAR_MAP.get(c.lower(), c.upper()) for c in text)

PRODUCT_EMOJI = {
    "buch":"🌿","weed":"🌿",
    "mewa":"🕊",
    "polak":"🐟","feta":"🐟",
    "koks":"✉️","kokaina":"✉️","cola":"✉️",
    "crystal":"💎","mefedron":"💎","3cmc":"💎","4cmc":"💎"
}

def get_product_emoji(text):
    for k,v in PRODUCT_EMOJI.items():
        if k in text.lower():
            return v
    return "📦"

# ================= UTIL =================

def now_pl():
    return datetime.now(TZ).strftime("%H:%M")

def build_offer(products, user):
    global offer_id
    offer_id += 1

    items = "\n".join([f"• {get_product_emoji(p)} {encode_name(p)}" for p in products])

    return f"""
<b>████████████████████</b>
<b>🔥 OSTATNIA SZANSA MARKET 🔥</b>
<b>████████████████████</b>

<b>🆔 #{offer_id}</b>   <b>🕒 {now_pl()}</b>

{items}

<b>████████████████████</b>
<b>📩 @{user}</b>
<b>████████████████████</b>
"""

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    kb = [
        [InlineKeyboardButton("⚡ SZYBKA OFERTA", callback_data="quick")],
        [InlineKeyboardButton("📄 MÓJ SZABLON", callback_data="mytpl")],
        [InlineKeyboardButton("➕ NOWA OFERTA", callback_data="new_offer")]
    ]

    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠 PANEL ADMINA", callback_data="admin")])

    await update.message.reply_text("🔥 MARKETPLACE 🔥", reply_markup=InlineKeyboardMarkup(kb))

# ================= BUTTONS =================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    username = q.from_user.username

    # QUICK POST
    if q.data == "quick":
        if not username or username.lower() not in VENDORS:
            await q.message.reply_text("❌ Nie jesteś vendorem.")
            return
        steps[uid] = {"quick": True}
        await q.message.reply_text("Wklej produkty (każdy w nowej linii):")
        return

    # TEMPLATE LOAD
    if q.data == "mytpl":
        if uid not in templates:
            await q.message.reply_text("❌ Brak zapisanego szablonu.")
            return
        steps[uid] = {"items": templates[uid]}
        preview = build_offer(templates[uid], username)
        kb = [[
            InlineKeyboardButton("✅ PUBLIKUJ", callback_data="send"),
            InlineKeyboardButton("❌ ANULUJ", callback_data="cancel")
        ]]
        await q.message.reply_text("Twój szablon:\n\n"+preview, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    # SEND
    if q.data == "send":
        data = steps[uid]["items"]
        ad = build_offer(data, username)

        msg = await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=TOPIC_ID,
            photo=LOGO_URL,
            caption=ad,
            parse_mode="HTML"
        )

        if uid in last_ad:
            try: await context.bot.delete_message(GROUP_ID, last_ad[uid])
            except: pass

        last_ad[uid] = msg.message_id
        steps.pop(uid)

        kb = [[
            InlineKeyboardButton("💾 ZAPISZ SZABLON", callback_data="save_tpl"),
            InlineKeyboardButton("❌ NIE", callback_data="nosave")
        ]]

        await q.message.reply_text("Zapisać to ogłoszenie jako szablon?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data == "save_tpl":
        templates[uid] = steps_cache[uid]
        await q.message.reply_text("💾 Szablon zapisany.")
        return

    if q.data == "nosave":
        await q.message.reply_text("OK.")
        return

    if q.data == "cancel":
        steps.pop(uid,None)
        await q.message.reply_text("❌ Anulowano.")

# ================= COLLECT =================

steps_cache = {}

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if uid not in steps:
        return

    if steps[uid].get("quick"):
        products = [x.strip() for x in text.split("\n") if x.strip()]
        steps_cache[uid] = products
        steps[uid] = {"items": products}

        preview = build_offer(products, update.effective_user.username)

        kb = [[
            InlineKeyboardButton("✅ PUBLIKUJ", callback_data="send"),
            InlineKeyboardButton("❌ ANULUJ", callback_data="cancel")
        ]]

        await update.message.reply_text("Podgląd:\n\n"+preview, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND, start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect))
    print("🔥 MARKETPLACE QUICK MODE ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
