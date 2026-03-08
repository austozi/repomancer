
from flask import Blueprint, render_template, request, current_app, send_from_directory, abort
from sqlalchemy import case
import os
from .database import db, App, Variant

public_bp = Blueprint('public', __name__, template_folder='templates')


@public_bp.route('/')
def index():
    q = (request.args.get('q') or '').strip()
    sort = (request.args.get('sort') or 'name').lower()
    page = int(request.args.get('page') or 1)
    page_size = int(current_app.config.get('PAGE_SIZE', 20))

    query = App.query
    if q:
        like = f"%{q}%"
        query = query.filter((App.name.ilike(like)) | (App.tags.ilike(like)) | (App.description.ilike(like)))

    if sort == 'updated':
        nulls_last = case((App.last_update_check.is_(None), 1), else_=0)
        query = query.order_by(nulls_last.asc(), App.last_update_check.desc())
    else:
        query = query.order_by(App.name.asc())

    total = query.count()

    apps = query.offset((page - 1) * page_size).limit(page_size).all()

    variants = Variant.query.filter(Variant.app_id.in_([a.id for a in apps])).all() if apps else []
    app_variants = {}
    for v in variants:
        app_variants.setdefault(v.app_id, []).append(v)

    pages = (total + page_size - 1) // page_size
    return render_template('index.html', apps=apps, total=total, q=q, sort=sort, page=page, pages=pages, app_variants=app_variants)


@public_bp.route('/app/<int:app_id>')
def app_detail(app_id: int):
    app_obj = App.query.get_or_404(app_id)
    variants = Variant.query.filter_by(app_id=app_id).all()
    return render_template('app_detail.html', app=app_obj, variants=variants)


@public_bp.route('/files/<path:rel>')
def files(rel: str):
    base = current_app.config.get('DOWNLOAD_DIR')
    if not base:
        abort(404)
    abs_path = os.path.abspath(os.path.join(base, rel))
    if not abs_path.startswith(os.path.abspath(base) + os.sep):
        abort(404)
    if not os.path.exists(abs_path):
        abort(404)
    return send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path), as_attachment=False)


@public_bp.route('/icons/<path:rel>')
def icons(rel: str):
    base = current_app.config.get('ICONS_DIR')
    if not base:
        abort(404)
    abs_path = os.path.abspath(os.path.join(base, rel))
    if not abs_path.startswith(os.path.abspath(base) + os.sep):
        abort(404)
    if not os.path.exists(abs_path):
        abort(404)
    return send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path), as_attachment=False)
