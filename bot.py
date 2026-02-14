# MARKETPLACE PREMIUM ULTRA v7777.7777
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
"u":"Ц","v":"√","w":"₩","x":"Ж","y":"¥","z":"Ƶ"
}

def encode(t):
    return "".join(CHAR_MAP.get(c.lower(),c.upper()) for c in t)

# ================= EMOJI =================

PRODUCT_EMOJI={
"buch":"🌿","weed":"🌿",
"mewa":"🕊",
"polak":"🐟","feta":"🐟",
"koks":"✉️","kokaina":"✉️","cola":"✉️",
"crystal":"💎","mefedron":"💎",
"xanax":"💊","mdma":"🍬","lsd":"🧠",
"hasz":"🟫","speed":"⚡"
}

def emoji(t):
    for k,v in PRODUCT_EMOJI.items():
        if k in t.lower():
            return v
    return "📦"

def now():
    return datetime.now(TZ).strftime("%H:%M")

# ================= TEMPLATES =================

def render(products,user,style):
    global offer_id
    offer_id+=1
    items="\n".join([f"• {emoji(p)} {encode(p)}" for p in products])

    templates={
0:f"""
<b>████████████████████</b>
<b>🔥 QUICK MARKET 🔥</b>
<b>████████████████████</b>

🆔 #{offer_id} | 🕒 {now()}

{items}

<b>@{user}</b>
""",

1:f"""
<b>╔══════════════╗</b>
<b>⚡ MARKET ⚡</b>
<b>╚══════════════╝</b>

{items}

<b>@{user}</b>
""",

2:f"""
<b>━━━━━━━━━━━━━━</b>
<b>💎 PREMIUM 💎</b>
<b>━━━━━━━━━━━━━━</b>

{items}

<b>@{user}</b>
""",

3:f"""
<b>████ OSTATNIA ████</b>

{items}

<b>@{user}</b>
""",

4:f"""
<b>🛍 MARKETPLACE</b>

{items}

<b>@{user}</b>
""",

5:f"""
<b>╭━━━━━━━━━━━━╮</b>
<b>🔥 ULTRA 🔥</b>
<b>╰━━━━━━━━━━━━╯</b>

{items}

<b>@{user}</b>
"""
    }

    return templates[style]

# ================= START =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    user=update.effective_user.username.lower()

    if uid==ADMIN_ID:
        VENDORS.add(user)

    kb=[
        [InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new")],
        [InlineKeyboardButton("⚡ SZYBKA OFERTA",callback_data="quick")],
        [InlineKeyboardButton("📂 MOJE SZABLONY",callback_data="mytpl")]
    ]

    if uid==ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠 PANEL ADMINA",callback_data="admin")])

    await update.message.reply_text("🔥 MARKETPLACE PREMIUM ULTRA 🔥",reply_markup=InlineKeyboardMarkup(kb))

# ================= ADMIN =================

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ DODAJ VENDORA",callback_data="add_vendor")],
        [InlineKeyboardButton("👥 VENDORZY",callback_data="vendors")],
        [InlineKeyboardButton("⛔ DODAJ SŁOWO BLACKLIST",callback_data="blacklist_add")],
        [InlineKeyboardButton("📛 USUŃ SŁOWO BLACKLIST",callback_data="blacklist_remove")],
        [InlineKeyboardButton("🧹 WYCZYŚĆ TEMAT",callback_data="clean")],
        [InlineKeyboardButton("🔄 RESET LIMITÓW",callback_data="reset")]
    ]
)
    
# ================= BUTTONS =================

async def buttons(update:Update,context:ContextTypes.DEFAULT_TYPE):

    # RESET TRYBÓW ADMINA PRZY KAŻDYM KLIKNIĘCIU
    context.user_data.pop("add_bl", None)
    context.user_data.pop("add_vendor", None)

    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    user = (q.from_user.username or "no_username").lower()



    # ADMIN
# ================= BLACKLIST ADD =================

if q.data=="blacklist_add" and uid==ADMIN_ID:
    context.user_data["add_bl"]=True
       await q.message.reply_text("✍️ Podaj słowo do DODANIA do blacklisty:")
    return

# ================= BLACKLIST REMOVE =================

if q.data=="blacklist_remove" and uid==ADMIN_ID:
    if not blacklist:
        await q.message.reply_text("Blacklist jest pusta")
        return

    rows = []
    for w in blacklist:
        rows.append([InlineKeyboardButton(f"❌ {w}",callback_data=f"delbl_{w}")])

    rows.append([InlineKeyboardButton("⬅ POWRÓT",callback_data="admin")])

    await q.message.reply_text(
        "📛 USUŃ SŁOWO Z BLACKLISTY:",
        reply_markup=InlineKeyboardMarkup(rows)
    )
    return


if q.data.startswith("delbl_") and uid==ADMIN_ID:
    word = q.data[6:]
    blacklist.discard(word)
    await q.message.reply_text(f"🗑 USUNIĘTO: {word}")
    return

    if q.data=="admin" and uid==ADMIN_ID:
        await q.message.reply_text("🛠 PANEL ADMINA",reply_markup=admin_kb())
        return

    if q.data=="add_vendor" and uid==ADMIN_ID:
        context.user_data["add_vendor"]=True
        await q.message.reply_text("Podaj username vendora:")
        return

    if q.data=="vendors" and uid==ADMIN_ID:
        rows=[[InlineKeyboardButton(v.upper(),callback_data=f"v_{v}")] for v in VENDORS]
        await q.message.reply_text("VENDORZY:",reply_markup=InlineKeyboardMarkup(rows))
        return

    if q.data.startswith("v_") and uid==ADMIN_ID:
        v=q.data[2:]
        kb=[
            [InlineKeyboardButton("🗑 USUŃ",callback_data=f"del_{v}")],
            [InlineKeyboardButton("⬅ POWRÓT",callback_data="vendors")]
        ]
        await q.message.reply_text(f"{v.upper()}\nOFERTY: {vendor_stats.get(v,0)}",reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("del_") and uid==ADMIN_ID:
        VENDORS.discard(q.data[4:])
        await q.message.reply_text("USUNIĘTO")
        return

    if q.data=="add_bl" and uid==ADMIN_ID:
        context.user_data["bl"]=True
        await q.message.reply_text("Podaj słowo:")
        return

    # QUICK
    if q.data=="quick":
        rows=[
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(1,6)],
            [InlineKeyboardButton(str(i),callback_data=f"q{i}") for i in range(6,11)]
        ]
        await q.message.reply_text("ILE PRODUKTÓW?",reply_markup=InlineKeyboardMarkup(rows))
        return

    # NEW OFFER
    if q.data=="new":
        rows=[[InlineKeyboardButton(f"SZABLON {i}",callback_data=f"tpl_{i}")] for i in range(1,6)]
        await q.message.reply_text("WYBIERZ SZABLON:",reply_markup=InlineKeyboardMarkup(rows))
        return

    if q.data.startswith("tpl_"):
        style=int(q.data[-1])
        steps[uid]={"style":style,"items":[]}
        preview=render(["BUCH","KOKS"],"preview",style)
        await q.message.reply_text(preview,parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("DALEJ",callback_data="qty")]]))
        return

    if q.data=="qty":
        await q.message.reply_text("ILE PRODUKTÓW? (1-10)")
        return

    if q.data.startswith("q"):
        steps[uid]={"style":0,"qty":int(q.data[1:]),"items":[]}
        await q.message.reply_text("PODAJ PRODUKT 1")
        return

    if q.data=="send":
        ad=render(steps[uid]["items"],user,steps[uid]["style"])
        await context.bot.send_photo(GROUP_ID,LOGO_URL,caption=ad,parse_mode="HTML",message_thread_id=TOPIC_ID)
        vendor_stats[user]=vendor_stats.get(user,0)+1
        await q.message.reply_text("OPUBLIKOWANO\nZAPISAĆ JAKO SZABLON?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💾 ZAPISZ",callback_data="save")]]))
        return

    if q.data=="save":
        saved_templates.setdefault(user,[]).append(steps[uid]["items"])
        steps.pop(uid)
        await q.message.reply_text("ZAPISANO")
        return

    if q.data=="mytpl":
        rows=[[InlineKeyboardButton(f"SZABLON {i+1}",callback_data=f"use_{i}")]
              for i in range(len(saved_templates.get(user,[])))]
        await q.message.reply_text("TWOJE SZABLONY:",reply_markup=InlineKeyboardMarkup(rows))
        return

    if q.data.startswith("use_"):
        idx=int(q.data[4:])
        ad=render(saved_templates[user][idx],user,0)
        await context.bot.send_photo(GROUP_ID,LOGO_URL,caption=ad,parse_mode="HTML",message_thread_id=TOPIC_ID)
        return

# ================= COLLECT =================

async def collect(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    text=update.message.text

if context.user_data.get("add_bl") and uid == ADMIN_ID:
    blacklist.add(text.lower())
    context.user_data["add_bl"] = False
    await update.message.reply_text(
        f"✅ Dodano do blacklisty: {text.lower()}"
    )
    return
    
if context.user_data.get("add_vendor") and uid == ADMIN_ID:
    VENDORS.add(text.lower())
    context.user_data["add_vendor"] = False
    await update.message.reply_text("✅ Dodano vendora")
    return

    if context.user_data.get("bl") and uid==ADMIN_ID:
        blacklist.add(text.lower())
        context.user_data["bl"]=False
        await update.message.reply_text("DODANO DO BLACKLISTY")
        return

    if uid not in steps: return

    if any(w in text.lower() for w in blacklist):
        await update.message.reply_text("❌ ZABLOKOWANE SŁOWO")
        return

    if "qty" not in steps[uid]:
        steps[uid]["qty"]=int(text)
        await update.message.reply_text("PODAJ PRODUKT 1")
        return

    steps[uid]["items"].append(text)

    if len(steps[uid]["items"])<steps[uid]["qty"]:
        await update.message.reply_text(f"PODAJ PRODUKT {len(steps[uid]['items'])+1}")
    else:
        ad=render(steps[uid]["items"],update.effective_user.username,steps[uid]["style"])
        await update.message.reply_text(ad,parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send")]]))

# ================= MAIN =================

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND,start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,collect))
    print("🔥 MARKETPLACE PREMIUM ULTRA v7777.7777 ONLINE")
    app.run_polling()

if __name__=="__main__":
    main()







