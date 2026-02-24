import os
import re
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

def template(username, content, typ):
    icon = "🔎" if typ == "WTB" else "🔁" if typ == "WTT" else "🏪"
    return (
        f"╔══════════════════╗\n"
        f"   {icon} {typ} MARKET\n"
        f"╚══════════════════╝\n\n"
        f"👤 {username}\n\n"
        f"{content}"
    )

# ======================
# START (TYLKO PRYWATNIE)
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    keyboard = [[
        InlineKeyboardButton("WTB", callback_data="WTB"),
        InlineKeyboardButton("WTS", callback_data="WTS"),
        InlineKeyboardButton("WTT", callback_data="WTT"),
    ]]

    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙ Panel", callback_data="ADMIN")])

    await update.message.reply_text(
        "Wybierz typ ogłoszenia:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ======================
# BUTTON HANDLER
# ======================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    if query.message.chat.type != "private":
        return

    if query.data in ["WTB", "WTT"]:
        context.user_data["type"] = query.data
        context.user_data["topic"] = (
            WTB_TOPIC if query.data == "WTB" else WTT_TOPIC
        )
        await query.edit_message_text("Napisz treść ogłoszenia:")
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
        context.user_data["products"] = []
        await query.edit_message_text("Podaj nazwę produktu 1:")
        return

# ======================
# MESSAGE HANDLER (PRYWATNIE)
# ======================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    text = update.message.text

    # WTS FLOW
    if "wts_count" in context.user_data:
        if contains_price(text):
            await update.message.reply_text("❌ Zakaz cen.")
            return

        context.user_data["products"].append(text)

        if len(context.user_data["products"]) < context.user_data["wts_count"]:
            await update.message.reply_text(
                f"Produkt {len(context.user_data['products'])+1}:"
            )
            return

        username_display = f"@{user.username}" if user.username else user.first_name
        mapped_products = [map_text(p) for p in context.user_data["products"]]

        final = template(
            username_display,
            "\n".join([f"{i+1}. {p}" for i, p in enumerate(mapped_products)]),
            "WTS"
        )

        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            text=final,
        )

        await update.message.reply_text("✅ Opublikowano w grupie.")
        context.user_data.clear()
        return

    # WTB / WTT
    if "topic" in context.user_data:
        username_display = f"@{user.username}" if user.username else user.first_name
        mapped = map_text(text)

        final = template(
            username_display,
            mapped,
            context.user_data["type"]
        )

        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=context.user_data["topic"],
            text=final,
        )

        await update.message.reply_text("✅ Opublikowano w grupie.")
        context.user_data.clear()
        return

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🔥 DM → GROUP BOT działa")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
