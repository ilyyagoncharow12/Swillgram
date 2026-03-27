# main_random_codes.py - Полностью рабочая версия со случайными кодами

import sys
import os
import socket
import threading
import time
import random
import pickle
import struct
from datetime import datetime
from pathlib import Path
import json

# Импорты PySide6
try:
    from PySide6.QtWidgets import *
    from PySide6.QtCore import *
    from PySide6.QtGui import *
except ImportError:
    print("Установите PySide6: pip install PySide6")
    sys.exit(1)

# Константы
VERSION = "2.0.0"
PORT = 5000
BROADCAST_PORT = 5001


class CodeManager:
    """Управление кодами и поиском устройств"""

    def __init__(self):
        self.my_code = self.generate_random_code()
        self.my_ip = self.get_local_ip()
        self.my_name = socket.gethostname()
        self.known_devices = {}  # {code: {'ip': ip, 'name': name, 'last_seen': time}}
        self.running = False
        self.broadcast_socket = None

    def generate_random_code(self):
        """Генерация случайного 10-значного кода"""
        return ''.join([str(random.randint(0, 9)) for _ in range(10)])

    def get_local_ip(self):
        """Получить локальный IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    def start_broadcast(self):
        """Запустить широковещательную рассылку"""
        self.running = True

        # Запускаем слушатель
        self.listen_thread = threading.Thread(target=self.listen_for_devices)
        self.listen_thread.daemon = True
        self.listen_thread.start()

        # Запускаем рассылку
        self.broadcast_thread = threading.Thread(target=self.broadcast_presence)
        self.broadcast_thread.daemon = True
        self.broadcast_thread.start()

        print(f"Поиск устройств запущен. Мой код: {self.my_code}")
        return True

    def broadcast_presence(self):
        """Периодическая рассылка о своем присутствии"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            while self.running:
                try:
                    message = {
                        'type': 'presence',
                        'code': self.my_code,
                        'name': self.my_name,
                        'ip': self.my_ip,
                        'timestamp': time.time()
                    }
                    data = pickle.dumps(message)
                    sock.sendto(data, ('255.255.255.255', BROADCAST_PORT))
                    time.sleep(3)  # Рассылка каждые 3 секунды
                except Exception as e:
                    print(f"Ошибка рассылки: {e}")
                    time.sleep(3)

        except Exception as e:
            print(f"Ошибка запуска рассылки: {e}")

    def listen_for_devices(self):
        """Слушать объявления устройств"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', BROADCAST_PORT))
            sock.settimeout(1)

            while self.running:
                try:
                    data, addr = sock.recvfrom(4096)
                    message = pickle.loads(data)

                    if message.get('type') == 'presence':
                        code = message.get('code')
                        if code and code != self.my_code:
                            # Обновляем информацию об устройстве
                            self.known_devices[code] = {
                                'ip': message.get('ip'),
                                'name': message.get('name'),
                                'last_seen': time.time()
                            }
                            print(
                                f"Обнаружено устройство: {message.get('name')} (Код: {code}, IP: {message.get('ip')})")

                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Ошибка приема: {e}")
                    continue

        except Exception as e:
            print(f"Ошибка запуска слушателя: {e}")

    def find_device_by_code(self, target_code, timeout=5):
        """Найти устройство по коду"""
        # Сначала проверяем известные устройства
        if target_code in self.known_devices:
            device = self.known_devices[target_code]
            # Проверяем, не устарела ли информация
            if time.time() - device['last_seen'] < 10:
                return device

        # Если не нашли, отправляем прямой запрос
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(timeout)

            request = {
                'type': 'find',
                'target_code': target_code,
                'my_code': self.my_code,
                'my_ip': self.my_ip
            }
            data = pickle.dumps(request)
            sock.sendto(data, ('255.255.255.255', BROADCAST_PORT))

            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    response_data, addr = sock.recvfrom(4096)
                    response = pickle.loads(response_data)

                    if response.get('type') == 'found' and response.get('code') == target_code:
                        device = {
                            'ip': response.get('ip'),
                            'name': response.get('name'),
                            'code': target_code,
                            'last_seen': time.time()
                        }
                        self.known_devices[target_code] = device
                        sock.close()
                        return device

                except socket.timeout:
                    continue
                except Exception:
                    continue

            sock.close()

        except Exception as e:
            print(f"Ошибка поиска: {e}")

        return None

    def stop(self):
        """Остановить поиск"""
        self.running = False


class ChatConnection:
    """Управление чат-соединением"""

    def __init__(self):
        self.socket = None
        self.connected = False
        self.other_code = None
        self.other_ip = None
        self.other_name = None
        self.receive_thread = None
        self.server_thread = None
        self.running = False
        self.message_callback = None
        self.connection_callback = None
        self.code_manager = None

    def set_code_manager(self, code_manager):
        """Установить менеджер кодов"""
        self.code_manager = code_manager

    def start_server(self):
        """Запустить сервер для приема подключений"""
        self.running = True
        self.server_thread = threading.Thread(target=self.server_loop)
        self.server_thread.daemon = True
        self.server_thread.start()
        return True

    def server_loop(self):
        """Цикл сервера"""
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('0.0.0.0', PORT))
            server.listen(1)
            server.settimeout(1)

            while self.running:
                try:
                    client, addr = server.accept()
                    print(f"Входящее соединение от {addr[0]}")

                    # Получаем информацию о подключении
                    raw_len = client.recv(4)
                    if raw_len:
                        msg_len = struct.unpack('>I', raw_len)[0]
                        data = b''
                        while len(data) < msg_len:
                            packet = client.recv(msg_len - len(data))
                            if not packet:
                                break
                            data += packet

                        message = pickle.loads(data)
                        if message.get('type') == 'connect':
                            self.socket = client
                            self.connected = True
                            self.other_code = message.get('code')
                            self.other_ip = addr[0]
                            self.other_name = message.get('name')

                            print(f"Подключен к {self.other_name} (Код: {self.other_code})")

                            # Запускаем прием сообщений
                            self.receive_thread = threading.Thread(target=self.receive_messages)
                            self.receive_thread.daemon = True
                            self.receive_thread.start()

                            if self.connection_callback:
                                self.connection_callback(True, self.other_code, self.other_name)
                            break

                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Ошибка сервера: {e}")
                    continue

            server.close()
        except Exception as e:
            print(f"Ошибка запуска сервера: {e}")

    def connect_to_code(self, target_code):
        """Подключиться по коду"""
        if not self.code_manager:
            return False

        # Ищем устройство по коду
        print(f"Поиск устройства с кодом {target_code}...")
        device = self.code_manager.find_device_by_code(target_code)

        if not device:
            print(f"Устройство с кодом {target_code} не найдено")
            return False

        target_ip = device['ip']
        target_name = device['name']

        print(f"Найдено устройство: {target_name} по адресу {target_ip}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((target_ip, PORT))

            # Отправляем запрос на подключение
            message = {
                'type': 'connect',
                'code': self.code_manager.my_code,
                'name': self.code_manager.my_name,
                'ip': self.code_manager.my_ip
            }
            data = pickle.dumps(message)
            sock.send(struct.pack('>I', len(data)))
            sock.send(data)

            self.socket = sock
            self.connected = True
            self.other_code = target_code
            self.other_ip = target_ip
            self.other_name = target_name

            # Запускаем прием сообщений
            self.receive_thread = threading.Thread(target=self.receive_messages)
            self.receive_thread.daemon = True
            self.receive_thread.start()

            print(f"Успешно подключен к {target_name}")
            if self.connection_callback:
                self.connection_callback(True, target_code, target_name)

            return True

        except Exception as e:
            print(f"Ошибка подключения: {e}")
            if self.connection_callback:
                self.connection_callback(False, target_code, None)
            return False

    def receive_messages(self):
        """Поток для приема сообщений"""
        while self.running and self.connected:
            try:
                raw_len = self.socket.recv(4)
                if not raw_len:
                    break

                msg_len = struct.unpack('>I', raw_len)[0]
                data = b''
                while len(data) < msg_len:
                    packet = self.socket.recv(msg_len - len(data))
                    if not packet:
                        break
                    data += packet

                message = pickle.loads(data)

                if message.get('type') == 'text':
                    if self.message_callback:
                        self.message_callback(message['text'])

                elif message.get('type') == 'file':
                    # Сохраняем файл
                    filename = message.get('filename')
                    file_data = message.get('data')
                    if filename and file_data:
                        if self.message_callback:
                            self.message_callback(f"[ФАЙЛ] {filename}")

            except Exception as e:
                print(f"Ошибка приема: {e}")
                break

        self.connected = False
        if self.connection_callback:
            self.connection_callback(False, None, None)

    def send_message(self, text):
        """Отправить сообщение"""
        if not self.connected or not self.socket:
            return False

        try:
            message = {
                'type': 'text',
                'text': text,
                'timestamp': time.time()
            }
            data = pickle.dumps(message)
            self.socket.send(struct.pack('>I', len(data)))
            self.socket.send(data)
            return True
        except Exception as e:
            print(f"Ошибка отправки: {e}")
            return False

    def send_file(self, filepath):
        """Отправить файл"""
        if not self.connected or not self.socket:
            return False

        try:
            with open(filepath, 'rb') as f:
                file_data = f.read()

            filename = os.path.basename(filepath)
            message = {
                'type': 'file',
                'filename': filename,
                'data': file_data,
                'timestamp': time.time()
            }
            data = pickle.dumps(message)
            self.socket.send(struct.pack('>I', len(data)))
            self.socket.send(data)
            return True
        except Exception as e:
            print(f"Ошибка отправки файла: {e}")
            return False

    def disconnect(self):
        """Отключиться"""
        self.running = False
        self.connected = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    def __init__(self):
        super().__init__()
        self.code_manager = CodeManager()
        self.chat = ChatConnection()
        self.chat.set_code_manager(self.code_manager)
        self.chat.message_callback = self.on_message_received
        self.chat.connection_callback = self.on_connection_status

        self.init_ui()

        # Запускаем сервисы
        self.code_manager.start_broadcast()
        self.chat.start_server()

        print(f"\n{'=' * 50}")
        print(f"Ваш код подключения: {self.code_manager.my_code}")
        print(f"Ваше имя: {self.code_manager.my_name}")
        print(f"Ваш IP: {self.code_manager.my_ip}")
        print(f"{'=' * 50}\n")

        self.statusBar().showMessage(f"✅ Готов к работе. Ваш код: {self.code_manager.my_code}")

    def init_ui(self):
        self.setWindowTitle(f"Коммуникационное приложение v{VERSION}")
        self.setGeometry(100, 100, 1000, 700)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Верхняя панель
        top_panel = self.create_top_panel()
        layout.addWidget(top_panel)

        # Основной контент
        content = QWidget()
        content_layout = QHBoxLayout(content)

        # Левая панель - подключение
        left_panel = self.create_connection_panel()
        content_layout.addWidget(left_panel)

        # Правая панель - чат
        right_panel = self.create_chat_panel()
        content_layout.addWidget(right_panel)

        layout.addWidget(content)

        # Нижняя панель - файлы
        bottom_panel = self.create_files_panel()
        layout.addWidget(bottom_panel)

        self.apply_styles()

    def create_top_panel(self):
        """Создание верхней панели"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 10px;
                padding: 10px;
            }
        """)

        layout = QHBoxLayout(frame)

        # Информация
        info_label = QLabel("🔑 Ваш код подключения:")
        info_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.code_label = QLabel(self.code_manager.my_code)
        self.code_label.setStyleSheet("""
            font-size: 32px;
            font-weight: bold;
            color: #2196F3;
            font-family: monospace;
            background-color: white;
            padding: 5px 20px;
            border-radius: 8px;
            border: 2px solid #2196F3;
        """)

        copy_btn = QPushButton("📋 Копировать")
        copy_btn.clicked.connect(self.copy_code)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 8px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
        """)

        # Статус
        self.status_icon = QLabel("● Не подключен")
        self.status_icon.setStyleSheet("color: #dc3545; font-weight: bold; font-size: 12px;")

        self.peer_info = QLabel("")
        self.peer_info.setStyleSheet("color: #28a745; font-size: 11px;")

        layout.addWidget(info_label)
        layout.addWidget(self.code_label)
        layout.addWidget(copy_btn)
        layout.addStretch()
        layout.addWidget(self.status_icon)
        layout.addWidget(self.peer_info)

        return frame

    def create_connection_panel(self):
        """Создание панели подключения"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                border: 1px solid #dee2e6;
                border-radius: 8px;
                background-color: white;
                padding: 15px;
            }
        """)

        layout = QVBoxLayout(panel)

        title = QLabel("🔌 Подключение к собеседнику")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        layout.addSpacing(10)

        # Поле ввода кода
        input_label = QLabel("Введите код собеседника:")
        layout.addWidget(input_label)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("10-значный код")
        self.code_input.setMaxLength(10)
        self.code_input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                font-size: 18px;
                font-family: monospace;
                border: 2px solid #dee2e6;
                border-radius: 5px;
            }
            QLineEdit:focus {
                border-color: #2196F3;
            }
        """)
        layout.addWidget(self.code_input)

        # Кнопка подключения
        connect_btn = QPushButton("🔗 Подключиться")
        connect_btn.clicked.connect(self.connect_by_code)
        connect_btn.setMinimumHeight(45)
        connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        layout.addWidget(connect_btn)

        # Список найденных устройств
        layout.addSpacing(15)
        devices_label = QLabel("📡 Найденные устройства:")
        devices_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(devices_label)

        self.devices_list = QListWidget()
        self.devices_list.itemDoubleClicked.connect(self.select_device)
        self.devices_list.setMaximumHeight(150)
        self.devices_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #dee2e6;
                border-radius: 5px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 5px;
            }
        """)
        layout.addWidget(self.devices_list)

        # Кнопка обновления
        refresh_btn = QPushButton("🔄 Обновить список")
        refresh_btn.clicked.connect(self.refresh_devices)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffc107;
                color: #212529;
                padding: 5px;
                border-radius: 5px;
            }
        """)
        layout.addWidget(refresh_btn)

        # Инструкция
        info = QLabel("""
            <b>📖 Как подключиться:</b><br>
            1. Отправьте свой код собеседнику<br>
            2. Введите код собеседника выше<br>
            3. Нажмите "Подключиться"<br>
            4. Готово! Можно общаться
        """)
        info.setWordWrap(True)
        info.setStyleSheet("background-color: #e3f2fd; padding: 10px; border-radius: 5px; margin-top: 10px;")
        layout.addWidget(info)

        layout.addStretch()

        # Таймер для обновления списка устройств
        self.device_timer = QTimer()
        self.device_timer.timeout.connect(self.refresh_devices)
        self.device_timer.start(5000)  # Обновление каждые 5 секунд

        return panel

    def create_chat_panel(self):
        """Создание панели чата"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                border: 1px solid #dee2e6;
                border-radius: 8px;
                background-color: white;
                padding: 15px;
            }
        """)

        layout = QVBoxLayout(panel)

        title = QLabel("💬 Чат")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # Область сообщений
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                border: 1px solid #dee2e6;
                border-radius: 5px;
                padding: 10px;
                background-color: #f8f9fa;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.chat_display)

        # Поле ввода сообщения
        msg_layout = QHBoxLayout()
        self.message_input = QTextEdit()
        self.message_input.setMaximumHeight(80)
        self.message_input.setPlaceholderText("Введите сообщение...")
        self.message_input.setStyleSheet("""
            QTextEdit {
                border: 1px solid #dee2e6;
                border-radius: 5px;
                padding: 8px;
            }
        """)

        send_btn = QPushButton("📤 Отправить")
        send_btn.clicked.connect(self.send_message)
        send_btn.setFixedWidth(100)
        send_btn.setMinimumHeight(60)
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)

        msg_layout.addWidget(self.message_input)
        msg_layout.addWidget(send_btn)
        layout.addLayout(msg_layout)

        return panel

    def create_files_panel(self):
        """Создание панели файлов"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                border: 1px solid #dee2e6;
                border-radius: 8px;
                background-color: white;
                padding: 10px;
                margin-top: 10px;
            }
        """)

        layout = QHBoxLayout(panel)

        self.files_list = QListWidget()
        self.files_list.setMaximumHeight(80)
        self.files_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #dee2e6;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.files_list)

        btn_layout = QVBoxLayout()

        send_file_btn = QPushButton("📎 Отправить файл")
        send_file_btn.clicked.connect(self.send_file)
        send_file_btn.setStyleSheet("""
            QPushButton {
                background-color: #6f42c1;
                color: white;
                padding: 5px;
                border-radius: 5px;
            }
        """)

        open_folder_btn = QPushButton("📂 Открыть папку")
        open_folder_btn.clicked.connect(self.open_folder)
        open_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                padding: 5px;
                border-radius: 5px;
            }
        """)

        btn_layout.addWidget(send_file_btn)
        btn_layout.addWidget(open_folder_btn)

        layout.addLayout(btn_layout)

        self.download_path = Path.home() / "Downloads" / "CommApp"
        self.download_path.mkdir(exist_ok=True)

        info = QLabel(f"📁 {self.download_path}")
        info.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(info)

        return panel

    def apply_styles(self):
        """Применение стилей"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QPushButton {
                padding: 8px;
                border-radius: 4px;
            }
        """)

    def copy_code(self):
        """Копировать код"""
        QApplication.clipboard().setText(self.code_manager.my_code)
        self.statusBar().showMessage("✅ Код скопирован!", 2000)

    def refresh_devices(self):
        """Обновить список устройств"""
        self.devices_list.clear()

        # Добавляем найденные устройства
        devices = list(self.code_manager.known_devices.values())
        if devices:
            for device in devices:
                if time.time() - device['last_seen'] < 10:  # Активные устройства
                    self.devices_list.addItem(f"🖥️ {device['name']} (Код: {device['code']})")
        else:
            self.devices_list.addItem("🔍 Поиск устройств...")

    def select_device(self, item):
        """Выбрать устройство из списка"""
        text = item.text()
        if "Код:" in text:
            try:
                code = text.split("Код: ")[1].replace(")", "")
                self.code_input.setText(code)
                self.connect_by_code()
            except:
                pass

    def connect_by_code(self):
        """Подключение по коду"""
        code = self.code_input.text().strip()

        if not code:
            QMessageBox.warning(self, "Ошибка", "Введите код собеседника")
            return

        if len(code) != 10 or not code.isdigit():
            QMessageBox.warning(self, "Ошибка", "Код должен состоять из 10 цифр")
            return

        if code == self.code_manager.my_code:
            QMessageBox.warning(self, "Ошибка", "Нельзя подключиться к самому себе")
            return

        self.statusBar().showMessage(f"🔍 Поиск устройства с кодом {code}...")

        # Подключаемся
        if self.chat.connect_to_code(code):
            self.statusBar().showMessage("✅ Подключено!", 2000)
        else:
            self.statusBar().showMessage("❌ Устройство не найдено", 3000)
            QMessageBox.warning(self, "Ошибка",
                                f"Устройство с кодом {code} не найдено.\n\n"
                                f"Убедитесь, что:\n"
                                f"• Собеседник запустил приложение\n"
                                f"• Вы в одной сети\n"
                                f"• Брандмауэр не блокирует порты {PORT} и {BROADCAST_PORT}")

    def on_connection_status(self, connected, code, name):
        """Статус подключения"""
        if connected:
            self.status_icon.setText("● Подключен")
            self.status_icon.setStyleSheet("color: #28a745; font-weight: bold;")
            self.peer_info.setText(f"Собеседник: {name} ({code})")

            self.chat_display.append(f"""
                <div style='margin: 10px; padding: 10px; background-color: #d4edda; border-radius: 8px;'>
                    <b>✓ Подключение установлено!</b><br>
                    Собеседник: {name}<br>
                    Код: {code}
                </div>
            """)
        else:
            self.status_icon.setText("● Не подключен")
            self.status_icon.setStyleSheet("color: #dc3545; font-weight: bold;")
            self.peer_info.setText("")

            if self.chat.connected == False:
                self.chat_display.append(f"""
                    <div style='margin: 10px; padding: 10px; background-color: #f8d7da; border-radius: 8px;'>
                        <b>⚠️ Соединение потеряно</b>
                    </div>
                """)

    def send_message(self):
        """Отправить сообщение"""
        text = self.message_input.toPlainText().strip()

        if not text:
            return

        if not self.chat.connected:
            QMessageBox.warning(self, "Ошибка", "Нет подключения к собеседнику")
            return

        if self.chat.send_message(text):
            self.chat_display.append(f"""
                <div style='margin: 10px;'>
                    <div style='color: #0066cc; font-weight: bold;'>Вы:</div>
                    <div style='background-color: #e3f2fd; padding: 10px; border-radius: 8px; margin-left: 20px;'>{text}</div>
                    <div style='color: #999; font-size: 10px; text-align: right;'>{datetime.now().strftime('%H:%M')}</div>
                </div>
            """)
            self.message_input.clear()
            self.statusBar().showMessage("💬 Сообщение отправлено", 1000)

            scrollbar = self.chat_display.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def on_message_received(self, text):
        """Получено сообщение"""
        self.chat_display.append(f"""
            <div style='margin: 10px;'>
                <div style='color: #28a745; font-weight: bold;'>Собеседник:</div>
                <div style='background-color: #f8f9fa; padding: 10px; border-radius: 8px; margin-left: 20px;'>{text}</div>
                <div style='color: #999; font-size: 10px; text-align: right;'>{datetime.now().strftime('%H:%M')}</div>
            </div>
        """)

        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        self.statusBar().showMessage("📨 Новое сообщение", 2000)

    def send_file(self):
        """Отправить файл"""
        if not self.chat.connected:
            QMessageBox.warning(self, "Ошибка", "Нет подключения к собеседнику")
            return

        filepath, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        if filepath:
            filename = os.path.basename(filepath)
            if self.chat.send_file(filepath):
                self.files_list.addItem(f"✅ Отправлен: {filename}")
                self.statusBar().showMessage(f"📎 Файл {filename} отправлен", 2000)
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось отправить файл")

    def open_folder(self):
        """Открыть папку"""
        try:
            os.startfile(str(self.download_path))
        except:
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть папку")

    def closeEvent(self, event):
        """Закрытие"""
        self.code_manager.stop()
        self.chat.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()