import smtplib
from datetime import datetime, timedelta
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from kivy.uix.image import Image
from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import ScreenManager
from kivy.uix.gridlayout import GridLayout
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window
from kivy.graphics import Rectangle, RoundedRectangle
import sqlite3
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.camera import Camera
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.graphics.texture import Texture
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line
import cv2
from pyzbar.pyzbar import decode

# Set window size
Window.size = (360, 640)

class DatabaseManager:
    def __init__(self):
        self.visitors_db = 'visitors.db'
        self.accounts_db = 'accounts.db'
        self.messages_file = 'messages.json'
        self.last_check_file = 'last_check.json'
        self.notification_viewed_file = 'notification_viewed.json'
        self.init_databases()

    def add_event_visitor(self, name, reason, person_to_visit, visit_date, visit_time,
                          valid_id, email, time_in, created_at):
        """Add a visitor directly (for events) and return the visitor ID"""
        conn = sqlite3.connect(self.visitors_db)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO visitors (name, reason, person_to_visit, visit_date, visit_time, 
                                valid_id, email, time_in, first_time_in, created_at, is_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (name, reason, person_to_visit, visit_date, visit_time, valid_id, email,
              time_in, time_in, created_at))
        conn.commit()
        visitor_id = cursor.lastrowid
        conn.close()
        return visitor_id

    def init_databases(self):
        # Initialize visitors database
        conn = sqlite3.connect(self.visitors_db)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS visitors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                reason TEXT NOT NULL,
                person_to_visit TEXT NOT NULL,
                visit_date TEXT NOT NULL,
                visit_time TEXT NOT NULL,
                valid_id TEXT,
                email TEXT NOT NULL,
                time_in TEXT,
                time_out TEXT,
                first_time_in TEXT,
                first_time_out TEXT,
                created_at TEXT NOT NULL,
                is_verified INTEGER DEFAULT 0
            )
        ''')
        cursor.execute("PRAGMA table_info(visitors)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'first_time_in' not in columns:
            cursor.execute("ALTER TABLE visitors ADD COLUMN first_time_in TEXT")
        if 'first_time_out' not in columns:
            cursor.execute("ALTER TABLE visitors ADD COLUMN first_time_out TEXT")
        if 'created_at' not in columns:
            cursor.execute("ALTER TABLE visitors ADD COLUMN created_at TEXT")
        conn.commit()
        conn.close()

        # Initialize accounts database
        conn = sqlite3.connect(self.accounts_db)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user'
            )
        ''')
        cursor.execute('SELECT COUNT(*) FROM accounts WHERE username = ?', ('admin',))
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO accounts (username, password, role) VALUES (?, ?, ?)',
                           ('admin', 'admin123', 'admin'))
        conn.commit()
        conn.close()

        # Initialize messages file
        if not os.path.exists(self.messages_file):
            with open(self.messages_file, 'w') as f:
                json.dump([], f)

        # Initialize last check file
        if not os.path.exists(self.last_check_file):
            with open(self.last_check_file, 'w') as f:
                json.dump({'last_check': ''}, f)

        # Initialize notification viewed file
        if not os.path.exists(self.notification_viewed_file):
            with open(self.notification_viewed_file, 'w') as f:
                json.dump({'last_viewed': ''}, f)

    def verify_login(self, username, password):
        conn = sqlite3.connect(self.accounts_db)
        cursor = conn.cursor()
        cursor.execute('SELECT role FROM accounts WHERE username = ? AND password = ?',
                       (username, password))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    def get_visitors(self):
        conn = sqlite3.connect(self.visitors_db)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM visitors ORDER BY visit_date DESC, visit_time DESC')
        visitors = cursor.fetchall()
        conn.close()
        return visitors

    def update_time_in(self, visitor_id, time_in):
        conn = sqlite3.connect(self.visitors_db)
        cursor = conn.cursor()
        cursor.execute("SELECT first_time_in FROM visitors WHERE id = ?", (visitor_id,))
        first_time_in = cursor.fetchone()[0]
        if not first_time_in:
            cursor.execute("UPDATE visitors SET time_in = ?, first_time_in = ? WHERE id = ?",
                           (time_in, time_in, visitor_id))
        else:
            cursor.execute("UPDATE visitors SET time_in = ? WHERE id = ?", (time_in, visitor_id))
        conn.commit()
        conn.close()

    def update_time_out(self, visitor_id, time_out):
        conn = sqlite3.connect(self.visitors_db)
        cursor = conn.cursor()
        cursor.execute("SELECT first_time_out FROM visitors WHERE id = ?", (visitor_id,))
        first_time_out = cursor.fetchone()[0]
        if not first_time_out:
            cursor.execute("UPDATE visitors SET time_out = ?, first_time_out = ? WHERE id = ?",
                           (time_out, time_out, visitor_id))
        else:
            cursor.execute("UPDATE visitors SET time_out = ? WHERE id = ?", (time_out, visitor_id))
        conn.commit()
        conn.close()

    def mark_notifications_viewed(self):
        """Mark that user has viewed notifications (clicked the bell)"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.notification_viewed_file, 'w') as f:
            json.dump({'last_viewed': timestamp}, f)
        return timestamp

    def get_last_viewed(self):
        """Get when notifications were last viewed"""
        try:
            with open(self.notification_viewed_file, 'r') as f:
                data = json.load(f)
                return data.get('last_viewed', '')
        except:
            return ''

    def has_unviewed_notifications(self):
        """Check if there are notifications that haven't been viewed yet"""
        last_viewed = self.get_last_viewed()
        new_visitors = self.get_new_visitors(last_viewed)
        return len(new_visitors) > 0

    def add_account(self, username, password, role='user'):
        conn = sqlite3.connect(self.accounts_db)
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO accounts (username, password, role) VALUES (?, ?, ?)',
                           (username, password, role))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False

    def delete_account(self, username):
        if username == 'admin':
            return False
        conn = sqlite3.connect(self.accounts_db)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM accounts WHERE username = ?', (username,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    def get_accounts(self):
        conn = sqlite3.connect(self.accounts_db)
        cursor = conn.cursor()
        cursor.execute('SELECT username, role FROM accounts')
        accounts = cursor.fetchall()
        conn.close()
        return accounts

    def add_message(self, username, message):
        try:
            with open(self.messages_file, 'r') as f:
                messages = json.load(f)
        except:
            messages = []
        messages.append({
            'username': username,
            'message': message,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        with open(self.messages_file, 'w') as f:
            json.dump(messages, f, indent=2)

    def get_messages(self):
        try:
            with open(self.messages_file, 'r') as f:
                return json.load(f)
        except:
            return []

    def delete_message(self, timestamp):
        try:
            with open(self.messages_file, 'r') as f:
                messages = json.load(f)
            messages = [msg for msg in messages if msg['timestamp'] != timestamp]
            with open(self.messages_file, 'w') as f:
                json.dump(messages, f, indent=2)
            return True
        except:
            return False

    def delete_visitor(self, visitor_id):
        conn = sqlite3.connect(self.visitors_db)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM visitors WHERE id = ?', (visitor_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    def update_visitor_reentry(self, visitor_id, new_reason):
        conn = sqlite3.connect(self.visitors_db)
        cursor = conn.cursor()
        cursor.execute("SELECT reason FROM visitors WHERE id = ?", (visitor_id,))
        current_reason = cursor.fetchone()[0]
        updated_reason = f"{current_reason} / {new_reason}"
        new_time_in = datetime.now().strftime("%H:%M:%S")
        cursor.execute("UPDATE visitors SET reason = ?, time_in = ?, time_out = NULL WHERE id = ?",
                       (updated_reason, new_time_in, visitor_id))
        conn.commit()
        conn.close()
        return new_time_in

    def get_new_visitors(self, last_check_time):
        conn = sqlite3.connect(self.visitors_db)
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, visit_date, visit_time, created_at FROM visitors WHERE created_at > ? ORDER BY created_at DESC',
                       (last_check_time,))
        new_visitors = cursor.fetchall()
        conn.close()
        return new_visitors

    def update_last_check(self):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.last_check_file, 'w') as f:
            json.dump({'last_check': timestamp}, f)
        return timestamp

    def get_last_check(self):
        try:
            with open(self.last_check_file, 'r') as f:
                data = json.load(f)
                return data.get('last_check', '')
        except:
            return ''

class LoginScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'login'
        main_layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        with main_layout.canvas.before:
            Color(0.1, 0.1, 0.2, 1)
            self.rect = Rectangle(size=main_layout.size, pos=main_layout.pos)
        main_layout.bind(size=self._update_rect, pos=self._update_rect)
        title = Label(text='GATE_PASS', font_size=dp(32), size_hint_y=0.3,
                      color=(1, 1, 1, 1), bold=True)
        main_layout.add_widget(title)
        form_layout = BoxLayout(orientation='vertical', spacing=dp(15), size_hint_y=0.5)
        self.username_input = TextInput(hint_text='Username', multiline=False,
                                        size_hint_y=None, height=dp(40))
        form_layout.add_widget(self.username_input)
        self.password_input = TextInput(hint_text='Password', password=True, multiline=False,
                                        size_hint_y=None, height=dp(40))
        form_layout.add_widget(self.password_input)
        login_btn = Button(text='Log In', size_hint_y=None, height=dp(50),
                           background_color=(0.2, 0.6, 0.8, 1))
        login_btn.bind(on_press=self.login)
        form_layout.add_widget(login_btn)
        main_layout.add_widget(form_layout)
        main_layout.add_widget(Label(size_hint_y=0.2))
        self.add_widget(main_layout)

    def _update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def login(self, instance):
        username = self.username_input.text.strip()
        password = self.password_input.text.strip()
        if not username or not password:
            self.show_popup('Error', 'Please enter both username and password')
            return
        role = App.get_running_app().db.verify_login(username, password)
        if role:
            App.get_running_app().current_user = username
            App.get_running_app().user_role = role
            self.manager.current = 'dashboard'
            self.username_input.text = ''
            self.password_input.text = ''
        else:
            self.show_popup('Error', 'Invalid credentials')

    def show_popup(self, title, message):
        layout = BoxLayout(orientation='vertical', padding=20, spacing=15)

        with layout.canvas.before:
            Color(0.2, 0.2, 0.2, 0.9)
            self.rect = RoundedRectangle(radius=[20], size=layout.size, pos=layout.pos)
            layout.bind(size=lambda *x: setattr(self.rect, 'size', layout.size),
                        pos=lambda *x: setattr(self.rect, 'pos', layout.pos))

        message_label = Label(text=message, color=(1, 1, 1, 1), font_size=18)
        close_btn = Button(
            text="Close",
            size_hint=(1, 0.3),
            background_color=(1, 0, 0, 1),
            color=(1, 1, 1, 1)
        )

        # ✅ Add widgets to the layout
        layout.add_widget(message_label)
        layout.add_widget(close_btn)

        popup = Popup(title=title, content=layout, size_hint=(0.7, 0.4), auto_dismiss=False)
        close_btn.bind(on_release=popup.dismiss)
        popup.open()


class DashboardScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'dashboard'
        self.notification_count = 0

        main_layout = BoxLayout(orientation='vertical')

        # Header with notification bell
        header = BoxLayout(size_hint_y=0.1, padding=dp(10))
        header.add_widget(Label(text='GATE_PASS Dashboard', font_size=dp(20), bold=True))

        # Notification bell button with badge
        bell_container = BoxLayout(size_hint_x=0.15, orientation='vertical')
        self.notification_btn = Button(
            text='N',  # Bell emoji
            font_size=dp(24),
            size_hint=(1, 0.8),
            background_color=(0.2, 0.2, 0.2, 0.1)  # Transparent background
        )
        self.notification_btn.bind(on_press=self.go_to_notifications)

        # Badge for notification count
        self.badge_label = Label(
            text='',
            font_size=dp(10),
            size_hint=(1, 0.2),
            color=(1, 1, 1, 1),
            bold=True
        )

        bell_container.add_widget(self.notification_btn)
        bell_container.add_widget(self.badge_label)
        header.add_widget(bell_container)

        main_layout.add_widget(header)

        # Main content
        content = BoxLayout(orientation='vertical', size_hint_y=0.7, padding=dp(20))
        scan_btn = Button(text='Scan QR Code', size_hint=(0.8, 0.3), pos_hint={'center_x': 0.5},
                          background_color=(0.2, 0.8, 0.2, 1), font_size=dp(18))
        scan_btn.bind(on_press=self.scan_qr)
        content.add_widget(scan_btn)
        main_layout.add_widget(content)

        # Bottom navigation (3 buttons now instead of 4)
        bottom_nav = GridLayout(cols=3, size_hint_y=0.2, padding=dp(5), spacing=dp(5))
        message_btn = Button(text='Message', background_color=(0.6, 0.6, 0.8, 1))
        message_btn.bind(on_press=lambda x: setattr(self.manager, 'current', 'messages'))
        bottom_nav.add_widget(message_btn)

        log_btn = Button(text='Visitor Log', background_color=(0.8, 0.6, 0.6, 1))
        log_btn.bind(on_press=lambda x: setattr(self.manager, 'current', 'visitor_log'))
        bottom_nav.add_widget(log_btn)

        account_btn = Button(text='Account', background_color=(0.6, 0.8, 0.6, 1))
        account_btn.bind(on_press=lambda x: setattr(self.manager, 'current', 'account'))
        bottom_nav.add_widget(account_btn)

        main_layout.add_widget(bottom_nav)
        self.add_widget(main_layout)

        # Schedule notification checking
        Clock.schedule_interval(self.check_notifications, 3)

    def on_enter(self):
        self.check_notifications()

    def check_notifications(self, dt=None):
        app = App.get_running_app()

        # Check if there are unviewed notifications
        has_unviewed = app.db.has_unviewed_notifications()

        if has_unviewed:
            # Get count for the badge
            last_viewed = app.db.get_last_viewed()
            new_visitors = app.db.get_new_visitors(last_viewed)
            new_count = len(new_visitors)
        else:
            new_count = 0

        # Only update if count changed to avoid unnecessary UI updates
        if new_count != self.notification_count:
            self.notification_count = new_count
            self.update_notification_display()

    def update_notification_display(self):
        if self.notification_count > 0:
            # Show badge with count
            self.badge_label.text = str(self.notification_count)
            # Make bell more prominent
            self.notification_btn.background_color = (1, 0.3, 0.3, 0.8)  # Red background
            self.notification_btn.text = '🔔'  # Bell emoji

            # Optional: Make it pulse/animate
            from kivy.animation import Animation
            anim = Animation(font_size=dp(28), duration=0.5) + Animation(font_size=dp(24), duration=0.5)
            anim.repeat = True
            anim.start(self.notification_btn)

        else:
            # No notifications
            self.badge_label.text = ''
            self.notification_btn.background_color = (0.2, 0.2, 0.2, 0.1)  # Back to transparent
            self.notification_btn.text = '🔔'  # Regular bell

            # Stop any animations
            from kivy.animation import Animation
            Animation.cancel_all(self.notification_btn)
            self.notification_btn.font_size = dp(24)

    def go_to_notifications(self, instance):
        # Stop the pulsing animation when clicked
        from kivy.animation import Animation
        Animation.cancel_all(self.notification_btn)
        self.notification_btn.font_size = dp(24)

        # Mark notifications as viewed and hide the badge number
        app = App.get_running_app()
        app.db.mark_notifications_viewed()  # This line is crucial - it was missing!
        self.badge_label.text = ''

        # Reset notification count since user has viewed them
        self.notification_count = 0
        self.update_notification_display()

        self.manager.current = 'notifications'

    def scan_qr(self, instance):
        self.manager.current = "qr_scanner"

class MessagesScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'messages'
        main_layout = BoxLayout(orientation='vertical')
        header = BoxLayout(size_hint_y=0.1, padding=dp(10))
        back_btn = Button(text='← Back', size_hint_x=0.2)
        back_btn.bind(on_press=lambda x: setattr(self.manager, 'current', 'dashboard'))
        header.add_widget(back_btn)
        header.add_widget(Label(text='Messages', font_size=dp(18), bold=True))
        main_layout.add_widget(header)
        self.messages_scroll = ScrollView()
        self.messages_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5))
        self.messages_layout.bind(minimum_height=self.messages_layout.setter('height'))
        self.messages_scroll.add_widget(self.messages_layout)
        main_layout.add_widget(self.messages_scroll)
        input_layout = BoxLayout(size_hint_y=0.15, padding=dp(10), spacing=dp(10))
        self.message_input = TextInput(hint_text='Type your message...', multiline=False)
        send_btn = Button(text='Send', size_hint_x=0.2)
        send_btn.bind(on_press=self.send_message)
        input_layout.add_widget(self.message_input)
        input_layout.add_widget(send_btn)
        main_layout.add_widget(input_layout)
        self.add_widget(main_layout)
        Clock.schedule_interval(self.refresh_messages, 2)

    def on_enter(self):
        self.refresh_messages()

    def refresh_messages(self, dt=None):
        messages = App.get_running_app().db.get_messages()
        self.messages_layout.clear_widgets()
        current_user = App.get_running_app().current_user
        is_admin = App.get_running_app().user_role == 'admin'
        for msg in messages:
            is_own_message = msg['username'] == current_user
            outer_box = BoxLayout(
                orientation='horizontal',
                size_hint_y=None,
                height=dp(80),
                padding=dp(8),
                spacing=dp(8)
            )
            if is_own_message:
                outer_box.add_widget(Widget(size_hint_x=0.3))
            msg_widget = BoxLayout(
                orientation='vertical',
                size_hint_y=None,
                size_hint_x=0.7 if is_own_message else 0.7 if is_admin else 1.0,
                height=dp(80),
                padding=dp(10),
                spacing=dp(5)
            )
            header_layout = BoxLayout(size_hint_y=None, height=dp(20))
            if is_own_message:
                header_layout.add_widget(Label(
                    text=f"{msg['timestamp']}",
                    font_size=dp(10),
                    color=(0.7, 0.7, 0.7, 1),
                    halign="left",
                    valign="middle"
                ))
                header_layout.add_widget(Label(
                    text=f"{msg['username']}",
                    font_size=dp(12),
                    bold=True,
                    color=(1, 1, 1, 1),
                    halign="right",
                    valign="middle"
                ))
            else:
                header_layout.add_widget(Label(
                    text=f"{msg['username']}",
                    font_size=dp(12),
                    bold=True,
                    color=(1, 1, 1, 1),
                    halign="left",
                    valign="middle"
                ))
                header_layout.add_widget(Label(
                    text=f"{msg['timestamp']}",
                    font_size=dp(10),
                    color=(0.7, 0.7, 0.7, 1),
                    halign="right",
                    valign="middle"
                ))
            msg_widget.add_widget(header_layout)
            msg_widget.add_widget(Label(
                text=msg['message'],
                font_size=dp(14),
                color=(1, 1, 1, 1),
                halign="right" if is_own_message else "left",
                valign="top"
            ))
            with msg_widget.canvas.before:
                if is_own_message:
                    Color(0.25, 0.41, 0.88, 1)
                else:
                    Color(39 / 255, 39 / 255, 42 / 255, 1)
                rect = RoundedRectangle(pos=msg_widget.pos, size=msg_widget.size, radius=[10])
            def update_rect(instance, value, rectangle=rect):
                rectangle.pos = instance.pos
                rectangle.size = instance.size
            msg_widget.bind(pos=update_rect, size=update_rect)
            outer_box.add_widget(msg_widget)
            if is_admin:
                delete_btn = Button(
                    text='Delete',
                    size_hint_x=0.3,
                    size_hint_y=None,
                    height=dp(30),
                    background_color=(0.8, 0.2, 0.2, 1)
                )
                delete_btn.bind(on_press=lambda x, t=msg['timestamp']: self.delete_message(t))
                outer_box.add_widget(delete_btn)
            elif not is_own_message:
                outer_box.add_widget(Widget(size_hint_x=0.3))
            self.messages_layout.add_widget(outer_box)

    def send_message(self, instance):
        message = self.message_input.text.strip()
        if message:
            username = App.get_running_app().current_user
            App.get_running_app().db.add_message(username, message)
            self.message_input.text = ''
            self.refresh_messages()

    def delete_message(self, timestamp):
        if App.get_running_app().db.delete_message(timestamp):
            self.refresh_messages()
            popup = Popup(
                title='Success',
                content=Label(text='Message deleted successfully!'),
                size_hint=(0.8, 0.3)
            )
            popup.open()
        else:
            popup = Popup(
                title='Error',
                content=Label(text='Failed to delete message!'),
                size_hint=(0.8, 0.3)
            )
            popup.open()


class VisitorLogScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'visitor_log'
        main_layout = BoxLayout(orientation='vertical')

        # Header
        header = BoxLayout(size_hint_y=0.1, padding=dp(10))
        back_btn = Button(text='← Back', size_hint_x=0.2)
        back_btn.bind(on_press=lambda x: setattr(self.manager, 'current', 'dashboard'))
        header.add_widget(back_btn)
        header.add_widget(Label(text='Visitor Log', font_size=dp(18), bold=True))
        main_layout.add_widget(header)

        # Report Type Tabs (Daily, Weekly, Monthly, All Time)
        tab_layout = BoxLayout(size_hint_y=0.08, spacing=dp(5), padding=dp(5))
        self.daily_btn = Button(text='Daily', background_color=(0.2, 0.6, 0.8, 1))
        self.weekly_btn = Button(text='Weekly', background_color=(0.5, 0.5, 0.5, 1))
        self.monthly_btn = Button(text='Monthly', background_color=(0.5, 0.5, 0.5, 1))
        self.all_time_btn = Button(text='All Time', background_color=(0.5, 0.5, 0.5, 1))

        self.daily_btn.bind(on_press=lambda x: self.switch_tab('daily'))
        self.weekly_btn.bind(on_press=lambda x: self.switch_tab('weekly'))
        self.monthly_btn.bind(on_press=lambda x: self.switch_tab('monthly'))
        self.all_time_btn.bind(on_press=lambda x: self.switch_tab('all_time'))

        tab_layout.add_widget(self.daily_btn)
        tab_layout.add_widget(self.weekly_btn)
        tab_layout.add_widget(self.monthly_btn)
        tab_layout.add_widget(self.all_time_btn)
        main_layout.add_widget(tab_layout)

        self.current_tab = 'daily'

        # Search and Filter
        filter_layout = BoxLayout(size_hint_y=0.1, spacing=dp(5), padding=dp(5))
        self.search_input = TextInput(hint_text='Search by name', multiline=False, size_hint_x=0.5)
        self.status_filter = Spinner(
            text='All Statuses',
            values=('All Statuses', 'Pending', 'Inside the premises', 'Already left the premises'),
            size_hint_x=0.3
        )
        search_btn = Button(text='Search', size_hint_x=0.2)
        search_btn.bind(on_press=self.refresh_visitors)
        filter_layout.add_widget(self.search_input)
        filter_layout.add_widget(self.status_filter)
        filter_layout.add_widget(search_btn)
        main_layout.add_widget(filter_layout)

        # Date Range Display
        self.date_range_label = Label(
            text='Today',
            size_hint_y=0.05,
            font_size=dp(12),
            color=(0.7, 0.7, 0.7, 1)
        )
        main_layout.add_widget(self.date_range_label)

        # Statistics Summary
        self.stats_layout = BoxLayout(size_hint_y=0.08, padding=dp(5), spacing=dp(5))
        main_layout.add_widget(self.stats_layout)

        # Visitor List
        self.scroll = ScrollView()
        self.visitor_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5))
        self.visitor_layout.bind(minimum_height=self.visitor_layout.setter('height'))
        self.scroll.add_widget(self.visitor_layout)
        main_layout.add_widget(self.scroll)
        self.add_widget(main_layout)

    def switch_tab(self, tab):
        self.current_tab = tab

        # Update button colors
        self.daily_btn.background_color = (0.2, 0.6, 0.8, 1) if tab == 'daily' else (0.5, 0.5, 0.5, 1)
        self.weekly_btn.background_color = (0.2, 0.6, 0.8, 1) if tab == 'weekly' else (0.5, 0.5, 0.5, 1)
        self.monthly_btn.background_color = (0.2, 0.6, 0.8, 1) if tab == 'monthly' else (0.5, 0.5, 0.5, 1)
        self.all_time_btn.background_color = (0.2, 0.6, 0.8, 1) if tab == 'all_time' else (0.5, 0.5, 0.5, 1)

        self.refresh_visitors()

    def get_date_range(self):
        """Get start and end dates based on current tab - FIXED VERSION"""
        today = datetime.now().date()

        if self.current_tab == 'daily':
            return today, today
        elif self.current_tab == 'weekly':
            # Get the entire current week (Monday to Sunday)
            start_date = today - timedelta(days=today.weekday())  # Monday of current week
            end_date = start_date + timedelta(days=6)  # Sunday of current week
            return start_date, end_date
        elif self.current_tab == 'monthly':
            # Get the entire current month (1st to last day)
            start_date = today.replace(day=1)
            # Get last day of current month
            if today.month == 12:
                end_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
            return start_date, end_date
        else:  # all_time
            # Return None to indicate no filtering
            return None, None

    def update_statistics(self, visitors):
        """Update the statistics summary"""
        self.stats_layout.clear_widgets()

        total = len(visitors)
        pending = sum(1 for v in visitors if not v[8])
        inside = sum(1 for v in visitors if v[8] and not v[9])
        left = sum(1 for v in visitors if v[9])

        stats = [
            ('Total', total, (0.2, 0.6, 0.8, 1)),
            ('Pending', pending, (1, 1, 0, 1)),
            ('Inside', inside, (0, 1, 0, 1)),
            ('Left', left, (1, 0, 0, 1))
        ]

        for label, count, color in stats:
            stat_box = BoxLayout(orientation='vertical', padding=dp(5))
            with stat_box.canvas.before:
                Color(*color)
                rect = Rectangle(pos=stat_box.pos, size=stat_box.size)
                stat_box.bind(pos=lambda instance, value, r=rect: setattr(r, 'pos', instance.pos),
                              size=lambda instance, value, r=rect: setattr(r, 'size', instance.size))

            stat_box.add_widget(Label(text=str(count), font_size=dp(20), bold=True, color=(1, 1, 1, 1)))
            stat_box.add_widget(Label(text=label, font_size=dp(12), color=(1, 1, 1, 1)))
            self.stats_layout.add_widget(stat_box)

    def on_enter(self):
        self.refresh_visitors()

    def refresh_visitors(self, instance=None):
        search_term = self.search_input.text.strip().lower()
        status_filter = self.status_filter.text
        visitors = App.get_running_app().db.get_visitors()

        # Filter by date range based on tab - FIXED VERSION
        start_date, end_date = self.get_date_range()
        filtered_visitors = []

        # Update date range label
        if self.current_tab == 'daily':
            self.date_range_label.text = f"Today: {start_date.strftime('%B %d, %Y')}"
        elif self.current_tab == 'weekly':
            self.date_range_label.text = f"Week: {start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
        elif self.current_tab == 'monthly':
            self.date_range_label.text = f"Month: {start_date.strftime('%B %Y')}"
        else:  # all_time
            self.date_range_label.text = "All Time"

        for visitor in visitors:
            try:
                visit_date = datetime.strptime(visitor[4], '%Y-%m-%d').date()

                # If all_time tab, include all visitors (no date filtering)
                if start_date is None and end_date is None:
                    filtered_visitors.append(visitor)
                # Otherwise filter by date range
                elif start_date <= visit_date <= end_date:
                    filtered_visitors.append(visitor)
            except Exception as e:
                print(f"Error parsing date for visitor {visitor[0]}: {e}")
                continue

        self.visitor_layout.clear_widgets()
        is_admin = App.get_running_app().user_role == 'admin'

        # Update statistics
        self.update_statistics(filtered_visitors)

        # If no visitors in range, show message
        if not filtered_visitors:
            no_visitor_label = Label(
                text=f'No visitors found for this {self.current_tab.replace("_", " ")} period',
                font_size=dp(14),
                color=(0.7, 0.7, 0.7, 1),
                size_hint_y=None,
                height=dp(60)
            )
            self.visitor_layout.add_widget(no_visitor_label)
            return

        for visitor in filtered_visitors:
            # Filter by search term (name)
            if search_term and search_term not in visitor[1].lower():
                continue

            # Determine status
            if not visitor[8]:
                status = "Pending"
                status_color = (1, 1, 0, 1)
            elif visitor[8] and not visitor[9]:
                status = "Inside the premises"
                status_color = (0, 1, 0, 1)
            else:
                status = "Already left the premises"
                status_color = (1, 0, 0, 1)

            if status_filter != 'All Statuses' and status != status_filter:
                continue

            # Display visitor
            visitor_widget = BoxLayout(
                orientation='vertical', size_hint_y=None, height=dp(250), padding=dp(10), spacing=dp(5)
            )

            # Info section
            info_layout = BoxLayout(orientation='vertical', size_hint_y=0.8)
            info_text = f"Name: {visitor[1]}\n"
            info_text += f"Purpose: {visitor[2]}\n"
            info_text += f"Person to Visit: {visitor[3]}\n"
            info_text += f"Date: {visitor[4]} | Time: {visitor[5]}\n"
            info_text += f"Email: {visitor[7] if visitor[7] else 'N/A'}\n"
            info_text += f"Valid ID: {visitor[6] if visitor[6] else 'N/A'}\n"
            info_text += f"First Time In: {visitor[10] if visitor[10] else '-'}\n"
            info_text += f"First Time Out: {visitor[11] if visitor[11] else '-'}\n"
            info_text += f"Current Time In: {visitor[8] if visitor[8] else '-'}\n"
            info_text += f"Current Time Out: {visitor[9] if visitor[9] else '-'}\n"

            visitor_label = Label(
                text=info_text,
                font_size=dp(12),
                halign='left',
                valign='top',
                color=(1, 1, 1, 1)
            )
            visitor_label.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
            info_layout.add_widget(visitor_label)

            status_label = Label(
                text=f"Status: {status}",
                font_size=dp(12),
                color=status_color,
                size_hint_y=None,
                height=dp(20)
            )
            info_layout.add_widget(status_label)
            visitor_widget.add_widget(info_layout)

            # Action buttons section
            if is_admin:
                action_layout = BoxLayout(size_hint_y=0.2, spacing=dp(5))

                # Show Approve/Decline buttons only for pending visitors
                if status == "Pending":
                    approve_btn = Button(
                        text='Approve',
                        background_color=(0, 0.8, 0, 1),
                        color=(1, 1, 1, 1)
                    )
                    approve_btn.bind(on_press=lambda x, v=visitor: self.approve_visitor(v))
                    action_layout.add_widget(approve_btn)

                    decline_btn = Button(
                        text='Decline',
                        background_color=(0.8, 0.4, 0, 1),
                        color=(1, 1, 1, 1)
                    )
                    decline_btn.bind(on_press=lambda x, v=visitor: self.decline_visitor(v))
                    action_layout.add_widget(decline_btn)

                # Delete button always available for admin
                delete_btn = Button(
                    text='Delete',
                    background_color=(0.8, 0.2, 0.2, 1),
                    color=(1, 1, 1, 1)
                )
                delete_btn.bind(on_press=lambda x, vid=visitor[0]: self.delete_visitor(vid))
                action_layout.add_widget(delete_btn)

                visitor_widget.add_widget(action_layout)

            with visitor_widget.canvas.before:
                Color(0.1529, 0.1529, 0.1647, 1)
                rect = Rectangle(pos=visitor_widget.pos, size=visitor_widget.size)

            def update_rect(instance, value, rect=rect):
                rect.pos = instance.pos
                rect.size = instance.size

            visitor_widget.bind(pos=update_rect, size=update_rect)
            self.visitor_layout.add_widget(visitor_widget)

    def approve_visitor(self, visitor):
        """Approve a visitor and send email notification"""
        visitor_id, name, reason, person_to_visit, visit_date, visit_time, valid_id, email = visitor[:8]

        if not email:
            self.show_popup('Error', 'No email address found for this visitor!')
            return

        # Update visitor as verified in database
        conn = App.get_running_app().db.visitors_db
        import sqlite3
        conn = sqlite3.connect(conn)
        cursor = conn.cursor()
        cursor.execute("UPDATE visitors SET is_verified = 1 WHERE id = ?", (visitor_id,))
        conn.commit()
        conn.close()

        # Send approval email
        subject = "Visitor Access Approved - GATE_PASS"
        body = f"""
Dear {name},

Your visitor request has been APPROVED!

Details:
- Purpose: {reason}
- Person to Visit: {person_to_visit}
- Date: {visit_date}
- Time: {visit_time}

Please present your QR code at the gate for entry.

Best regards,
GATE_PASS System
        """

        if self.send_email(email, subject, body):
            self.show_popup('Success', f'Visitor {name} approved and email sent!')
            self.refresh_visitors()
        else:
            self.show_popup('Warning', f'Visitor approved but email failed to send to {email}')
            self.refresh_visitors()

    def decline_visitor(self, visitor):
        """Show popup to get decline reason and send email"""
        visitor_id, name, reason, person_to_visit, visit_date, visit_time, valid_id, email = visitor[:8]

        if not email:
            self.show_popup('Error', 'No email address found for this visitor!')
            return

        layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        with layout.canvas.before:
            Color(0.2, 0.2, 0.2, 0.9)
            rect = RoundedRectangle(radius=[20], size=layout.size, pos=layout.pos)
            layout.bind(size=lambda *x: setattr(rect, 'size', layout.size),
                        pos=lambda *x: setattr(rect, 'pos', layout.pos))

        label = Label(
            text=f"Decline visitor: {name}\n\nPlease provide a reason:",
            color=(1, 1, 1, 1),
            font_size=dp(16),
            size_hint_y=0.3
        )

        reason_input = TextInput(
            hint_text='Enter reason for declining...',
            multiline=True,
            size_hint_y=0.4
        )

        button_layout = BoxLayout(size_hint_y=0.3, spacing=dp(10))
        submit_btn = Button(text='Submit', background_color=(0.8, 0.2, 0.2, 1))
        cancel_btn = Button(text='Cancel', background_color=(0.5, 0.5, 0.5, 1))

        popup = Popup(
            title='Decline Visitor',
            content=layout,
            size_hint=(0.85, 0.5),
            auto_dismiss=False
        )

        def on_submit(instance):
            decline_reason = reason_input.text.strip()
            if not decline_reason:
                self.show_popup('Error', 'Please provide a reason for declining!')
                return

            # Send decline email
            subject = "Visitor Access Declined - GATE_PASS"
            body = f"""
Dear {name},

We regret to inform you that your visitor request has been DECLINED.

Details of your request:
- Purpose: {reason}
- Person to Visit: {person_to_visit}
- Date: {visit_date}
- Time: {visit_time}

Reason for decline:
{decline_reason}

If you have any questions, please contact the administration.

Best regards,
GATE_PASS System
            """

            popup.dismiss()

            if self.send_email(email, subject, body):
                # Delete the visitor record after declining
                self.delete_visitor(visitor_id)
                self.show_popup('Success', f'Visitor {name} declined and email sent!')
            else:
                self.show_popup('Error', f'Failed to send decline email to {email}')

        submit_btn.bind(on_press=on_submit)
        cancel_btn.bind(on_press=popup.dismiss)

        button_layout.add_widget(submit_btn)
        button_layout.add_widget(cancel_btn)

        layout.add_widget(label)
        layout.add_widget(reason_input)
        layout.add_widget(button_layout)

        popup.open()

    def send_email(self, to_email, subject, body):
        """Send email notification"""
        try:
            smtp_server = "smtp.gmail.com"
            smtp_port = 587
            sender_email = "marvincunanan1236600@gmail.com"
            sender_password = "ntdvqukkehuzbuca"

            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = to_email
            msg['Subject'] = subject

            msg.attach(MIMEText(body, 'plain'))

            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
            server.quit()

            return True
        except Exception as e:
            print(f"Email error: {e}")
            return False

    def delete_visitor(self, visitor_id):
        if App.get_running_app().db.delete_visitor(visitor_id):
            self.refresh_visitors()
            self.show_popup('Success', 'Visitor deleted successfully!')
        else:
            self.show_popup('Error', 'Failed to delete visitor!')

    def show_popup(self, title, message):
        layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        with layout.canvas.before:
            Color(0.2, 0.2, 0.2, 0.9)
            rect = RoundedRectangle(radius=[20], size=layout.size, pos=layout.pos)
            layout.bind(size=lambda *x: setattr(rect, 'size', layout.size),
                        pos=lambda *x: setattr(rect, 'pos', layout.pos))

        message_label = Label(text=message, color=(1, 1, 1, 1), font_size=dp(16))
        close_btn = Button(
            text="Close",
            size_hint=(1, 0.3),
            background_color=(0.2, 0.6, 0.8, 1),
            color=(1, 1, 1, 1)
        )

        popup = Popup(title=title, content=layout, size_hint=(0.7, 0.4), auto_dismiss=False)
        close_btn.bind(on_release=popup.dismiss)

        layout.add_widget(message_label)
        layout.add_widget(close_btn)
        popup.open()


class NotificationsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'notifications'
        main_layout = BoxLayout(orientation='vertical')
        header = BoxLayout(size_hint_y=0.1, padding=dp(10))
        back_btn = Button(text='← Back', size_hint_x=0.2)
        back_btn.bind(on_press=lambda x: setattr(self.manager, 'current', 'dashboard'))
        header.add_widget(back_btn)
        header.add_widget(Label(text='Notifications', font_size=dp(18), bold=True))
        main_layout.add_widget(header)
        self.scroll = ScrollView()
        self.notification_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5))
        self.notification_layout.bind(minimum_height=self.notification_layout.setter('height'))
        self.scroll.add_widget(self.notification_layout)
        main_layout.add_widget(self.scroll)
        self.add_widget(main_layout)

        # Add a "Clear All" button in the header
        clear_btn = Button(text='Clear All', size_hint_x=0.3, background_color=(0.8, 0.2, 0.2, 1))
        clear_btn.bind(on_press=self.clear_all_notifications)
        header.add_widget(clear_btn)

        Clock.schedule_interval(self.refresh_notifications, 5)

    def on_enter(self):
        self.refresh_notifications()

    def clear_all_notifications(self, instance):
        app = App.get_running_app()
        app.db.update_last_check()
        self.refresh_notifications()

        # Reset the dashboard notification bell
        dashboard_screen = self.manager.get_screen('dashboard')
        dashboard_screen.notification_count = 0
        dashboard_screen.update_notification_display()

        # Show confirmation popup
        layout = BoxLayout(orientation='vertical', padding=20, spacing=15)
        message_label = Label(text='All notifications cleared!', color=(1, 1, 1, 1), font_size=18)
        close_btn = Button(text="OK", size_hint=(1, 0.3), background_color=(0.2, 0.8, 0.2, 1))
        popup = Popup(title='Success', content=layout, size_hint=(0.6, 0.3), auto_dismiss=True)
        close_btn.bind(on_release=popup.dismiss)
        layout.add_widget(message_label)
        layout.add_widget(close_btn)
        popup.open()

    def refresh_notifications(self, dt=None):
        app = App.get_running_app()
        last_check = app.db.get_last_check()
        new_visitors = app.db.get_new_visitors(last_check)

        self.notification_layout.clear_widgets()

        if not new_visitors:
            no_notif_label = Label(
                text='No new visitors',
                font_size=dp(14),
                color=(1, 1, 1, 1),
                size_hint_y=None,
                height=dp(50),
                halign='center',
                valign='middle'
            )
            self.notification_layout.add_widget(no_notif_label)
        else:
            for visitor in new_visitors:
                notif_widget = BoxLayout(
                    orientation='vertical',
                    size_hint_y=None,
                    height=dp(80),
                    padding=dp(10)
                )
                notif_text = f"New Visitor: {visitor[1]}\n"
                notif_text += f"Date: {visitor[2]} | Time: {visitor[3]}\n"
                notif_text += f"Added: {visitor[4]}"
                notif_label = Label(
                    text=notif_text,
                    font_size=dp(12),
                    color=(1, 1, 1, 1),
                    halign='left',
                    valign='top'
                )
                notif_label.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
                notif_widget.add_widget(notif_label)
                with notif_widget.canvas.before:
                    Color(0.1529, 0.1529, 0.1647, 1)
                    rect = Rectangle(pos=notif_widget.pos, size=notif_widget.size)

                def update_rect(instance, value, rect=rect):
                    rect.pos = instance.pos
                    rect.size = instance.size

                notif_widget.bind(pos=update_rect, size=update_rect)
                self.notification_layout.add_widget(notif_widget)

# Updated AccountScreen with Option 1 Background Image
# Place this inside your project and replace your current AccountScreen class

class AccountScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'account'
        self.built = False

    # -------------------------
    # Popup
    # -------------------------
    def show_popup(self, title, message):
        layout = BoxLayout(orientation='vertical', spacing=10, padding=10)

        label = Label(text=message)
        ok_btn = Button(text="OK", size_hint_y=0.3)

        layout.add_widget(label)
        layout.add_widget(ok_btn)

        popup = Popup(title=title, content=layout,
                      size_hint=(0.8, 0.3), auto_dismiss=False)

        ok_btn.bind(on_release=popup.dismiss)
        popup.open()

    # -------------------------
    # Screen Lifecycle
    # -------------------------
    def on_enter(self):
        if not self.built:
            self.build_ui()
            self.built = True

        app = App.get_running_app()
        if hasattr(app, 'user_role') and app.user_role == 'admin' and hasattr(self, 'accounts_layout'):
            self.refresh_accounts()

    # -------------------------
    # UI BUILD (WITH BACKGROUND)
    # -------------------------
    def build_ui(self):
        self.clear_widgets()

        # Root layout for stacking
        root = FloatLayout()

        # Background image
        bg = Image(
            source='static/Laco.png',  # your background image
            allow_stretch=True,
            keep_ratio=False,
            size_hint=(1, 1),
            pos_hint={'x': 0, 'y': 0}
        )
        root.add_widget(bg)

        # Main foreground layout
        main_layout = BoxLayout(orientation='vertical', size_hint=(1, 1))
        root.add_widget(main_layout)

        # Header
        header = BoxLayout(size_hint_y=0.1, padding=dp(10))
        back_btn = Button(text='← Back', size_hint_x=0.2)
        back_btn.bind(on_press=lambda x: setattr(self.manager, 'current', 'dashboard'))
        header.add_widget(back_btn)

        header.add_widget(Label(text='Account Management', font_size=dp(18), bold=True))
        main_layout.add_widget(header)

        # Admin or user section
        app = App.get_running_app()
        is_admin = hasattr(app, 'user_role') and app.user_role == 'admin'

        if is_admin:
            self.build_admin_ui(main_layout)
        else:
            self.build_user_ui(main_layout)

        # Logout button
        logout_btn = Button(text='Log Out', size_hint_y=0.2,
                            background_color=(0.8, 0.2, 0.2, 1))
        logout_btn.bind(on_press=self.logout)
        main_layout.add_widget(logout_btn)

        self.add_widget(root)

    # -------------------------
    # ADMIN UI
    # -------------------------
    def build_admin_ui(self, main_layout):
        add_section = BoxLayout(orientation='vertical', size_hint_y=0.35,
                                padding=dp(10), spacing=dp(10))

        add_section.add_widget(Label(text='Add New Account:', font_size=dp(16),
                                     bold=True, size_hint_y=0.2))

        form_layout = GridLayout(cols=2, spacing=dp(10), size_hint_y=0.7)

        form_layout.add_widget(Label(text='Username:'))
        self.new_username = TextInput(multiline=False)
        form_layout.add_widget(self.new_username)

        form_layout.add_widget(Label(text='Password:'))
        self.new_password = TextInput(password=True, multiline=False)
        form_layout.add_widget(self.new_password)

        form_layout.add_widget(Label(text='Confirm Password:'))
        self.confirm_password = TextInput(password=True, multiline=False)
        form_layout.add_widget(self.confirm_password)

        add_section.add_widget(form_layout)

        add_btn = Button(text='Add Account', size_hint_y=0.2)
        add_btn.bind(on_press=self.add_account)
        add_section.add_widget(add_btn)

        main_layout.add_widget(add_section)

        accounts_section = BoxLayout(orientation='vertical', size_hint_y=0.45)
        accounts_section.add_widget(Label(text='Existing Accounts:',
                                          font_size=dp(16), bold=True,
                                          size_hint_y=0.1))

        accounts_scroll = ScrollView()
        self.accounts_layout = BoxLayout(orientation='vertical',
                                         size_hint_y=None,
                                         spacing=dp(5))
        self.accounts_layout.bind(minimum_height=self.accounts_layout.setter('height'))
        accounts_scroll.add_widget(self.accounts_layout)
        accounts_section.add_widget(accounts_scroll)
        main_layout.add_widget(accounts_section)

    # -------------------------
    # USER UI
    # -------------------------
    def build_user_ui(self, main_layout):
        content_area = BoxLayout(orientation='vertical', size_hint_y=0.7, padding=dp(20))
        app = App.get_running_app()
        welcome_text = f'Welcome, {app.current_user if hasattr(app, "current_user") else "User"}!\n\nThis is your account page.'
        content_area.add_widget(Label(text=welcome_text, font_size=dp(16), halign='center'))
        main_layout.add_widget(content_area)

    # -------------------------
    # REFRESH ACCOUNTS
    # -------------------------
    def refresh_accounts(self):
        try:
            accounts = App.get_running_app().db.get_accounts()
            self.accounts_layout.clear_widgets()

            for account in accounts:
                account_widget = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))

                account_widget.add_widget(Label(text=f"{account[0]} ({account[1]})",
                                                font_size=dp(14)))

                if account[0] != 'admin':
                    delete_btn = Button(text='Delete', size_hint_x=0.3,
                                        background_color=(0.8, 0.2, 0.2, 1))
                    delete_btn.bind(on_press=lambda x, username=account[0]:
                                    self.delete_account(username))
                    account_widget.add_widget(delete_btn)

                self.accounts_layout.add_widget(account_widget)

        except Exception as e:
            print(f"Error refreshing accounts: {e}")

    # -------------------------
    # ADD ACCOUNT
    # -------------------------
    def add_account(self, instance):
        try:
            username = self.new_username.text.strip()
            password = self.new_password.text.strip()
            confirm_password = self.confirm_password.text.strip()

            if not username or not password or not confirm_password:
                self.show_popup('Error', 'All fields are required.')
                return

            if password != confirm_password:
                self.show_popup('Error', 'Passwords do not match!')
                return

            if len(password) < 6:
                self.show_popup('Error', 'Password must be at least 6 characters.')
                return

            if not any(c.isdigit() for c in password):
                self.show_popup('Error', 'Password must contain at least one number.')
                return

            if not any(c.isalpha() for c in password):
                self.show_popup('Error', 'Password must contain at least one letter.')
                return

            special_chars = "!@#$%^&*()-_=+[]{};:'\",.<>?/\\|`~"
            if not any(c in special_chars for c in password):
                self.show_popup('Error', 'Password must contain at least one\n special character(!@#$ etc).')
                return

            if App.get_running_app().db.add_account(username, password):
                self.new_username.text = ''
                self.new_password.text = ''
                self.confirm_password.text = ''
                self.refresh_accounts()
                self.show_popup('Success', 'Account added successfully!')
            else:
                self.show_popup('Error', 'Username already exists!')

        except Exception as e:
            print(f"Error adding account: {e}")

    # -------------------------
    # DELETE ACCOUNT
    # -------------------------
    def delete_account(self, username):
        if App.get_running_app().db.delete_account(username):
            self.refresh_accounts()
            self.show_popup('Success', 'Account deleted successfully!')
        else:
            self.show_popup('Error', 'Failed to delete account!')

    # -------------------------
    # LOGOUT
    # -------------------------
    def logout(self, instance):
        app = App.get_running_app()
        app.current_user = None
        app.user_role = None
        self.built = False
        self.manager.current = 'login'


class QRScannerScreen(Screen):
    def __init__(self, db_manager, **kwargs):
        super().__init__(**kwargs)
        self.name = "qr_scanner"
        self.db = db_manager
        self.qr_detected = False
        self.capture = None
        self.event = None
        main_layout = BoxLayout(orientation="vertical", padding=10, spacing=10)

        # Header with back button and manual entry button
        header = BoxLayout(size_hint_y=0.1, padding=5, spacing=10)
        back_btn = Button(text="Back", size_hint=(0.2, 0.5))
        back_btn.bind(on_press=self.go_back)
        header.add_widget(back_btn)
        header.add_widget(Label(text="QR Scanner", font_size=18, bold=True))

        # Add manual entry button for events
        manual_entry_btn = Button(
            text="+Visitor",
            size_hint=(0.3, 0.5),
            background_color=(0.2, 0.6, 1, 1)
        )
        manual_entry_btn.bind(on_press=self.show_manual_entry_popup)
        header.add_widget(manual_entry_btn)

        main_layout.add_widget(header)

        camera_container = BoxLayout(size_hint_y=0.6, padding=10)
        self.camera = Camera(play=False)
        self.camera.resolution = (640, 480)
        self.camera.allow_stretch = True
        self.camera.keep_ratio = True
        with camera_container.canvas.before:
            Color(0, 1, 0, 1)
            self.border = Line(rectangle=(0, 0, 0, 0), width=2)
        camera_container.add_widget(self.camera)
        main_layout.add_widget(camera_container)

        footer = Label(
            text="Place QR Code inside the green box or use Event Visitor button",
            size_hint_y=0.1,
            font_size=14,
            color=(0.7, 0.7, 0.7, 1)
        )
        main_layout.add_widget(footer)
        self.add_widget(main_layout)
        camera_container.bind(size=self.update_border, pos=self.update_border)

    def update_border(self, instance, value):
        self.border.rectangle = (
            instance.x,
            instance.y,
            instance.width,
            instance.height
        )

    def on_enter(self):
        try:
            self.capture = cv2.VideoCapture(0)
            if not self.capture.isOpened():
                raise Exception("Camera not available")
            self.qr_detected = False
            self.event = Clock.schedule_interval(self.update, 1.0 / 30.0)
        except Exception as e:
            self.show_popup("Error", f"Camera failed: {str(e)}\nUse test button for demo.")

    def on_leave(self):
        if self.capture:
            self.capture.release()
            self.capture = None
        if self.event:
            self.event.cancel()
            self.event = None

    def update(self, dt):
        if not self.capture:
            return
        ret, frame = self.capture.read()
        if not ret:
            return
        frame = cv2.flip(frame, 0)
        decoded_objs = decode(frame)
        if decoded_objs and not self.qr_detected:
            qr_data = decoded_objs[0].data.decode("utf-8")
            self.qr_detected = True
            self.verify_visitor(qr_data)
        buf = cv2.flip(frame, 1).tobytes()
        texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt="bgr")
        texture.blit_buffer(buf, colorfmt="bgr", bufferfmt="ubyte")
        self.camera.texture = texture

    def show_manual_entry_popup(self, instance):
        """Show popup for manually adding event visitors"""
        layout = BoxLayout(orientation='vertical', padding=20, spacing=15)
        with layout.canvas.before:
            Color(0.2, 0.2, 0.2, 0.9)
            self.rect = RoundedRectangle(radius=[20], size=layout.size, pos=layout.pos)
            layout.bind(size=lambda *x: setattr(self.rect, 'size', layout.size),
                        pos=lambda *x: setattr(self.rect, 'pos', layout.pos))

        title_label = Label(
            text="Quick Event Visitor Entry",
            color=(1, 1, 1, 1),
            font_size=20,
            bold=True,
            size_hint_y=0.12
        )

        # Input fields
        form_layout = BoxLayout(orientation='vertical', spacing=10, size_hint_y=0.73)

        name_input = TextInput(
            hint_text="Visitor Name *",
            multiline=False,
            size_hint_y=None,
            height=40
        )

        reason_input = TextInput(
            hint_text="Event (what's the event) *",
            multiline=False,
            size_hint_y=None,
            height=40
        )

        person_input = TextInput(
            hint_text="Relative Inside *",
            multiline=False,
            size_hint_y=None,
            height=40
        )

        email_input = TextInput(
            hint_text="Email Address *",
            multiline=False,
            size_hint_y=None,
            height=40
        )

        valid_id_input = TextInput(
            hint_text="ID (ex:TIN,Driver's License etc)",
            multiline=False,
            size_hint_y=None,
            height=40
        )

        form_layout.add_widget(name_input)
        form_layout.add_widget(reason_input)
        form_layout.add_widget(person_input)
        form_layout.add_widget(email_input)
        form_layout.add_widget(valid_id_input)

        # Buttons
        button_layout = BoxLayout(orientation='horizontal', size_hint_y=0.15, spacing=10)
        add_btn = Button(
            text="Add Visitor",
            background_color=(0, 1, 0, 1),
            color=(1, 1, 1, 1)
        )
        cancel_btn = Button(
            text="Cancel",
            background_color=(1, 0, 0, 1),
            color=(1, 1, 1, 1)
        )

        popup = Popup(
            title="Manual Event Entry",
            content=layout,
            size_hint=(0.9, 0.75),
            auto_dismiss=False
        )

        def on_add(instance):
            name = name_input.text.strip()
            reason = reason_input.text.strip()
            person_to_visit = person_input.text.strip()
            email = email_input.text.strip()
            valid_id = valid_id_input.text.strip()

            if not name or not reason or not person_to_visit or not email:
                self.show_popup("Error", "Please fill in all required fields (*)")
                return

            # Add visitor to database
            now_date = datetime.now().strftime("%Y-%m-%d")
            now_time = datetime.now().strftime("%H:%M:%S")
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            try:
                # Create visitor record for event
                visitor_id = self.db.add_event_visitor(
                    name=name,
                    reason=reason,
                    person_to_visit=person_to_visit,
                    visit_date=now_date,
                    visit_time=now_time,
                    valid_id=valid_id if valid_id else None,
                    email=email,
                    time_in=now_time,
                    created_at=created_at
                )

                popup.dismiss()
                self.show_popup(
                    "Success ✅",
                    f"Visitor added and checked in!\n\n"
                    f"Name: {name}\n"
                    f"Reason: {reason}\n"
                    f"Person to Visit: {person_to_visit}\n"
                    f"Email: {email}\n"
                    f"Valid ID: {valid_id if valid_id else 'N/A'}\n"
                    f"Time In: {now_time}"
                )
            except Exception as e:
                self.show_popup("Error", f"Failed to add visitor: {str(e)}")

        add_btn.bind(on_press=on_add)
        cancel_btn.bind(on_press=popup.dismiss)

        button_layout.add_widget(add_btn)
        button_layout.add_widget(cancel_btn)

        layout.add_widget(title_label)
        layout.add_widget(form_layout)
        layout.add_widget(button_layout)

        popup.open()

    def verify_visitor(self, qr_data):
        visitors = self.db.get_visitors()
        found = False
        qr_data_clean = ' '.join(qr_data.lower().split())

        for visitor in visitors:
            visitor_id = visitor[0]
            name = visitor[1] or ''
            reason = visitor[2] or ''
            person_to_visit = visitor[3] or ''
            visit_date = visitor[4]
            visit_time = visitor[5]
            valid_id_file = visitor[6] or ''
            email = visitor[7] or ''
            time_in = visitor[8]
            time_out = visitor[9]
            first_time_in = visitor[10]
            first_time_out = visitor[11]

            # Clean visitor data
            visitor_name_clean = ' '.join(name.lower().split())
            visitor_person_clean = ' '.join(person_to_visit.lower().split())
            visitor_id_clean = ' '.join(valid_id_file.lower().split())

            # Flexible matching: Name + Person to Visit (always) + Valid ID (optional)
            if visitor_name_clean in qr_data_clean and visitor_person_clean in qr_data_clean:
                # If valid ID exists in DB and QR, check it; otherwise ignore
                if visitor_id_clean:
                    if visitor_id_clean in qr_data_clean:
                        match = True
                    else:
                        match = False
                else:
                    match = True
                if match:
                    found = True
                    now = datetime.now().strftime("%H:%M:%S")

                    if not time_in:
                        self.db.update_time_in(visitor_id, now)
                        message = (f"✅ Check-In Successful!\n\n"
                                   f"Name: {name}\n"
                                   f"Reason: {reason}\n"
                                   f"Person to visit: {person_to_visit}\n"
                                   f"First Time In: {now}\n"
                                   f"Current Time In: {now}")
                        self.show_popup("Visitor Verified", message)
                    elif not time_out:
                        self.db.update_time_out(visitor_id, now)
                        message = (f"✅ Check-Out Successful!\n\n"
                                   f"Name: {name}\n"
                                   f"Reason: {reason}\n"
                                   f"Person to visit: {person_to_visit}\n"
                                   f"First Time In: {first_time_in if first_time_in else '-'}\n"
                                   f"First Time Out: {now}\n"
                                   f"Current Time Out: {now}")
                        self.show_popup("Visitor Verified", message)
                    else:
                        if "/" in reason:
                            self.show_popup("Re-Entry Limit Reached", "Only one re-entry allowed per visitor.")
                        else:
                            self.show_reentry_popup(visitor_id, name, reason, first_time_in, first_time_out)
                    break

        if not found:
            self.show_popup("Not Found ❌", f"No visitor with QR data:\n{qr_data}")

    def show_popup(self, title, message):
        layout = BoxLayout(orientation='vertical', padding=20, spacing=15)
        with layout.canvas.before:
            Color(0.2, 0.2, 0.2, 0.9)
            self.rect = RoundedRectangle(radius=[20], size=layout.size, pos=layout.pos)
            layout.bind(size=lambda *x: setattr(self.rect, 'size', layout.size),
                        pos=lambda *x: setattr(self.rect, 'pos', layout.pos))
        message_label = Label(text=message, color=(1, 1, 1, 1), font_size=18)
        close_btn = Button(text="Close", size_hint=(1, 0.3), background_color=(1, 0, 0, 1), color=(1, 1, 1, 1))
        popup = Popup(title=title, content=layout, size_hint=(0.85, 0.5), auto_dismiss=False)
        close_btn.bind(on_release=popup.dismiss)
        popup.bind(on_dismiss=lambda *args: self.reset_scanner())
        layout.add_widget(message_label)
        layout.add_widget(close_btn)
        popup.open()

    def show_reentry_popup(self, visitor_id, name, old_reason, first_time_in, first_time_out):
        layout = BoxLayout(orientation='vertical', padding=20, spacing=15)
        with layout.canvas.before:
            Color(0.2, 0.2, 0.2, 0.9)
            self.rect = RoundedRectangle(radius=[20], size=layout.size, pos=layout.pos)
            layout.bind(size=lambda *x: setattr(self.rect, 'size', layout.size),
                        pos=lambda *x: setattr(self.rect, 'pos', layout.pos))
        message_label = Label(
            text=(f"⚠️ Already Checked Out!\n\n"
                  f"Name: {name}\n"
                  f"Current Reason: {old_reason}\n"
                  f"First Time In: {first_time_in if first_time_in else '-'}\n"
                  f"First Time Out: {first_time_out if first_time_out else '-'}\n\n"
                  f"Would you like to re-enter?"),
            color=(1, 1, 1, 1),
            font_size=18
        )
        reason_input = TextInput(hint_text="Enter reason for re-entry", multiline=False, size_hint_y=0.3)
        button_layout = BoxLayout(orientation='horizontal', size_hint_y=0.3, spacing=10)
        confirm_btn = Button(text="Confirm", background_color=(0, 1, 0, 1), color=(1, 1, 1, 1))
        cancel_btn = Button(text="Cancel", background_color=(1, 0, 0, 1), color=(1, 1, 1, 1))
        popup = Popup(title="Visitor Re-Entry", content=layout, size_hint=(0.85, 0.6), auto_dismiss=False)

        def on_confirm(instance):
            new_reason = reason_input.text.strip()
            if not new_reason:
                self.show_popup("Error", "Please enter a reason for re-entry")
                return
            new_time_in = self.db.update_visitor_reentry(visitor_id, new_reason)
            popup.dismiss()
            self.show_popup("Re-Entry Successful",
                            f"✅ Re-Entry Successful!\n\n"
                            f"Name: {name}\n"
                            f"Updated Reason: {old_reason} / {new_reason}\n"
                            f"First Time In: {first_time_in if first_time_in else '-'}\n"
                            f"First Time Out: {first_time_out if first_time_out else '-'}\n"
                            f"Current Time In: {new_time_in}")

        confirm_btn.bind(on_press=on_confirm)
        cancel_btn.bind(on_press=popup.dismiss)
        popup.bind(on_dismiss=lambda *args: self.reset_scanner())
        button_layout.add_widget(confirm_btn)
        button_layout.add_widget(cancel_btn)
        layout.add_widget(message_label)
        layout.add_widget(reason_input)
        layout.add_widget(button_layout)
        popup.open()

    def reset_scanner(self):
        Clock.schedule_once(lambda dt: self._reset_flag(), 1)

    def _reset_flag(self):
        self.qr_detected = False

    def go_back(self, instance):
        self.manager.current = "dashboard"

class GatePassApp(App):
    def build(self):
        self.title = 'GATE_PASS'
        self.db = DatabaseManager()
        self.current_user = None
        self.user_role = None
        sm = ScreenManager()
        sm.add_widget(LoginScreen())
        sm.add_widget(DashboardScreen())
        sm.add_widget(MessagesScreen())
        sm.add_widget(VisitorLogScreen())
        sm.add_widget(NotificationsScreen())
        sm.add_widget(AccountScreen())
        sm.add_widget(QRScannerScreen(self.db))
        return sm

if __name__ == '__main__':
    GatePassApp().run()