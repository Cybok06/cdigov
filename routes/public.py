from flask import Blueprint, render_template, session, redirect, url_for
from models import Registration, PERSONAL_FIELDS, utcnow
from services.database_service import current_draft
from services.analytics_service import track

bp = Blueprint('public', __name__)


def page(name, event='page_view', path=None, **kwargs):
    path = path or ('/' if name == 'index' else '/' + name)
    track('page_view', path)
    if event != 'page_view':
        track(event, path)
    return render_template(name + '.html', **kwargs)


@bp.get('/')
def index():
    return register('/')


@bp.get('/privacy')
def privacy():
    return page('privacy')


@bp.get('/register')
def register(path='/register'):
    document = current_draft()
    if document and document['expires_at'] <= utcnow():
        session.pop('draft_token', None)
        document = None
    record = Registration(document) if document else None
    if record and record.status == 'submitted':
        return redirect(url_for('public.success'))
    initial = {field: getattr(record, field) or '' for field in PERSONAL_FIELDS} if record else {}
    initial.update(dual_citizenship=record.dual_citizenship if record else False,
        draft_token=session.get('draft_token') if record else None,
        location_saved=bool(record and record.locations), photo_saved=bool(record and record.profile_image_path))
    return page('register', 'form_opened', path=path, initial=initial)


@bp.get('/register/')
def register_slash():
    return redirect(url_for('public.index'))


@bp.get('/success')
def success():
    document = current_draft()
    if not document or document['status'] != 'submitted' or document['expires_at'] <= utcnow():
        return redirect(url_for('public.register'))
    return render_template('success.html', reference=document['reference_number'])
