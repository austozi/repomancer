
from __future__ import annotations
import os
import re
import threading
from datetime import datetime
from packaging import version as pkg_version
from apscheduler.schedulers.background import BackgroundScheduler
from flask import current_app
from .database import db, App, Variant
from .scraping import run_strategy, HTTPClient


scheduler: BackgroundScheduler | None = None


def compare_versions(v1: str | None, v2: str | None) -> int:
    if not v1 and not v2:
        return 0
    if not v1:
        return -1
    if not v2:
        return 1
    try:
        a = pkg_version.parse(v1)
        b = pkg_version.parse(v2)
        if a < b:
            return -1
        if a > b:
            return 1
        return 0
    except Exception:
        return (v1 > v2) - (v1 < v2)


def sanitise_filename(name: str) -> str:
    return ''.join(c for c in name if c.isalnum() or c in ('-', '_', '.', ' ')).strip()


def slugify(text: str) -> str:
    """Return a URL-friendly slug: lowercase, no spaces, only a-z0-9-.
    All non-alphanumeric characters are replaced with '-'; runs collapsed.
    """
    text = (text or '').lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = re.sub(r'-{2,}', '-', text).strip('-')
    return text or 'app'


def download_installer(url: str, app_name: str, variant_key: str) -> tuple[str, int]:
    base = current_app.config['DOWNLOAD_DIR']
    filename = url.split('/')[-1]
    filename = sanitise_filename(filename) or f"{variant_key}.bin"
    rel_dir = os.path.join(slugify(app_name), variant_key)
    dest_dir = os.path.join(base, rel_dir)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)

    ua = current_app.config.get('DEFAULT_USER_AGENT')
    ref = current_app.config.get('DEFAULT_REFERRER')
    timeout = int(current_app.config.get('REQUEST_TIMEOUT', 15))
    client = HTTPClient(user_agent=ua, referrer=ref, timeout=timeout)
    size = client.download(url, dest)
    rel_path = os.path.relpath(dest, base)
    return rel_path, size


def check_variant(variant: Variant, app_obj: App) -> bool:
    ua = app_obj.ua_override or current_app.config.get('DEFAULT_USER_AGENT')
    ref = app_obj.referrer_override or current_app.config.get('DEFAULT_REFERRER')
    timeout = int(current_app.config.get('REQUEST_TIMEOUT', 15))

    prev_version = variant.current_version
    prev_url = variant.installer_url

    new_version, dl_url = run_strategy(variant.strategy_type, variant.strategy_config, ua, ref, timeout)

    updated = False
    if new_version:
        if compare_versions(prev_version, new_version) < 0:
            variant.current_version = new_version
            updated = True

    if dl_url:
        variant.installer_url = dl_url

    need_download = False
    base = current_app.config['DOWNLOAD_DIR']
    local_abs = os.path.join(base, variant.local_file_path) if variant.local_file_path else None

    if updated or not variant.local_file_path or (local_abs and not os.path.exists(local_abs)) or (dl_url and prev_url and dl_url != prev_url):
        need_download = True

    if dl_url and need_download:
        try:
            rel_path, size = download_installer(dl_url, app_obj.name, variant.key)
            variant.local_file_path = rel_path
            variant.file_size_bytes = size
            variant.last_updated = datetime.utcnow()
            updated = True
        except Exception as e:
            current_app.logger.error(f"Download failed for app={app_obj.name} variant={variant.key} url={dl_url}: {e}")

    if not variant.last_updated:
        variant.last_updated = datetime.utcnow()

    db.session.add(variant)
    return updated


def recompute_app(app_obj: App):
    latest = None
    for v in app_obj.variants:
        if v.current_version:
            if latest is None or compare_versions(latest, v.current_version) < 0:
                latest = v.current_version
    app_obj.latest_version = latest

    latest_check = None
    for v in app_obj.variants:
        if v.last_updated and (latest_check is None or v.last_updated > latest_check):
            latest_check = v.last_updated
    app_obj.last_update_check = latest_check or datetime.utcnow()
    db.session.add(app_obj)


def check_all_apps():
    apps = App.query.all()
    for app_obj in apps:
        for v in app_obj.variants:
            if not v.enabled:
                continue
            try:
                check_variant(v, app_obj)
            except Exception as e:
                current_app.logger.error(f"Variant check failed app={app_obj.name} variant={v.key}: {e}")
        recompute_app(app_obj)
    db.session.commit()


def check_app_by_id(app_id: int):
    app_obj = App.query.get(app_id)
    if not app_obj:
        return
    for v in app_obj.variants:
        if not v.enabled:
            continue
        try:
            check_variant(v, app_obj)
        except Exception as e:
            current_app.logger.error(f"Variant check failed app={app_obj.name} variant={v.key}: {e}")
    recompute_app(app_obj)
    db.session.commit()


def _background_check_all():
    with current_app.app_context():
        check_all_apps()


def trigger_check_all_async():
    t = threading.Thread(target=_background_check_all, daemon=True)
    t.start()


def init_scheduler(app):
    global scheduler
    interval = int(app.config.get('SCHEDULE_INTERVAL_MIN', 0))
    if interval <= 0:
        return
    scheduler = BackgroundScheduler()

    @scheduler.scheduled_job('interval', minutes=interval)
    def scheduled_job():
        with app.app_context():
            check_all_apps()

    scheduler.start()
