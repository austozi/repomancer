
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from werkzeug.utils import secure_filename
from .database import db, App, Variant
from .tasks import trigger_check_all_async, check_app_by_id
from .scraping import HTTPClient
from .tasks import slugify  # reuse existing helper for safe folder names
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import os, json

# Allowed icon extensions; we will normalise the stored filename to logo.<ext>
ALLOWED_ICON_EXTS = {'.png', '.webp', '.jpg', '.jpeg', '.svg'}
# Allowed installer extensions for manual uploads
ALLOWED_INSTALLER_EXTS = {'.msi', '.exe', '.zip'}

admin_bp = Blueprint('admin', __name__, template_folder='templates')


def safe_flash(message, category='info'):
    try:
        if current_app.secret_key:
            flash(message, category)
    except Exception:
        pass


def _cleanup_old_logos(folder: str, keep_ext: str | None = None):
    """Delete prior logo.* files in folder, except the target extension if provided.
    keep_ext must include leading dot, e.g. '.png'.
    """
    try:
        for name in os.listdir(folder):
            low = name.lower()
            if not low.startswith('logo.'):
                continue
            _, ext = os.path.splitext(low)
            if ext not in ALLOWED_ICON_EXTS:
                continue
            if keep_ext and ext == keep_ext.lower():
                try:
                    os.remove(os.path.join(folder, name))
                except Exception:
                    pass
                continue
            try:
                os.remove(os.path.join(folder, name))
            except Exception:
                pass
    except FileNotFoundError:
        pass


@admin_bp.route('/')
def admin_index():
    apps = App.query.order_by(App.name.asc()).all()
    return render_template('admin_index.html', apps=apps)


@admin_bp.route('/check-all', methods=['POST'])
def admin_check_all():
    trigger_check_all_async()
    safe_flash('Update check started in background', 'info')
    return redirect(url_for('admin.admin_index'))


@admin_bp.route('/app/new', methods=['GET', 'POST'])
@admin_bp.route('/app/<int:app_id>/edit', methods=['GET', 'POST'])
def admin_app_form(app_id=None):
    app_obj = App.query.get(app_id) if app_id else None

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            safe_flash('Name is required', 'danger')
            return render_template('admin_app_form.html', app=app_obj)

        # Save simple fields first so we have an id for the icon path
        values = dict(
            name=name,
            description=request.form.get('description') or None,
            licence=request.form.get('licence') or None,
            changelog_url=request.form.get('changelog_url') or None,
            icon_url=request.form.get('icon_url') or None,
            publisher_name=request.form.get('publisher_name') or None,
            project_website=request.form.get('project_website') or None,
            tags=request.form.get('tags') or None,
            ua_override=(request.form.get('ua_override') or None),
            referrer_override=(request.form.get('referrer_override') or None),
            meta_strategy_config=(request.form.get('meta_strategy_config') or None),
        )
        if app_obj:
            for k, v in values.items():
                setattr(app_obj, k, v)
        else:
            app_obj = App(**values)
            db.session.add(app_obj)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            safe_flash('An app with this name already exists. Please choose another name.', 'danger')
            return render_template('admin_app_form.html', app=app_obj)

        # Ensure icon folder exists under ICONS_DIR/<app_id>
        icons_base = os.path.join(current_app.config['ICONS_DIR'], str(app_obj.id))
        os.makedirs(icons_base, exist_ok=True)

        uploaded = request.files.get('icon_file')
        if uploaded and uploaded.filename:
            filename = secure_filename(uploaded.filename)
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALLOWED_ICON_EXTS:
                ext = '.png'
            _cleanup_old_logos(icons_base, keep_ext=ext)
            dest = os.path.join(icons_base, f'logo{ext}')
            uploaded.save(dest)
            rel = os.path.relpath(dest, current_app.config['ICONS_DIR'])
            app_obj.icon_local_path = rel
            db.session.commit()
            safe_flash('Icon uploaded and normalised to logo file name', 'success')
        else:
            remote = (request.form.get('icon_url') or app_obj.icon_url or '').strip()
            if remote.lower().startswith(('http://', 'https://')):
                try:
                    client = HTTPClient(
                        user_agent=current_app.config.get('DEFAULT_USER_AGENT'),
                        referrer=current_app.config.get('DEFAULT_REFERRER'),
                        timeout=int(current_app.config.get('REQUEST_TIMEOUT', 15))
                    )
                    name_part = secure_filename(remote.split('/')[-1].split('?')[0])
                    ext = os.path.splitext(name_part)[1].lower()
                    if ext not in ALLOWED_ICON_EXTS:
                        ext = '.png'
                    _cleanup_old_logos(icons_base, keep_ext=ext)
                    dest = os.path.join(icons_base, f'logo{ext}')
                    client.download(remote, dest)
                    rel = os.path.relpath(dest, current_app.config['ICONS_DIR'])
                    app_obj.icon_local_path = rel
                    db.session.commit()
                    safe_flash('Remote icon downloaded and normalised to logo file name', 'success')
                except Exception as e:
                    current_app.logger.error(f"Failed to fetch icon from {remote}: {e}")
                    safe_flash('Failed to fetch icon from remote URL. You can upload a file instead.', 'warning')

        return redirect(url_for('admin.admin_index'))

    return render_template('admin_app_form.html', app=app_obj)


@admin_bp.route('/app/<int:app_id>')
def admin_app_detail(app_id):
    app_obj = App.query.get_or_404(app_id)
    variants = Variant.query.filter_by(app_id=app_id).all()
    return render_template('admin_app_detail.html', app=app_obj, variants=variants)


@admin_bp.route('/app/<int:app_id>/check', methods=['POST'])
def admin_check_app(app_id):
    check_app_by_id(app_id)
    safe_flash('Update check completed for app', 'success')
    return redirect(url_for('admin.admin_app_detail', app_id=app_id))


@admin_bp.route('/app/<int:app_id>/variant/new', methods=['GET', 'POST'])
@admin_bp.route('/variant/<int:variant_id>/edit', methods=['GET', 'POST'])
def admin_variant_form(app_id=None, variant_id=None):
    variant = Variant.query.get(variant_id) if variant_id else None
    app_obj = App.query.get(app_id) if app_id else (variant.app if variant else None)

    if request.method == 'POST':
        key = request.form.get('key', '').strip()
        strategy_type = request.form.get('strategy_type', 'generic')
        strategy_config = request.form.get('strategy_config', '{}')

        # Preferred checkbox: 'disable_updates' -> enabled = not disable_updates
        if 'disable_updates' in request.form:
            disable_updates = (request.form.get('disable_updates') == 'on')
            enabled = (not disable_updates)
        else:
            # Back-compat with any existing 'enabled' checkbox
            enabled = (request.form.get('enabled') == 'on')

        # Optional manual version string for uploaded installers
        manual_version = (request.form.get('manual_version') or '').strip()

        try:
            json.loads(strategy_config)
        except json.JSONDecodeError:
            safe_flash('Strategy config must be valid JSON', 'danger')
            return render_template('admin_variant_form.html', app=app_obj, variant=variant)

        if variant:
            variant.key = key
            variant.strategy_type = strategy_type
            variant.strategy_config = strategy_config
            variant.enabled = enabled
        else:
            variant = Variant(app_id=app_obj.id, key=key, strategy_type=strategy_type, strategy_config=strategy_config, enabled=enabled)
            db.session.add(variant)
            db.session.flush()

        # If a manual version is provided, set it
        if manual_version:
            try:
                variant.current_version = manual_version
            except Exception:
                pass

        # Optional installer upload (MSI/EXE/ZIP) for legacy/proprietary apps
        uploaded = request.files.get('installer_file')
        if uploaded and uploaded.filename:
            fname = secure_filename(uploaded.filename)
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ALLOWED_INSTALLER_EXTS:
                safe_flash('Invalid installer type. Allowed: MSI, EXE, ZIP', 'danger')
                return render_template('admin_variant_form.html', app=app_obj, variant=variant)

            base = current_app.config['DOWNLOAD_DIR']
            rel_dir = os.path.join(slugify(app_obj.name), key)
            dest_dir = os.path.join(base, rel_dir)
            os.makedirs(dest_dir, exist_ok=True)

            dest = os.path.join(dest_dir, fname)
            uploaded.save(dest)

            rel_path = os.path.relpath(dest, base)
            variant.local_file_path = rel_path
            try:
                variant.file_size_bytes = os.path.getsize(dest)
            except Exception:
                pass
            variant.last_updated = datetime.utcnow()

        db.session.commit()
        safe_flash('Variant saved', 'success')
        return redirect(url_for('admin.admin_app_detail', app_id=app_obj.id))

    return render_template('admin_variant_form.html', app=app_obj, variant=variant)


@admin_bp.route('/variant/<int:variant_id>/delete', methods=['POST'])
def admin_variant_delete(variant_id):
    variant = Variant.query.get_or_404(variant_id)
    app_id = variant.app_id
    try:
        db.session.delete(variant)
        db.session.commit()
        safe_flash('Variant deleted', 'info')
    except Exception:
        db.session.rollback()
        safe_flash('Failed to delete variant', 'danger')
    return redirect(url_for('admin.admin_app_detail', app_id=app_id))
