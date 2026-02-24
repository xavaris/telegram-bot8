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
# ENV
# ==============================
TOKEN = os.getenv("KEY")
GROUP_ID = int(os.getenv("GROUP_ID"))
WTB_TOPIC = int(os.getenv("WTB"))
WTS_TOPIC = int(os.getenv("WTS"))
WTT_TOPIC = int(os.getenv("WTT"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOGO_URL = os.getenv("LOGO_URL")

env_vendors = os.getenv("VENDORS", "")
vendors = set(v.strip().lower() for v in env_vendors.split(",") if v.strip())

# ==============================
# BLACKLIST
# ==============================
BANNED_WORDS = [
    "mewa",
    "buch",
    "xanax",
    "tussy",
    "weed",
    "koks",
    "cocaine",
    "heroina",
    "lsd",
]

def obfuscate_word(word: str) -> str:
    replace_map = {
        "a": "@",
        "e": "3",
        "i": "1",
        "o": "0",
        "u": "υ",
        "s": "$",
    }
    result = ""
    for char in word:
        result += replace_map.get(char.lower(), char)
    return result

def smart_mask_caps(text: str) -> str:
    def normalize(word):
        return re.sub(r'[^a-zA-Z]', '', word.lower())

    words = text.split()
    final_words = []

    for word in words:
        normalized = normalize(word)

        if any(bad in normalized for bad in BANNED_WORDS):
            masked = obfuscate_word(word)
            final_words.append(masked.upper())
        else:
            final_words.append(word.upper())

    return " ".join(final_words)

def contains_price(text: str) -> bool:
    return bool(re.search(r"\d+|zł|pln|usd|€|\$", text.lower()))

# ==============================
# PREMIUM TEMPLATE
# ==============================
def premium_template(title: str, username: str, content: str) -> str:
    return (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 {title} MARKET\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {username}\n\n"
        f"{content}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ OFFICIAL MARKETPLACE SYSTEM"
    )

# ==============================
# START (PRIVATE ONLY)
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    keyboard = [[
        InlineKeyboardButton("🔎 WTB", callback_data="WTB"),
        InlineKeyboardButton("🏪 WTS", callback_data="WTS"),
        InlineKeyboardButton("🔁 WTT", callback_data="WTT"),
    ]]

    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙ ADMIN PANEL", callback_data="ADMIN")])

    await update.message.reply_text(
        "💎 WYBIERZ TYP OGŁOSZENIA:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ==============================
# ADMIN PANEL
# ==============================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ DODAJ VENDORA", callback_data="ADD_VENDOR")],
        [InlineKeyboardButton("➖ USUŃ VENDORA", callback_data="REMOVE_VENDOR")],
        [InlineKeyboardButton("📋 LISTA VENDORÓW", callback_data="LIST_VENDORS")],
    ]

    await update.effective_message.reply_text(
        "⚙ PANEL ADMINA:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ==============================
# BUTTON HANDLER
# ==============================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.message.chat.type != "private":
        return

    user = query.from_user

    if query.data == "ADMIN" and user.id == ADMIN_ID:
        await admin_panel(update, context)
        return

    if query.data == "LIST_VENDORS":
        vendor_list = "\n".join(f"• @{v}" for v in vendors) or "BRAK"
        await query.edit_message_text(f"📋 VENDORZY:\n\n{vendor_list}")
        return

    if query.data in ["ADD_VENDOR", "REMOVE_VENDOR"]:
        context.user_data["admin_action"] = query.data
        await query.edit_message_text("PODAJ @USERNAME:")
        return

    if query.data in ["WTB", "WTT"]:
        context.user_data["type"] = query.data
        context.user_data["topic"] = (
            WTB_TOPIC if query.data == "WTB" else WTT_TOPIC
        )
        await query.edit_message_text("✍ NAPISZ TREŚĆ OGŁOSZENIA:")
        return

    if query.data == "WTS":
        if user.username is None or user.username.lower() not in vendors and user.id != ADMIN_ID:
            await query.edit_message_text("❌ TYLKO VENDOR MOŻE PUBLIKOWAĆ WTS.")
            return

        context.user_data["type"] = "WTS"
        context.user_data["topic"] = WTS_TOPIC
        context.user_data["products"] = []

        await query.edit_message_text(
            "🛒 PODAWAJ NAZWY PRODUKTÓW.\nKAŻDY W OSOBNEJ WIADOMOŚCI.\nNAPISZ /DONE GDY SKOŃCZYSZ."
        )
        return

# ==============================
# MESSAGE HANDLER
# ==============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    text = update.message.text

    # ADMIN ACTION
    if user.id == ADMIN_ID and "admin_action" in context.user_data:
        username = text.replace("@", "").strip().lower()

        if context.user_data["admin_action"] == "ADD_VENDOR":
            vendors.add(username)
            await update.message.reply_text("✅ DODANO VENDORA.")
        else:
            vendors.discard(username)
            await update.message.reply_text("❌ USUNIĘTO VENDORA.")

        context.user_data.clear()
        return

    # WTS FLOW
    if context.user_data.get("type") == "WTS":
        if text.upper() == "/DONE":
            username_display = (
                f"@{user.username}" if user.username else user.first_name
            )

            products_text = "\n".join(
                f"{i+1}. {smart_mask_caps(p)}"
                for i, p in enumerate(context.user_data["products"])
            )

            await context.bot.send_photo(
                chat_id=GROUP_ID,
                message_thread_id=WTS_TOPIC,
                photo=LOGO_URL,
                caption=premium_template("WTS", username_display.upper(), products_text),
            )

            await update.message.reply_text("✅ OPUBLIKOWANO.")
            context.user_data.clear()
            return

        if contains_price(text):
            await update.message.reply_text("❌ ZAKAZ PODAWANIA CEN.")
            return

        context.user_data["products"].append(text)
        await update.message.reply_text("✔ DODANO. KOLEJNY LUB /DONE.")
        return

    # WTB / WTT
    if "topic" in context.user_data:
        username_display = (
            f"@{user.username}" if user.username else user.first_name
        )

        final_text = smart_mask_caps(text)

        await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=context.user_data["topic"],
            photo=LOGO_URL,
            caption=premium_template(
                context.user_data["type"],
                username_display.upper(),
                final_text,
            ),
        )

        await update.message.reply_text("✅ OPUBLIKOWANO.")
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

    print("💎 FINAL PRO 999.999 MARKET BOT DZIAŁA")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
