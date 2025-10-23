import sqlite3
import json
import os
import time
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
            print("5. Выход")
            
            choice = input("\nВведите номер (1-5): ").strip()
            
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
                print("👋 До свидания!")
                break
            
            else:
                print("❌ Неверный выбор")
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    main()
