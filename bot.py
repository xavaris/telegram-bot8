# MARKETPLACE PREMIUM BOT
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

# ================= STYLE =================

CHAR_MAP = {"a":"@","e":"3","i":"1","o":"0","s":"$","t":"7"}

def encode(t):
    return "".join(CHAR_MAP.get(c.lower(),c.upper()) for c in t)

def now():
    return datetime.now(TZ).strftime("%H:%M")

# ================= RENDER =================

def render_offer(products,user,style):
    global offer_id
    offer_id+=1
    items="\n".join([f"• {encode(p)}" for p in products])

    templates = {
0:f"""<b>████████████████████</b>
<b>🔥 QUICK MARKET 🔥</b>
<b>████████████████████</b>

🆔 #{offer_id} | 🕒 {now()}

{items}

<b>@{user}</b>""",

1:f"""<b>╔══════════════╗</b>
<b>⚡ MARKET ⚡</b>
<b>╚══════════════╝</b>

{items}

<b>@{user}</b>""",

2:f"""<b>━━━━━━━━━━━━━━</b>
<b>💎 PREMIUM 💎</b>
<b>━━━━━━━━━━━━━━</b>

{items}

<b>@{user}</b>""",

3:f"""<b>████ OSTATNIA ████</b>

{items}

<b>@{user}</b>""",

4:f"""<b>🛍 MARKETPLACE</b>

{items}

<b>@{user}</b>""",

5:f"""<b>╭━━━━━━━━━━━━╮</b>
<b>🔥 ULTRA 🔥</b>
<b>╰━━━━━━━━━━━━╯</b>

{items}

<b>@{user}</b>"""
    }

    return templates[style]

# ================= START =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    kb=[
        [InlineKeyboardButton("➕ NOWA OFERTA",callback_data="new")],
        [InlineKeyboardButton("⚡ SZYBKA OFERTA",callback_data="quick")],
        [InlineKeyboardButton("📂 MOJE SZABLONY",callback_data="templates")]
    ]
    if update.effective_user.id==ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠 PANEL ADMINA",callback_data="admin")])

    await update.message.reply_text("🔥 MARKETPLACE PREMIUM 🔥",
        reply_markup=InlineKeyboardMarkup(kb))

# ================= ADMIN =================

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 VENDORZY",callback_data="vendors")],
        [InlineKeyboardButton("⛔ DODAJ BLACKLIST",callback_data="add_bl")],
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

    if q.data=="vendors" and uid==ADMIN_ID:
        rows=[[InlineKeyboardButton(v.upper(),callback_data=f"v_{v}")] for v in VENDORS]
        await q.message.reply_text("VENDORZY:",reply_markup=InlineKeyboardMarkup(rows))
        return

    if q.data=="add_bl" and uid==ADMIN_ID:
        context.user_data["bl"]=True
        await q.message.reply_text("Podaj słowo:")
        return

    if q.data=="clean" and uid==ADMIN_ID:
        for m in list(last_ad.values()):
            try: await context.bot.delete_message(GROUP_ID,m)
            except: pass
        last_ad.clear()
        await q.message.reply_text("TEMAT WYCZYSZCZONY")
        return

    if q.data=="reset" and uid==ADMIN_ID:
        daily.clear()
        await q.message.reply_text("LIMITY ZRESETOWANE")
        return

    # QUICK OFFER
    if q.data=="quick":
        steps[uid]={"style":0,"items":[]}
        await q.message.reply_text("ILE PRODUKTÓW? (1-10)")
        return

    # NEW OFFER
    if q.data=="new":
        kb=[[InlineKeyboardButton(f"SZABLON {i}",callback_data=f"tpl_{i}")] for i in range(1,6)]
        await q.message.reply_text("WYBIERZ SZABLON:",
            reply_markup=InlineKeyboardMarkup(kb))
        return

    if q.data.startswith("tpl_"):
        style=int(q.data[-1])
        steps[uid]={"style":style,"items":[]}
        await q.message.reply_text(
            render_offer(["PRODUKT A","PRODUKT B"],"preview",style),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("DALEJ",callback_data="qty")]])
        )
        return

    if q.data=="qty":
        await q.message.reply_text("ILE PRODUKTÓW? (1-10)")
        return

    # SEND
    if q.data=="send":
        ad=render_offer(steps[uid]["items"],user,steps[uid]["style"])
        msg=await context.bot.send_photo(GROUP_ID,LOGO_URL,
            caption=ad,parse_mode="HTML",
            message_thread_id=TOPIC_ID)

        last_ad[uid]=msg.message_id
        vendor_stats[user]=vendor_stats.get(user,0)+1

        await q.message.reply_text(
            "OPUBLIKOWANO\nZapisać jako szablon?",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("💾 ZAPISZ",callback_data="save")]]
            )
        )
        return

    if q.data=="save":
        saved_templates.setdefault(user,[]).append(steps[uid]["items"])
        steps.pop(uid)
        await q.message.reply_text("ZAPISANO")
        return

    if q.data=="templates":
        rows=[[InlineKeyboardButton(f"SZABLON {i+1}",callback_data=f"use_{i}")]
              for i in range(len(saved_templates.get(user,[])))]
        await q.message.reply_text("TWOJE SZABLONY:",
            reply_markup=InlineKeyboardMarkup(rows))
        return

    if q.data.startswith("use_"):
        idx=int(q.data[4:])
        ad=render_offer(saved_templates[user][idx],user,0)
        await context.bot.send_photo(GROUP_ID,LOGO_URL,
            caption=ad,parse_mode="HTML",
            message_thread_id=TOPIC_ID)
        return

# ================= COLLECT =================

async def collect(update:Update,context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    text=update.message.text

    if context.user_data.get("bl") and uid==ADMIN_ID:
        blacklist.add(text.lower())
        context.user_data["bl"]=False
        await update.message.reply_text("DODANO DO BLACKLISTY")
        return

    if uid not in steps: return

    if "qty" not in steps[uid]:
        steps[uid]["qty"]=int(text)
        await update.message.reply_text("PODAJ PRODUKT 1")
        return

    if any(w in text.lower() for w in blacklist):
        await update.message.reply_text("❌ ZABLOKOWANE SŁOWO")
        return

    steps[uid]["items"].append(text)

    if len(steps[uid]["items"])<steps[uid]["qty"]:
        await update.message.reply_text(
            f"PODAJ PRODUKT {len(steps[uid]['items'])+1}")
    else:
        ad=render_offer(steps[uid]["items"],
                        update.effective_user.username,
                        steps[uid]["style"])
        await update.message.reply_text(ad,parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ PUBLIKUJ",callback_data="send")]]
            ))

# ================= MAIN =================

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND,start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,collect))
    print("🔥 MARKETPLACE PREMIUM ONLINE")
    app.run_polling()

if __name__=="__main__":
    main()
