from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import random
import string

db = SQLAlchemy()

def generate_unique_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(8), unique=True, nullable=False, default=generate_unique_id)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    profile_picture = db.Column(db.String(200), default='default.png')
    status = db.Column(db.String(100), default='Онлайн')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    messages_sent = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender')
    messages_received = db.relationship('Message', foreign_keys='Message.recipient_id', backref='recipient')
    groups_created = db.relationship('Group', backref='creator')
    groups = db.relationship('GroupMember', back_populates='user')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    content = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), default='text')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship('GroupMember', back_populates='group')

class GroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user = db.relationship('User', back_populates='groups')
    group = db.relationship('Group', back_populates='members')