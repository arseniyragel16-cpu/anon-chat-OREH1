import os
import sys
from dotenv import load_dotenv
import asyncio
import logging
from enum import Enum
from typing import Dict, Optional, Tuple
from datetime import datetime
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
    stream=sys.stdout  # Важно для Koyeb!
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('BOT_TOKEN')

if not TOKEN:
    logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN не найден!")
    logger.error("Добавьте BOT_TOKEN в Environment Variables в Koyeb")
    sys.exit(1)

logger.info(f"✅ Бот запускается... Токен: {TOKEN[:10]}...")

# Состояния пользователей
class UserState(Enum):
    IDLE = "idle"
    SEARCHING = "searching"
    CHATTING = "chatting"

# Хранилище данных
class ChatManager:
    def __init__(self):
        self.user_states = {}
        self.user_partners = {}
        self.waiting_queue = []
        self.user_gender = {}
        self.user_interests = {}
        self.chat_history = defaultdict(list)
    
    def add_to_queue(self, user_id: int, gender: str = None, interests: str = None):
        if user_id not in self.waiting_queue:
            self.waiting_queue.append(user_id)
            self.user_states[user_id] = UserState.SEARCHING
            if gender:
                self.user_gender[user_id] = gender
            if interests:
                self.user_interests[user_id] = interests
    
    def remove_from_queue(self, user_id: int):
        if user_id in self.waiting_queue:
            self.waiting_queue.remove(user_id)
    
    def find_partner(self, user_id: int) -> Optional[int]:
        if not self.waiting_queue:
            return None
        
        for potential_partner in self.waiting_queue:
            if potential_partner != user_id:
                return potential_partner
        
        return None
    
    def connect_users(self, user1: int, user2: int):
        self.user_partners[user1] = user2
        self.user_partners[user2] = user1
        self.user_states[user1] = UserState.CHATTING
        self.user_states[user2] = UserState.CHATTING
        
        self.remove_from_queue(user1)
        self.remove_from_queue(user2)
    
    def disconnect_users(self, user_id: int):
        if user_id in self.user_partners:
            partner_id = self.user_partners[user_id]
            
            del self.user_partners[user_id]
            if partner_id in self.user_partners:
                del self.user_partners[partner_id]
            
            self.user_states[user_id] = UserState.IDLE
            self.user_states[partner_id] = UserState.IDLE
            
            return partner_id
        return None

chat_manager = ChatManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = f"""
👋 Привет, {user.first_name}!

Добро пожаловать в анонимный чат-рулетку!

Доступные команды:
/search - Найти собеседника
/stop - Остановить диалог
/next - Следующий собеседник
/info - Информация о боте
/settings - Настройки поиска

⚠️ Правила:
1. Уважайте собеседников
2. Не рассылайте спам
3. Будьте вежливы
Удачи в поиске)

Нажмите /search чтобы начать поиск!
    """
    
    await update.message.reply_text(welcome_text)

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if chat_manager.user_states.get(user_id) == UserState.CHATTING:
        await update.message.reply_text("❌ Вы уже в диалоге! Используйте /stop чтобы закончить.")
        return
    
    chat_manager.add_to_queue(user_id)
    
    keyboard = [
        [InlineKeyboardButton("👤 Любой пол", callback_data="gender_any")],
        [InlineKeyboardButton("👨 Только мужчины", callback_data="gender_male")],
        [InlineKeyboardButton("👩 Только женщины", callback_data="gender_female")],
        [InlineKeyboardButton("🚀 Начать поиск", callback_data="start_search")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔍 Настройте поиск собеседника или начните поиск:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith("gender_"):
        gender = data.split("_")[1]
        chat_manager.user_gender[user_id] = gender
        
        await query.edit_message_text(
            text=f"✅ Установлен фильтр: {gender}\nНажмите 'Начать поиск'"
        )
    
    elif data == "start_search":
        await query.edit_message_text("🔍 Ищем собеседника...")
        
        partner_id = chat_manager.find_partner(user_id)
        
        if partner_id:
            chat_manager.connect_users(user_id, partner_id)
            
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Собеседник найден! Начинайте общение.\n/stop - закончить диалог\n/next - следующий собеседник"
            )
            
            await context.bot.send_message(
                chat_id=partner_id,
                text="✅ Собеседник найден! Начинайте общение.\n/stop - закончить диалог\n/next - следующий собеседник"
            )
        else:
            await query.edit_message_text(
                "⏳ Ожидаем собеседника...\nВы в очереди.\n/stop - отменить поиск"
            )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if chat_manager.user_states.get(user_id) != UserState.CHATTING:
        await update.message.reply_text("❌ Вы не в диалоге! Используйте /search чтобы найти собеседника.")
        return
    
    partner_id = chat_manager.user_partners.get(user_id)
    if not partner_id:
        await update.message.reply_text("❌ Собеседник не найден!")
        return
    
    try:
        message = update.message
        
        if message.text:
            await context.bot.send_message(
                chat_id=partner_id,
                text=f"💬: {message.text}"
            )
        elif message.photo:
            await context.bot.send_photo(
                chat_id=partner_id,
                photo=message.photo[-1].file_id,
                caption=f"📷: {message.caption if message.caption else ''}"
            )
        elif message.sticker:
            await context.bot.send_sticker(
                chat_id=partner_id,
                sticker=message.sticker.file_id
            )
        elif message.voice:
            await context.bot.send_voice(
                chat_id=partner_id,
                voice=message.voice.file_id
            )
        elif message.document:
            await context.bot.send_message(
                chat_id=partner_id,
                text="📎 Пользователь отправил файл"
            )
        else:
            await update.message.reply_text("⚠️ Этот тип сообщения не поддерживается в чат-рулетке")
            
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        await update.message.reply_text("❌ Не удалось отправить сообщение!")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if chat_manager.user_states.get(user_id) == UserState.CHATTING:
        partner_id = chat_manager.disconnect_users(user_id)
        
        if partner_id:
            await context.bot.send_message(
                chat_id=partner_id,
                text="❌ Собеседник завершил диалог."
            )
        
        await update.message.reply_text("✅ Диалог завершен!\n/search - найти нового собеседника")
    
    elif chat_manager.user_states.get(user_id) == UserState.SEARCHING:
        chat_manager.remove_from_queue(user_id)
        chat_manager.user_states[user_id] = UserState.IDLE
        await update.message.reply_text("✅ Поиск отменен!")
    
    else:
        await update.message.reply_text("❌ Вы не в диалоге и не в поиске!")

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if chat_manager.user_states.get(user_id) == UserState.CHATTING:
        partner_id = chat_manager.disconnect_users(user_id)
        
        if partner_id:
            await context.bot.send_message(
                chat_id=partner_id,
                text="❌ Собеседник перешел к следующему диалогу."
            )
        
        chat_manager.add_to_queue(user_id)
        partner_id = chat_manager.find_partner(user_id)
        
        if partner_id:
            chat_manager.connect_users(user_id, partner_id)
            
            await update.message.reply_text("✅ Ищем следующего собеседника...")
            await asyncio.sleep(1)
            
            await update.message.reply_text("✅ Новый собеседник найден!")
            await context.bot.send_message(
                chat_id=partner_id,
                text="✅ Найден новый собеседник!"
            )
        else:
            await update.message.reply_text("⏳ Ищем следующего собеседника...")
    
    else:
        await update.message.reply_text("❌ Вы не в диалоге! Используйте /search")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info_text = """
🤖 Анонимный Чат-Рулетка

📊 Статистика:
• Пользователей в поиске: {}
• Активных диалогов: {}

⚙️ Технологии:
• Python + python-telegram-bot
• Анонимное соединение
• Мгновенная доставка сообщений

👨‍💻 Разработчик: 
 @Lomtikiyulsokogoneba 
😎Владелец:
 @hranitelsemeni01

📝 Правила:
1. Общайтесь уважительно
2. Не спамьте
3. Не передавайте личные данные
4. Сообщайте о нарушениях
    """.format(
        len(chat_manager.waiting_queue),
        len(chat_manager.user_partners) // 2
    )
    
    await update.message.reply_text(info_text)

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👤 Фильтр по полу", callback_data="filter_gender")],
        [InlineKeyboardButton("🎯 Фильтр по интересам", callback_data="filter_interests")],
        [InlineKeyboardButton("🚫 Заблокировать пользователя", callback_data="block_user")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚙️ Настройки чат-рулетки:",
        reply_markup=reply_markup
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

def main():
    # ВАЖНО: замените на ваш токен от @BotFather
    TOKEN = "8299271667:AAG6Yvm7yk7POlulI4bJtRaBy77bSfYYPWE"
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("next", next_chat))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("settings", settings))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчики сообщений (исправленные)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message
    ))
    application.add_handler(MessageHandler(
        filters.PHOTO | filters.VOICE, handle_message
    ))
    
    # Обработчик ошибок - ПРАВИЛЬНЫЙ ОТСТУП
    application.add_error_handler(error_handler)
    
    logger.info("🤖 Бот запущен и ожидает сообщений...")
    application.run_polling()

if __name__ == '__main__':
    main()