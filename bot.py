# MARKETPLACE PREMIUM ULTRA FINAL v6666.6666
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

# ================= MAPA LITER =================

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

# ================= EMOJI =================

PRODUCT_EMOJI={
"buch":"🌿","weed":"🌿",
"mewa":"🕊",
"polak":"🐟","feta":"🐟",
"koks":"✉️","kokaina":"✉️","cola":"✉️",
"crystal":"💎","mefedron":"💎",
"xanax":"💊","mdma":"🍬","lsd":"🧠","hasz":"🟫","speed":"⚡"
}

def get_emoji(t):
    for k,v in PRODUCT_EMOJI.items():
        if k in t.lower():
            return v
    return "📦"

def now():
    return datetime.now(TZ).strftime("%H:%M")

# ================= RENDER =================

def render_offer(products,user):
    global offer_id
    offer_id+=1

    items="\n".join([
        f"• {get_emoji(p)} {encode(p)}"
        for p in products
    ])

    return f"""
<b>████████████████████████</b>
<b>🔥💥🔥 OSTATNIA SZANSA 🔥💥🔥</b>
<b>████████████████████████</b>

<b>🆔 #{offer_id}</b> | <b>🕒 {now()}</b>

{items}

<b>████████████████████████</b>
<b>📩 @{user}</b>
<b>████████████████████████</b>
"""

# ================= START =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    user=update.effective_user.username.lower()

    if uid==ADMIN_ID:
        VENDORS.add(user)

    kb=[
        [InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new")],
        [InlineKeyboardButton("⚡ SZYBKA OFERTA",callback_data="quick")],
        [InlineKeyboardButton("📂 MOJE SZABLONY",callback_data="templates")]
    ]

    if uid==ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠 PANEL ADMINA",callback_data="admin")])

    await update.message.reply_text(
        "🔥 MARKETPLACE PREMIUM ULTRA 🔥",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ================= ADMIN PANEL =================

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ DODAJ VENDORA",callback_data="add_vendor")],
        [InlineKeyboardButton("👥 VENDORZY",callback_data="vendors")],
        [InlineKeyboardButton("⛔ BLACKLISTA",callback_data="blacklist")],
        [InlineKeyboardButton("🧹 WYCZYŚĆ TEMAT",callback_data="clean")],
        [InlineKeyboardButton("🔄 RESET LIMITÓW",callback_data="reset")]
    ])

# ================= BUTTONS =================

async def buttons(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()

    uid=q.from_user.id
    user=q.from_user.username.lower()

    # ADMIN
    if q.data=="admin" and uid==ADMIN_ID:
        await q.message.reply_text("🛠 PANEL ADMINA",reply_markup=admin_kb())
        return

    if q.data=="add_vendor" and uid==ADMIN_ID:
        context.user_data["add_vendor"]=True
        await q.message.reply_text("Podaj @username vendora:")
        return

    if q.data=="vendors" and uid==ADMIN_ID:
        rows=[[InlineKeyboardButton(v.upper(),callback_data=f"v_{v}")] for v in VENDORS]
        await q.message.reply_text("👥 VENDORZY:",reply_markup=InlineKeyboardMarkup(rows))
        return

    if q.data.startswith("v_") and uid==ADMIN_ID:
        v=q.data[2:]
        stats=vendor_stats.get(v,0)

        kb=[
            [InlineKeyboardButton("🗑 USUŃ VENDORA",callback_data=f"del_{v}")],
            [InlineKeyboardButton("⬅ POWRÓT",callback_data="vendors")]
        ]

        await q.message.reply_text(
            f"👤 {v.upper()}\n📊 OFERTY: {stats}",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if q.data.startswith("del_") and uid==ADMIN_ID:
        VENDORS.discard(q.data[4:])
        await q.message.reply_text("🗑 VENDOR USUNIĘTY")
        return

    if q.data=="blacklist" and uid==ADMIN_ID:
        context.user_data["add_bl"]=True
        await q.message.reply_text("Podaj słowo do blacklisty:")
        return

    # QUICK OFFER -> kafelki
    if q.data=="quick":
        if user not in VENDORS:
            await q.message.reply_text("❌ NIE JESTEŚ VENDOREM")
            return

        rows=[
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(1,6)],
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(6,11)]
        ]

        await q.message.reply_text(
            "⚡ ILE PRODUKTÓW?",
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if q.data.startswith("q"):
        steps[uid]={"qty":int(q.data[1:]),"items":[]}
        await q.message.reply_text("Podaj produkt 1")
        return

    # SEND
    if q.data=="send":
        ad=render_offer(steps[uid]["items"],user)

        msg=await context.bot.send_photo(
            GROUP_ID,
            LOGO_URL,
            caption=ad,
            parse_mode="HTML",
            message_thread_id=TOPIC_ID
        )

        last_ad[uid]=msg.message_id
        vendor_stats[user]=vendor_stats.get(user,0)+1
        steps.pop(uid)

        await q.message.reply_text("✅ OPUBLIKOWANO")
        return

# ================= COLLECT =================

async def collect(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    text=update.message.text

    if context.user_data.get("add_vendor") and uid==ADMIN_ID:
        VENDORS.add(text.replace("@","").lower())
        context.user_data["add_vendor"]=False
        await update.message.reply_text("✅ DODANO VENDORA")
        return

    if context.user_data.get("add_bl") and uid==ADMIN_ID:
        blacklist.add(text.lower())
        context.user_data["add_bl"]=False
        await update.message.reply_text("⛔ DODANO DO BLACKLISTY")
        return

    if uid not in steps:
        return

    if any(w in text.lower() for w in blacklist):
        await update.message.reply_text("❌ ZABLOKOWANE SŁOWO")
        return

    steps[uid]["items"].append(text)

    if len(steps[uid]["items"])<steps[uid]["qty"]:
        await update.message.reply_text(
            f"Podaj produkt {len(steps[uid]['items'])+1}"
        )
    else:
        ad=render_offer(steps[uid]["items"],
                        update.effective_user.username)

        await update.message.reply_text(
            ad,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send")]]
            )
        )

# ================= MAIN =================

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND,start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,collect))
    print("🔥 MARKETPLACE PREMIUM ULTRA v6666.6666 ONLINE")
    app.run_polling()

if __name__=="__main__":
    main()
