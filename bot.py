import os
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, 
    ConversationHandler, ContextTypes, filters
)
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

# Отключаем шумные логи от httpx и telegram библиотек
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)

# Получаем токен бота из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")

# Получаем ID администраторов из переменных окружения
ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = []
if ADMIN_IDS_STR:
    try:
        ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()]
    except ValueError:
        logger.warning("Ошибка при парсинге ADMIN_IDS. Рассылка будет недоступна.")

# Инициализируем менеджер БД
db_manager = DatabaseManager()

# Глобальные переменные для мониторинга
monitoring_active = False
last_configs = {}
last_clients = []

# Состояния для ConversationHandler - используем разные диапазоны для разных диалогов
# Рассылка: 10-19
MAIL_WAITING_MESSAGE = 10
MAIL_CONFIRM = 11

# Отчет: 20-29
REPORT_PROVIDER = 20
REPORT_DEVICE = 21
REPORT_COMMENTS = 22

# Константы для завершения диалогов
END = ConversationHandler.END

def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором"""
    return user_id in ADMIN_IDS

# ==================== ОБЩИЕ ФУНКЦИИ ====================

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
    
    # Объединяем информацию о всех клиентах в одно сообщение
    messages = []
    for client_data in menu_data:
        email = client_data['email']
        
        if client_data['traffic_stats']:
            message = f"👤 **{email}**\n\n"
            message += f"🔼 Исходящий трафик: ↑{round(client_data['up_gb'], 3)}GB\n"
            message += f"🔽 Входящий трафик: ↓{round(client_data['down_gb'], 3)}GB\n"
            message += f"📊 Всего: ↑↓{round(client_data['total_gb'], 3)}GB"
        else:
            message = f"👤 **{email}**\n\n"
            message += "📊 Статистика трафика недоступна"
        
        messages.append(message)
    
    # Объединяем все сообщения
    full_message = "\n\n".join(messages)
    
    # Добавляем время обновления в конце
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_message += f"\n\n📋🔄 Обновлено: {current_time}"
    
    # Добавляем информацию о команде /report
    full_message += f"\n\n📝 Используйте /report для сообщения о проблемах"
    
    # Добавляем админские команды для администраторов
    if is_admin(user_id):
        full_message += f"\n\n🔐 **Админские команды:**\n"
        full_message += f"📢 /mail - рассылка сообщений всем пользователям\n"
        full_message += f"📝 /report - создание отчета о проблеме"
    
    # Создаем кнопки для первого клиента (если есть)
    if menu_data:
        first_email = menu_data[0]['email']
        keyboard = [
            [InlineKeyboardButton("📄 Мой конфиг", callback_data=f"config_{first_email}")],
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{first_email}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(full_message, parse_mode='Markdown', reply_markup=reply_markup)

async def show_menu_from_callback(query, context: Optional[ContextTypes.DEFAULT_TYPE] = None) -> None:
    """Показать меню из callback query"""
    user_id = query.from_user.id
    menu_data = db_manager.get_user_menu_data(user_id)
    
    if not menu_data:
        await query.edit_message_text("❌ Клиенты не найдены.")
        return
    
    # Объединяем информацию о всех клиентах в одно сообщение
    messages = []
    for client_data in menu_data:
        email = client_data['email']
        
        if client_data['traffic_stats']:
            message = f"👤 **{email}**\n\n"
            message += f"🔼 Исходящий трафик: ↑{round(client_data['up_gb'], 3)}GB\n"
            message += f"🔽 Входящий трафик: ↓{round(client_data['down_gb'], 3)}GB\n"
            message += f"📊 Всего: ↑↓{round(client_data['total_gb'], 3)}GB"
        else:
            message = f"👤 **{email}**\n\n"
            message += "📊 Статистика трафика недоступна"
        
        messages.append(message)
    
    # Объединяем все сообщения
    full_message = "\n\n".join(messages)
    
    # Добавляем время обновления в конце
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_message += f"\n\n📋🔄 Обновлено: {current_time}"
    
    # Добавляем информацию о команде /report
    full_message += f"\n\n📝 Используйте /report для сообщения о проблемах"
    
    # Добавляем админские команды для администраторов
    if is_admin(user_id):
        full_message += f"\n\n🔐 **Админские команды:**\n"
        full_message += f"📢 /mail - рассылка сообщений всем пользователям\n"
        full_message += f"📝 /report - создание отчета о проблеме"
    
    # Создаем кнопки для первого клиента (если есть)
    if menu_data:
        first_email = menu_data[0]['email']
        keyboard = [
            [InlineKeyboardButton("📄 Мой конфиг", callback_data=f"config_{first_email}")],
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{first_email}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(full_message, parse_mode='Markdown', reply_markup=reply_markup)

async def show_menu_by_user_id(bot, user_id: int, chat_id: int, edit_message_id: Optional[int] = None) -> None:
    """Показать меню по user_id (для использования после завершения диалогов)"""
    logger.info(f"[MENU] show_menu_by_user_id вызвана для user_id={user_id}, chat_id={chat_id}")
    menu_data = db_manager.get_user_menu_data(user_id)
    
    logger.info(f"[MENU] Получено данных о клиентах: {len(menu_data) if menu_data else 0}")
    
    if not menu_data:
        message_text = "❌ Клиенты не найдены."
        logger.warning(f"[MENU] Клиенты не найдены для пользователя {user_id}")
        if edit_message_id:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=edit_message_id, text=message_text)
            except:
                await bot.send_message(chat_id=chat_id, text=message_text)
        else:
            await bot.send_message(chat_id=chat_id, text=message_text)
        return
    
    # Объединяем информацию о всех клиентах в одно сообщение
    messages = []
    for client_data in menu_data:
        email = client_data['email']
        
        if client_data['traffic_stats']:
            message = f"👤 **{email}**\n\n"
            message += f"🔼 Исходящий трафик: ↑{round(client_data['up_gb'], 3)}GB\n"
            message += f"🔽 Входящий трафик: ↓{round(client_data['down_gb'], 3)}GB\n"
            message += f"📊 Всего: ↑↓{round(client_data['total_gb'], 3)}GB"
        else:
            message = f"👤 **{email}**\n\n"
            message += "📊 Статистика трафика недоступна"
        
        messages.append(message)
    
    # Объединяем все сообщения
    full_message = "\n\n".join(messages)
    
    # Добавляем время обновления в конце
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_message += f"\n\n📋🔄 Обновлено: {current_time}"
    
    # Добавляем информацию о команде /report
    full_message += f"\n\n📝 Используйте /report для сообщения о проблемах"
    
    # Добавляем админские команды для администраторов
    if is_admin(user_id):
        full_message += f"\n\n🔐 **Админские команды:**\n"
        full_message += f"📢 /mail - рассылка сообщений всем пользователям\n"
        full_message += f"📝 /report - создание отчета о проблеме"
    
    # Создаем кнопки для первого клиента (если есть)
    if menu_data:
        first_email = menu_data[0]['email']
        keyboard = [
            [InlineKeyboardButton("📄 Мой конфиг", callback_data=f"config_{first_email}")],
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{first_email}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if edit_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=edit_message_id,
                    text=full_message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            except:
                await bot.send_message(
                    chat_id=chat_id,
                    text=full_message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
        else:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=full_message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
                logger.info(f"[MENU] Сообщение с меню успешно отправлено пользователю {user_id}")
            except Exception as e:
                logger.error(f"[MENU] Ошибка при отправке меню пользователю {user_id}: {e}")
                raise

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки (только для обычных кнопок, не связанных с диалогами)"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if query.data.startswith("config_"):
        email = query.data.replace("config_", "")
        
        # Получаем все конфиги пользователя
        user_clients = db_manager.get_user_clients(user_id)
        
        if not user_clients:
            await query.edit_message_text("❌ Клиенты не найдены.")
            return
        
        # Формируем сообщение со всеми конфигами
        config_messages = []
        for client in user_clients:
            client_email = client.get('email', '')
            config = db_manager.generate_vless_config(client)
            
            config_messages.append(f"📄 Твой конфиг для `{client_email}`:\n```\n{config}\n```")
        
        # Объединяем все конфиги
        full_message = "\n\n".join(config_messages)
        
        # Создаем кнопку "Меню"
        keyboard = [[InlineKeyboardButton("📋 Меню", callback_data="menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(full_message, parse_mode='Markdown', reply_markup=reply_markup)
    
    elif query.data.startswith("refresh_"):
        email = query.data.replace("refresh_", "")
        await show_menu_from_callback(query, context)
    
    elif query.data == "menu":
        await show_menu_from_callback(query, context)
    
    elif query.data == "menu_from_config":
        # Обработка кнопки "Меню" из сообщения об обновлении конфига
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
        logger.info(f"[MENU] Обработка кнопки меню от пользователя {user_id} в чате {chat_id}")
        
        # Убираем кнопку из сообщения
        try:
            await query.edit_message_reply_markup(reply_markup=None)
            logger.info(f"[MENU] Кнопка успешно скрыта")
        except Exception as e:
            logger.error(f"[MENU] Ошибка при удалении кнопки меню: {e}")
        
        # Отправляем новое сообщение с меню
        try:
            await show_menu_by_user_id(context.bot, user_id, chat_id)
            logger.info(f"[MENU] Меню успешно отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"[MENU] Ошибка при отправке меню пользователю {user_id}: {e}")
            await query.answer("Ошибка при загрузке меню", show_alert=True)
    
    elif query.data.startswith("admin_config_"):
        # Обработка кнопки "Конфиг" из уведомления о новом клиенте (только для админов)
        user_id = query.from_user.id
        
        if not is_admin(user_id):
            await query.answer("У вас нет прав администратора", show_alert=True)
            return
        
        client_id = query.data.replace("admin_config_", "")
        logger.info(f"[ADMIN] Запрос конфига для клиента {client_id} от администратора {user_id}")
        
        # Находим клиента по ID
        all_clients = db_manager.get_all_clients()
        target_client = None
        for client in all_clients:
            if client.get('id') == client_id:
                target_client = client
                break
        
        if not target_client:
            await query.answer("Клиент не найден", show_alert=True)
            return
        
        # Генерируем конфиг
        config = db_manager.generate_vless_config(target_client)
        client_email = target_client.get('email', 'Неизвестно')
        
        # Убираем кнопку из сообщения
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            logger.error(f"Ошибка при удалении кнопки конфига: {e}")
        
        # Отправляем конфиг отдельным сообщением
        config_message = f"🔑 Конфиг для `{client_email}`:\n```\n{config}\n```"
        
        try:
            await query.message.reply_text(config_message, parse_mode='Markdown')
            logger.info(f"[ADMIN] Конфиг отправлен администратору {user_id} для клиента {client_email}")
        except Exception as e:
            logger.error(f"Ошибка отправки конфига администратору {user_id}: {e}")
            await query.answer("Ошибка при генерации конфига", show_alert=True)

# ==================== РАССЫЛКА ====================

async def mail_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало режима рассылки - этап 1: активация"""
    user_id = update.effective_user.id
    logger.info(f"[MAIL] ===== ENTRY POINT: Команда /mail от пользователя {user_id} =====")
    
    # Проверяем права администратора
    if not is_admin(user_id):
        logger.warning(f"[MAIL] Пользователь {user_id} не является администратором")
        await update.message.reply_text("❌ Извините, у вас нет прав на выполнение этой команды.")
        return END
    
    # Очищаем возможные старые данные
    context.user_data.pop('mail_text', None)
    context.user_data.pop('mail_telegram_ids', None)
    context.user_data.pop('mail_message_id', None)
    context.user_data.pop('mail_chat_id', None)
    
    message = "📢 Режим рассылки активирован\n\n"
    message += "Введите ваше сообщение для рассылки всем пользователям."
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="mail_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    mail_message = await update.message.reply_text(message, reply_markup=reply_markup)
    
    # Сохраняем ID сообщения с кнопкой отмены
    context.user_data['mail_message_id'] = mail_message.message_id
    context.user_data['mail_chat_id'] = update.message.chat_id
    
    logger.info(f"[MAIL] Этап 1: Режим рассылки активирован для пользователя {user_id}, состояние: MAIL_WAITING_MESSAGE")
    return MAIL_WAITING_MESSAGE

async def mail_receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение сообщения для рассылки - этап 2: обработка сообщения"""
    user_id = update.effective_user.id
    message_text = update.message.text or update.message.caption or ""
    
    logger.info(f"[MAIL] Этап 2: Получено сообщение от пользователя {user_id}")
    
    # Проверяем права администратора
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return END
    
    if not message_text.strip():
        await update.message.reply_text("❌ Сообщение не может быть пустым. Попробуйте еще раз.")
        return MAIL_WAITING_MESSAGE
    
    # Убираем кнопку отмены из первого сообщения
    mail_message_id = context.user_data.get('mail_message_id')
    mail_chat_id = context.user_data.get('mail_chat_id')
    if mail_message_id and mail_chat_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=mail_chat_id,
                message_id=mail_message_id,
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении кнопки отмены: {e}")
    
    # Получаем все уникальные telegram ID пользователей
    telegram_ids = db_manager.get_all_unique_telegram_ids()
    
    if not telegram_ids:
        await update.message.reply_text("❌ Не найдено пользователей для рассылки.")
        return END
    
    # Сохраняем сообщение для подтверждения
    context.user_data['mail_text'] = message_text
    context.user_data['mail_telegram_ids'] = telegram_ids
    
    # Показываем статистику отдельным сообщением
    stats_message = f"📊 Статистика рассылки:\n\n"
    stats_message += f"👥 Получателей: {len(telegram_ids)} человек\n\n"
    stats_message += f"👀 Превью сообщения ниже:"
    
    await update.message.reply_text(stats_message)
    
    # Показываем превью отдельным сообщением
    message_with_signature = f"⚫️ Тёмная Сторона сообщает:\n\n{message_text}"
    
    await update.message.reply_text(message_with_signature)
    
    # Запрашиваем подтверждение
    confirm_message = "❓ Отправить рассылку?"
    
    keyboard = [
        [InlineKeyboardButton("✅ Отправить", callback_data="mail_confirm")],
        [InlineKeyboardButton("❌ Отменить", callback_data="mail_cancel_confirm")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    confirm_msg = await update.message.reply_text(confirm_message, reply_markup=reply_markup)
    context.user_data['mail_confirm_message_id'] = confirm_msg.message_id
    
    logger.info(f"[MAIL] Этап 3: Показано превью и запрошено подтверждение для пользователя {user_id}, переход в состояние MAIL_CONFIRM")
    return MAIL_CONFIRM

async def mail_handle_confirm_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка кнопок подтверждения/отмены рассылки"""
    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id
    
    logger.info(f"[MAIL] Обработка кнопки {callback_data} от пользователя {user_id}")
    
    if callback_data == "mail_confirm":
        await query.answer("Начинаю рассылку...")
        await query.edit_message_text("⏳ Начинаю рассылку...")
        
        mail_text = context.user_data.get('mail_text')
        telegram_ids = context.user_data.get('mail_telegram_ids')
        
        if not mail_text or not telegram_ids:
            await query.answer("Ошибка: данные рассылки не найдены", show_alert=True)
            logger.error(f"[MAIL] Ошибка: данные рассылки не найдены для пользователя {user_id}")
            return END
        
        # Выполняем рассылку
        success_count = 0
        failed_count = 0
        
        # Формируем сообщение с подписью
        message_with_signature = f"⚫️ Тёмная Сторона сообщает:\n\n{mail_text}"
        
        for tg_id in telegram_ids:
            try:
                await context.bot.send_message(
                    chat_id=tg_id,
                    text=message_with_signature
                )
                success_count += 1
                logger.info(f"[MAIL] Сообщение успешно отправлено пользователю {tg_id}")
            except Exception as e:
                failed_count += 1
                logger.error(f"[MAIL] Ошибка отправки сообщения пользователю {tg_id}: {e}")
        
        # Отправляем статистику администратору
        stats_message = "✅ Рассылка завершена!\n\n"
        stats_message += f"📊 Статистика:\n"
        stats_message += f"✅ Успешно отправлено: {success_count}\n"
        stats_message += f"❌ Ошибок: {failed_count}\n"
        stats_message += f"📈 Всего пользователей: {len(telegram_ids)}"
        
        await query.message.reply_text(stats_message)
        
        # Очищаем данные
        context.user_data.pop('mail_text', None)
        context.user_data.pop('mail_telegram_ids', None)
        context.user_data.pop('mail_message_id', None)
        context.user_data.pop('mail_chat_id', None)
        context.user_data.pop('mail_confirm_message_id', None)
        
        logger.info(f"[MAIL] Рассылка завершена для пользователя {user_id}: успешно {success_count}, ошибок {failed_count}")
        
        # Показываем главное меню
        await show_menu_by_user_id(context.bot, user_id, query.message.chat_id)
        
        return END
    
    elif callback_data == "mail_cancel_confirm":
        await query.answer("Рассылка отменена")
        await query.edit_message_text("❌ Рассылка отменена")
        
        # Очищаем данные
        context.user_data.pop('mail_text', None)
        context.user_data.pop('mail_telegram_ids', None)
        context.user_data.pop('mail_message_id', None)
        context.user_data.pop('mail_chat_id', None)
        context.user_data.pop('mail_confirm_message_id', None)
        
        # Показываем главное меню
        await show_menu_by_user_id(context.bot, user_id, query.message.chat_id)
        
        return END
    
    # Если callback_data не распознан, возвращаемся в то же состояние
    await query.answer("Неизвестная команда")
    return MAIL_CONFIRM

async def mail_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена рассылки на любом этапе"""
    query = update.callback_query
    await query.answer("Рассылка отменена")
    
    user_id = query.from_user.id
    callback_data = query.data
    logger.info(f"[MAIL] Отмена рассылки от пользователя {user_id}, callback_data: {callback_data}, текущее состояние: {context.user_data.get('_conversation_state')}")
    
    # Убираем кнопки отмены из всех сообщений
    mail_message_id = context.user_data.get('mail_message_id')
    mail_chat_id = context.user_data.get('mail_chat_id')
    if mail_message_id and mail_chat_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=mail_chat_id,
                message_id=mail_message_id,
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении кнопки отмены: {e}")
    
    mail_confirm_message_id = context.user_data.get('mail_confirm_message_id')
    if mail_confirm_message_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=query.message.chat_id,
                message_id=mail_confirm_message_id,
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении кнопки подтверждения: {e}")
    
    # Очищаем данные
    context.user_data.pop('mail_text', None)
    context.user_data.pop('mail_telegram_ids', None)
    context.user_data.pop('mail_message_id', None)
    context.user_data.pop('mail_chat_id', None)
    context.user_data.pop('mail_confirm_message_id', None)
    
    # Показываем главное меню
    await show_menu_by_user_id(context.bot, user_id, query.message.chat_id)
    
    return END

# ==================== ОТЧЕТ ====================

async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания отчета - этап 1: активация"""
    user_id = update.effective_user.id
    logger.info(f"[REPORT] ===== ENTRY POINT: Команда /report от пользователя {user_id} =====")
    
    # Проверяем авторизацию
    if not db_manager.is_user_authorized(user_id):
        logger.warning(f"[REPORT] Пользователь {user_id} не авторизован")
        await update.message.reply_text("❌ Вы не авторизованы. Обратитесь к администратору.")
        return END
    
    # Инициализируем данные отчета
    context.user_data['report_data'] = {
        'provider': None,
        'device': None,
        'comments': None,
        'message_ids': []
    }
    
    # Задаем первый вопрос
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="report_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.message.reply_text(
        "📝 Создание отчета о проблеме\n\n1️⃣ Ваш провайдер:",
        reply_markup=reply_markup
    )
    
    # Сохраняем ID сообщения
    context.user_data['report_data']['message_ids'].append(message.message_id)
    
    logger.info(f"[REPORT] Этап 1: Режим отчета активирован для пользователя {user_id}, состояние: REPORT_PROVIDER")
    return REPORT_PROVIDER

async def report_provider(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ответа на вопрос о провайдере - этап 2"""
    user_id = update.effective_user.id
    message_text = update.message.text or update.message.caption or ""
    
    logger.info(f"[REPORT] Этап 2: Получен ответ о провайдере от пользователя {user_id}")
    
    if not message_text.strip():
        await update.message.reply_text("❌ Пожалуйста, введите текст.")
        return REPORT_PROVIDER
    
    report_data = context.user_data.get('report_data', {})
    if not report_data:
        logger.error(f"[REPORT] Ошибка: report_data не найден для пользователя {user_id}")
        await update.message.reply_text("❌ Ошибка: данные отчета потеряны. Начните заново с /report")
        return END
    
    report_data['provider'] = message_text.strip()
    
    # Убираем кнопку отмены из предыдущего сообщения
    if report_data.get('message_ids'):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.message.chat_id,
                message_id=report_data['message_ids'][-1],
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении кнопки отмены: {e}")
    
    # Задаем второй вопрос
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="report_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.message.reply_text(
        "2️⃣ Устройство - телефон или ПК:",
        reply_markup=reply_markup
    )
    report_data['message_ids'].append(message.message_id)
    
    logger.info(f"[REPORT] Этап 3: Задан вопрос об устройстве для пользователя {user_id}, переход в состояние REPORT_DEVICE")
    return REPORT_DEVICE

async def report_device(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ответа на вопрос об устройстве - этап 3"""
    user_id = update.effective_user.id
    message_text = update.message.text or update.message.caption or ""
    
    logger.info(f"[REPORT] Этап 3: Получен ответ об устройстве от пользователя {user_id}")
    
    if not message_text.strip():
        await update.message.reply_text("❌ Пожалуйста, введите текст.")
        return REPORT_DEVICE
    
    report_data = context.user_data.get('report_data', {})
    if not report_data:
        logger.error(f"[REPORT] Ошибка: report_data не найден для пользователя {user_id}")
        await update.message.reply_text("❌ Ошибка: данные отчета потеряны. Начните заново с /report")
        return END
    
    report_data['device'] = message_text.strip()
    
    # Убираем кнопку отмены из предыдущего сообщения
    if report_data.get('message_ids'):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.message.chat_id,
                message_id=report_data['message_ids'][-1],
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении кнопки отмены: {e}")
    
    # Задаем третий вопрос
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="report_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.message.reply_text(
        "3️⃣ Комментарии - что работает, когда сломалось, что не открывается:",
        reply_markup=reply_markup
    )
    report_data['message_ids'].append(message.message_id)
    
    logger.info(f"[REPORT] Этап 4: Задан вопрос о комментариях для пользователя {user_id}, переход в состояние REPORT_COMMENTS")
    return REPORT_COMMENTS

async def report_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка комментариев и завершение отчета - этап 4"""
    user_id = update.effective_user.id
    message_text = update.message.text or update.message.caption or ""
    
    logger.info(f"[REPORT] Этап 4: Получены комментарии от пользователя {user_id}")
    
    if not message_text.strip():
        await update.message.reply_text("❌ Пожалуйста, введите текст.")
        return REPORT_COMMENTS
    
    report_data = context.user_data.get('report_data', {})
    if not report_data:
        logger.error(f"[REPORT] Ошибка: report_data не найден для пользователя {user_id}")
        await update.message.reply_text("❌ Ошибка: данные отчета потеряны. Начните заново с /report")
        return END
    
    report_data['comments'] = message_text.strip()
    
    # Убираем кнопку отмены из предыдущего сообщения
    if report_data.get('message_ids'):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.message.chat_id,
                message_id=report_data['message_ids'][-1],
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении кнопки отмены: {e}")
    
    # Отправляем финальное сообщение пользователю
    final_message = "⚫️ Ваше сообщение принято Тёмной Стороной. Спасибо! ⚫️\n\n"
    final_message += "⚡️⭐ Да пребудет с тобой Сила ⭐⚡️"
    
    await update.message.reply_text(final_message)
    
    # Формируем и отправляем отчет администраторам
    user = update.effective_user
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username or f"ID: {user_id}"
    user_link = f"[{user_name}](tg://user?id={user_id})"
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    admin_message = f"📋 **Новый отчет о проблеме**\n\n"
    admin_message += f"👤 Отправитель: {user_link}\n"
    admin_message += f"🕐 Время: {current_time}\n\n"
    admin_message += f"**1️⃣ Провайдер:**\n{report_data['provider']}\n\n"
    admin_message += f"**2️⃣ Устройство:**\n{report_data['device']}\n\n"
    admin_message += f"**3️⃣ Комментарии:**\n{report_data['comments']}"
    
    # Отправляем всем администраторам
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message,
                parse_mode='Markdown'
            )
            logger.info(f"[REPORT] Отчет отправлен администратору {admin_id}")
        except Exception as e:
            logger.error(f"[REPORT] Ошибка отправки отчета администратору {admin_id}: {e}")
    
    # Очищаем данные отчета
    context.user_data.pop('report_data', None)
    
    logger.info(f"[REPORT] Этап 5: Отчет завершен для пользователя {user_id}")
    
    # Показываем главное меню
    await show_menu_by_user_id(context.bot, user_id, update.message.chat_id)
    
    return END

async def report_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена создания отчета"""
    query = update.callback_query
    await query.answer("Отчет отменен")
    
    user_id = query.from_user.id
    logger.info(f"[REPORT] Отмена отчета от пользователя {user_id}")
    
    report_data = context.user_data.get('report_data', {})
    message_ids = report_data.get('message_ids', [])
    
    # Удаляем кнопки отмены из всех сообщений
    for msg_id in message_ids:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=query.message.chat_id,
                message_id=msg_id,
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении кнопки отмены: {e}")
    
    context.user_data.pop('report_data', None)
    await show_menu_from_callback(query, context)
    return END

# ==================== МОНИТОРИНГ ====================

def format_new_client_message(client: Dict) -> str:
    """Форматировать информацию о новом клиенте для сообщения"""
    client_id = client.get('id', 'Неизвестно')
    email = client.get('email', 'Неизвестно')
    
    # Получаем информацию о трафике
    total = client.get('total', 0)
    if total == 0:
        traffic_info = "♾️ Unlimited(Reset)"
    else:
        traffic_gb = db_manager.bytes_to_gb(total)
        traffic_info = f"{round(traffic_gb, 3)}GB"
    
    # Получаем дату исчерпания
    expiry_time = client.get('expiryTime', 0)
    if expiry_time == 0:
        expiry_info = "♾️ Безлимит"
    else:
        expiry_date = datetime.fromtimestamp(expiry_time / 1000)
        expiry_info = expiry_date.strftime("%Y-%m-%d %H:%M:%S")
    
    # Получаем комментарий
    comment = client.get('comment', '')
    if not comment:
        comment = 'Нет комментария'
    
    # Получаем remark инбаунда
    inbound_remark = db_manager.get_inbound_remark()
    
    message = f"🔄 Инбаунды: {inbound_remark}\n\n"
    message += f"🔑 ID: {client_id}\n"
    message += f"📧 Email: {email}\n"
    message += f"📊 Трафик: {traffic_info}\n"
    message += f"📅 Дата исчерпания: {expiry_info}\n"
    message += f"💬 Комментарий: {comment}"
    
    return message

async def monitor_database_changes(application: Application) -> None:
    """Мониторинг изменений в БД и отправка уведомлений"""
    global monitoring_active, last_configs, last_clients
    
    monitoring_active = True
    logger.info("Запуск мониторинга изменений БД...")
    
    # Инициализируем начальное состояние
    last_configs = db_manager.get_all_user_configs()
    last_clients = db_manager.get_all_clients()
    
    while monitoring_active:
        try:
            # Проверяем изменения конфигов
            changed_configs = db_manager.check_config_changes(last_configs)
            
            # Отправляем уведомления о изменениях конфигов
            for tg_id, updated_configs in changed_configs.items():
                for config_data in updated_configs:
                    email = config_data['email']
                    config = config_data['config']
                    
                    message = f"🚨 Конфиг для {email} был обновлён\n\n"
                    message += f"```\n{config}\n```"
                    
                    # Добавляем кнопку "Меню"
                    keyboard = [[InlineKeyboardButton("📋 Меню", callback_data="menu_from_config")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    try:
                        await application.bot.send_message(
                            chat_id=tg_id,
                            text=message,
                            parse_mode='Markdown',
                            reply_markup=reply_markup
                        )
                        logger.info(f"Отправлено уведомление об обновлении конфига для {email} (TG ID: {tg_id})")
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления для {tg_id}: {e}")
            
            # Проверяем новых клиентов
            new_clients = db_manager.check_new_clients(last_clients)
            
            # Отправляем уведомления о новых клиентах администраторам
            for new_client in new_clients:
                client_info = format_new_client_message(new_client)
                client_email = new_client.get('email', '')
                client_id = new_client.get('id', '')
                
                # Добавляем кнопку "Конфиг"
                keyboard = [[InlineKeyboardButton("🔑 Конфиг", callback_data=f"admin_config_{client_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Отправляем всем администраторам
                for admin_id in ADMIN_IDS:
                    try:
                        await application.bot.send_message(
                            chat_id=admin_id,
                            text=client_info,
                            reply_markup=reply_markup
                        )
                        logger.info(f"Отправлено уведомление о новом клиенте {client_email} администратору {admin_id}")
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления о новом клиенте администратору {admin_id}: {e}")
            
            # Обновляем состояние
            if changed_configs:
                last_configs = db_manager.get_all_user_configs()
                logger.info(f"Обнаружены изменения в конфигах: {len(changed_configs)} пользователей")
            
            if new_clients:
                last_clients = db_manager.get_all_clients()
                logger.info(f"Обнаружены новые клиенты: {len(new_clients)}")
            
            # Ждем перед следующей проверкой
            await asyncio.sleep(30)  # Проверяем каждые 30 секунд
            
        except Exception as e:
            logger.error(f"Ошибка в мониторинге БД: {e}")
            await asyncio.sleep(60)  # При ошибке ждем дольше

def main() -> None:
    """Основная функция для запуска бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики команд (ВАЖНО: перед ConversationHandler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    
    # ConversationHandler для рассылки
    # Fallbacks обрабатывают кнопки во ВСЕХ состояниях ConversationHandler
    mail_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("mail", mail_start)],
        states={
            MAIL_WAITING_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, mail_receive_message)
            ],
            MAIL_CONFIRM: [
                # В состоянии подтверждения обрабатываем все callback queries
                CallbackQueryHandler(mail_handle_confirm_button),
            ],
        },
        fallbacks=[
            # Обрабатываем кнопку отмены на первом этапе
            CallbackQueryHandler(mail_cancel_handler, pattern="^mail_cancel$"),
        ],
        per_message=False,
    )
    application.add_handler(mail_conv_handler)
    
    # ConversationHandler для отчета
    report_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("report", report_start)],
        states={
            REPORT_PROVIDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, report_provider)
            ],
            REPORT_DEVICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, report_device)
            ],
            REPORT_COMMENTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, report_comments)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(report_cancel_handler, pattern="^report_cancel$"),
        ],
        per_message=False,  # Изменено на False для правильной работы CallbackQueryHandler
    )
    application.add_handler(report_conv_handler)
    
    # Добавляем обработчик кнопок (должен быть после ConversationHandler)
    # Обрабатывает только кнопки, не связанные с диалогами
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
