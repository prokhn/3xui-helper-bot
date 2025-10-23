import sqlite3
import json
import os
import hashlib
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

class DatabaseManager:
    def __init__(self):
        self.db_path = os.getenv('DB_PATH')
        if not self.db_path:
            raise ValueError("DB_PATH не найден в переменных окружения!")
    
    def get_connection(self):
        """Получить соединение с БД (read-only для избежания блокировок)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Для доступа к колонкам по имени
        return conn
    
    def get_inbound_data(self) -> Optional[Dict]:
        """Получить данные первого inbound (settings, listen, port, remark, stream_settings)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT settings, listen, port, remark, stream_settings FROM inbounds LIMIT 1")
                row = cursor.fetchone()
                if row:
                    inbound_data = {
                        'settings': json.loads(row['settings']) if row['settings'] else {},
                        'listen': row['listen'],
                        'port': row['port'],
                        'remark': row['remark'],
                        'stream_settings': json.loads(row['stream_settings']) if row['stream_settings'] else {}
                    }
                    return inbound_data
        except Exception as e:
            print(f"Ошибка при чтении inbound данных: {e}")
        return None
    
    def get_user_clients(self, telegram_id: int) -> List[Dict]:
        """Получить всех клиентов для данного Telegram ID"""
        inbound_data = self.get_inbound_data()
        if not inbound_data or 'clients' not in inbound_data.get('settings', {}):
            return []
        
        user_clients = []
        for client in inbound_data['settings']['clients']:
            if client.get('tgId') == telegram_id:
                user_clients.append(client)
        
        return user_clients
    
    def get_traffic_stats(self, email: str) -> Optional[Tuple[int, int]]:
        """Получить статистику трафика для email (up, down в байтах)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT up, down FROM client_traffics WHERE email = ?", 
                    (email,)
                )
                row = cursor.fetchone()
                if row:
                    return (row['up'], row['down'])
        except Exception as e:
            print(f"Ошибка при чтении статистики трафика: {e}")
        return None
    
    def is_user_authorized(self, telegram_id: int) -> bool:
        """Проверить авторизован ли пользователь"""
        return len(self.get_user_clients(telegram_id)) > 0
    
    def bytes_to_gb(self, bytes_value: int) -> float:
        """Конвертировать байты в гигабайты"""
        return round(bytes_value / (1024 ** 3), 2)
    
    def generate_vless_config(self, client: Dict) -> str:
        """Сгенерировать VLESS конфиг для клиента"""
        try:
            inbound_data = self.get_inbound_data()
            if not inbound_data:
                return "Ошибка получения данных сервера"
            
            # Извлекаем данные из inbound_data
            listen = inbound_data.get('listen', '0.0.0.0')
            port = str(inbound_data.get('port', ''))
            remark = inbound_data.get('remark', '')
            
            stream_settings = inbound_data.get('stream_settings', {})
            network = stream_settings.get('network', 'tcp')
            security = stream_settings.get('security', 'none')
            
            settings = stream_settings.get('settings', {})
            public_key = settings.get('publicKey', '')
            fingerprint = settings.get('fingerprint', '')
            
            reality_settings = stream_settings.get('realitySettings', {})
            server_name = reality_settings.get('serverNames', [''])[0]
            short_id = reality_settings.get('shortIds', [''])[0]
            
            # Данные клиента
            client_id = client.get('id', '')
            email = client.get('email', '')
            flow = 'xtls-rprx-vision'
            
            # Формируем конфиг
            config = f"vless://{client_id}@{listen}:{port}?type={network}&security={security}&pbk={public_key}&fp={fingerprint}&sni={server_name}&sid={short_id}&spx=%2F&flow={flow}#{remark}-{email}"
            
            return config
            
        except Exception as e:
            print(f"Ошибка при генерации конфига: {e}")
            return "Ошибка генерации конфига"
    
    # Публичные методы для бота
    def get_user_menu_data(self, telegram_id: int) -> List[Dict]:
        """Получить данные для меню пользователя"""
        user_clients = self.get_user_clients(telegram_id)
        menu_data = []
        
        for client in user_clients:
            email = client.get('email', 'Неизвестно')
            traffic_stats = self.get_traffic_stats(email)
            
            client_data = {
                'email': email,
                'client': client,
                'traffic_stats': traffic_stats
            }
            
            if traffic_stats:
                up_bytes, down_bytes = traffic_stats
                client_data['up_gb'] = self.bytes_to_gb(up_bytes)
                client_data['down_gb'] = self.bytes_to_gb(down_bytes)
                client_data['total_gb'] = client_data['up_gb'] + client_data['down_gb']
            
            menu_data.append(client_data)
        
        return menu_data
    
    def get_client_config(self, telegram_id: int, email: str) -> Optional[str]:
        """Получить конфиг для конкретного клиента"""
        user_clients = self.get_user_clients(telegram_id)
        
        for client in user_clients:
            if client.get('email') == email:
                return self.generate_vless_config(client)
        
        return None
    
    def get_database_hash(self) -> str:
        """Получить хеш текущего состояния БД для мониторинга изменений"""
        try:
            with self.get_connection() as conn:
                # Получаем данные из обеих таблиц
                inbound_cursor = conn.execute("SELECT settings, listen, port, remark, stream_settings FROM inbounds LIMIT 1")
                inbound_row = inbound_cursor.fetchone()
                
                traffic_cursor = conn.execute("SELECT email, up, down FROM client_traffics")
                traffic_rows = traffic_cursor.fetchall()
                
                # Создаем строку для хеширования
                data_string = ""
                
                if inbound_row:
                    data_string += f"inbound:{inbound_row['settings']}:{inbound_row['listen']}:{inbound_row['port']}:{inbound_row['remark']}:{inbound_row['stream_settings']}"
                
                for row in traffic_rows:
                    data_string += f"traffic:{row['email']}:{row['up']}:{row['down']}"
                
                # Возвращаем MD5 хеш
                return hashlib.md5(data_string.encode('utf-8')).hexdigest()
                
        except Exception as e:
            print(f"Ошибка при получении хеша БД: {e}")
            return ""
    
    def get_all_user_configs(self) -> Dict[int, List[Dict]]:
        """Получить все конфиги всех пользователей для мониторинга изменений"""
        try:
            inbound_data = self.get_inbound_data()
            if not inbound_data or 'clients' not in inbound_data.get('settings', {}):
                return {}
            
            user_configs = {}
            
            for client in inbound_data['settings']['clients']:
                tg_id = client.get('tgId')
                if tg_id:
                    if tg_id not in user_configs:
                        user_configs[tg_id] = []
                    
                    config_data = {
                        'email': client.get('email', ''),
                        'config': self.generate_vless_config(client),
                        'client_id': client.get('id', ''),
                        'client_data': client
                    }
                    user_configs[tg_id].append(config_data)
            
            return user_configs
            
        except Exception as e:
            print(f"Ошибка при получении всех конфигов: {e}")
            return {}
    
    def check_config_changes(self, old_configs: Dict[int, List[Dict]]) -> Dict[int, List[Dict]]:
        """Проверить изменения в конфигах и вернуть обновленные"""
        current_configs = self.get_all_user_configs()
        changed_configs = {}
        
        for tg_id, current_user_configs in current_configs.items():
            old_user_configs = old_configs.get(tg_id, [])
            
            # Проверяем изменения для каждого email пользователя
            for current_config in current_user_configs:
                email = current_config['email']
                
                # Ищем соответствующий старый конфиг
                old_config = None
                for old_cfg in old_user_configs:
                    if old_cfg['email'] == email:
                        old_config = old_cfg
                        break
                
                # Если конфиг изменился или это новый конфиг
                if not old_config or old_config['config'] != current_config['config']:
                    if tg_id not in changed_configs:
                        changed_configs[tg_id] = []
                    changed_configs[tg_id].append(current_config)
        
        return changed_configs
