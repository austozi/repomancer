
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


def init_db():
    db.create_all()

class App(db.Model):
    __tablename__ = 'apps'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, nullable=False)
    description = db.Column(db.Text)
    licence = db.Column(db.String)
    changelog_url = db.Column(db.String)
    icon_url = db.Column(db.String)
    icon_local_path = db.Column(db.String)
    latest_version = db.Column(db.String)
    last_update_check = db.Column(db.DateTime)
    publisher_name = db.Column(db.String)
    project_website = db.Column(db.String)
    tags = db.Column(db.String)
    ua_override = db.Column(db.String)
    referrer_override = db.Column(db.String)
    meta_strategy_config = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    variants = db.relationship('Variant', backref='app', lazy=True)

class Variant(db.Model):
    __tablename__ = 'variants'
    id = db.Column(db.Integer, primary_key=True)
    app_id = db.Column(db.Integer, db.ForeignKey('apps.id'), nullable=False)
    key = db.Column(db.String, nullable=False)
    strategy_type = db.Column(db.String, default='generic')
    strategy_config = db.Column(db.Text, default='{}')
    enabled = db.Column(db.Boolean, default=True)

    current_version = db.Column(db.String)
    installer_url = db.Column(db.String)
    local_file_path = db.Column(db.String)
    file_size_bytes = db.Column(db.Integer)
    last_updated = db.Column(db.DateTime)
