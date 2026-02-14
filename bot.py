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
vendor_stats = {}
quick_templates = {}   # {vendor:[items]}
offer_id = 1000

# ================= STYLE =================

CHAR_MAP={"a":"@","e":"3","i":"1","o":"0","s":"$","t":"7"}

def encode_name(t):
    return "".join(CHAR_MAP.get(c.lower(),c.upper()) for c in t)

PRODUCT_EMOJI={
"buch":"🌿","weed":"🌿",
"mewa":"🕊",
"polak":"🐟","feta":"🐟",
"koks":"✉️","kokaina":"✉️","cola":"✉️",
"crystal":"💎","mefedron":"💎"
}

def get_product_emoji(t):
    for k,v in PRODUCT_EMOJI.items():
        if k in t.lower(): return v
    return "📦"

# ================= TIME =================

def now_pl():
    return datetime.now(TZ).strftime("%H:%M")

# ================= 5 VISUAL TEMPLATES =================

def build_offer(products,user,style):
    global offer_id
    offer_id+=1
    items="\n".join([f"• {get_product_emoji(p)} {encode_name(p)}" for p in products])

    if style==1:
        return f"""
<b>████████████████</b>
<b>🔥 OSTATNIA SZANSA 🔥</b>
<b>████████████████</b>

<b>🆔 #{offer_id}</b> | <b>{now_pl()}</b>

{items}

<b>@{user}</b>
"""

    if style==2:
        return f"""
<b>╔══════════════╗</b>
<b>⚡ MARKET ⚡</b>
<b>╚══════════════╝</b>

{items}

<b>📩 @{user}</b>
"""

    if style==3:
        return f"""
<b>🛍 OSTATNIA SZANSA</b>

{items}

<b>Kontakt: @{user}</b>
"""

    if style==4:
        return f"""
<b>━━━━━━━━━━━━━━</b>
<b>🔥 MARKET 🔥</b>
<b>━━━━━━━━━━━━━━</b>

{items}

<b>━━━━━━━━━━━━━━</b>
<b>@{user}</b>
"""

    if style==5:
        return f"""
<b>████████████████████</b>
<b>💎 PREMIUM MARKET 💎</b>
<b>████████████████████</b>

{items}

<b>📩 @{user}</b>
"""

# ================= START =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    kb=[
        [InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new_offer")],
        [InlineKeyboardButton("⚡ SZYBKA OFERTA",callback_data="quick_offer")]
    ]
    await update.message.reply_text("🔥 MARKETPLACE 🔥",reply_markup=InlineKeyboardMarkup(kb))

# ================= BUTTONS =================

async def buttons(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    uid=q.from_user.id
    user=q.from_user.username.lower()

    # NEW OFFER → TEMPLATE PICK
    if q.data=="new_offer":
        kb=[[InlineKeyboardButton(f"SZABLON {i}",callback_data=f"tpl_{i}") for i in range(1,6)]]
        await q.message.reply_text("WYBIERZ WYGLĄD:",reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("tpl_"):
        style=int(q.data[-1])
        steps[uid]={"style":style,"items":[],"qty":None}
        kb=[[InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(1,6)],
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(6,11)]]
        await q.message.reply_text("ILE PRODUKTÓW?",reply_markup=InlineKeyboardMarkup(kb))
        return

    # QUICK OFFER
    if q.data=="quick_offer":
        steps[uid]={"style":1,"items":[],"qty":None,"quick":True}
        kb=[[InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(1,6)],
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(6,11)]]
        await q.message.reply_text("ILE PRODUKTÓW?",reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("q"):
        steps[uid]["qty"]=int(q.data[1:])
        await q.message.reply_text("PODAJ PRODUKT 1")
        return

    # SEND
    if q.data=="send":
        data=steps[uid]
        ad=build_offer(data["items"],user,data["style"])

        msg=await context.bot.send_photo(
            GROUP_ID,LOGO_URL,
            caption=ad,parse_mode="HTML",
            message_thread_id=TOPIC_ID
        )

        last_ad[uid]=msg.message_id

        kb=[
            [InlineKeyboardButton("💾 ZAPISZ JAKO SZYBKA",callback_data="save_quick")],
            [InlineKeyboardButton("❌ NIE",callback_data="no_save")]
        ]

        await q.message.reply_text("Zapisać jako szybką ofertę?",reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data=="save_quick":
        quick_templates[user]=steps[uid]["items"]
        steps.pop(uid)
        await q.message.reply_text("✅ ZAPISANO")
        return

    if q.data=="no_save":
        steps.pop(uid)
        await q.message.reply_text("OK")
        return

# ================= COLLECT =================

async def collect(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if uid not in steps: return

    steps[uid]["items"].append(update.message.text)

    if len(steps[uid]["items"])<steps[uid]["qty"]:
        await update.message.reply_text(f"PODAJ PRODUKT {len(steps[uid]['items'])+1}")
    else:
        ad=build_offer(
            steps[uid]["items"],
            update.effective_user.username,
            steps[uid]["style"]
        )

        kb=[[InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send")]]

        await update.message.reply_text(
            ad,parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# ================= MAIN =================

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND,start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,collect))
    print("🔥 MARKETPLACE TEMPLATE SYSTEM ONLINE")
    app.run_polling()

if __name__=="__main__":
    main()
