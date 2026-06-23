"""
Aternos Telegram Bot
====================
Установка (Python 3.11):
    py -3.11 -m pip install python-telegram-bot python-aternos

Запуск:
    py -3.11 aternos_bot.py
"""
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram import ReplyKeyboardMarkup, KeyboardButton

# ============================================================
#  НАСТРОЙКИ
# ============================================================

BOT_TOKEN      = "8630079060:AAFc4_F_a4YPD_ZR9IYjCAlizsoLMHWFCj0"
ATERNOS_LOGIN  = "Winten1"
ATERNOS_PASSWORD = "102030405060708090"

ALLOWED_IDS = {
    1591310608,
    1097971699,
    1380295628,
    619502775,
    1134125196,
}

COOLDOWN_MINUTES = 2

# ============================================================

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

last_action: dict[int, datetime] = {}
server_busy = False


def is_allowed(uid: int) -> bool:
    return uid in ALLOWED_IDS


def cooldown_left(uid: int) -> int:
    if uid not in last_action:
        return 0
    delta = datetime.now() - last_action[uid]
    remaining = timedelta(minutes=COOLDOWN_MINUTES) - delta
    return max(0, int(remaining.total_seconds()))

def reply_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🟢 Запустить"), KeyboardButton("🔴 Остановить")],
        [KeyboardButton("❓ Помощь")],
    ], resize_keyboard=True)


# ──────────────────────────────────────────────
#  Aternos
# ──────────────────────────────────────────────

def _get_server():
    from python_aternos import Client
    atclient = Client.from_credentials(ATERNOS_LOGIN, ATERNOS_PASSWORD)
    servers = atclient.list_servers()
    if not servers:
        raise Exception("Серверы не найдены на аккаунте.")
    return servers[0]

async def aternos_start() -> str:
    try:
        srv = _get_server()
        srv.start()
        return "✅ Сервер запускается — обычно 1–3 минуты."
    except Exception as e:
        log.error(f"Ошибка запуска: {e}")
        return f"⚠️ Не удалось запустить.\nОшибка: {e}"


async def aternos_stop() -> str:
    try:
        srv = _get_server()
        srv.stop()
        return "🔴 Сервер остановлен."
    except Exception as e:
        log.error(f"Ошибка остановки: {e}")
        return f"⚠️ Не удалось остановить.\nОшибка: {e}"


# ──────────────────────────────────────────────
#  Клавиатура
# ──────────────────────────────────────────────

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Запустить сервер",  callback_data="launch")],
        [InlineKeyboardButton("🔴 Остановить сервер", callback_data="stop")],
        [InlineKeyboardButton("❓ Помощь",            callback_data="help")],
    ])


# ──────────────────────────────────────────────
#  Команды
# ──────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("❌ У тебя нет доступа к этому боту.")
        return
    await update.message.reply_text(
        "👋 Привет! Я Слава, управляю Minecraft-сервером на Aternos.\n\nВыбери действие:",
        reply_markup=reply_keyboard()
    )

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("❌ Нет доступа.")
        return
    await update.message.reply_text(
        "Привет, Я Слава, управляю Minecraft-сервером на Aternos.\n\nВыбери действие:",
        reply_markup=reply_keyboard()
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "📖 *Команды:*\n"
        "/start — главное меню\n"
        "/launch — запустить сервер\n"
        "/stop — остановить сервер\n"
        "/help — это сообщение\n\n"
        "⚠️ *Помни:* Aternos выключает сервер автоматически\n"
        "через ~5 минут если никто не подключён.",
        parse_mode="Markdown"
    )

async def cmd_launch_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("❌ Нет доступа.")
        return
    await _do_action(update, uid, "launch", via_callback=False)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return
    await _do_action(update, update.effective_user.id, "stop", via_callback=False)


async def cmd_prank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text("Ебать ты даун")


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if not is_allowed(uid):
        await query.edit_message_text("❌ У тебя нет доступа.")
        return

    if query.data in ("launch", "stop"):
        await _do_action(update, uid, query.data, via_callback=True)
    elif query.data == "help":
        await query.edit_message_text(
            "📖 *Команды:*\n"
            "/start — главное меню\n"
            "/launch — запустить сервер\n"
            "/stop — остановить сервер\n\n"
            "⚠️ Aternos выключает сервер через ~5 минут без игроков.",
            parse_mode="Markdown"
        )


# ──────────────────────────────────────────────
#  Общая логика действия
# ──────────────────────────────────────────────

async def _do_action(update: Update, uid: int, action: str, via_callback: bool):
    global server_busy

    # Кулдаун
    left = cooldown_left(uid)
    if left > 0:
        text = f"⏳ Подожди ещё {left} сек."
        if via_callback:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    # Уже выполняется
    if server_busy:
        text = "🔄 Уже выполняется команда, подожди!"
        if via_callback:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    # Сообщение «подождите»
    if action == "launch":
        wait_text = "⏳ Подключаюсь к Aternos и запускаю сервер..."
    else:
        wait_text = "⏳ Подключаюсь к Aternos и останавливаю сервер..."

    if via_callback:
        await update.callback_query.edit_message_text(wait_text)
        send = update.callback_query.message.reply_text
    else:
        await update.message.reply_text(wait_text)
        send = update.message.reply_text

    server_busy = True
    last_action[uid] = datetime.now()

    try:
        if action == "launch":
            result = await aternos_start()
        else:
            result = await aternos_stop()
    finally:
        server_busy = False

    await send(result, reply_markup=main_keyboard())


# ──────────────────────────────────────────────
#  Точка входа
# ──────────────────────────────────────────────

def main():
    if BOT_TOKEN == "СЮДА_ТОКЕН_ОТ_BOTFATHER":
        print("❌ Вставь токен бота в переменную BOT_TOKEN!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.Text(["67"]), cmd_prank))
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(CommandHandler("menu",   cmd_menu))

    app.add_handler(MessageHandler(filters.Text(["🟢 Запустить"]), cmd_launch_btn))
    app.add_handler(MessageHandler(filters.Text(["🔴 Остановить"]), cmd_stop))
    app.add_handler(MessageHandler(filters.Text(["❓ Помощь"]), cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_menu))

    log.info("Бот запущен. Нажми Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
