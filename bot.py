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

# ==============================
# ENV VARIABLES
# ==============================
TOKEN = os.getenv("KEY")
GROUP_ID = int(os.getenv("GROUP_ID"))
WTB_TOPIC = int(os.getenv("WTB"))
WTS_TOPIC = int(os.getenv("WTS"))
WTT_TOPIC = int(os.getenv("WTT"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

vendors = set()

# ==============================
# CHAR MAP
# ==============================
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

# ==============================
# TEMPLATES
# ==============================
def template_wtb_wtt(username, content, typ):
    icon = "🔎" if typ == "WTB" else "🔁"
    return (
        "╔══════════════════════╗\n"
        f"        {icon} {typ} MARKET\n"
        "╚══════════════════════╝\n\n"
        f"👤 USER: {username}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{content}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

def template_wts(username, products):
    msg = (
        "╔══════════════════════╗\n"
        "        🏪 WTS STORE\n"
        "╚══════════════════════╝\n\n"
        f"👤 VENDOR: {username}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🛒 PRODUCTS:\n\n"
    )
    for i, p in enumerate(products, 1):
        msg += f"{i}️⃣ {p}\n"
    msg += "\n━━━━━━━━━━━━━━━━━━━━━━"
    return msg

# ==============================
# START
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    user_id = update.effective_user.id

    keyboard = [
        [
            InlineKeyboardButton("WTB", callback_data="WTB"),
            InlineKeyboardButton("WTS", callback_data="WTS"),
            InlineKeyboardButton("WTT", callback_data="WTT"),
        ]
    ]

    if user_id == ADMIN_ID:
        keyboard.append(
            [InlineKeyboardButton("⚙ Panel Admina", callback_data="ADMIN_PANEL")]
        )

    await update.message.reply_text(
        "Wybierz typ ogłoszenia:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ==============================
# BUTTONS
# ==============================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.message.chat.id != GROUP_ID:
        return

    user = query.from_user
    user_id = user.id
    username = user.username

    if query.data == "ADMIN_PANEL" and user_id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("➕ Dodaj Vendora", callback_data="ADD")],
            [InlineKeyboardButton("➖ Usuń Vendora", callback_data="REMOVE")],
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
        if user_id != ADMIN_ID and username not in vendors:
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
        await query.edit_message_text("Podaj nazwę produktu 1:")
        return

    if query.data in ["WTB", "WTT"]:
        context.user_data["selected_type"] = query.data
        context.user_data["selected_topic"] = (
            WTB_TOPIC if query.data == "WTB" else WTT_TOPIC
        )
        await query.edit_message_text("Napisz treść ogłoszenia:")
        return

# ==============================
# MESSAGE HANDLER
# ==============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    user = update.effective_user
    text = update.message.text

    # ADMIN ACTION
    if user.id == ADMIN_ID and "admin_action" in context.user_data:
        username = text.replace("@", "")
        if context.user_data["admin_action"] == "ADD":
            vendors.add(username)
            await update.message.reply_text("✅ Dodano vendora")
        else:
            vendors.discard(username)
            await update.message.reply_text("❌ Usunięto vendora")

        context.user_data.clear()
        return

    # WTS FLOW
    if "wts_count" in context.user_data:
        if contains_price(text):
            await update.message.reply_text("❌ Zakaz cen.")
            return

        context.user_data["wts_products"].append(text)

        if len(context.user_data["wts_products"]) < context.user_data["wts_count"]:
            next_num = len(context.user_data["wts_products"]) + 1
            await update.message.reply_text(f"Produkt {next_num}:")
            return

        username_display = f"@{user.username}" if user.username else user.first_name
        mapped_products = [map_text(p) for p in context.user_data["wts_products"]]
        final = template_wts(username_display, mapped_products)

        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            text=final,
        )

        await update.message.reply_text("✅ WTS dodane")
        context.user_data.clear()
        return

    # WTB / WTT
    if "selected_topic" in context.user_data:
        username_display = f"@{user.username}" if user.username else user.first_name
        mapped = map_text(text)

        final = template_wtb_wtt(
            username_display,
            mapped,
            context.user_data["selected_type"],
        )

        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=context.user_data["selected_topic"],
            text=final,
        )

        await update.message.reply_text("✅ Dodano ogłoszenie")
        context.user_data.clear()
        return

# ==============================
# MAIN
# ==============================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🔥 BOT działa w jednej grupie (3 tematy)")
    app.run_polling()

if __name__ == "__main__":
    main()
