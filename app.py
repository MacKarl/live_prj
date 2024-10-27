import telebot
from telebot import types
from urllib.parse import quote

from dotenv import load_dotenv

import os
import threading
import re


class User:
    def __init__(self, chat_id, groups=None, contact=None):
        self.chat_id = chat_id
        self.groups = groups if groups else ["news"]
        self.contact = contact
        self.consultation_requests = []  # Добавлено для хранения запросов


class Admin(User):
    def __init__(self, chat_id, password):
        super().__init__(chat_id)
        self.password = password
        self.publish_mode = False
        self.pending_message = None

class SuperAdmin(Admin):
    def __init__(self, chat_id):
        super().__init__(chat_id, None)


class BotManager:
    def __init__(self, token, admin_password, superadmin_password, group_chat_id):
        self.bot = telebot.TeleBot(token)
        self.admin_password = admin_password
        self.superadmin_password = superadmin_password
        self.admins = {}
        self.superadmins = {}
        self.subscribers = {}
        self.groups = {"news": "Новостная группа"}
        self.group_chat_id = group_chat_id  # Добавлено для группы
        self.publish_timeout = 15 * 60 # 15 minutes in seconds
        self.timers = {}

        # Обработчики команд
        self.bot.message_handler(commands=['start'])(self.start)
        self.bot.message_handler(commands=['admin'])(self.admin_login)
        self.bot.message_handler(commands=['superadmin'])(self.superadmin_login)
        self.bot.message_handler(commands=['publish'])(self.enter_publish_mode)
        self.bot.message_handler(commands=['stop'])(self.exit_publish_mode)
        self.bot.message_handler(commands=['help'])(self.help_command)
        self.bot.message_handler(commands=['create_group'])(self.create_group)
        self.bot.message_handler(commands=['home'])(self.home)
        self.bot.message_handler(commands=['consultation'])(self.request_consultation)
        self.bot.message_handler(func=lambda message: True)(self.handle_message)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith("select_group_"))(self.handle_group_selection)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith("subscribe_"))(self.handle_subscription)
        self.bot.callback_query_handler(func=lambda call: call.data in ["confirm_send", "edit_message", "cancel_message"])(self.handle_confirmation)

    def start(self, message):
        chat_id = message.chat.id

        # Авто добавление в группы через параметр группы в URL
        params = message.text.split()
        if len(params) > 1 and params[1] in self.groups:
            group = params[1]
            self.subscribers[chat_id] = User(chat_id, [group, "news"])
            self.bot.send_message(chat_id, f"Вы были добавлены в группу '{self.groups[group]}'")
        else:
            self.subscribers[chat_id] = User(chat_id, ["news"])

        # Показываем доступные группы
        self.show_home_menu(chat_id)

    def home(self, message):
        chat_id = message.chat.id
        self.show_home_menu(chat_id)
    
    def show_home_menu(self, chat_id):
        # Главное меню с кнопками для подписки на рассылки
        markup = types.InlineKeyboardMarkup()

        # Показываем только публичные группы (которые не заканчиваются на 'private')
        for group_id, group_name in self.groups.items():
            if not group_id.endswith("private"):
                markup.add(types.InlineKeyboardButton(text=f"Подписаться на {group_name}", callback_data=f"subscribe_{group_id}"))

        self.bot.send_message(chat_id, "Добро пожаловать в главное меню! Выберите рассылку, на которую хотите подписаться:", reply_markup=markup)

    def admin_login(self, message):
        chat_id = message.chat.id
        if chat_id in self.admins:
            self.bot.send_message(chat_id, "Вы уже вошли в режим администратора.")
        else:
            self.bot.send_message(chat_id, "Введите пароль:")

    # Функция для входа супер-администратора
    def superadmin_login(self, message):
        chat_id = message.chat.id
        if chat_id in self.superadmins:
            self.bot.send_message(chat_id, "Вы уже супер-администратор.")
        elif chat_id in self.admins:
            self.bot.send_message(chat_id, "Введите пароль супер-администратора:")


    def enter_publish_mode(self, message):
        chat_id = message.chat.id
        if chat_id in self.admins:
            self.admins[chat_id].publish_mode = True
            self.bot.send_message(chat_id, "Вы вошли в режим публикации. Введите сообщение, которое хотите отправить подписчикам.")
            
            self.reset_inactivity_timer(chat_id)
        else:
            self.bot.send_message(chat_id, "Вы не являетесь администратором. Доступ запрещен.")

    def exit_publish_mode(self, message):
        chat_id = message.chat.id
        if chat_id in self.admins and self.admins[chat_id].publish_mode:
            self.disable_publish_mode(chat_id)
            self.bot.send_message(chat_id, "Вы вышли из режима публикации.")
        elif chat_id not in self.admins:
            self.bot.send_message(chat_id, "Вы не являетесь администратором. Доступ запрещен.")
        else:
            self.bot.send_message(chat_id, "Вы не находитесь в режиме публикации.")

    def disable_publish_mode(self, chat_id):
        """Disable publish mode and cancel any existing timer."""
        if chat_id in self.admins and self.admins[chat_id].publish_mode:
            self.admins[chat_id].publish_mode = False
            self.admins[chat_id].pending_message = None
        if chat_id in self.timers:
            self.timers[chat_id].cancel()

    def reset_inactivity_timer(self, chat_id):
        """Reset the inactivity timer for the admin's publish mode."""
        if chat_id in self.timers:
            self.timers[chat_id].cancel()

        # Start a new timer
        timer = threading.Timer(self.publish_timeout, lambda: self.exit_publish_mode_due_to_inactivity(chat_id))
        self.timers[chat_id] = timer
        timer.start()

    def exit_publish_mode_due_to_inactivity(self, chat_id):
        """Exit publish mode after 15 minutes of inactivity."""
        if chat_id in self.admins and self.admins[chat_id].publish_mode:
            self.bot.send_message(chat_id, "Вышли из режима публикации из-за бездействия.")
            self.disable_publish_mode(chat_id)

    def create_group(self, message):
        chat_id = message.chat.id
        if chat_id in self.admins:
            # Начинаем процесс создания группы с запроса публичного имени группы
            self.bot.send_message(chat_id, "Введите публичное имя новой группы. Например, 'Новостная группа':")
            self.bot.register_next_step_handler(message, self.get_group_name)
        else:
            self.bot.send_message(chat_id, "Вы не являетесь администратором. Доступ запрещен.")

    def get_group_name(self, message):
        chat_id = message.chat.id
        group_name = message.text.strip()

        # Сохраняем публичное имя и запрашиваем ID группы
        self.bot.send_message(chat_id, "Теперь введите ID группы (только латиницей, например, 'news_group'):")
        self.bot.register_next_step_handler(message, self.get_group_id, group_name)

    def get_group_id(self, message, group_name):
        chat_id = message.chat.id
        group_id = message.text.strip()

        # Проверка ID через RegEx (только латинские буквы, цифры, нижнее подчеркивание)
        if not re.match(r"^[a-zA-Z0-9_]+$", group_id):
            self.bot.send_message(chat_id, "ID может содержать только латинские буквы, цифры и символ нижнего подчеркивания (_). Попробуйте снова:")
            self.bot.register_next_step_handler(message, self.get_group_id, group_name)
        else:
            # Проверяем, существует ли уже такая группа
            if group_id in self.groups:
                self.bot.send_message(chat_id, "Группа с таким ID уже существует. Попробуйте снова:")
                self.bot.register_next_step_handler(message, self.get_group_id, group_name)
            else:
                # Сохраняем новую группу
                self.groups[group_id] = group_name
                self.bot.send_message(chat_id, f"Группа '{group_name}' с ID '{group_id}' успешно создана.")

                # Генерируем ссылку на подписку
                link = f"https://t.me/{self.bot.get_me().username}?start={quote(group_id)}"
                self.bot.send_message(chat_id, f"Ссылка для подписки на группу '{group_name}': {link}")

                # Проверяем, приватная ли группа (ID заканчивается на 'private')
                if group_id.endswith("private"):
                    self.bot.send_message(chat_id, f"Группа '{group_name}' является приватной и не будет отображаться на главной странице.")
                else:
                    self.bot.send_message(chat_id, f"Группа '{group_name}' является публичной и будет отображаться на главной странице.")

    def save_new_group(self, message):
        group_name = message.text
        chat_id = message.chat.id

        # Добавляем новую группу
        group_id = group_name.lower().replace(" ", "_")
        self.groups[group_id] = group_name
        self.bot.send_message(chat_id, f"Группа '{group_name}' успешно создана.")

        # Генерируем ссылку на подписку
        link = f"https://t.me/{self.bot.get_me().username}?start={quote(group_id)}"
        self.bot.send_message(chat_id, f"Ссылка для подписки на группу '{group_name}': {link}")


    def handle_subscription(self, call):
        chat_id = call.message.chat.id
        subscription_type = call.data.split("subscribe_")[1]
        
        if subscription_type in self.groups.keys():
            if subscription_type not in self.subscribers[chat_id].groups:
                self.subscribers[chat_id].groups.append(subscription_type)
                self.bot.send_message(chat_id, f"Вы подписались на рассылку {self.groups[subscription_type]}.")
            else:
                self.bot.send_message(chat_id, f"Вы уже подписаны на рассылку {self.groups[subscription_type]}.")
 
    def handle_message(self, message):
        chat_id = message.chat.id
        text = message.text

        if chat_id in self.admins and self.admins[chat_id].publish_mode:
            # Сохраняем сообщение, чтобы потом отправить его в выбранную группу
            self.admins[chat_id].pending_message = text

            # Создаем кнопки для выбора группы
            markup = types.InlineKeyboardMarkup()
            for group_id, group_name in self.groups.items():
                markup.add(types.InlineKeyboardButton(text=group_name, callback_data=f"select_group_{group_id}"))

            self.bot.send_message(chat_id, "Выберите группу для отправки сообщения:", reply_markup=markup)

        elif text == self.admin_password:
            self.admins[chat_id] = Admin(chat_id, self.admin_password)
            self.bot.send_message(chat_id, "Пароль администратора принят. Вы вошли в режим администратора. Используйте команду /publish для публикации.")
        elif text == self.superadmin_password and chat_id in self.admins:
            self.superadmins[chat_id] = SuperAdmin(chat_id)
            self.bot.send_message(chat_id, "Пароль супер-администратора принят. Вы теперь супер-администратор.")
            self.notify_superadmins(f"Пользователь {chat_id} стал супер-администратором.")
        elif chat_id in self.admins:
            self.bot.send_message(chat_id, "Вы вошли как администратор. Используйте команду /publish для публикации.")
        else:
            self.bot.send_message(chat_id, "Вы не авторизованы для выполнения этого действия.")

    def notify_superadmins(self, message_text):
        for superadmin_id in self.superadmins:
            self.bot.send_message(superadmin_id, message_text)


    def handle_group_selection(self, call):
        chat_id = call.message.chat.id
        group_id = call.data.split("select_group_")[1]

        if chat_id in self.admins and self.admins[chat_id].publish_mode:
            # Сохраняем выбранную группу для отправки
            self.admins[chat_id].pending_message_group = group_id
            group_name = self.groups[group_id]

            # Создание кнопок для подтверждения
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(text="Отправить", callback_data="confirm_send"),
                types.InlineKeyboardButton(text="Изменить", callback_data="edit_message"),
                types.InlineKeyboardButton(text="Отменить", callback_data="cancel_message")
            )

            # Предварительный просмотр сообщения
            self.bot.send_message(chat_id, f"Хотите отправить это сообщение в группу '{group_name}'?\n\n{self.admins[chat_id].pending_message}", reply_markup=markup)

    

    def handle_confirmation(self, call):
        chat_id = call.message.chat.id
        action = call.data
        
        if chat_id in self.admins and self.admins[chat_id].publish_mode:
            if action == "confirm_send":
                message_text = self.admins[chat_id].pending_message

                # Добавляем ссылки в конец сообщения
                message_text += "\n\nЖивые Проекты\n" \
                                "[Instagram](https://www.instagram.com/lifeprojectsru) | " \
                                "[Telegram](https://t.me/livingprojects)"
                
                group_id = self.admins[chat_id].pending_message_group

                # Отправляем сообщение подписчикам выбранной группы
                for subscriber in self.subscribers.values():
                    if group_id in subscriber.groups or 'news' in subscriber.groups:
                        self.bot.send_message(subscriber.chat_id, message_text, parse_mode="Markdown")

                self.bot.send_message(chat_id, "Сообщение отправлено подписчикам.")
                self.disable_publish_mode(chat_id)
                self.admins[chat_id].pending_message = None
            elif action == "edit_message":
                self.bot.send_message(chat_id, "Пожалуйста, введите новое сообщение.")
                self.reset_inactivity_timer(chat_id)  # Reset the timer on interaction
            elif action == "cancel_message":
                self.disable_publish_mode(chat_id)
                self.bot.send_message(chat_id, "Сообщение отменено.")

    def request_consultation(self, message):
        chat_id = message.chat.id

        # Запрашиваем описание запроса у пользователя
        self.bot.send_message(chat_id, "Пожалуйста, опишите ваш запрос на консультацию. Ответ придёт в этом боте!")
        
        # Регистрация следующего шага для получения описания запроса
        self.bot.register_next_step_handler(message, self.save_consultation_request)

    def save_consultation_request(self, message, group_name=None):
        chat_id = message.chat.id
        description = message.text

        # Сохраняем описание запроса у пользователя
        if chat_id not in self.subscribers:
            self.subscribers[chat_id] = User(chat_id)

        # Сохраняем запрос консультации
        if not hasattr(self.subscribers[chat_id], 'consultation_requests'):
            self.subscribers[chat_id].consultation_requests = []

        self.subscribers[chat_id].consultation_requests.append({
            'description': description,
            'timestamp': message.date,
            'group_names': [self.groups[group_name]] if group_name else []
        })

        # Формируем сообщение для администраторов
        admin_message = (
            f"Пользователь {chat_id} запросил консультацию.\n"
            f"Описание запроса: {description}\n"
            f"Время запроса: {message.date}\n"
            f"Группы: {', '.join(self.subscribers[chat_id].groups)}\n"
            f"Чтобы ответить пользователю, используйте функцию 'Reply' в этой группе."
        )

        # Отправляем сообщение в группу, где присутствуют администраторы
        self.bot.send_message(self.group_chat_id, admin_message)

        self.bot.send_message(chat_id, "Ваш запрос на консультацию отправлен. Ожидайте ответа.")

    def help_command(self, message):
        chat_id = message.chat.id

        if chat_id in self.superadmins:
            help_text = (
                "Команды для супер-администраторов:\n"
                "/superadmin - Войти как супер-администратор\n"
                "/admin - Войти как администратор\n"
                "/publish - Войти в режим публикации\n"
                "/stop - Выйти из режима публикации\n"
                "/create_group - Создать новую группу\n"
                "/help - Показать это сообщение\n"
            )
        elif chat_id in self.admins:
            help_text = (
                "Команды для администраторов:\n"
                "/admin - Войти как администратор\n"
                "/publish - Войти в режим публикации\n"
                "/stop - Выйти из режима публикации\n"
                "/create_group - Создать новую группу\n"
                "/help - Показать это сообщение\n"

                "Команды для всех пользователей:\n"
                "/start - Запустить бота\n"
                "/home - Вернуться в главное меню\n"
                "/consultation - Запросить консультацию\n"
                "/help - Показать это сообщение"
            )
        else:
            help_text = (
                "Доступные команды:\n"
                "/start - Запустить бота\n"
                "/home - Вернуться в главное меню\n"
                "/consultation - Запросить консультацию\n"
                "/help - Показать это сообщение"
            )

        self.bot.send_message(chat_id, help_text)
    def run(self):
        self.bot.polling()

# Запуск бота
if __name__ == '__main__':

    # Load environment variables
    load_dotenv()
    TOKEN = os.environ.get("TELEGRAM_API_KEY") #'7448862042:AAEvAsZee2AzbzEwiW2Anw1DDoE4EU8044A'
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASS") #'your_admin_password'
    SUPERADMIN_PASSWORD = os.environ.get("SUPER_ADMIN_PASS") #'your_superadmin_password'
    GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID") #'-4515658282' 
    bot_manager = BotManager(TOKEN, ADMIN_PASSWORD, SUPERADMIN_PASSWORD, GROUP_CHAT_ID)
    bot_manager.run()

