import os
import random
import datetime
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
TOPIC_ID = int(os.getenv("TOPIC_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

VENDORS = set(v.strip().lower() for v in os.getenv("VENDOR_NAME","").split(","))

POLAND = ZoneInfo("Europe/Warsaw")
LOGO_URL = "https://dump.li/image/get/78f6f8dc8e370504.png"

MAX_DAILY = 2

BLACKLIST = {"dzieci","weapon","fraud","carding","gun"}

HASHTAGS = {
    "weed":"#weed",
    "buch":"#weed",
    "koks":"#coke",
    "kokaina":"#coke",
    "xanax":"#pills",
    "mdma":"#pills",
    "lsd":"#psy"
}

# ================== MEMORY ==================

daily = {}
last_offer = {}
offer_number = 0

# ================== STYLE ==================

REPLACE = {
    "a":"Å","e":"Ë","i":"Ï","o":"Ø","u":"Ü","s":"Ś","c":"Ç"
}

def stylize(t):
    return "".join(REPLACE.get(c.lower(),c).upper() for c in t)

def pick_icon(name):
    n=name.lower()
    if "weed" in n or "buch" in n: return "🌿"
    if "koks" in n or "kokaina" in n: return "❄️"
    if "xanax" in n or "mdma" in n: return "💊"
    if "lsd" in n: return "🧪"
    return "💎"

# ================== HELPERS ==================

def is_vendor(user):
    return user.username and user.username.lower() in VENDORS

def has_blacklist(text):
    return any(w in text.lower() for w in BLACKLIST)

def build_hashtags(products):
    tags=set()
    for p in products:
        for k,v in HASHTAGS.items():
            if k in p.lower():
                tags.add(v)
    return " ".join(tags)

def build_offer(username, products, number):
    now = datetime.datetime.now(POLAND).strftime("%H:%M")

    text = f"""
💥💥 OSTATNIA SZANSA 💥💥

🆔 #{number}    ⏱ {now}

🚨 OFERTA 🚨

"""
    for p in products:
        text += f"{pick_icon(p)} {stylize(p)}\n"

    text += f"""

📩 @{username}
⚠️ PISZ PO CENĘ
{build_hashtags(products)}
"""
    return text

# ================== START ==================

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not is_vendor(update.message.from_user):
        await update.message.reply_text("❌ Brak uprawnień.")
        return

    kb=[[InlineKeyboardButton(str(i),callback_data=f"c{i}")]
        for i in range(1,11)]

    await update.message.reply_text(
        "Ile towarów? (1-10)",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================== COUNT ==================

async def choose(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    context.user_data["count"]=int(q.data[1:])
    context.user_data["products"]=[]
    await q.message.reply_text("Podaj nazwę towaru:")

# ================== COLLECT ==================

async def collect(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if "count" not in context.user_data:
        return

    if has_blacklist(update.message.text):
        await update.message.reply_text("⛔ Zakazany produkt.")
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
        "TAK BĘDZIE WYGLĄDAĆ OGŁOSZENIE:\n\n"+preview,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("WYŚLIJ",callback_data="send"),
             InlineKeyboardButton("ANULUJ",callback_data="cancel")]
        ])
    )

# ================== SEND ==================

async def send_offer(update:Update, context:ContextTypes.DEFAULT_TYPE):
    global offer_number
    q=update.callback_query
    await q.answer()

    user=q.from_user.username.lower()
    today=datetime.date.today()

    if user not in daily or daily[user]["date"]!=today:
        daily[user]={"date":today,"count":0}

    if daily[user]["count"]>=MAX_DAILY:
        await q.message.edit_text("⛔ Limit dzienny.")
        return

    daily[user]["count"]+=1
    offer_number+=1

    text=build_offer(user,context.user_data["products"],offer_number)

    if user in last_offer:
        try:
            await context.bot.delete_message(GROUP_ID,last_offer[user])
        except:
            pass

    msg=await context.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=TOPIC_ID,
        photo=LOGO_URL,
        caption=text
    )

    last_offer[user]=msg.message_id
    context.user_data.clear()

    try:
        await q.message.edit_text("✅ Ogłoszenie wysłane.")
    except:
        pass

# ================== CANCEL ==================

async def cancel(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    context.user_data.clear()
    try:
        await q.message.edit_text("Anulowano. /start")
    except:
        pass

# ================== ADMIN ==================

async def addvendor(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id!=ADMIN_ID:
        return
    if not context.args:
        return
    VENDORS.add(context.args[0].lower())
    await update.message.reply_text("Dodano.")

async def delvendor(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id!=ADMIN_ID:
        return
    if not context.args:
        return
    VENDORS.discard(context.args[0].lower())
    await update.message.reply_text("Usunięto.")

# ================== MAIN ==================

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("addvendor",addvendor))
    app.add_handler(CommandHandler("delvendor",delvendor))

    app.add_handler(CallbackQueryHandler(choose,pattern="^c"))
    app.add_handler(CallbackQueryHandler(send_offer,pattern="^send$"))
    app.add_handler(CallbackQueryHandler(cancel,pattern="^cancel$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,collect))

    print("🔥 MARKET BOT ONLINE 🔥")
    app.run_polling()

if __name__=="__main__":
    main()
