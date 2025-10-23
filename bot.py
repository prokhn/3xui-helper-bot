import os
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv
from database import DatabaseManager

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токен бота из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")

# Инициализируем менеджер БД
db_manager = DatabaseManager()

# Глобальные переменные для мониторинга
monitoring_active = False
last_configs = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id
    
    # Проверяем авторизацию
    if db_manager.is_user_authorized(user_id):
        await show_menu(update, context)
    else:
        welcome_message = f"Привет, {user.first_name}! 👋\n\n"
        welcome_message += f"Ваш Telegram ID: `{user_id}`\n\n"
        welcome_message += "❌ Ваш клиент не найден в базе данных.\n"
        welcome_message += "Обратитесь к администратору для добавления вашего аккаунта."
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /menu"""
    user_id = update.effective_user.id
    
    if not db_manager.is_user_authorized(user_id):
        await update.message.reply_text("❌ Вы не авторизованы. Обратитесь к администратору.")
        return
    
    await show_menu(update, context)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать меню с информацией о клиентах"""
    user_id = update.effective_user.id
    menu_data = db_manager.get_user_menu_data(user_id)
    
    if not menu_data:
        await update.message.reply_text("❌ Клиенты не найдены.")
        return
    
    # Отправляем информацию для каждого клиента
    for client_data in menu_data:
        email = client_data['email']
        
        if client_data['traffic_stats']:
            message = f"👤 **{email}**\n\n"
            message += f"🔼 Исходящий трафик: ↑{client_data['up_gb']}GB\n"
            message += f"🔽 Входящий трафик: ↓{client_data['down_gb']}GB\n"
            message += f"📊 Всего: ↑↓{client_data['total_gb']}GB"
        else:
            message = f"👤 **{email}**\n\n"
            message += "📊 Статистика трафика недоступна"
        
        # Добавляем время обновления
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message += f"\n\n📋🔄 Обновлено: {current_time}"
        
        # Создаем кнопки
        keyboard = [
            [InlineKeyboardButton("📄 Мой конфиг", callback_data=f"config_{email}")],
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{email}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if query.data.startswith("config_"):
        email = query.data.replace("config_", "")
        
        # Получаем конфиг через публичный API
        config = db_manager.get_client_config(user_id, email)
        
        if not config:
            await query.edit_message_text("❌ Клиент не найден.")
            return
        
        message = f"📄 Твой конфиг:\n\n```\n{config}\n```"
        
        # Создаем кнопку "Меню"
        keyboard = [[InlineKeyboardButton("📋 Меню", callback_data="menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    elif query.data.startswith("refresh_"):
        email = query.data.replace("refresh_", "")
        
        # Обновляем данные и показываем меню
        await show_menu_from_callback(query)
    
    elif query.data == "menu":
        # Возвращаемся в меню
        await show_menu_from_callback(query)

async def show_menu_from_callback(query) -> None:
    """Показать меню из callback query"""
    user_id = query.from_user.id
    menu_data = db_manager.get_user_menu_data(user_id)
    
    if not menu_data:
        await query.edit_message_text("❌ Клиенты не найдены.")
        return
    
    # Отправляем информацию для каждого клиента
    messages = []
    for client_data in menu_data:
        email = client_data['email']
        
        if client_data['traffic_stats']:
            message = f"👤 **{email}**\n\n"
            message += f"🔼 Исходящий трафик: ↑{client_data['up_gb']}GB\n"
            message += f"🔽 Входящий трафик: ↓{client_data['down_gb']}GB\n"
            message += f"📊 Всего: ↑↓{client_data['total_gb']}GB"
        else:
            message = f"👤 **{email}**\n\n"
            message += "📊 Статистика трафика недоступна"
        
        # Добавляем время обновления
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message += f"\n\n📋🔄 Обновлено: {current_time}"
        
        messages.append(message)
    
    # Объединяем все сообщения
    full_message = "\n\n".join(messages)
    
    # Создаем кнопки для первого клиента (если есть)
    if menu_data:
        first_email = menu_data[0]['email']
        keyboard = [
            [InlineKeyboardButton("📄 Мой конфиг", callback_data=f"config_{first_email}")],
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{first_email}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(full_message, parse_mode='Markdown', reply_markup=reply_markup)

async def monitor_database_changes(application: Application) -> None:
    """Мониторинг изменений в БД и отправка уведомлений"""
    global monitoring_active, last_configs
    
    monitoring_active = True
    logger.info("Запуск мониторинга изменений БД...")
    
    # Инициализируем начальное состояние
    last_configs = db_manager.get_all_user_configs()
    
    while monitoring_active:
        try:
            # Проверяем изменения
            changed_configs = db_manager.check_config_changes(last_configs)
            
            # Отправляем уведомления о изменениях
            for tg_id, updated_configs in changed_configs.items():
                for config_data in updated_configs:
                    email = config_data['email']
                    config = config_data['config']
                    
                    message = f"🚨 Конфиг для {email} был обновлён\n\n"
                    message += f"```\n{config}\n```"
                    
                    try:
                        await application.bot.send_message(
                            chat_id=tg_id,
                            text=message,
                            parse_mode='Markdown'
                        )
                        logger.info(f"Отправлено уведомление об обновлении конфига для {email} (TG ID: {tg_id})")
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления для {tg_id}: {e}")
            
            # Обновляем состояние
            if changed_configs:
                last_configs = db_manager.get_all_user_configs()
                logger.info(f"Обнаружены изменения в конфигах: {len(changed_configs)} пользователей")
            
            # Ждем перед следующей проверкой
            await asyncio.sleep(30)  # Проверяем каждые 30 секунд
            
        except Exception as e:
            logger.error(f"Ошибка в мониторинге БД: {e}")
            await asyncio.sleep(60)  # При ошибке ждем дольше

def main() -> None:
    """Основная функция для запуска бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    
    # Добавляем обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Добавляем задачу мониторинга при запуске приложения
    async def post_init(application: Application) -> None:
        """Инициализация после запуска приложения"""
        global monitoring_active
        monitoring_active = True
        logger.info("Запуск мониторинга изменений БД...")
        
        # Запускаем мониторинг как фоновую задачу
        asyncio.create_task(monitor_database_changes(application))
    
    # Добавляем обработчик инициализации
    application.post_init = post_init
    
    # Добавляем обработчик остановки
    async def post_stop(application: Application) -> None:
        """Остановка мониторинга при завершении"""
        global monitoring_active
        monitoring_active = False
        logger.info("Мониторинг изменений БД остановлен")
    
    application.post_stop = post_stop
    
    # Запускаем бота с мониторингом
    logger.info("Бот запускается с мониторингом изменений БД...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
