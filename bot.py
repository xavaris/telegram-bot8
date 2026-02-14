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

# ================= UTIL =================

def now_pl():
    return datetime.now(TZ).strftime("%H:%M")

def build_offer(products, user):
    global offer_id
    offer_id += 1

    items = "\n".join([f"• {p}" for p in products])

    return f"""
<b>━━━━━━━━━━━━━━━━━━━━━━</b>
<b>🛍️ OSTATNIA SZANSA MARKET</b>
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
    for w in blacklist:
        if w in text.lower():
            return True
    return False

# ================= MAIN MENU =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ NOWA OFERTA", callback_data="new_offer")],
        [InlineKeyboardButton("🛠 PANEL ADMINA", callback_data="admin")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 OSTATNIA SZANSA MARKET 🔥\nWybierz opcję:",
        reply_markup=main_menu()
    )

# ================= BUTTONS =================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    username = q.from_user.username

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
            [InlineKeyboardButton("1",callback_data="q1"),
             InlineKeyboardButton("2",callback_data="q2"),
             InlineKeyboardButton("3",callback_data="q3")],
            [InlineKeyboardButton("4",callback_data="q4"),
             InlineKeyboardButton("5",callback_data="q5")]
        ]

        await q.message.reply_text(
            "Ile produktów?",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # ===== QTY =====
    if q.data.startswith("q"):
        qty = int(q.data[1:])
        steps[uid] = {"qty":qty,"items":[]}
        await q.message.reply_text("Podaj produkt 1:")
        return

    # ===== CONFIRM SEND =====
    if q.data == "send":
        data = steps[uid]
        ad = build_offer(data["items"], username)

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

        await q.message.reply_text("✅ Opublikowano.")
        return

    if q.data == "cancel":
        steps.pop(uid,None)
        await q.message.reply_text("❌ Anulowano.")
        return

    # ===== ADMIN PANEL =====
    if q.data == "admin":
        if uid != ADMIN_ID:
            return

        kb = [
            [InlineKeyboardButton("📃 Vendorzy",callback_data="avendors")],
            [InlineKeyboardButton("⛔ Blacklista",callback_data="ablacklist")],
            [InlineKeyboardButton("➕ Dodaj słowo",callback_data="addword")],
            [InlineKeyboardButton("🗑 Wyczyść blacklistę",callback_data="clearbl")]
        ]

        await q.message.reply_text(
            "🛠 PANEL ADMINA",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if q.data == "avendors":
        await q.message.reply_text("\n".join(VENDORS))
        return

    if q.data == "ablacklist":
        await q.message.reply_text(
            "BLACKLISTA:\n" + ("\n".join(blacklist) if blacklist else "pusta")
        )
        return

    if q.data == "addword":
        context.user_data["add_blacklist"] = True
        await q.message.reply_text("Podaj słowo do blacklisty:")
        return

    if q.data == "clearbl":
        blacklist.clear()
        await q.message.reply_text("✅ Blacklista wyczyszczona.")
        return

# ================= COLLECT TEXT =================

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    # ADMIN ADD BLACKLIST WORD
    if context.user_data.get("add_blacklist"):
        blacklist.add(text.lower())
        context.user_data["add_blacklist"] = False
        await update.message.reply_text(f"⛔ Dodano: {text}")
        return

    if uid not in steps:
        return

    if contains_blacklist(text):
        await update.message.reply_text("❌ Niedozwolone słowo.")
        return

    steps[uid]["items"].append(text)

    if len(steps[uid]["items"]) < steps[uid]["qty"]:
        await update.message.reply_text(
            f"Podaj produkt {len(steps[uid]['items'])+1}:"
        )
    else:
        preview = build_offer(
            steps[uid]["items"],
            update.effective_user.username
        )

        kb = [[
            InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send"),
            InlineKeyboardButton("❌ ANULUJ",callback_data="cancel")
        ]]

        await update.message.reply_text(
            "Tak będzie wyglądała oferta:\n\n"+preview,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.COMMAND, start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect))

    print("🔥 MARKETPLACE BOT PREMIUM v99999.0 ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
