
import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from sqlalchemy import text

# Local imports
from .database import db, init_db
from .views import public_bp
from .admin import admin_bp
from .tasks import init_scheduler


def create_app():
    app = Flask(__name__)

    # Secret key for sessions/flash
    app.secret_key = os.getenv('REPOMANCER_SECRET_KEY', 'change-me')

    # Basic config
    app.config['HOST'] = os.getenv('REPOMANCER_HOST', '0.0.0.0')
    app.config['PORT'] = int(os.getenv('REPOMANCER_PORT', '8000'))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.getenv('REPOMANCER_DB_PATH', '/data/repomancer.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['DOWNLOAD_DIR'] = os.getenv('REPOMANCER_DOWNLOAD_DIR', '/data/downloads')
    app.config['ICONS_DIR'] = os.getenv('REPOMANCER_ICONS_DIR', '/data/icons')
    app.config['DEFAULT_USER_AGENT'] = os.getenv('REPOMANCER_USER_AGENT', 'Mozilla/5.0')
    app.config['DEFAULT_REFERRER'] = os.getenv('REPOMANCER_REFERRER', 'https://example.com/')
    app.config['PAGE_SIZE'] = int(os.getenv('REPOMANCER_PAGE_SIZE', '20'))
    app.config['REQUEST_TIMEOUT'] = int(os.getenv('REPOMANCER_REQUEST_TIMEOUT', '15'))
    app.config['SCHEDULE_INTERVAL_MIN'] = int(os.getenv('REPOMANCER_UPDATE_INTERVAL_MINUTES', '0'))
    app.config['LOG_LEVEL'] = os.getenv('REPOMANCER_LOG_LEVEL', 'INFO').upper()
    app.config['LOG_PATH'] = os.getenv('REPOMANCER_LOG_PATH', '/data/logs/repomancer.log')
    app.config['GITHUB_TOKEN'] = os.getenv('GITHUB_TOKEN')

    # Logging: rotating file under /data/logs
    try:
        os.makedirs(os.path.dirname(app.config['LOG_PATH']), exist_ok=True)
        handler = RotatingFileHandler(app.config['LOG_PATH'], maxBytes=2*1024*1024, backupCount=3)
        fmt = logging.Formatter('[%(asctime)s] %(levelname)s in %(name)s: %(message)s')
        handler.setFormatter(fmt)
        handler.setLevel(getattr(logging, app.config['LOG_LEVEL'], logging.INFO))
        app.logger.addHandler(handler)
        app.logger.setLevel(handler.level)
    except Exception:
        # Non-fatal if logging cannot be configured (eg read-only FS at init)
        pass

    # Jinja filters
    @app.template_filter('human_size')
    def human_size(num):
        try:
            n = int(num)
        except Exception:
            return '-'
        units = ['bytes', 'KB', 'MB', 'GB', 'TB']
        size = float(n)
        for u in units:
            if size < 1024 or u == units[-1]:
                if u == 'bytes':
                    return f"{int(size)} {u}"
                return f"{size:.2f} {u}"
            size /= 1024.0
        return f"{n} bytes"

    @app.template_filter('basename')
    def basename(path):
        try:
            return os.path.basename(path)
        except Exception:
            return path

    # Init DB and lightweight migrations
    db.init_app(app)
    with app.app_context():
        init_db()
        # Ensure apps.icon_local_path exists (SQLite)
        try:
            rows = db.session.execute(text("PRAGMA table_info(apps)")).fetchall()
            cols = [r[1] for r in rows]
            if 'icon_local_path' not in cols:
                app.logger.info("Adding column apps.icon_local_path via migration")
                db.session.execute(text("ALTER TABLE apps ADD COLUMN icon_local_path TEXT"))
                db.session.commit()
        except Exception as e:
            app.logger.warning(f"DB migration check failed (icon_local_path): {e}")

    # Register blueprints (public at root, admin under /admin)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Scheduler
    init_scheduler(app)

    return app
