from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Message, Group, GroupMember, generate_unique_id
import os
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Создаем папку для загрузок
os.makedirs('static/uploads', exist_ok=True)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            return 'Заполните все поля', 400

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('chat'))
        return 'Неверное имя пользователя или пароль', 401
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if not username or not email or not password:
            return 'Заполните все поля', 400

        if User.query.filter_by(username=username).first():
            return 'Имя пользователя уже занято', 400

        if User.query.filter_by(email=email).first():
            return 'Email уже используется', 400

        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('chat'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/chat')
@login_required
def chat():
    users = User.query.filter(User.id != current_user.id).all()
    groups = Group.query.join(GroupMember).filter(GroupMember.user_id == current_user.id).all()
    return render_template('index.html', users=users, groups=groups)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        if 'username' in request.form:
            current_user.username = request.form['username']
        if 'status' in request.form:
            current_user.status = request.form['status']

        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename:
                filename = f"{current_user.id}_{file.filename}"
                file.save(os.path.join('static/uploads', filename))
                current_user.profile_picture = filename

        db.session.commit()
        return redirect(url_for('profile'))
    return render_template('profile.html', user=current_user)


@app.route('/create_group', methods=['POST'])
@login_required
def create_group():
    name = request.form.get('name')
    if not name:
        return 'Название группы обязательно', 400

    new_group = Group(name=name, creator_id=current_user.id)
    db.session.add(new_group)
    db.session.commit()

    member = GroupMember(user_id=current_user.id, group_id=new_group.id)
    db.session.add(member)
    db.session.commit()

    return redirect(url_for('chat'))


# WebSocket события
@socketio.on('join')
def handle_join(data):
    room = data['room']
    join_room(room)


@socketio.on('send_message')
def handle_message(data):
    msg = Message(
        sender_id=current_user.id,
        recipient_id=data.get('recipient_id'),
        group_id=data.get('group_id'),
        content=data['content'],
        type=data.get('type', 'text')
    )
    db.session.add(msg)
    db.session.commit()

    room = None
    if data.get('group_id'):
        room = f'group_{data["group_id"]}'
    elif data.get('recipient_id'):
        room = f'user_{data["recipient_id"]}'

    emit('new_message', {
        'id': msg.id,
        'sender': current_user.username,
        'content': msg.content,
        'type': msg.type,
        'timestamp': msg.timestamp.isoformat(),
        'group_id': msg.group_id,
        'recipient_id': msg.recipient_id
    }, room=room)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)