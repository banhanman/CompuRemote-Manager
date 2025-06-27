import logging
import threading
import time
import json
import os
from wakeonlan import send_magic_packet
import paramiko
import pythonping
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)

# Конфигурация
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
ADMIN_ID = YOUR_ADMIN_USER_ID  # Ваш Telegram ID
COMPUTERS_FILE = "computers.json"
MONITORING_INTERVAL = 300  # 5 минут

# Состояния для ConversationHandler
ADD_NAME, ADD_IP, ADD_MAC = range(3)

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

class ComputerManager:
    def __init__(self, filename):
        self.filename = filename
        self.computers = self.load_data()
        
    def load_data(self):
        if os.path.exists(self.filename):
            with open(self.filename, 'r') as f:
                return json.load(f)
        return {}
    
    def save_data(self):
        with open(self.filename, 'w') as f:
            json.dump(self.computers, f, indent=4)
    
    def add_computer(self, name, ip, mac):
        self.computers[name] = {
            "ip": ip,
            "mac": mac,
            "monitoring": False
        }
        self.save_data()
    
    def remove_computer(self, name):
        if name in self.computers:
            del self.computers[name]
            self.save_data()
            return True
        return False
    
    def toggle_monitoring(self, name):
        if name in self.computers:
            self.computers[name]["monitoring"] = not self.computers[name]["monitoring"]
            self.save_data()
            return self.computers[name]["monitoring"]
        return None

# Инициализация менеджера
manager = ComputerManager(COMPUTERS_FILE)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещен!")
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить компьютер", callback_data="add_computer")],
        [InlineKeyboardButton("🖥️ Список компьютеров", callback_data="list_computers")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔒 *CompuRemote Manager*\nУправление вашими компьютерами",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def list_computers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not manager.computers:
        await query.edit_message_text("Список компьютеров пуст!")
        return
    
    keyboard = []
    for name, data in manager.computers.items():
        status = "🟢" if data["monitoring"] else "🔴"
        keyboard.append([
            InlineKeyboardButton(
                f"{name} {status}",
                callback_data=f"manage_{name}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "🖥️ *Ваши компьютеры:*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def manage_computer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    computer_name = query.data.split("_")[1]
    
    keyboard = [
        [
            InlineKeyboardButton("🔌 Включить", callback_data=f"poweron_{computer_name}"),
            InlineKeyboardButton("🛑 Выключить", callback_data=f"shutdown_{computer_name}")
        ],
        [
            InlineKeyboardButton(
                "👁️ Вкл/Выкл мониторинг" if not manager.computers[computer_name]["monitoring"] else "👁️ Выкл мониторинг",
                callback_data=f"monitor_{computer_name}"
            )
        ],
        [
            InlineKeyboardButton("🗑️ Удалить", callback_data=f"remove_{computer_name}"),
            InlineKeyboardButton("🔙 Назад", callback_data="list_computers")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"⚙️ *Управление:* `{computer_name}`\nIP: `{manager.computers[computer_name]['ip']}`",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def add_computer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите имя компьютера:")
    return ADD_NAME

async def add_computer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["computer_name"] = update.message.text
    await update.message.reply_text("Введите IP-адрес компьютера:")
    return ADD_IP

async def add_computer_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ip"] = update.message.text
    await update.message.reply_text("Введите MAC-адрес компьютера (формат: 00:11:22:33:44:55):")
    return ADD_MAC

async def add_computer_mac(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mac = update.message.text
    manager.add_computer(
        context.user_data["computer_name"],
        context.user_data["ip"],
        mac
    )
    await update.message.reply_text(f"✅ Компьютер `{context.user_data['computer_name']}` добавлен!", parse_mode="Markdown")
    return ConversationHandler.END

async def power_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    computer_name = query.data.split("_")[1]
    mac = manager.computers[computer_name]["mac"]
    
    try:
        send_magic_packet(mac)
        await query.edit_message_text(f"⚡ Команда включения отправлена для `{computer_name}`", parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")

async def shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    computer_name = query.data.split("_")[1]
    ip = manager.computers[computer_name]["ip"]
    
    try:
        # Для Windows: shutdown /s /f /t 0
        # Для Linux: sudo shutdown now
        # Требует предварительной настройки SSH-доступа
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username="YOUR_USER", password="YOUR_PASSWORD")
        stdin, stdout, stderr = ssh.exec_command("shutdown /s /f /t 0")
        ssh.close()
        await query.edit_message_text(f"⏻ Команда выключения отправлена для `{computer_name}`", parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")

async def toggle_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    computer_name = query.data.split("_")[1]
    status = manager.toggle_monitoring(computer_name)
    
    if status:
        await query.edit_message_text(f"👁️ Мониторинг ВКЛЮЧЕН для `{computer_name}`", parse_mode="Markdown")
    else:
        await query.edit_message_text(f"👁️ Мониторинг ВЫКЛЮЧЕН для `{computer_name}`", parse_mode="Markdown")

async def remove_computer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    computer_name = query.data.split("_")[1]
    
    if manager.remove_computer(computer_name):
        await query.edit_message_text(f"🗑️ Компьютер `{computer_name}` удален!", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Ошибка удаления!")

def monitoring_task(context: ContextTypes.DEFAULT_TYPE):
    for name, data in manager.computers.items():
        if data["monitoring"]:
            response = pythonping.ping(data["ip"], count=1, timeout=2)
            if not response.success():
                context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"⚠️ Компьютер `{name}` ({data['ip']}) не в сети!",
                    parse_mode="Markdown"
                )

def main():
    # Создаем Application
    application = Application.builder().token(TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    
    # Обработчики callback
    application.add_handler(CallbackQueryHandler(list_computers, pattern="^list_computers$"))
    application.add_handler(CallbackQueryHandler(list_computers, pattern="^back$"))
    application.add_handler(CallbackQueryHandler(manage_computer, pattern="^manage_"))
    application.add_handler(CallbackQueryHandler(power_on, pattern="^poweron_"))
    application.add_handler(CallbackQueryHandler(shutdown, pattern="^shutdown_"))
    application.add_handler(CallbackQueryHandler(toggle_monitor, pattern="^monitor_"))
    application.add_handler(CallbackQueryHandler(remove_computer, pattern="^remove_"))
    
    # Обработчик добавления компьютера
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_computer_start, pattern="^add_computer$")],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_computer_name)],
            ADD_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_computer_ip)],
            ADD_MAC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_computer_mac)]
        },
        fallbacks=[]
    )
    application.add_handler(conv_handler)
    
    # Запуск мониторинга
    job_queue = application.job_queue
    job_queue.run_repeating(
        lambda ctx: monitoring_task(ctx),
        interval=MONITORING_INTERVAL,
        first=10
    )
    
    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()
