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

# ======================
# ENV
# ======================
TOKEN = os.getenv("KEY")
GROUP_ID = int(os.getenv("GROUP_ID"))
WTB_TOPIC = int(os.getenv("WTB"))
WTS_TOPIC = int(os.getenv("WTS"))
WTT_TOPIC = int(os.getenv("WTT"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOGO_URL = os.getenv("LOGO_URL")

env_vendors = os.getenv("VENDORS", "")
vendors = set(v.strip().lower() for v in env_vendors.split(",") if v.strip())

# ======================
# MAPA SŁÓW (KONKRETNA)
# ======================
BANNED_MAP = {
    "mewa": "M3W@",
    "buch": "BЦCH",
    "xanax": "XΛNΛX",
    "tussy": "TЦ$$Y",
    "weed": "W33D",
    "clony": "CL0NY",
    "koks": "KØK$",
}

def smart_mask_caps(text: str) -> str:
    words = text.split()
    result = []

    for word in words:
        clean = re.sub(r'[^a-zA-Z]', '', word).lower()

        if clean in BANNED_MAP:
            result.append(BANNED_MAP[clean])
        else:
            result.append(word.upper())

    return " ".join(result)

def contains_price(text: str) -> bool:
    return bool(re.search(r"\d+|zł|pln|usd|€|\$", text.lower()))

# ======================
# TEMPLATE PREMIUM
# ======================
def premium_template(title: str, username: str, content: str, is_vendor: bool) -> str:

    badge = "👑 VERIFIED VENDOR\n" if is_vendor else ""

    return (
        "═══════════════════════════\n"
        f"   ☠  {title}  BLACK MARKET  ☠\n"
        "═══════════════════════════\n\n"
        f"{badge}"
        f"👤  {username}\n"
        "───────────────────────────\n\n"
        f"{content}\n\n"
        "───────────────────────────\n"
        "⚡ OFFICIAL MARKET SYSTEM\n"
        "═══════════════════════════"
    )

# ======================
# START (DM ONLY)
# ======================
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
        "WYBIERZ TYP OGŁOSZENIA:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ======================
# ADMIN PANEL
# ======================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ DODAJ VENDORA", callback_data="ADD_VENDOR")],
        [InlineKeyboardButton("➖ USUŃ VENDORA", callback_data="REMOVE_VENDOR")],
        [InlineKeyboardButton("📋 LISTA VENDORÓW", callback_data="LIST_VENDORS")],
    ]

    await update.effective_message.reply_text(
        "PANEL ADMINA:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ======================
# BUTTON HANDLER
# ======================
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
        await query.edit_message_text(f"VENDORZY:\n\n{vendor_list}")
        return

    if query.data in ["ADD_VENDOR", "REMOVE_VENDOR"]:
        context.user_data["admin_action"] = query.data
        await query.edit_message_text("PODAJ @USERNAME:")
        return

    if query.data in ["WTB", "WTT"]:
        context.user_data["type"] = query.data
        context.user_data["topic"] = WTB_TOPIC if query.data == "WTB" else WTT_TOPIC
        await query.edit_message_text("NAPISZ TREŚĆ OGŁOSZENIA:")
        return

    if query.data == "WTS":
        if user.username is None or (
            user.username.lower() not in vendors and user.id != ADMIN_ID
        ):
            await query.edit_message_text("TYLKO VENDOR MOŻE PUBLIKOWAĆ WTS.")
            return

        keyboard = []
        row = []
        for i in range(1, 11):
            row.append(InlineKeyboardButton(str(i), callback_data=f"WTS_COUNT_{i}"))
            if i % 5 == 0:
                keyboard.append(row)
                row = []

        await query.edit_message_text(
            "ILE PRODUKTÓW CHCESZ DODAĆ?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data.startswith("WTS_COUNT_"):
        count = int(query.data.split("_")[-1])
        context.user_data["wts_total"] = count
        context.user_data["wts_products"] = []
        context.user_data["wts_current"] = 1

        await query.edit_message_text("PODAJ NAZWĘ PRODUKTU 1 (BEZ CEN):")
        return

# ======================
# MESSAGE HANDLER
# ======================
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
            await update.message.reply_text("DODANO VENDORA.")
        else:
            vendors.discard(username)
            await update.message.reply_text("USUNIĘTO VENDORA.")

        context.user_data.clear()
        return

    # WTS FLOW
    if "wts_total" in context.user_data:
        if contains_price(text):
            await update.message.reply_text("ZAKAZ PODAWANIA CEN.")
            return

        context.user_data["wts_products"].append(text)

        if len(context.user_data["wts_products"]) < context.user_data["wts_total"]:
            next_num = len(context.user_data["wts_products"]) + 1
            await update.message.reply_text(
                f"PODAJ NAZWĘ PRODUKTU {next_num} (BEZ CEN):"
            )
            return

        username_display = (
            f"@{user.username}" if user.username else user.first_name
        ).upper()

        is_vendor = (
            user.username and user.username.lower() in vendors
        )

        products_text = "\n".join(
            f"✦  {smart_mask_caps(p)}"
            for p in context.user_data["wts_products"]
        )

        await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=WTS_TOPIC,
            photo=LOGO_URL,
            caption=premium_template(
                "WTS",
                username_display,
                products_text,
                is_vendor
            ),
        )

        await update.message.reply_text("OPUBLIKOWANO.")
        context.user_data.clear()
        return

    # WTB / WTT
    if "topic" in context.user_data:
        username_display = (
            f"@{user.username}" if user.username else user.first_name
        ).upper()

        is_vendor = (
            user.username and user.username.lower() in vendors
        )

        final_text = smart_mask_caps(text)

        await context.bot.send_photo(
            chat_id=GROUP_ID,
            message_thread_id=context.user_data["topic"],
            photo=LOGO_URL,
            caption=premium_template(
                context.user_data["type"],
                username_display,
                final_text,
                is_vendor
            ),
        )

        await update.message.reply_text("OPUBLIKOWANO.")
        context.user_data.clear()
        return

# ======================
# MAIN
# ======================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("FINAL PRO MARKET BOT RUNNING")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
