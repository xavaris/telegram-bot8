import os
from datetime import datetime
import pytz

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
TOPIC_ID = int(os.getenv("TOPIC_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOGO_URL = os.getenv("LOGO_URL")
MAX_DAILY = int(os.getenv("MAX_DAILY", "2"))

VENDORS = os.getenv("VENDOR_NAME","").lower().split(",")

TZ = pytz.timezone("Europe/Warsaw")

# ================= MEMORY =================

steps = {}
daily = {}
last_ad = {}
blacklist = set()
offer_id = 1000

# ================= STYLING MAP =================

CHAR_MAP = {
    "a": "@","b": "В","c": "(","d": "D","e": "3","f": "F","g": "G",
    "h": "H","i": "1","j": "J","k": "K","l": "L","m": "M","n": "N",
    "o": "0","p": "P","q": "Q","r": "R","s": "$","t": "7",
    "u": "Ü","v": "V","w": "W","x": "X","y": "Y","z": "Z",
    "ą": "@","ć": "C","ę": "3","ł": "L","ń": "N",
    "ó": "0","ś": "$","ż": "Z","ź": "Z"
}

def encode_name(text):
    return "".join(CHAR_MAP.get(c.lower(), c.upper()) for c in text)

# ================= PRODUCT EMOJI =================

PRODUCT_EMOJI = {
    "buch": "🌿","weed": "🌿",
    "mewa": "🕊",
    "polak": "🐟","feta": "🐟",
    "koks": "✉️","kokaina": "✉️","cola": "✉️",
    "crystal": "💎","mefedron": "💎","3cmc": "💎","4cmc": "💎","3mmc": "💎","4mmc": "💎",
    "xanax": "💊","alprazolam": "💊",
    "lsd": "🧠","kwas": "🧠",
    "mdma": "🍬","ecstasy": "🍬",
    "hasz": "🟫","haszysz": "🟫",
    "speed": "⚡","amfa": "⚡"
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

    items = "\n".join([
        f"• {get_product_emoji(p)} {encode_name(p)}"
        for p in products
    ])

    return f"""
<b>━━━━━━━━━━━━━━━━━━━━━━</b>
<b>🛍 OSTATNIA SZANSA MARKET</b>
<b>━━━━━━━━━━━━━━━━━━━━━━</b>

<b>🆔 Oferta:</b> #{offer_id}
<b>🕒 Godzina:</b> {now_pl()}

<b>📦 OFERTA</b>

{items}

<b>━━━━━━━━━━━━━━━━━━━━━━</b>
<b>📩 Kontakt:</b> @{user}
<b>━━━━━━━━━━━━━━━━━━━━━━</b>
"""

def contains_blacklist(text):
    return any(w in text.lower() for w in blacklist)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid == ADMIN_ID:
        kb = [
            [InlineKeyboardButton("➕ NOWA OFERTA", callback_data="new_offer")],
            [InlineKeyboardButton("🛠 PANEL ADMINA", callback_data="admin")]
        ]
    else:
        kb = [[InlineKeyboardButton("➕ NOWA OFERTA", callback_data="new_offer")]]

    await update.message.reply_text(
        "🔥 WITAJ W MARKETPLACE 🔥",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= BUTTONS =================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    username = q.from_user.username

    # ===== ADMIN PANEL =====
    if q.data == "admin" and uid == ADMIN_ID:
        kb = [
            [InlineKeyboardButton("📃 Vendorzy", callback_data="vendors")],
            [InlineKeyboardButton("⛔ Blacklista", callback_data="show_bl")],
            [InlineKeyboardButton("➕ Dodaj słowo", callback_data="add_bl")],
            [InlineKeyboardButton("🗑 Wyczyść blacklistę", callback_data="clear_bl")],
            [InlineKeyboardButton("🔄 Reset limitów", callback_data="reset_limits")]
        ]
        await q.message.reply_text("🛠 PANEL ADMINA", reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data == "vendors" and uid == ADMIN_ID:
        await q.message.reply_text("\n".join(VENDORS))
        return

    if q.data == "show_bl" and uid == ADMIN_ID:
        await q.message.reply_text("BLACKLISTA:\n" + ("\n".join(blacklist) if blacklist else "pusta"))
        return

    if q.data == "add_bl" and uid == ADMIN_ID:
        context.user_data["add_blacklist"] = True
        await q.message.reply_text("Podaj słowo:")
        return

    if q.data == "clear_bl" and uid == ADMIN_ID:
        blacklist.clear()
        await q.message.reply_text("✅ Wyczyścione")
        return

    if q.data == "reset_limits" and uid == ADMIN_ID:
        daily.clear()
        await q.message.reply_text("✅ Limity zresetowane")
        return

    # ===== NEW OFFER =====
    if q.data == "new_offer":
        if not username or username.lower() not in VENDORS:
            await q.message.reply_text("❌ Nie jesteś vendorem.")
            return

        today = datetime.now(TZ).date()
        daily.setdefault(uid, {"date":today,"count":0})

        if daily[uid]["date"] != today:
            daily[uid] = {"date":today,"count":0}

        if daily[uid]["count"] >= MAX_DAILY:
            await q.message.reply_text("❌ Dzisiejszy limit wykorzystany.")
            return

        kb = [
            [InlineKeyboardButton(str(i), callback_data=f"q{i}") for i in range(1,6)],
            [InlineKeyboardButton(str(i), callback_data=f"q{i}") for i in range(6,11)]
        ]

        await q.message.reply_text("Ile produktów?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("q"):
        steps[uid] = {"qty": int(q.data[1:]), "items":[]}
        await q.message.reply_text("Podaj produkt 1:")
        return

    if q.data == "send":
        ad = build_offer(steps[uid]["items"], username)

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

        last_ad[uid] = msg.message_id
        daily[uid]["count"] += 1
        steps.pop(uid)

        await q.message.reply_text("✅ Opublikowano")

    if q.data == "cancel":
        steps.pop(uid,None)
        await q.message.reply_text("❌ Anulowano")

# ================= COLLECT =================

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if context.user_data.get("add_blacklist") and uid == ADMIN_ID:
        blacklist.add(text.lower())
        context.user_data["add_blacklist"] = False
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
        preview = build_offer(steps[uid]["items"], update.effective_user.username)

        kb = [[
            InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send"),
            InlineKeyboardButton("❌ ANULUJ",callback_data="cancel")
        ]]

        await update.message.reply_text(
            "Tak będzie wyglądać oferta:\n\n"+preview,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND, start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect))
    print("🔥 MARKETPLACE PREMIUM v19238128733.0 ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
