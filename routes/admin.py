import io
import math
import re
from datetime import datetime, timedelta
from functools import wraps
from types import SimpleNamespace
from bson import ObjectId
from flask import Blueprint, request, render_template, redirect, url_for, flash, abort, send_file, session, current_app
from flask_login import current_user, login_user, logout_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from db import db
from models import AdminUser, DevelopmentAdmin, Registration, PERSONAL_FIELDS, name_tokens, search_hash, utcnow
from extensions import limiter
from services.upload_service import read_image
from services.database_service import retained_condition, object_id, NO_PHOTO

bp = Blueprint('admin', __name__, url_prefix='/admin')
DUMMY_HASH = generate_password_hash('constant-timing-dummy-password')


def authorized(*roles):
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if current_app.config['DEV_ADMIN_AUTH_DISABLED'] and not current_user.is_authenticated:
                login_user(DevelopmentAdmin(), remember=False)
            elif not current_user.is_authenticated:
                return redirect(url_for('admin.login', next=request.path))
            if not current_user.is_active or current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorate


read_access = authorized('viewer', 'admin', 'owner')


@bp.get('')
def entry():
    if current_app.config['DEV_ADMIN_AUTH_DISABLED'] and not current_user.is_authenticated:
        login_user(DevelopmentAdmin(), remember=False)
    return redirect(url_for('admin.dashboard' if current_user.is_authenticated else 'admin.login'))


def audit(action, kind='registration', record_id=None):
    db.audit_logs.insert_one(dict(admin_id=current_user.id, action=action, record_type=kind,
        record_id=record_id, timestamp=utcnow()))


def dates():
    try:
        start = datetime.fromisoformat(request.args.get('start') or (utcnow() - timedelta(days=29)).date().isoformat())
        end = datetime.fromisoformat(request.args.get('end') or utcnow().date().isoformat()) + timedelta(days=1)
        if start.tzinfo or end.tzinfo or start >= end or (end - start).days > 366:
            raise ValueError()
    except ValueError:
        abort(400, description='Choose a date range of up to 366 days.')
    return start, end


def retained_record(record_id):
    document = db.registrations.find_one({'_id': object_id(record_id), **retained_condition()}, NO_PHOTO)
    if not document:
        abort(404)
    return Registration(document)


def pagination(query):
    try:
        page = int(request.args.get('page', '1'))
        if page < 1:
            raise ValueError()
    except ValueError:
        abort(400, description='Choose a valid page number.')
    total = db.registrations.count_documents(query)
    pages = math.ceil(total / 20)
    if page > max(pages, 1):
        abort(404)
    documents = db.registrations.find(query, NO_PHOTO).sort('created_at', -1).skip((page - 1) * 20).limit(20)
    return SimpleNamespace(items=[Registration(doc) for doc in documents], total=total, pages=pages,
        page=page, has_prev=page > 1, prev_num=page - 1, has_next=page < pages, next_num=page + 1)


@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 30 per hour', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip() or current_app.config['DEV_ADMIN_USERNAME']
        document = db.admin_users.find_one({'username': username})
        user = AdminUser(document) if document else None
        password = request.form.get('password', '')
        valid = check_password_hash(user.password_hash if user else DUMMY_HASH, password[:256]) and len(password) <= 256
        if valid and user and user.is_active and user.role in {'owner', 'admin', 'viewer'}:
            session.clear()
            login_user(user, remember=False)
            session.permanent = True
            db.admin_users.update_one({'_id': ObjectId(user.id)}, {'$set': {'last_login': utcnow()}})
            audit('login', 'admin', user.id)
            return redirect(url_for('admin.dashboard'))
        flash('Unable to sign in. Check your credentials.', 'danger')
    return render_template('admin/login.html')


@bp.post('/logout')
@login_required
def logout():
    audit('logout', 'admin', current_user.id)
    logout_user()
    session.clear()
    return redirect(url_for('admin.login'))


def daily(collection, query, field):
    return {item['_id']: item['count'] for item in collection.aggregate([
        {'$match': query}, {'$group': {'_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$' + field}}, 'count': {'$sum': 1}}}])}


@bp.get('/dashboard')
@read_access
def dashboard():
    start, end = dates()
    period = {'created_at': {'$gte': start, '$lt': end}, **retained_condition()}
    visits = {'timestamp': {'$gte': start, '$lt': end}, 'event_type': 'page_view'}
    unique = list(db.analytics.aggregate([{'$match': visits}, {'$group': {'_id': '$anonymous_visitor_id'}}, {'$count': 'total'}]))
    metrics = {
        'Total page views': db.analytics.count_documents(visits),
        'Unique visitors': unique[0]['total'] if unique else 0,
        'Registrations started': db.registrations.count_documents(period),
        'Completed registrations': db.registrations.count_documents({**period, 'status': 'submitted'}),
        'Incomplete drafts': db.registrations.count_documents({**period, 'status': {'$ne': 'submitted'}}),
        'With saved locations': db.registrations.count_documents({**period, 'location': {'$exists': True}}),
        'Registrations today': db.registrations.count_documents({'created_at': {'$gte': utcnow().replace(hour=0, minute=0, second=0, microsecond=0)}, **retained_condition()}),
    }
    labels = [(start + timedelta(days=i)).date().isoformat() for i in range((end-start).days)]
    views = daily(db.analytics, visits, 'timestamp')
    started = daily(db.registrations, period, 'created_at')
    submitted = daily(db.registrations, {'submitted_at': {'$gte': start, '$lt': end}, **retained_condition()}, 'submitted_at')
    series = dict(labels=labels, visits=[views.get(x,0) for x in labels], started=[started.get(x,0) for x in labels],
        submitted=[submitted.get(x,0) for x in labels], complete=metrics['Completed registrations'], incomplete=metrics['Incomplete drafts'])
    recent = [Registration(doc) for doc in db.registrations.find(retained_condition(), NO_PHOTO).sort('created_at', -1).limit(6)]
    audit('view_dashboard', 'analytics')
    return render_template('admin/dashboard.html', metrics=metrics, series=series, recent=recent,
        start=start.date(), end=(end-timedelta(days=1)).date())


def filtered_query(locations=False):
    query = retained_condition()
    if locations:
        query['location'] = {'$exists': True}
    term = request.args.get('q', '').strip()[:150]
    if term:
        if term.upper().startswith('CDI-'):
            query['reference_number'] = {'$regex': '^' + re.escape(term.upper())}
        else:
            words = name_tokens(term)
            if not words:
                query['_id'] = None
            else:
                query['search_tokens'] = {'$all': [search_hash(word) for word in set(words)]}
    status = request.args.get('status')
    if status in {'in_progress','location_saved','submitted'}:
        query['status'] = status
    for key, operator, adjustment in [('start','$gte',0),('end','$lt',1)]:
        if request.args.get(key):
            try:
                value = datetime.fromisoformat(request.args[key]) + timedelta(days=adjustment)
                if value.tzinfo:
                    raise ValueError()
            except ValueError:
                abort(400, description='Enter a valid date.')
            query.setdefault('created_at', {})[operator] = value
    return query


@bp.get('/registrations')
@read_access
def registrations():
    result = pagination(filtered_query())
    audit('list_registrations')
    return render_template('admin/registrations.html', pagination=result)


@bp.get('/registrations/<record_id>')
@read_access
def detail(record_id):
    record = retained_record(record_id)
    audit('view_sensitive_record', record_id=record.id)
    return render_template('admin/registration_detail.html', record=record, fields=PERSONAL_FIELDS)


@bp.get('/registrations/<record_id>/photo')
@read_access
def photo(record_id):
    record = retained_record(record_id)
    if not record.profile_image_path:
        abort(404)
    audit('view_photo', record_id=record.id)
    return send_file(io.BytesIO(read_image(record.profile_image_path)), mimetype='image/jpeg', max_age=0)


@bp.post('/registrations/<record_id>/delete')
@authorized('owner')
def delete(record_id):
    record = retained_record(record_id)
    if request.form.get('reference') != record.reference_number:
        abort(400, description='Enter the registration reference to confirm deletion.')
    # Write an audit intention before deletion; a logging failure must prevent deletion.
    audit('delete_record_requested', record_id=record.id)
    db.registrations.delete_one({'_id': ObjectId(record.id)})
    audit('delete_record', record_id=record.id)
    flash('Registration deleted.', 'success')
    return redirect(url_for('admin.registrations'))


@bp.get('/locations')
@read_access
def locations():
    result = pagination(filtered_query(True))
    audit('view_sensitive_locations')
    return render_template('admin/locations.html', pagination=result)


@bp.get('/visitors')
@read_access
def visitors():
    start, end = dates()
    grouped = db.analytics.aggregate([{'$match': {'timestamp': {'$gte': start,'$lt': end}}},
        {'$group': {'_id': '$event_type','count': {'$sum': 1}}}, {'$sort': {'_id': 1}}])
    rows = [(item['_id'], item['count']) for item in grouped]
    audit('view_visitors', 'analytics')
    return render_template('admin/visitors.html', rows=rows, start=start.date(), end=(end-timedelta(days=1)).date())


@bp.route('/settings', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
@read_access
def settings():
    if request.method == 'POST':
        old = request.form.get('current_password','')
        new = request.form.get('new_password','')
        if len(old) > 256 or not check_password_hash(current_user.password_hash,old) or not 14 <= len(new) <= 256:
            flash('Enter your current password and a new password of 14–256 characters.','danger')
        else:
            audit('change_password_requested','admin',current_user.id)
            db.admin_users.update_one({'_id': ObjectId(current_user.id)}, {'$set': {'password_hash': generate_password_hash(new)}})
            audit('change_password','admin',current_user.id)
            flash('Password updated.','success')
    logs = [SimpleNamespace(**doc) for doc in db.audit_logs.find().sort('timestamp',-1).limit(30)] if current_user.role == 'owner' else []
    return render_template('admin/settings.html',logs=logs)
