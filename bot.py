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
MAX_DAILY = int(os.getenv("MAX_DAILY","2"))

VENDORS = set(os.getenv("VENDOR_NAME","").lower().split(","))

TZ = pytz.timezone("Europe/Warsaw")

# ================= MEMORY =================

steps = {}
daily = {}
last_ad = {}
blacklist = set()
offer_id = 1000

# ================= STYLE =================

MAP = {"a":"@","e":"3","i":"1","o":"0","s":"$","t":"7"}

def encode(text):
    return "".join(MAP.get(c.lower(),c.upper()) for c in text)

EMOJI = {
    "buch":"🌿","weed":"🌿",
    "mewa":"🕊",
    "koks":"✉️","kokaina":"✉️",
    "crystal":"💎","mefedron":"💎",
    "xanax":"💊"
}

def get_emoji(text):
    for k,v in EMOJI.items():
        if k in text.lower():
            return v
    return "📦"

# ================= UTIL =================

def now():
    return datetime.now(TZ).strftime("%H:%M")

def build_offer(products,user):
    global offer_id
    offer_id += 1
    items = "\n".join([f"• {get_emoji(p)} {encode(p)}" for p in products])

    return f"""
<b>████████████████████████</b>
<b>🔥💥 OSTATNIA SZANSA MARKET 💥🔥</b>
<b>████████████████████████</b>

<b>🆔 OFERTA:</b> #{offer_id}
<b>🕒 GODZINA:</b> {now()}

{items}

<b>████████████████████████</b>
<b>📩 @{user}</b>
<b>████████████████████████</b>
"""

def contains_blacklist(text):
    return any(w in text.lower() for w in blacklist)

# ================= LISTENER (TEMAT) =================

async def topic_listener(update:Update, context:ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return
    if update.message.chat_id != GROUP_ID:
        return
    if update.message.message_thread_id != TOPIC_ID:
        return

    uid = update.effective_user.id
    username = update.effective_user.username
    txt = update.message.text.lower()

    # ===== !POST =====
    if txt == "!post":
        if not username or username.lower() not in VENDORS:
            await update.message.reply_text("❌ Nie jesteś vendorem.")
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new_offer")],
            [InlineKeyboardButton("❌ ANULUJ",callback_data="cancel")]
        ])

        await update.message.reply_text("Panel vendora:",reply_markup=kb)
        return

    # ===== !ADMIN =====
    if txt == "!admin" and uid == ADMIN_ID:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 WYCZYŚĆ TEMAT",callback_data="clean_topic")],
            [InlineKeyboardButton("⛔ POKAŻ BLACKLISTĘ",callback_data="show_bl")],
            [InlineKeyboardButton("➕ DODAJ SŁOWO BL",callback_data="add_bl")],
            [InlineKeyboardButton("🗑 WYCZYŚĆ BL",callback_data="clear_bl")]
        ])
        await update.message.reply_text("🛠 PANEL ADMINA",reply_markup=kb)
        return

# ================= BUTTONS =================

async def buttons(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    username = q.from_user.username

    # ===== NEW OFFER =====
    if q.data=="new_offer":
        steps[uid]={"qty":None,"items":[]}
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(1,6)],
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(6,11)]
        ])
        await q.message.reply_text("Ile produktów?",reply_markup=kb)

    if q.data.startswith("q"):
        steps[uid]["qty"]=int(q.data[1:])
        await q.message.reply_text("Podaj produkt 1:")

    if q.data=="send":
        ad = build_offer(steps[uid]["items"],username)

        msg = await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=TOPIC_ID,
            photo=LOGO_URL,
            caption=ad,
            parse_mode="HTML"
        )

        if uid in last_ad:
            try:
                await context.bot.delete_message(GROUP_ID,last_ad[uid])
            except: pass

        last_ad[uid]=msg.message_id
        steps.pop(uid)

        await q.message.reply_text("✅ OPUBLIKOWANO")

    if q.data=="cancel":
        steps.pop(uid,None)
        await q.message.reply_text("❌ ANULOWANO")

    # ===== ADMIN =====
    if q.data=="clean_topic" and uid==ADMIN_ID:
        removed=0
        for mid in list(last_ad.values()):
            try:
                await context.bot.delete_message(GROUP_ID,mid)
                removed+=1
            except: pass
        last_ad.clear()
        await q.message.reply_text(f"🧹 USUNIĘTO {removed} OGŁOSZEŃ")

    if q.data=="show_bl" and uid==ADMIN_ID:
        await q.message.reply_text("\n".join(blacklist) if blacklist else "pusta")

    if q.data=="add_bl" and uid==ADMIN_ID:
        context.user_data["add_bl"]=True
        await q.message.reply_text("Podaj słowo:")

    if q.data=="clear_bl" and uid==ADMIN_ID:
        blacklist.clear()
        await q.message.reply_text("WYCZYSZCZONO")

# ================= COLLECT =================

async def collect(update:Update, context:ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return
    if update.message.message_thread_id!=TOPIC_ID:
        return

    uid = update.effective_user.id
    text = update.message.text

    if context.user_data.get("add_bl") and uid==ADMIN_ID:
        blacklist.add(text.lower())
        context.user_data["add_bl"]=False
        await update.message.reply_text("Dodano.")
        return

    if uid not in steps:
        return

    if contains_blacklist(text):
        await update.message.reply_text("❌ Niedozwolone słowo.")
        return

    steps[uid]["items"].append(text)

    if len(steps[uid]["items"]) < steps[uid]["qty"]:
        await update.message.reply_text(f"Podaj produkt {len(steps[uid]['items'])+1}:")
    else:
        preview = build_offer(steps[uid]["items"],update.effective_user.username)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send"),
             InlineKeyboardButton("❌ ANULUJ",callback_data="cancel")]
        ])

        await update.message.reply_text(
            "PODGLĄD:\n\n"+preview,
            parse_mode="HTML",
            reply_markup=kb
        )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, topic_listener))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect))
    print("🔥 AGGRESSIVE MARKET ONLINE")
    app.run_polling()

if __name__=="__main__":
    main()
