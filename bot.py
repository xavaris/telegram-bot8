import os, requests
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

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
TOPIC_ID = int(os.getenv("TOPIC_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOGO_URL = os.getenv("LOGO_URL")

VENDORS = os.getenv("VENDOR_NAME","").lower().split(",")

MAX_PER_DAY = 2
TZ = pytz.timezone("Europe/Warsaw")

# ================= MEMORY =================

steps = {}
daily = {}
last_ad = {}

# ================= MAP =================

MAP = {
"a":"@", "e":"3", "i":"!", "o":"0", "s":"$", "b":"8",
"k":"X", "m":"M", "t":"7", "l":"1", "g":"6", "r":"2",
"c":"(", "h":"#"
}

def encode(t):
    return "".join(MAP.get(c,c) for c in t.lower()).upper()

# ================= FORMAT =================

def build_ad(products, user):
    now = datetime.now(TZ).strftime("%H:%M")
    items = "\n".join([f"• {encode(p)}" for p in products])

    return f"""
🎆🔥🎆  O S T A T N I A  S Z A N S A  🎆🔥🎆

╔════════════════════╗
🔥 O F F E R T A 🔥
╚════════════════════╝

{items}

━━━━━━━━━━━━━━━━━━━━
📩 @{user}
🕒 {now}
━━━━━━━━━━━━━━━━━━━━
"""

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not user.username or user.username.lower() not in VENDORS:
        await update.message.reply_text("❌ Brak dostępu.")
        return

    kb = [[InlineKeyboardButton(str(i), callback_data=f"q_{i}") for i in range(1,6)],
          [InlineKeyboardButton(str(i), callback_data=f"q_{i}") for i in range(6,11)]]

    await update.message.reply_text("Ile produktów?", reply_markup=InlineKeyboardMarkup(kb))

# ================= BUTTONS =================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id

    if q.data.startswith("q_"):
        steps[uid] = {"qty": int(q.data[2:]), "items":[]}
        await q.message.reply_text("Podaj produkt 1:")
        return

    if q.data == "yes":
        data = steps[uid]
        ad = build_ad(data["items"], q.from_user.username)

        await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=TOPIC_ID,
            photo=LOGO_URL,
            caption=ad
        )

        if uid in last_ad:
            try:
                await context.bot.delete_message(GROUP_ID, last_ad[uid])
            except: pass

        steps.pop(uid)
        await q.message.reply_text("✅ Opublikowano.")

    if q.data == "no":
        steps.pop(uid)
        await q.message.reply_text("Anulowano. /start")

# ================= COLLECT =================

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in steps:
        return

    steps[uid]["items"].append(update.message.text)

    if len(steps[uid]["items"]) < steps[uid]["qty"]:
        await update.message.reply_text(
            f"Podaj produkt {len(steps[uid]['items'])+1}:"
        )
    else:
        ad = build_ad(steps[uid]["items"], update.effective_user.username)

        kb = [[
            InlineKeyboardButton("✅ WYŚLIJ", callback_data="yes"),
            InlineKeyboardButton("❌ ANULUJ", callback_data="no")
        ]]

        await update.message.reply_text(
            f"Tak będzie wyglądało Twoje ogłoszenie:\n{ad}",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# ================= PANEL ADMINA =================

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "🛠 PANEL ADMINA\n\n"
        "/vendors - lista vendorów\n"
        "/reload - przeładuj vendorów"
    )

async def vendors_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text("\n".join(VENDORS))

async def reload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global VENDORS
    VENDORS = os.getenv("VENDOR_NAME","").lower().split(",")
    await update.message.reply_text("♻️ Vendorzy przeładowani.")

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("vendors", vendors_cmd))
    app.add_handler(CommandHandler("reload", reload_cmd))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect))

    print("🔥 OSTATNIA SZANSA BOT ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
