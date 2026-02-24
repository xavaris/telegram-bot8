import os
import re
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("KEY")
GROUP_ID = int(os.getenv("GROUP_ID"))
WTB_TOPIC = int(os.getenv("WTB"))
WTS_TOPIC = int(os.getenv("WTS"))
WTT_TOPIC = int(os.getenv("WTT"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

vendors = set()

CHAR_MAP = {
    "a":"@","b":"ß","c":"¢","d":"Ð","e":"3","f":"₣","g":"6",
    "h":"Ħ","i":"1","j":"ʝ","k":"Ҡ","l":"Ł","m":"₥","n":"И",
    "o":"Ø","p":"₱","q":"Ǫ","r":"Я","s":"$","t":"7",
    "u":"Ц","v":"√","w":"₩","x":"Ж","y":"¥","z":"Ƶ"
}

def map_text(text: str) -> str:
    result = ""
    for char in text:
        lower = char.lower()
        if lower in CHAR_MAP:
            mapped = CHAR_MAP[lower]
            if char.isupper():
                mapped = mapped.upper()
            result += mapped
        else:
            result += char
    return result

def contains_price(text: str) -> bool:
    return bool(re.search(r"\d+|zł|\$|€|pln|usd", text.lower()))

def template_basic(username, content, typ):
    icon = "🔎" if typ == "WTB" else "🔁"
    return (
        f"╔══════════════════╗\n"
        f"   {icon} {typ} MARKET\n"
        f"╚══════════════════╝\n\n"
        f"👤 {username}\n\n"
        f"{content}"
    )

def template_wts(username, products):
    msg = (
        "╔══════════════════╗\n"
        "   🏪 WTS STORE\n"
        "╚══════════════════╝\n\n"
        f"👤 {username}\n\n"
    )
    for i, p in enumerate(products, 1):
        msg += f"{i}️⃣ {p}\n"
    return msg

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    keyboard = [
        [
            InlineKeyboardButton("WTB", callback_data="WTB"),
            InlineKeyboardButton("WTS", callback_data="WTS"),
            InlineKeyboardButton("WTT", callback_data="WTT"),
        ]
    ]

    if update.effective_user.id == ADMIN_ID:
        keyboard.append(
            [InlineKeyboardButton("⚙ Panel Admina", callback_data="ADMIN")]
        )

    await update.message.reply_text(
        "Wybierz temat:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.message.chat.id != GROUP_ID:
        return

    user = query.from_user

    if query.data == "ADMIN" and user.id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("➕ Dodaj", callback_data="ADD")],
            [InlineKeyboardButton("➖ Usuń", callback_data="REMOVE")],
        ]
        await query.edit_message_text(
            "Panel Admina:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data in ["ADD", "REMOVE"]:
        context.user_data["admin_action"] = query.data
        await query.edit_message_text("Podaj @username:")
        return

    if query.data == "WTS":
        if user.id != ADMIN_ID and user.username not in vendors:
            await query.edit_message_text("❌ Tylko vendor.")
            return

        keyboard = []
        row = []
        for i in range(1, 11):
            row.append(InlineKeyboardButton(str(i), callback_data=f"WTS_{i}"))
            if i % 5 == 0:
                keyboard.append(row)
                row = []

        await query.edit_message_text(
            "Ile produktów?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data.startswith("WTS_"):
        count = int(query.data.split("_")[1])
        context.user_data["wts_count"] = count
        context.user_data["wts_products"] = []
        await query.edit_message_text("Produkt 1:")
        return

    if query.data in ["WTB", "WTT"]:
        context.user_data["type"] = query.data
        context.user_data["topic"] = (
            WTB_TOPIC if query.data == "WTB" else WTT_TOPIC
        )
        await query.edit_message_text("Napisz treść:")
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    user = update.effective_user
    text = update.message.text

    if user.id == ADMIN_ID and "admin_action" in context.user_data:
        username = text.replace("@", "")
        if context.user_data["admin_action"] == "ADD":
            vendors.add(username)
            await update.message.reply_text("✅ Dodano")
        else:
            vendors.discard(username)
            await update.message.reply_text("❌ Usunięto")
        context.user_data.clear()
        return

    if "wts_count" in context.user_data:
        if contains_price(text):
            await update.message.reply_text("❌ Zakaz cen")
            return

        context.user_data["wts_products"].append(text)

        if len(context.user_data["wts_products"]) < context.user_data["wts_count"]:
            await update.message.reply_text(
                f"Produkt {len(context.user_data['wts_products'])+1}:"
            )
            return

        username_display = f"@{user.username}" if user.username else user.first_name
        mapped_products = [map_text(p) for p in context.user_data["wts_products"]]

        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            text=template_wts(username_display, mapped_products),
        )

        context.user_data.clear()
        return

    if "topic" in context.user_data:
        username_display = f"@{user.username}" if user.username else user.first_name
        mapped = map_text(text)

        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=context.user_data["topic"],
            text=template_basic(
                username_display,
                mapped,
                context.user_data["type"],
            ),
        )

        context.user_data.clear()
        return

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🔥 Railway Bot Running (Single Instance Mode)")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
