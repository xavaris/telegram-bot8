import os
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== ENV ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

VENDOR_NAMES = os.getenv("VENDOR_NAMES", "").split(",")
LOGO_URL = os.getenv("LOGO_URL")

GROUP_ID = -1003831965198
TOPIC_ID = 42

TIMEZONE = ZoneInfo("Europe/Warsaw")

# ================== STORAGE ==================

VENDORS = set(v.strip().lower() for v in VENDOR_NAMES if v.strip())
BLACKLIST = set()
SILENT_MODE = False
DAILY_LIMIT = 2
user_posts = defaultdict(list)
offer_counter = 0

# ================== STYLE ==================

EMOJIS = ["🔥","💣","⚡","🚀","💥","🧨","👑","🩸"]

FRAME = "╔════════════════════╗\n" \
        "║   💎 OSTATNIA SZANSA 💎   ║\n" \
        "╚════════════════════╝"

# ================== HELPERS ==================

def now_pl():
    return datetime.now(TIMEZONE)

def stylize(text):
    return text.replace("a","@").replace("e","3").replace("i","!").replace("o","0").replace("s","$")

def can_post(uid):
    today = now_pl().date()
    user_posts[uid] = [d for d in user_posts[uid] if d.date()==today]
    return len(user_posts[uid]) < DAILY_LIMIT

def register_post(uid):
    user_posts[uid].append(now_pl())

def contains_blacklist(text):
    for w in BLACKLIST:
        if w in text.lower():
            return True
    return False

def build_offer(products, username):
    global offer_counter
    offer_counter += 1
    emoji = EMOJIS[offer_counter % len(EMOJIS)]
    time = now_pl().strftime("%H:%M")

    items = "\n".join([f"• {stylize(p.upper())}" for p in products])

    return f"""
{FRAME}

      {emoji}  OFERTA #{offer_counter}
        🕒 {time}

━━━━━━━━━━━━━━━━━━━━

{items}

━━━━━━━━━━━━━━━━━━━━
📩 @{username}  (PW o cenę)
"""

# ================== START ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💎 MARKET BOT\n\n"
        "/new - dodaj ogłoszenie\n"
        "/panel - admin panel"
    )

# ================== NEW OFFER FLOW ==================

async def new_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    if not user or user.lower() not in VENDORS:
        await update.message.reply_text("❌ Nie jesteś vendorem.")
        return

    if not can_post(update.effective_user.id):
        await update.message.reply_text("⛔ Limit dzienny wykorzystany.")
        return

    context.user_data["products"] = []
    await update.message.reply_text("Ile produktów? (1-10)")
    context.user_data["step"] = "count"

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if SILENT_MODE:
        return

    step = context.user_data.get("step")

    if step == "count":
        try:
            count = int(update.message.text)
            if count < 1 or count > 10:
                raise
            context.user_data["remaining"] = count
            context.user_data["step"] = "product"
            await update.message.reply_text("Podaj nazwę produktu:")
        except:
            await update.message.reply_text("Podaj liczbę 1-10")

    elif step == "product":
        txt = update.message.text

        if contains_blacklist(txt):
            await update.message.reply_text("⛔ Zakazane słowo.")
            return

        context.user_data["products"].append(txt)
        context.user_data["remaining"] -= 1

        if context.user_data["remaining"] > 0:
            await update.message.reply_text("Następny produkt:")
        else:
            offer = build_offer(
                context.user_data["products"],
                update.effective_user.username
            )

            context.user_data["offer"] = offer

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ WYŚLIJ", callback_data="send")],
                [InlineKeyboardButton("❌ ANULUJ", callback_data="cancel")]
            ])

            await update.message.reply_photo(
                photo=LOGO_URL,
                caption=offer,
                reply_markup=kb
            )

# ================== BUTTONS ==================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "send":
        await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=TOPIC_ID,
            photo=LOGO_URL,
            caption=context.user_data["offer"]
        )
        register_post(q.from_user.id)
        await q.edit_message_caption("✅ Wysłano")
        context.user_data.clear()

    if q.data == "cancel":
        context.user_data.clear()
        await q.edit_message_caption("❌ Anulowano")

# ================== PANEL ADMINA ==================

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "/addvendor name\n"
        "/delvendor name\n"
        "/blacklist word\n"
        "/silent on/off"
    )

async def addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    VENDORS.add(" ".join(context.args).lower())
    await update.message.reply_text("✅ Dodano")

async def delvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    VENDORS.discard(" ".join(context.args).lower())
    await update.message.reply_text("❌ Usunięto")

async def blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    BLACKLIST.add(context.args[0].lower())
    await update.message.reply_text("⛔ Dodano")

async def silent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SILENT_MODE
    if update.effective_user.id != ADMIN_ID:
        return
    SILENT_MODE = context.args[0] == "on"
    await update.message.reply_text("OK")

# ================== MAIN ==================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_offer))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("addvendor", addvendor))
    app.add_handler(CommandHandler("delvendor", delvendor))
    app.add_handler(CommandHandler("blacklist", blacklist))
    app.add_handler(CommandHandler("silent", silent))

    app.add_handler(MessageHandler(filters.TEXT, collect))
    app.add_handler(MessageHandler(filters.PHOTO, lambda u,c: None))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.PRIVATE, collect))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, lambda u,c: None))
    app.add_handler(MessageHandler(filters.CallbackQuery, buttons))

    print("🔥 MARKET BOT ONLINE 🔥")
    app.run_polling()

if __name__ == "__main__":
    main()
