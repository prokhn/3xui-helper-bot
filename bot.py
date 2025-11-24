import os
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
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

def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором"""
    return user_id in ADMIN_IDS

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
            message += f"🔼 Исходящий трафик: ↑{client_data['up_gb']}GB\n"
            message += f"🔽 Входящий трафик: ↓{client_data['down_gb']}GB\n"
            message += f"📊 Всего: ↑↓{client_data['total_gb']}GB"
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
    
    # Создаем кнопки для первого клиента (если есть)
    if menu_data:
        first_email = menu_data[0]['email']
        keyboard = [
            [InlineKeyboardButton("📄 Мой конфиг", callback_data=f"config_{first_email}")],
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{first_email}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(full_message, parse_mode='Markdown', reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки"""
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
        
        # Обновляем данные и показываем меню
        await show_menu_from_callback(query)
    
    elif query.data == "menu":
        # Возвращаемся в меню
        await show_menu_from_callback(query)
    
    elif query.data == "cancel_mail":
        # Отмена рассылки
        context.user_data.pop('mail_mode', None)
        await query.answer("Рассылка отменена")
        await show_menu_from_callback(query)
    
    elif query.data == "cancel_report":
        # Отмена отчета
        report_data = context.user_data.get('report_data', {})
        message_ids = report_data.get('message_ids', [])
        
        # Удаляем кнопки отмены из всех сообщений
        for msg_id in message_ids:
            try:
                await query.bot.edit_message_reply_markup(
                    chat_id=query.message.chat_id,
                    message_id=msg_id,
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"Ошибка при удалении кнопки отмены: {e}")
        
        # Очищаем данные отчета
        context.user_data.pop('report_data', None)
        await query.answer("Отчет отменен")
        await show_menu_from_callback(query)

async def show_menu_from_callback(query) -> None:
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
            message += f"🔼 Исходящий трафик: ↑{client_data['up_gb']}GB\n"
            message += f"🔽 Входящий трафик: ↓{client_data['down_gb']}GB\n"
            message += f"📊 Всего: ↑↓{client_data['total_gb']}GB"
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
    
    # Создаем кнопки для первого клиента (если есть)
    if menu_data:
        first_email = menu_data[0]['email']
        keyboard = [
            [InlineKeyboardButton("📄 Мой конфиг", callback_data=f"config_{first_email}")],
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{first_email}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(full_message, parse_mode='Markdown', reply_markup=reply_markup)

async def mail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /mail - режим рассылки"""
    user_id = update.effective_user.id
    
    # Проверяем права администратора
    if not is_admin(user_id):
        await update.message.reply_text("❌ Извините, у вас нет прав на выполнение этой команды.")
        return
    
    # Активируем режим рассылки
    context.user_data['mail_mode'] = True
    
    message = "📢 Режим рассылки активирован\n\n"
    message += "Введите ваше сообщение для рассылки всем пользователям."
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_mail")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup)

async def handle_mail_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик сообщения в режиме рассылки"""
    user_id = update.effective_user.id
    
    # Проверяем, активен ли режим рассылки
    mail_mode = context.user_data.get('mail_mode', False)
    if not mail_mode:
        return
    
    logger.info(f"Обработка сообщения для рассылки от пользователя {user_id}")
    
    # Проверяем права администратора
    if not is_admin(user_id):
        context.user_data.pop('mail_mode', None)
        return
    
    # Получаем текст сообщения
    message_text = update.message.text or update.message.caption or ""
    
    if not message_text.strip():
        await update.message.reply_text("❌ Сообщение не может быть пустым. Попробуйте еще раз.")
        return
    
    # Отключаем режим рассылки
    context.user_data.pop('mail_mode', None)
    
    # Отправляем сообщение о начале рассылки
    await update.message.reply_text("⏳ Начинаю рассылку...")
    
    # Получаем все уникальные telegram ID пользователей
    telegram_ids = db_manager.get_all_unique_telegram_ids()
    
    await update.message.reply_text(f"🔍 Рассылка для {len(telegram_ids)} пользователей")

    if not telegram_ids:
        await update.message.reply_text("❌ Не найдено пользователей для рассылки.")
        return
    
    # Выполняем рассылку
    success_count = 0
    failed_count = 0
    
    # Формируем сообщение с подписью
    message_with_signature = f"⚫️ Тёмная Сторона сообщает:\n\n{message_text}"
    
    for tg_id in telegram_ids:
        try:
            await context.bot.send_message(
                chat_id=tg_id,
                text=message_with_signature
            )
            success_count += 1
            logger.info(f"Сообщение успешно отправлено пользователю {tg_id}")
        except Exception as e:
            failed_count += 1
            logger.error(f"Ошибка отправки сообщения пользователю {tg_id}: {e}")
    
    # Отправляем статистику администратору
    stats_message = "✅ Рассылка завершена!\n\n"
    stats_message += f"📊 Статистика:\n"
    stats_message += f"✅ Успешно отправлено: {success_count}\n"
    stats_message += f"❌ Ошибок: {failed_count}\n"
    stats_message += f"📈 Всего пользователей: {len(telegram_ids)}"
    
    await update.message.reply_text(stats_message)

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /report - создание отчета о проблеме"""
    user_id = update.effective_user.id
    
    # Проверяем авторизацию
    if not db_manager.is_user_authorized(user_id):
        await update.message.reply_text("❌ Вы не авторизованы. Обратитесь к администратору.")
        return
    
    # Инициализируем данные отчета
    context.user_data['report_data'] = {
        'provider': None,
        'device': None,
        'comments': None,
        'message_ids': []
    }
    
    # Задаем первый вопрос
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="cancel_report")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.message.reply_text(
        "📝 Создание отчета о проблеме\n\n1️⃣ Ваш провайдер:",
        reply_markup=reply_markup
    )
    
    # Сохраняем ID сообщения
    context.user_data['report_data']['message_ids'].append(message.message_id)
    context.user_data['report_data']['current_step'] = 'provider'

async def handle_report_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик сообщений в режиме создания отчета"""
    user_id = update.effective_user.id
    
    # Проверяем, активен ли режим создания отчета
    report_data = context.user_data.get('report_data')
    if not report_data:
        return
    
    current_step = report_data.get('current_step')
    if not current_step:
        return
    
    message_text = update.message.text or update.message.caption or ""
    
    if not message_text.strip():
        await update.message.reply_text("❌ Пожалуйста, введите текст.")
        return
    
    # Сохраняем ответ в зависимости от текущего шага
    if current_step == 'provider':
        report_data['provider'] = message_text.strip()
        report_data['current_step'] = 'device'
        
        # Убираем кнопку отмены из предыдущего сообщения
        if report_data['message_ids']:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=update.message.chat_id,
                    message_id=report_data['message_ids'][-1],
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"Ошибка при удалении кнопки отмены: {e}")
        
        # Задаем второй вопрос
        keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="cancel_report")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await update.message.reply_text(
            "2️⃣ Устройство - телефон или ПК:",
            reply_markup=reply_markup
        )
        report_data['message_ids'].append(message.message_id)
    
    elif current_step == 'device':
        report_data['device'] = message_text.strip()
        report_data['current_step'] = 'comments'
        
        # Убираем кнопку отмены из предыдущего сообщения
        if report_data['message_ids']:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=update.message.chat_id,
                    message_id=report_data['message_ids'][-1],
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"Ошибка при удалении кнопки отмены: {e}")
        
        # Задаем третий вопрос
        keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="cancel_report")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await update.message.reply_text(
            "3️⃣ Комментарии - что работает, когда сломалось, что не открывается:",
            reply_markup=reply_markup
        )
        report_data['message_ids'].append(message.message_id)
    
    elif current_step == 'comments':
        report_data['comments'] = message_text.strip()
        
        # Убираем кнопку отмены из предыдущего сообщения
        if report_data['message_ids']:
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
                logger.info(f"Отчет отправлен администратору {admin_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки отчета администратору {admin_id}: {e}")
        
        # Очищаем данные отчета
        context.user_data.pop('report_data', None)

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
    application.add_handler(CommandHandler("mail", mail))
    application.add_handler(CommandHandler("report", report))
    
    # Добавляем обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Добавляем обработчики сообщений (должны быть после других обработчиков)
    # Сначала обработчик рассылки, потом отчета (рассылка - одно сообщение, отчет - многошаговый)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_mail_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_report_message))
    
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
