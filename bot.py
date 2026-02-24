import os
import re
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==============================
# RAILWAY VARIABLES
# ==============================
TOKEN = os.getenv("KEY")
WTB_TOPIC = int(os.getenv("WTB"))
WTS_TOPIC = int(os.getenv("WTS"))
WTT_TOPIC = int(os.getenv("WTT"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

vendors = set()

# ==============================
# CHAR MAP (FULL ENCODE)
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
# PREMIUM TEMPLATES
# ==============================
def template_wtb_wtt(username, content, typ):
    icon = "🔎" if typ == "WTB" else "🔁"

    return (
        "╔══════════════════════╗\n"
        f"        {icon}  {typ} MARKET\n"
        "╚══════════════════════╝\n\n"
        f"👤 USER: {username}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{content}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Powered by MARKET BOT"
    )


def template_wts(username, products):
    message = (
        "╔══════════════════════╗\n"
        "        🏪  WTS STORE\n"
        "╚══════════════════════╝\n\n"
        f"👤 VENDOR: {username}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🛒 AVAILABLE PRODUCTS:\n\n"
    )

    for i, product in enumerate(products, 1):
        message += f"{i}️⃣  {product}\n"

    message += (
        "\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Trusted Market System"
    )

    return message


# ==============================
# START
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
# BUTTON HANDLER
# ==============================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id
    username = user.username

    # ADMIN PANEL
    if query.data == "ADMIN_PANEL" and user_id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("➕ Dodaj Vendora", callback_data="ADD_VENDOR")],
            [InlineKeyboardButton("➖ Usuń Vendora", callback_data="REMOVE_VENDOR")],
        ]
        await query.edit_message_text(
            "Panel Admina:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data == "ADD_VENDOR":
        context.user_data["admin_action"] = "add"
        await query.edit_message_text("Podaj @username do dodania:")
        return

    if query.data == "REMOVE_VENDOR":
        context.user_data["admin_action"] = "remove"
        await query.edit_message_text("Podaj @username do usunięcia:")
        return

    # WTS FLOW
    if query.data == "WTS":
        if user_id != ADMIN_ID and username not in vendors:
            await query.edit_message_text("❌ Temat tylko dla vendorów.")
            return

        keyboard = []
        row = []
        for i in range(1, 11):
            row.append(InlineKeyboardButton(str(i), callback_data=f"WTS_COUNT_{i}"))
            if i % 5 == 0:
                keyboard.append(row)
                row = []

        await query.edit_message_text(
            "Ile masz produktów?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data.startswith("WTS_COUNT_"):
        count = int(query.data.split("_")[-1])
        context.user_data["wts_count"] = count
        context.user_data["wts_products"] = []
        context.user_data["current_product"] = 1

        await query.edit_message_text("Podaj nazwę produktu 1 (bez cen):")
        return

    # WTB / WTT
    if query.data in ["WTB", "WTT"]:
        topic_map = {
            "WTB": WTB_TOPIC,
            "WTT": WTT_TOPIC,
        }

        context.user_data["selected_topic"] = topic_map[query.data]
        context.user_data["selected_type"] = query.data

        await query.edit_message_text("Napisz treść ogłoszenia:")
        return


# ==============================
# MESSAGE HANDLER
# ==============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    # ADMIN ACTION
    if user.id == ADMIN_ID and "admin_action" in context.user_data:
        username = text.replace("@", "")
        if context.user_data["admin_action"] == "add":
            vendors.add(username)
            await update.message.reply_text(f"✅ Dodano vendora @{username}")
        else:
            vendors.discard(username)
            await update.message.reply_text(f"❌ Usunięto vendora @{username}")

        del context.user_data["admin_action"]
        return

    # WTS FLOW
    if "wts_count" in context.user_data:
        if contains_price(text):
            await update.message.reply_text("❌ Zakaz podawania cen.")
            return

        context.user_data["wts_products"].append(text)

        if len(context.user_data["wts_products"]) < context.user_data["wts_count"]:
            next_num = len(context.user_data["wts_products"]) + 1
            await update.message.reply_text(f"Podaj nazwę produktu {next_num}:")
            return

        username_display = f"@{user.username}" if user.username else user.first_name
        mapped_products = [map_text(p) for p in context.user_data["wts_products"]]

        final = template_wts(username_display, mapped_products)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=final,
            message_thread_id=WTS_TOPIC,
        )

        await update.message.reply_text("✅ Ogłoszenie WTS dodane")

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
            chat_id=update.effective_chat.id,
            text=final,
            message_thread_id=context.user_data["selected_topic"],
        )

        await update.message.reply_text("✅ Ogłoszenie dodane")
        context.user_data.clear()
        return

    await update.message.reply_text("Użyj /start aby dodać ogłoszenie.")


# ==============================
# MAIN
# ==============================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🔥 MARKET BOT 9999.9999 działa...")
    app.run_polling()


if __name__ == "__main__":
    main()
