# MARKETPLACE PREMIUM ULTRA FINAL
# python-telegram-bot v20+

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
MAX_DAILY = int(os.getenv("MAX_DAILY","3"))

VENDORS = set(os.getenv("VENDOR_NAME","").lower().split(","))

TZ = pytz.timezone("Europe/Warsaw")

# ================= MEMORY =================

steps = {}
daily = {}
last_ad = {}
vendor_stats = {}
saved_templates = {}
blacklist = set()
offer_id = 1000

# ================= FULL MAPA LITER =================

CHAR_MAP = {
"a":"@","b":"ß","c":"¢","d":"Ð","e":"3","f":"₣","g":"6",
"h":"Ħ","i":"1","j":"ʝ","k":"Ҡ","l":"Ł","m":"₥","n":"И",
"o":"Ø","p":"₱","q":"Ǫ","r":"Я","s":"$","t":"7",
"u":"Ц","v":"√","w":"₩","x":"Ж","y":"¥","z":"Ƶ",
"ą":"@","ć":"¢","ę":"3","ł":"Ł","ń":"И",
"ó":"Ø","ś":"$","ż":"Ƶ","ź":"Ƶ"
}

def encode(text):
    return "".join(CHAR_MAP.get(c.lower(),c.upper()) for c in text)

# ================= EMOJI PRODUKTÓW =================

PRODUCT_EMOJI = {
"buch":"🌿","weed":"🌿",
"mewa":"🕊",
"polak":"🐟","feta":"🐟",
"koks":"✉️","kokaina":"✉️","cola":"✉️",
"crystal":"💎","mefedron":"💎","3cmc":"💎","4cmc":"💎",
"xanax":"💊",
"lsd":"🧠","kwas":"🧠",
"mdma":"🍬",
"hasz":"🟫",
"speed":"⚡"
}

def get_emoji(text):
    for k,v in PRODUCT_EMOJI.items():
        if k in text.lower():
            return v
    return "📦"

def now():
    return datetime.now(TZ).strftime("%H:%M")

# ================= RENDER PREMIUM =================

def render_offer(products,user,style):
    global offer_id
    offer_id += 1

    items = "\n".join([
        f"• {get_emoji(p)} {encode(p)}"
        for p in products
    ])

    return f"""
<b>████████████████████████</b>
<b>🔥💥🔥 OSTATNIA SZANSA 🔥💥🔥</b>
<b>████████████████████████</b>

<b>🆔 OFERTA:</b> #{offer_id}
<b>🕒 CZAS:</b> {now()}

{items}

<b>████████████████████████</b>
<b>📩 @{user}</b>
<b>████████████████████████</b>
"""

# ================= START =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user.username.lower()

    if uid == ADMIN_ID:
        VENDORS.add(user)

    kb = [
        [InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new")],
        [InlineKeyboardButton("⚡ SZYBKA OFERTA",callback_data="quick")],
        [InlineKeyboardButton("📂 MOJE SZABLONY",callback_data="templates")]
    ]

    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠 PANEL ADMINA",callback_data="admin")])

    await update.message.reply_text(
        "🔥 MARKETPLACE PREMIUM ULTRA 🔥",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= PANEL ADMINA =================

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 VENDORZY",callback_data="vendors")],
        [InlineKeyboardButton("⛔ BLACKLISTA",callback_data="blacklist")],
        [InlineKeyboardButton("🧹 WYCZYŚĆ TEMAT",callback_data="clean")],
        [InlineKeyboardButton("🔄 RESET LIMITÓW",callback_data="reset")]
    ])

# ================= BUTTONS =================

async def buttons(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    user = q.from_user.username.lower()

    # ADMIN PANEL
    if q.data == "admin" and uid == ADMIN_ID:
        await q.message.reply_text("🛠 PANEL ADMINA",reply_markup=admin_keyboard())
        return

    if q.data == "vendors" and uid == ADMIN_ID:
        rows = []
        for v in VENDORS:
            rows.append([InlineKeyboardButton(v.upper(),callback_data=f"v_{v}")])
        await q.message.reply_text("👥 VENDORZY:",reply_markup=InlineKeyboardMarkup(rows))
        return

    if q.data.startswith("v_") and uid == ADMIN_ID:
        v = q.data[2:]
        stats = vendor_stats.get(v,0)

        kb = [
            [InlineKeyboardButton("🗑 USUŃ VENDORA",callback_data=f"del_{v}")],
            [InlineKeyboardButton("⬅ POWRÓT",callback_data="vendors")]
        ]

        await q.message.reply_text(
            f"👤 {v.upper()}\n📊 OFERTY: {stats}",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if q.data.startswith("del_") and uid == ADMIN_ID:
        VENDORS.discard(q.data[4:])
        await q.message.reply_text("🗑 VENDOR USUNIĘTY")
        return

    if q.data == "blacklist" and uid == ADMIN_ID:
        context.user_data["add_bl"] = True
        await q.message.reply_text("Podaj słowo do blacklisty:")
        return

    if q.data == "clean" and uid == ADMIN_ID:
        for m in list(last_ad.values()):
            try:
                await context.bot.delete_message(GROUP_ID,m)
            except:
                pass
        last_ad.clear()
        await q.message.reply_text("🧹 TEMAT WYCZYSZCZONY")
        return

    if q.data == "reset" and uid == ADMIN_ID:
        daily.clear()
        await q.message.reply_text("🔄 LIMITY ZRESETOWANE")
        return

    # NEW OFFER
    if q.data == "new":
        steps[uid] = {"items":[]}
        await q.message.reply_text("Ile produktów? (1-10)")
        return

    if q.data == "send":
        ad = render_offer(steps[uid]["items"],user,0)

        msg = await context.bot.send_photo(
            GROUP_ID,
            LOGO_URL,
            caption=ad,
            parse_mode="HTML",
            message_thread_id=TOPIC_ID
        )

        last_ad[uid] = msg.message_id
        vendor_stats[user] = vendor_stats.get(user,0)+1
        steps.pop(uid)

        await q.message.reply_text("✅ OPUBLIKOWANO")
        return

# ================= COLLECT =================

async def collect(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if context.user_data.get("add_bl") and uid == ADMIN_ID:
        blacklist.add(text.lower())
        context.user_data["add_bl"] = False
        await update.message.reply_text("⛔ DODANO DO BLACKLISTY")
        return

    if uid not in steps:
        return

    if any(w in text.lower() for w in blacklist):
        await update.message.reply_text("❌ ZABLOKOWANE SŁOWO")
        return

    if "qty" not in steps[uid]:
        steps[uid]["qty"] = int(text)
        await update.message.reply_text("Podaj produkt 1")
        return

    steps[uid]["items"].append(text)

    if len(steps[uid]["items"]) < steps[uid]["qty"]:
        await update.message.reply_text(
            f"Podaj produkt {len(steps[uid]['items'])+1}"
        )
    else:
        ad = render_offer(steps[uid]["items"],
                          update.effective_user.username,
                          0)

        await update.message.reply_text(
            ad,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send")]]
            )
        )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND,start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,collect))
    print("🔥 MARKETPLACE PREMIUM ULTRA ONLINE")
    app.run_polling()

if __name__ == "__main__":
    main()
