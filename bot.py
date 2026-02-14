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

VENDORS = set(os.getenv("VENDOR_NAME","").lower().split(","))

TZ = pytz.timezone("Europe/Warsaw")

# ================= MEMORY =================

steps = {}
daily = {}
last_ad = {}
blacklist = set()
offer_id = 1000

# ================= STYLING MAP =================

CHAR_MAP = {
    "a":"@","e":"3","i":"1","o":"0","s":"$","t":"7"
}

def encode_name(text):
    return "".join(CHAR_MAP.get(c.lower(), c.upper()) for c in text)

# ================= PRODUCT EMOJI (opcjonalne) =================

PRODUCT_EMOJI = {
    "buch":"🌿","weed":"🌿",
    "mewa":"🕊",
    "polak":"🐟","feta":"🐟",
    "koks":"✉️","kokaina":"✉️","cola":"✉️",
    "crystal":"💎","mefedron":"💎","3cmc":"💎","4cmc":"💎",
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
<b>🛍 MARKETPLACE</b>
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

# ================= ADMIN PANEL =================

def vendor_keyboard():
    rows = []
    row = []
    for v in VENDORS:
        row.append(InlineKeyboardButton(v, callback_data="noop"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)

# ================= BUTTONS =================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    username = q.from_user.username

    # ===== ADMIN PANEL =====
    if q.data == "admin" and uid == ADMIN_ID:
        kb = [
            [InlineKeyboardButton("👥 Vendorzy", callback_data="show_vendors")],
            [InlineKeyboardButton("➕ Dodaj Vendora", callback_data="add_vendor")],
            [InlineKeyboardButton("➖ Usuń Vendora", callback_data="remove_vendor")],
            [InlineKeyboardButton("⛔ Blacklista", callback_data="show_bl")],
            [InlineKeyboardButton("➕ Dodaj słowo BL", callback_data="add_bl")],
            [InlineKeyboardButton("🗑 Wyczyść BL", callback_data="clear_bl")],
            [InlineKeyboardButton("🔄 Reset limitów", callback_data="reset_limits")]
        ]
        await q.message.reply_text("🛠 PANEL ADMINA", reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data == "show_vendors" and uid == ADMIN_ID:
        await q.message.reply_text("Aktualni vendorzy:", reply_markup=vendor_keyboard())
        return

    if q.data == "add_vendor" and uid == ADMIN_ID:
        context.user_data["add_vendor"] = True
        await q.message.reply_text("Podaj @username vendora:")
        return

    if q.data == "remove_vendor" and uid == ADMIN_ID:
        context.user_data["remove_vendor"] = True
        await q.message.reply_text("Podaj @username vendora do usunięcia:")
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
        await q.message.reply_text("Blacklista wyczyszczona.")
        return

    if q.data == "reset_limits" and uid == ADMIN_ID:
        daily.clear()
        await q.message.reply_text("Limity zresetowane.")
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
            except:
                pass

        last_ad[uid] = msg.message_id
        daily[uid]["count"] += 1
        steps.pop(uid)

        await q.message.reply_text("✅ Opublikowano")

# ================= COLLECT =================

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if context.user_data.get("add_blacklist") and uid == ADMIN_ID:
        blacklist.add(text.lower())
        context.user_data["add_blacklist"] = False
        await update.message.reply_text("Dodano do blacklisty.")
        return

    if context.user_data.get("add_vendor") and uid == ADMIN_ID:
        VENDORS.add(text.replace("@","").lower())
        context.user_data["add_vendor"] = False
        await update.message.reply_text("Vendor dodany.")
        return

    if context.user_data.get("remove_vendor") and uid == ADMIN_ID:
        VENDORS.discard(text.replace("@","").lower())
        context.user_data["remove_vendor"] = False
        await update.message.reply_text("Vendor usunięty.")
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
    print("🔥 MARKETPLACE PREMIUM vULTRA ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
