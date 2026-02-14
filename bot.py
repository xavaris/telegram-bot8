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
offer_id = 1000

# ================= STYLE =================

CHAR_MAP = {"a":"@","e":"3","i":"1","o":"0","s":"$","t":"7"}

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

# ================= 5 TEMPLATES =================

def render_offer(products,user,style):
    global offer_id
    offer_id+=1
    items="\n".join([f"• {get_product_emoji(p)} {encode_name(p)}" for p in products])

    if style==1:
        return f"""
<b>████████████████</b>
<b>🔥 OSTATNIA SZANSA 🔥</b>
<b>████████████████</b>

{items}

<b>@{user}</b>
"""

    if style==2:
        return f"""
<b>╔══════════════╗</b>
<b>⚡ MARKET ⚡</b>
<b>╚══════════════╝</b>

{items}

<b>@{user}</b>
"""

    if style==3:
        return f"""
<b>🛍 OSTATNIA SZANSA</b>

{items}

<b>@{user}</b>
"""

    if style==4:
        return f"""
<b>━━━━━━━━━━━━━━</b>
<b>🔥 MARKET 🔥</b>
<b>━━━━━━━━━━━━━━</b>

{items}

<b>@{user}</b>
"""

    if style==5:
        return f"""
<b>████████████████████</b>
<b>💎 PREMIUM MARKET 💎</b>
<b>████████████████████</b>

{items}

<b>@{user}</b>
"""

# ================= START =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if uid==ADMIN_ID:
        kb=[
            [InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new_offer")],
            [InlineKeyboardButton("🛠 PANEL ADMINA",callback_data="admin")]
        ]
    else:
        kb=[[InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new_offer")]]

    await update.message.reply_text("🔥 MARKETPLACE 🔥",reply_markup=InlineKeyboardMarkup(kb))

# ================= ADMIN =================

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📃 VENDORZY",callback_data="vendors")],
        [InlineKeyboardButton("🧹 WYCZYŚĆ TEMAT",callback_data="clean_topic")],
        [InlineKeyboardButton("🔄 RESET LIMITÓW",callback_data="reset_limits")]
    ])

def vendors_keyboard():
    rows=[]
    row=[]
    for v in VENDORS:
        row.append(InlineKeyboardButton(v.upper(),callback_data=f"v_{v}"))
        if len(row)==2:
            rows.append(row)
            row=[]
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("⬅ POWRÓT",callback_data="admin")])
    return InlineKeyboardMarkup(rows)

# ================= BUTTONS =================

async def buttons(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    uid=q.from_user.id
    user=q.from_user.username.lower()

    # ADMIN PANEL
    if q.data=="admin" and uid==ADMIN_ID:
        await q.message.reply_text("🛠 PANEL ADMINA",reply_markup=admin_keyboard())
        return

    if q.data=="vendors" and uid==ADMIN_ID:
        await q.message.reply_text("VENDORZY:",reply_markup=vendors_keyboard())
        return

    if q.data.startswith("v_") and uid==ADMIN_ID:
        v=q.data[2:]
        stats=vendor_stats.get(v,0)
        kb=[
            [InlineKeyboardButton("🗑 USUŃ VENDORA",callback_data=f"del_{v}")],
            [InlineKeyboardButton("⬅ POWRÓT",callback_data="vendors")]
        ]
        await q.message.reply_text(
            f"VENDOR: {v.upper()}\nOFERTY: {stats}",
            reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("del_") and uid==ADMIN_ID:
        VENDORS.discard(q.data[4:])
        await q.message.reply_text("USUNIĘTO")
        return

    if q.data=="clean_topic" and uid==ADMIN_ID:
        for m in list(last_ad.values()):
            try: await context.bot.delete_message(GROUP_ID,m)
            except: pass
        last_ad.clear()
        await q.message.reply_text("TEMAT WYCZYSZCZONY")
        return

    if q.data=="reset_limits" and uid==ADMIN_ID:
        daily.clear()
        await q.message.reply_text("LIMITY ZRESETOWANE")
        return

    # NEW OFFER -> TEMPLATE PICK
    if q.data=="new_offer":
        if user not in VENDORS:
            await q.message.reply_text("❌ NIE JESTEŚ VENDOREM")
            return

        kb=[[InlineKeyboardButton(f"SZABLON {i}",callback_data=f"tpl_{i}") for i in range(1,6)]]
        await q.message.reply_text("WYBIERZ SZABLON:",reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("tpl_"):
        style=int(q.data[-1])
        steps[uid]={"style":style,"items":[]}
        preview=render_offer(["BUCH","KOKS"],"preview",style)
        kb=[[InlineKeyboardButton("DALEJ",callback_data="qty")]]
        await q.message.reply_text(preview,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data=="qty":
        kb=[[InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(1,6)],
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(6,11)]]
        await q.message.reply_text("ILE PRODUKTÓW?",reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("q"):
        steps[uid]["qty"]=int(q.data[1:])
        await q.message.reply_text("PODAJ PRODUKT 1")
        return

    if q.data=="send":
        ad=render_offer(steps[uid]["items"],user,steps[uid]["style"])
        msg=await context.bot.send_photo(
            GROUP_ID,LOGO_URL,
            caption=ad,parse_mode="HTML",
            message_thread_id=TOPIC_ID)

        last_ad[uid]=msg.message_id
        vendor_stats[user]=vendor_stats.get(user,0)+1
        steps.pop(uid)

        await q.message.reply_text("✅ OPUBLIKOWANO")
        return

# ================= COLLECT =================

async def collect(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if uid not in steps: return

    steps[uid]["items"].append(update.message.text)

    if len(steps[uid]["items"])<steps[uid]["qty"]:
        await update.message.reply_text(f"PODAJ PRODUKT {len(steps[uid]['items'])+1}")
    else:
        ad=render_offer(steps[uid]["items"],update.effective_user.username,steps[uid]["style"])
        kb=[[InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send")]]
        await update.message.reply_text(ad,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

# ================= MAIN =================

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND,start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,collect))
    print("🔥 MARKETPLACE TEMPLATE + ADMIN ONLINE")
    app.run_polling()

if __name__=="__main__":
    main()
