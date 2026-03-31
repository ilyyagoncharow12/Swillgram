import os
import uuid
import sqlite3
import hashlib
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'xgram-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# Use file-based database for Render
DATABASE_PATH = os.environ.get('DATABASE_PATH', 'xgram.db')

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'avatars'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'files'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'photos'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'videos'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'audio'), exist_ok=True)


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            avatar TEXT,
            bio TEXT,
            last_seen DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Chats table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER NOT NULL,
            user2_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user1_id, user2_id)
        )
    ''')

    # Messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            content TEXT,
            file_type TEXT,
            file_path TEXT,
            file_name TEXT,
            file_size INTEGER,
            is_read BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )
    ''')

    # Calls table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            call_type TEXT,
            status TEXT,
            duration INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (caller_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        )
    ''')

    # Contacts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, contact_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (contact_id) REFERENCES users(id)
        )
    ''')

    # Favorites table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            file_type TEXT,
            file_path TEXT,
            file_name TEXT,
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def create_user(phone, username, password):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO users (phone, username, password, last_seen) VALUES (?, ?, ?, ?)',
            (phone, username, hash_password(password), datetime.now())
        )
        conn.commit()
        user_id = cursor.lastrowid
        return user_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_by_phone(phone):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE phone = ?', (phone,))
    user = cursor.fetchone()
    conn.close()
    return user


def get_user_by_username(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    conn.close()
    return user


def get_user_by_id(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user


def verify_user(phone, password):
    user = get_user_by_phone(phone)
    if user and user['password'] == hash_password(password):
        return user
    return None


def get_or_create_chat(user1_id, user2_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT id FROM chats WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)',
        (user1_id, user2_id, user2_id, user1_id)
    )
    chat = cursor.fetchone()

    if chat:
        return chat['id']

    cursor.execute(
        'INSERT INTO chats (user1_id, user2_id) VALUES (?, ?)',
        (user1_id, user2_id)
    )
    conn.commit()
    chat_id = cursor.lastrowid
    conn.close()
    return chat_id


def get_user_chats(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT c.id as chat_id, 
               CASE WHEN c.user1_id = ? THEN c.user2_id ELSE c.user1_id END as other_user_id,
               u.username, u.phone, u.avatar, u.bio,
               m.content as last_message,
               m.file_type as last_file_type,
               m.created_at as last_message_time,
               m.is_read,
               m.sender_id as last_sender_id,
               (SELECT COUNT(*) FROM messages WHERE chat_id = c.id AND sender_id != ? AND is_read = 0) as unread_count
        FROM chats c
        JOIN users u ON (CASE WHEN c.user1_id = ? THEN c.user2_id ELSE c.user1_id END) = u.id
        LEFT JOIN messages m ON m.id = (
            SELECT id FROM messages WHERE chat_id = c.id ORDER BY created_at DESC LIMIT 1
        )
        WHERE c.user1_id = ? OR c.user2_id = ?
        ORDER BY m.created_at DESC
    ''', (user_id, user_id, user_id, user_id, user_id))

    chats = cursor.fetchall()
    conn.close()
    return chats


def get_messages(chat_id, user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        'UPDATE messages SET is_read = 1 WHERE chat_id = ? AND sender_id != ?',
        (chat_id, user_id)
    )
    conn.commit()

    cursor.execute('''
        SELECT m.*, u.username, u.avatar 
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.chat_id = ?
        ORDER BY m.created_at ASC
    ''', (chat_id,))

    messages = cursor.fetchall()
    conn.close()
    return messages


def send_message(chat_id, sender_id, content, file_type=None, file_path=None, file_name=None, file_size=None):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO messages (chat_id, sender_id, content, file_type, file_path, file_name, file_size)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (chat_id, sender_id, content, file_type, file_path, file_name, file_size))

    conn.commit()
    message_id = cursor.lastrowid

    cursor.execute('''
        SELECT m.*, u.username, u.avatar 
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.id = ?
    ''', (message_id,))

    message = cursor.fetchone()
    conn.close()
    return message


def add_contact(user_id, contact_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO contacts (user_id, contact_id) VALUES (?, ?)',
            (user_id, contact_id)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_contacts(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT u.*, c.created_at as added_at
        FROM contacts c
        JOIN users u ON c.contact_id = u.id
        WHERE c.user_id = ?
        ORDER BY u.username
    ''', (user_id,))

    contacts = cursor.fetchall()
    conn.close()
    return contacts


def search_users(query, current_user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, username, phone, avatar, bio
        FROM users
        WHERE (username LIKE ? OR phone LIKE ?) AND id != ?
        LIMIT 20
    ''', (f'%{query}%', f'%{query}%', current_user_id))

    users = cursor.fetchall()
    conn.close()
    return users


def add_call(caller_id, receiver_id, call_type, status):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO calls (caller_id, receiver_id, call_type, status)
        VALUES (?, ?, ?, ?)
    ''', (caller_id, receiver_id, call_type, status))

    conn.commit()
    call_id = cursor.lastrowid
    conn.close()
    return call_id


def update_call_status(call_id, status, duration=0):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        'UPDATE calls SET status = ?, duration = ? WHERE id = ?',
        (status, duration, call_id)
    )
    conn.commit()
    conn.close()


def get_call_history(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT c.*,
               CASE WHEN c.caller_id = ? THEN u2.username ELSE u1.username END as contact_name,
               CASE WHEN c.caller_id = ? THEN u2.avatar ELSE u1.avatar END as contact_avatar,
               CASE WHEN c.caller_id = ? THEN u2.id ELSE u1.id END as contact_id,
               c.caller_id = ? as is_outgoing
        FROM calls c
        JOIN users u1 ON c.caller_id = u1.id
        JOIN users u2 ON c.receiver_id = u2.id
        WHERE c.caller_id = ? OR c.receiver_id = ?
        ORDER BY c.created_at DESC
        LIMIT 50
    ''', (user_id, user_id, user_id, user_id, user_id, user_id))

    calls = cursor.fetchall()
    conn.close()
    return calls


def update_user(user_id, **kwargs):
    conn = get_db()
    cursor = conn.cursor()

    for key, value in kwargs.items():
        if value is not None:
            cursor.execute(f'UPDATE users SET {key} = ? WHERE id = ?', (value, user_id))

    conn.commit()
    conn.close()


def delete_user(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
    cursor.execute('DELETE FROM contacts WHERE user_id = ? OR contact_id = ?', (user_id, user_id))
    cursor.execute('DELETE FROM chats WHERE user1_id = ? OR user2_id = ?', (user_id, user_id))
    cursor.execute('DELETE FROM messages WHERE sender_id = ?', (user_id,))
    cursor.execute('DELETE FROM calls WHERE caller_id = ? OR receiver_id = ?', (user_id, user_id))
    cursor.execute('DELETE FROM favorites WHERE user_id = ?', (user_id,))

    conn.commit()
    conn.close()


def add_to_favorites(user_id, file_type, file_path, file_name, note=None):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO favorites (user_id, file_type, file_path, file_name, note)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, file_type, file_path, file_name, note))

    conn.commit()
    fav_id = cursor.lastrowid
    conn.close()
    return fav_id


def get_favorites(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT * FROM favorites
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,))

    favorites = cursor.fetchall()
    conn.close()
    return favorites


def update_last_seen(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE users SET last_seen = ? WHERE id = ?',
        (datetime.now(), user_id)
    )
    conn.commit()
    conn.close()


# Flask routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('chat_page'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone')
        password = request.form.get('password')

        user = verify_user(phone, password)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['phone'] = user['phone']
            update_last_seen(user['id'])
            return redirect(url_for('chat_page'))
        else:
            return render_template('login.html', error='Неверный номер телефона или пароль')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        phone = request.form.get('phone')
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if len(password) < 8:
            return render_template('register.html', error='Пароль должен быть не менее 8 символов')

        if password != confirm_password:
            return render_template('register.html', error='Пароли не совпадают')

        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return render_template('register.html',
                                   error='Имя пользователя может содержать только латинские буквы, цифры и нижнее подчеркивание')

        user_id = create_user(phone, username, password)
        if user_id:
            session['user_id'] = user_id
            session['username'] = username
            session['phone'] = phone
            return redirect(url_for('chat_page'))
        else:
            return render_template('register.html', error='Пользователь с таким номером или именем уже существует')

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/chat')
def chat_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = get_user_by_id(session['user_id'])
    chats = get_user_chats(session['user_id'])
    contacts = get_contacts(session['user_id'])
    call_history = get_call_history(session['user_id'])
    favorites = get_favorites(session['user_id'])

    chat_list = []
    for chat in chats:
        chat_list.append({
            'id': chat['chat_id'],
            'user_id': chat['other_user_id'],
            'username': chat['username'],
            'avatar': chat['avatar'],
            'last_message': chat['last_message'],
            'last_file_type': chat['last_file_type'],
            'last_message_time': chat['last_message_time'],
            'unread_count': chat['unread_count'],
            'is_read': chat['is_read'] if chat['last_sender_id'] != session['user_id'] else True
        })

    return render_template('index.html',
                           user=user,
                           chats=chat_list,
                           contacts=contacts,
                           call_history=call_history,
                           favorites=favorites)


# API routes
@app.route('/api/search_users')
def api_search_users():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    query = request.args.get('q', '')
    users = search_users(query, session['user_id'])

    return jsonify([{
        'id': u['id'],
        'username': u['username'],
        'phone': u['phone'],
        'avatar': u['avatar'],
        'bio': u['bio']
    } for u in users])


@app.route('/api/add_contact', methods=['POST'])
def api_add_contact():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    contact_id = data.get('contact_id')

    if add_contact(session['user_id'], contact_id):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Already in contacts'}), 400


@app.route('/api/get_chat/<int:user_id>')
def api_get_chat(user_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    chat_id = get_or_create_chat(session['user_id'], user_id)
    messages = get_messages(chat_id, session['user_id'])
    other_user = get_user_by_id(user_id)

    return jsonify({
        'chat_id': chat_id,
        'other_user': {
            'id': other_user['id'],
            'username': other_user['username'],
            'phone': other_user['phone'],
            'avatar': other_user['avatar'],
            'bio': other_user['bio']
        },
        'messages': [{
            'id': m['id'],
            'sender_id': m['sender_id'],
            'content': m['content'],
            'file_type': m['file_type'],
            'file_path': m['file_path'],
            'file_name': m['file_name'],
            'file_size': m['file_size'],
            'is_read': m['is_read'],
            'created_at': m['created_at'],
            'sender_username': m['username'],
            'sender_avatar': m['avatar']
        } for m in messages]
    })


@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    chat_id = request.form.get('chat_id')
    content = request.form.get('content', '')

    file_type = None
    file_path = None
    file_name = None
    file_size = None

    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            file_name = secure_filename(file.filename)
            ext = file_name.rsplit('.', 1)[1].lower() if '.' in file_name else ''

            if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                file_type = 'photo'
            elif ext in ['mp4', 'webm', 'avi', 'mov']:
                file_type = 'video'
            elif ext in ['mp3', 'wav', 'ogg', 'm4a']:
                file_type = 'audio'
            else:
                file_type = 'document'

            unique_name = f"{uuid.uuid4().hex}.{ext}"
            folder = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_type}s")
            os.makedirs(folder, exist_ok=True)
            file_path = os.path.join(folder, unique_name)
            file.save(file_path)
            file_size = os.path.getsize(file_path)
            file_path = f"uploads/{file_type}s/{unique_name}"

    message = send_message(
        chat_id=chat_id,
        sender_id=session['user_id'],
        content=content,
        file_type=file_type,
        file_path=file_path,
        file_name=file_name,
        file_size=file_size
    )

    socketio.emit('new_message', {
        'chat_id': chat_id,
        'message': {
            'id': message['id'],
            'sender_id': message['sender_id'],
            'content': message['content'],
            'file_type': message['file_type'],
            'file_path': message['file_path'],
            'file_name': message['file_name'],
            'file_size': message['file_size'],
            'is_read': message['is_read'],
            'created_at': message['created_at'],
            'sender_username': message['username'],
            'sender_avatar': message['avatar']
        }
    }, room=f"chat_{chat_id}")

    return jsonify({'success': True, 'message': dict(message)})


@app.route('/api/mark_read', methods=['POST'])
def api_mark_read():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    chat_id = data.get('chat_id')

    get_messages(chat_id, session['user_id'])

    socketio.emit('messages_read', {
        'chat_id': chat_id,
        'user_id': session['user_id']
    }, room=f"chat_{chat_id}")

    return jsonify({'success': True})


@app.route('/api/make_call', methods=['POST'])
def api_make_call():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    receiver_id = data.get('receiver_id')
    call_type = data.get('call_type')

    call_id = add_call(session['user_id'], receiver_id, call_type, 'ringing')

    socketio.emit('incoming_call', {
        'call_id': call_id,
        'caller_id': session['user_id'],
        'caller_name': session['username'],
        'call_type': call_type
    }, room=f"user_{receiver_id}")

    return jsonify({'success': True, 'call_id': call_id})


@app.route('/api/answer_call', methods=['POST'])
def api_answer_call():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    call_id = data.get('call_id')

    update_call_status(call_id, 'answered')

    socketio.emit('call_answered', {
        'call_id': call_id,
        'user_id': session['user_id']
    })

    return jsonify({'success': True})


@app.route('/api/end_call', methods=['POST'])
def api_end_call():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    call_id = data.get('call_id')
    duration = data.get('duration', 0)

    update_call_status(call_id, 'ended', duration)

    return jsonify({'success': True})


@app.route('/api/update_profile', methods=['POST'])
def api_update_profile():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    username = request.form.get('username')
    bio = request.form.get('bio')

    updates = {}
    if username:
        existing = get_user_by_username(username)
        if existing and existing['id'] != session['user_id']:
            return jsonify({'success': False, 'error': 'Username already taken'}), 400
        updates['username'] = username
        session['username'] = username

    if bio is not None:
        updates['bio'] = bio

    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
            unique_name = f"{uuid.uuid4().hex}.{ext}"
            folder = os.path.join(app.config['UPLOAD_FOLDER'], 'avatars')
            os.makedirs(folder, exist_ok=True)
            file_path = os.path.join(folder, unique_name)
            file.save(file_path)
            updates['avatar'] = f"uploads/avatars/{unique_name}"

    if updates:
        update_user(session['user_id'], **updates)

    return jsonify({'success': True, 'user': updates})


@app.route('/api/add_to_favorites', methods=['POST'])
def api_add_to_favorites():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    note = request.form.get('note')
    file = request.files.get('file')

    file_type = None
    file_path = None
    file_name = None

    if file and file.filename:
        file_name = secure_filename(file.filename)
        ext = file_name.rsplit('.', 1)[1].lower() if '.' in file_name else ''

        if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
            file_type = 'photo'
        elif ext in ['mp4', 'webm', 'avi', 'mov']:
            file_type = 'video'
        elif ext in ['mp3', 'wav', 'ogg', 'm4a']:
            file_type = 'audio'
        else:
            file_type = 'document'

        unique_name = f"{uuid.uuid4().hex}.{ext}"
        folder = os.path.join(app.config['UPLOAD_FOLDER'], 'favorites')
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, unique_name)
        file.save(file_path)
        file_path = f"uploads/favorites/{unique_name}"

    fav_id = add_to_favorites(session['user_id'], file_type, file_path, file_name, note)

    return jsonify({'success': True, 'favorite_id': fav_id})


@app.route('/api/get_favorites')
def api_get_favorites():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    favorites = get_favorites(session['user_id'])

    return jsonify({
        'favorites': [{
            'id': f['id'],
            'file_type': f['file_type'],
            'file_path': f['file_path'],
            'file_name': f['file_name'],
            'note': f['note'],
            'created_at': f['created_at']
        } for f in favorites]
    })


@app.route('/api/delete_account', methods=['POST'])
def api_delete_account():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    confirmation = data.get('confirmation', '')

    user = get_user_by_id(session['user_id'])

    if confirmation == user['phone'] or confirmation == user['username']:
        delete_user(session['user_id'])
        session.clear()
        return jsonify({'success': True})

    return jsonify({'success': False, 'error': 'Incorrect confirmation'}), 400


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))


# Socket.IO events
@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        join_room(f"user_{session['user_id']}")
        emit('connected', {'user_id': session['user_id']})


@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        leave_room(f"user_{session['user_id']}")


@socketio.on('join_chat')
def handle_join_chat(data):
    if 'user_id' in session:
        chat_id = data.get('chat_id')
        join_room(f"chat_{chat_id}")


@socketio.on('leave_chat')
def handle_leave_chat(data):
    if 'user_id' in session:
        chat_id = data.get('chat_id')
        leave_room(f"chat_{chat_id}")


@socketio.on('typing')
def handle_typing(data):
    if 'user_id' in session:
        chat_id = data.get('chat_id')
        emit('user_typing', {
            'user_id': session['user_id'],
            'username': session['username']
        }, room=f"chat_{chat_id}")


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)