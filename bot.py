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
blacklist = set()
offer_id = 1000

vendor_stats = {}

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

# ================= UTIL =================

def now_pl():
    return datetime.now(TZ).strftime("%H:%M")

def build_offer(products,user):
    global offer_id
    offer_id+=1
    items="\n".join([f"• {get_product_emoji(p)} {encode_name(p)}" for p in products])
    return f"""
<b>████████████████████</b>
<b>🔥 OSTATNIA SZANSA 🔥</b>
<b>████████████████████</b>

<b>🆔 #{offer_id}</b>
<b>🕒 {now_pl()}</b>

{items}

<b>████████████████████</b>
<b>📩 @{user}</b>
"""

# ================= START =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if uid==ADMIN_ID:
        kb=[[InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new_offer")],
            [InlineKeyboardButton("🛠 PANEL ADMINA",callback_data="admin")]]
    else:
        kb=[[InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new_offer")]]

    await update.message.reply_text("🔥 MARKETPLACE 🔥",reply_markup=InlineKeyboardMarkup(kb))

# ================= ADMIN KEYBOARD =================

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📃 VENDORZY",callback_data="vendors")],
        [InlineKeyboardButton("🧹 WYCZYŚĆ TEMAT",callback_data="clean_topic")]
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
    user=q.from_user.username

    # ADMIN
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
            f"VENDOR: {v.upper()}\nOFERTY ŁĄCZNIE: {stats}",
            reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("del_") and uid==ADMIN_ID:
        v=q.data[4:]
        VENDORS.discard(v)
        await q.message.reply_text(f"USUNIĘTO {v.upper()}")
        return

    if q.data=="clean_topic" and uid==ADMIN_ID:
        for m in list(last_ad.values()):
            try: await context.bot.delete_message(GROUP_ID,m)
            except: pass
        last_ad.clear()
        await q.message.reply_text("TEMAT WYCZYSZCZONY")
        return

    # NEW OFFER
    if q.data=="new_offer":
        if user.lower() not in VENDORS:
            await q.message.reply_text("❌ NIE JESTEŚ VENDOREM")
            return

        today=datetime.now(TZ).date()
        daily.setdefault(uid,{"date":today,"count":0})
        if daily[uid]["date"]!=today:
            daily[uid]={"date":today,"count":0}

        if daily[uid]["count"]>=MAX_DAILY:
            await q.message.reply_text("LIMIT DZIŚ")
            return

        kb=[[InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(1,6)],
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(6,11)]]
        await q.message.reply_text("ILE PRODUKTÓW?",reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("q"):
        steps[uid]={"qty":int(q.data[1:]),"items":[]}
        await q.message.reply_text("PODAJ PRODUKT 1")
        return

    # EDIT
    if q.data.startswith("edit_"):
        idx=int(q.data.split("_")[1])
        steps[uid]["edit"]=idx
        await q.message.reply_text(f"PODAJ NOWĄ NAZWĘ DLA {idx+1}")
        return

    if q.data=="send":
        ad=build_offer(steps[uid]["items"],user)
        msg=await context.bot.send_photo(
            GROUP_ID,LOGO_URL,
            caption=ad,parse_mode="HTML",
            message_thread_id=TOPIC_ID)

        last_ad[uid]=msg.message_id
        daily[uid]["count"]+=1
        vendor_stats[user.lower()]=vendor_stats.get(user.lower(),0)+1
        steps.pop(uid)

        await q.message.reply_text("✅ OPUBLIKOWANO\n📊 STATUS: OK")
        return

# ================= COLLECT =================

async def collect(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    text=update.message.text

    if uid not in steps: return

    if "edit" in steps[uid]:
        i=steps[uid].pop("edit")
        steps[uid]["items"][i]=text
    else:
        steps[uid]["items"].append(text)

    if len(steps[uid]["items"])<steps[uid]["qty"]:
        await update.message.reply_text(f"PODAJ PRODUKT {len(steps[uid]['items'])+1}")
    else:
        rows=[]
        for i in range(len(steps[uid]["items"])):
            rows.append([InlineKeyboardButton(f"✏️ EDYTUJ {i+1}",callback_data=f"edit_{i}")])
        rows.append([
            InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send")
        ])
        await update.message.reply_text(
            build_offer(steps[uid]["items"],update.effective_user.username),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows)
        )

# ================= MAIN =================

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND,start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,collect))
    print("🔥 MARKETPLACE ULTRA ONLINE")
    app.run_polling()

if __name__=="__main__":
    main()
