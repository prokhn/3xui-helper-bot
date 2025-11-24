import sqlite3
import json
import os
import time
import uuid
from dotenv import load_dotenv

load_dotenv()

class DatabaseTester:
    def __init__(self):
        self.db_path = os.getenv('DB_PATH')
        if not self.db_path:
            raise ValueError("DB_PATH не найден в переменных окружения!")
    
    def get_connection(self):
        """Получить соединение с БД"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_current_sni(self):
        """Получить текущий SNI из БД"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT stream_settings FROM inbounds LIMIT 1")
                row = cursor.fetchone()
                if row and row['stream_settings']:
                    stream_settings = json.loads(row['stream_settings'])
                    reality_settings = stream_settings.get('realitySettings', {})
                    server_names = reality_settings.get('serverNames', [])
                    return server_names[0] if server_names else None
        except Exception as e:
            print(f"Ошибка при получении SNI: {e}")
        return None
    
    def get_inbound_settings(self):
        """Получить текущие настройки инбаунда"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT settings FROM inbounds LIMIT 1")
                row = cursor.fetchone()
                if row and row['settings']:
                    return json.loads(row['settings'])
        except Exception as e:
            print(f"Ошибка при получении настроек инбаунда: {e}")
        return None
    
    def get_existing_clients(self):
        """Получить список существующих клиентов"""
        settings = self.get_inbound_settings()
        if settings and 'clients' in settings:
            return settings['clients']
        return []
    
    def create_test_client(self, email=None, tg_id=None, total=0, expiry_time=0, comment="Тестовый клиент"):
        """Создать тестового клиента"""
        try:
            with self.get_connection() as conn:
                # Получаем текущие настройки
                cursor = conn.execute("SELECT settings FROM inbounds LIMIT 1")
                row = cursor.fetchone()
                
                if not row or not row['settings']:
                    print("❌ Не найдены settings в БД")
                    return False
                
                # Парсим JSON
                settings = json.loads(row['settings'])
                
                # Инициализируем массив клиентов, если его нет
                if 'clients' not in settings:
                    settings['clients'] = []
                
                # Генерируем уникальный email, если не указан
                if not email:
                    email = f"test_{int(time.time())}@test.com"
                
                # Проверяем, не существует ли уже клиент с таким email
                existing_emails = {client.get('email', '') for client in settings['clients']}
                if email in existing_emails:
                    print(f"❌ Клиент с email {email} уже существует")
                    return False
                
                # Генерируем UUID для клиента
                client_id = str(uuid.uuid4())
                
                # Создаем нового клиента
                new_client = {
                    'id': client_id,
                    'email': email,
                    'enable': True,
                    'total': total,  # 0 = безлимит
                    'expiryTime': expiry_time,  # 0 = безлимит
                    'limitIp': 0,  # 0 = безлимит
                    'flow': 'xtls-rprx-vision',
                    'comment': comment
                }
                
                # Добавляем tgId, если указан
                if tg_id:
                    new_client['tgId'] = int(tg_id)
                
                # Добавляем клиента в массив
                settings['clients'].append(new_client)
                
                # Обновляем БД
                new_settings = json.dumps(settings)
                conn.execute(
                    "UPDATE inbounds SET settings = ? WHERE id = (SELECT id FROM inbounds LIMIT 1)",
                    (new_settings,)
                )
                conn.commit()
                
                print(f"✅ Тестовый клиент успешно создан!")
                print(f"   📧 Email: {email}")
                print(f"   🔑 ID: {client_id}")
                if tg_id:
                    print(f"   👤 Telegram ID: {tg_id}")
                print(f"   📊 Трафик: {'Безлимит' if total == 0 else f'{total / (1024**3):.2f} GB'}")
                print(f"   📅 Срок действия: {'Безлимит' if expiry_time == 0 else 'Ограничен'}")
                print(f"   💬 Комментарий: {comment}")
                
                return True
                
        except Exception as e:
            print(f"❌ Ошибка при создании клиента: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def list_clients(self):
        """Показать список всех клиентов"""
        clients = self.get_existing_clients()
        if not clients:
            print("📋 Клиенты не найдены")
            return
        
        print(f"\n📋 Найдено клиентов: {len(clients)}\n")
        for i, client in enumerate(clients, 1):
            email = client.get('email', 'Неизвестно')
            client_id = client.get('id', 'Неизвестно')
            tg_id = client.get('tgId', 'Не указан')
            total = client.get('total', 0)
            expiry = client.get('expiryTime', 0)
            comment = client.get('comment', 'Нет комментария')
            
            print(f"{i}. 📧 {email}")
            print(f"   🔑 ID: {client_id[:8]}...")
            print(f"   👤 TG ID: {tg_id}")
            print(f"   📊 Трафик: {'Безлимит' if total == 0 else f'{total / (1024**3):.2f} GB'}")
            print(f"   📅 Срок: {'Безлимит' if expiry == 0 else 'Ограничен'}")
            print(f"   💬 {comment}")
            print()
    
    def delete_client(self, email=None, client_id=None):
        """Удалить клиента по email или ID"""
        try:
            with self.get_connection() as conn:
                # Получаем текущие настройки
                cursor = conn.execute("SELECT settings FROM inbounds LIMIT 1")
                row = cursor.fetchone()
                
                if not row or not row['settings']:
                    print("❌ Не найдены settings в БД")
                    return False
                
                # Парсим JSON
                settings = json.loads(row['settings'])
                
                # Инициализируем массив клиентов, если его нет
                if 'clients' not in settings:
                    settings['clients'] = []
                
                # Ищем клиента для удаления
                client_to_delete = None
                for client in settings['clients']:
                    if email and client.get('email') == email:
                        client_to_delete = client
                        break
                    elif client_id and client.get('id') == client_id:
                        client_to_delete = client
                        break
                
                if not client_to_delete:
                    identifier = email or client_id or "неизвестно"
                    print(f"❌ Клиент {identifier} не найден")
                    return False
                
                # Удаляем клиента из массива
                settings['clients'] = [c for c in settings['clients'] if c != client_to_delete]
                
                # Обновляем БД
                new_settings = json.dumps(settings)
                conn.execute(
                    "UPDATE inbounds SET settings = ? WHERE id = (SELECT id FROM inbounds LIMIT 1)",
                    (new_settings,)
                )
                conn.commit()
                
                deleted_email = client_to_delete.get('email', 'Неизвестно')
                deleted_id = client_to_delete.get('id', 'Неизвестно')
                print(f"✅ Клиент успешно удален!")
                print(f"   📧 Email: {deleted_email}")
                print(f"   🔑 ID: {deleted_id}")
                
                return True
                
        except Exception as e:
            print(f"❌ Ошибка при удалении клиента: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def change_sni(self, new_sni="example.com"):
        """Изменить SNI в БД"""
        try:
            with self.get_connection() as conn:
                # Получаем текущие настройки
                cursor = conn.execute("SELECT stream_settings FROM inbounds LIMIT 1")
                row = cursor.fetchone()
                
                if not row or not row['stream_settings']:
                    print("❌ Не найдены stream_settings в БД")
                    return False
                
                # Парсим JSON
                stream_settings = json.loads(row['stream_settings'])
                
                # Обновляем SNI
                if 'realitySettings' not in stream_settings:
                    stream_settings['realitySettings'] = {}
                
                if 'serverNames' not in stream_settings['realitySettings']:
                    stream_settings['realitySettings']['serverNames'] = []
                
                # Устанавливаем новый SNI
                stream_settings['realitySettings']['serverNames'] = [new_sni]
                
                # Обновляем БД
                new_stream_settings = json.dumps(stream_settings)
                conn.execute(
                    "UPDATE inbounds SET stream_settings = ? WHERE id = (SELECT id FROM inbounds LIMIT 1)",
                    (new_stream_settings,)
                )
                conn.commit()
                
                print(f"✅ SNI успешно изменен на: {new_sni}")
                return True
                
        except Exception as e:
            print(f"❌ Ошибка при изменении SNI: {e}")
            return False
    
    def restore_original_sni(self, original_sni):
        """Восстановить оригинальный SNI"""
        if original_sni:
            return self.change_sni(original_sni)
        return False
    
    def test_monitoring(self):
        """Тестировать мониторинг изменений"""
        print("🔍 Тестирование мониторинга изменений БД...")
        
        # Получаем текущий SNI
        original_sni = self.get_current_sni()
        print(f"📋 Текущий SNI: {original_sni}")
        
        if not original_sni:
            print("❌ Не удалось получить текущий SNI")
            return
        
        # Меняем SNI
        print("\n🔄 Изменяем SNI на example.com...")
        if self.change_sni("example.com"):
            print("✅ SNI изменен! Бот должен отправить уведомление.")
            print("⏳ Ждем 5 секунд...")
            time.sleep(5)
            
            # Возвращаем оригинальный SNI
            print(f"\n🔄 Возвращаем оригинальный SNI: {original_sni}")
            if self.restore_original_sni(original_sni):
                print("✅ SNI восстановлен! Бот должен отправить еще одно уведомление.")
            else:
                print("❌ Не удалось восстановить SNI")
        else:
            print("❌ Не удалось изменить SNI")

def main():
    """Основная функция"""
    print("🧪 Тестовый скрипт для проверки мониторинга БД")
    print("=" * 50)
    
    try:
        tester = DatabaseTester()
        
        while True:
            print("\nВыберите действие:")
            print("1. Показать текущий SNI")
            print("2. Изменить SNI на example.com")
            print("3. Изменить SNI на custom значение")
            print("4. Тестировать мониторинг (автоматически)")
            print("5. Показать список клиентов")
            print("6. Создать тестового клиента")
            print("7. Удалить клиента")
            print("8. Выход")
            
            choice = input("\nВведите номер (1-8): ").strip()
            
            if choice == "1":
                sni = tester.get_current_sni()
                print(f"📋 Текущий SNI: {sni}")
            
            elif choice == "2":
                tester.change_sni("example.com")
            
            elif choice == "3":
                custom_sni = input("Введите новый SNI: ").strip()
                if custom_sni:
                    tester.change_sni(custom_sni)
                else:
                    print("❌ Пустое значение SNI")
            
            elif choice == "4":
                tester.test_monitoring()
            
            elif choice == "5":
                tester.list_clients()
            
            elif choice == "6":
                print("\n📝 Создание тестового клиента")
                print("(Нажмите Enter для значений по умолчанию)")
                
                email = input("Email (по умолчанию: auto-generated): ").strip()
                if not email:
                    email = None
                
                tg_id = input("Telegram ID (по умолчанию: не указывать): ").strip()
                if not tg_id:
                    tg_id = None
                else:
                    try:
                        tg_id = int(tg_id)
                    except ValueError:
                        print("❌ Неверный формат Telegram ID")
                        continue
                
                total_input = input("Лимит трафика в GB (0 = безлимит, по умолчанию: 0): ").strip()
                total = 0
                if total_input:
                    try:
                        total_gb = float(total_input)
                        total = int(total_gb * (1024 ** 3))  # Конвертируем в байты
                    except ValueError:
                        print("❌ Неверный формат лимита трафика")
                        continue
                
                expiry_input = input("Срок действия в днях (0 = безлимит, по умолчанию: 0): ").strip()
                expiry_time = 0
                if expiry_input:
                    try:
                        days = int(expiry_input)
                        if days > 0:
                            expiry_time = int((time.time() + days * 24 * 60 * 60) * 1000)  # Конвертируем в миллисекунды
                    except ValueError:
                        print("❌ Неверный формат срока действия")
                        continue
                
                comment = input("Комментарий (по умолчанию: 'Тестовый клиент'): ").strip()
                if not comment:
                    comment = "Тестовый клиент"
                
                tester.create_test_client(email=email, tg_id=tg_id, total=total, expiry_time=expiry_time, comment=comment)
            
            elif choice == "7":
                print("\n🗑️ Удаление клиента")
                print("Выберите способ удаления:")
                print("1. По email")
                print("2. По ID")
                print("3. Выбрать из списка")
                
                delete_choice = input("\nВведите номер (1-3): ").strip()
                
                if delete_choice == "1":
                    email = input("Введите email клиента: ").strip()
                    if email:
                        tester.delete_client(email=email)
                    else:
                        print("❌ Email не может быть пустым")
                
                elif delete_choice == "2":
                    client_id = input("Введите ID клиента: ").strip()
                    if client_id:
                        tester.delete_client(client_id=client_id)
                    else:
                        print("❌ ID не может быть пустым")
                
                elif delete_choice == "3":
                    clients = tester.get_existing_clients()
                    if not clients:
                        print("❌ Клиенты не найдены")
                        continue
                    
                    print("\n📋 Список клиентов:")
                    for i, client in enumerate(clients, 1):
                        email = client.get('email', 'Неизвестно')
                        client_id = client.get('id', 'Неизвестно')
                        comment = client.get('comment', 'Нет комментария')
                        print(f"{i}. 📧 {email} (ID: {client_id[:8]}...) - {comment}")
                    
                    try:
                        index = int(input("\nВведите номер клиента для удаления: ").strip())
                        if 1 <= index <= len(clients):
                            selected_client = clients[index - 1]
                            email = selected_client.get('email')
                            tester.delete_client(email=email)
                        else:
                            print("❌ Неверный номер")
                    except ValueError:
                        print("❌ Неверный формат номера")
                else:
                    print("❌ Неверный выбор")
            
            elif choice == "8":
                print("👋 До свидания!")
                break
            
            else:
                print("❌ Неверный выбор")
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
