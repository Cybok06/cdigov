from datetime import timedelta
from flask import Blueprint, request, jsonify, session, abort, current_app
from extensions import limiter
from models import utcnow
from services.database_service import (bound_draft, current_draft, new_draft, validate_fields,
    encode_fields, mutate_draft, consent, delete_draft_record)
from services.location_service import save_location
from services.analytics_service import track
from services.upload_service import prepare_image

bp = Blueprint('registration', __name__)


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description='Send a valid JSON object.')
    return data


def response(record):
    return jsonify(draft_token=session['draft_token'], reference=record.reference_number, status=record.status)


@bp.post('/api/registration/draft')
@limiter.limit('30 per minute')
def draft():
    data = payload()
    values = validate_fields(data)
    if current_draft():
        record = bound_draft(data.get('draft_token'))
        record = mutate_draft(record, encode_fields(values, record))
    else:
        if data.get('draft_token'):
            # An absent record with this browser's valid token has expired/deleted.
            bound_draft(data['draft_token'])
        record = new_draft(values)
        track('draft_created', '/register', f'draft:{record.id}')
    return response(record)


@bp.post('/api/registration/location')
@limiter.limit('10 per minute')
def location():
    data = payload()
    record = bound_draft(data.get('draft_token', ''))
    record = save_location(record, data)
    return jsonify(message='Your location has been securely saved to your registration draft.', status=record.status)


@bp.post('/api/registration/location/decline')
@limiter.limit('10 per minute')
def decline():
    data = payload()
    record = bound_draft(data.get('draft_token', ''))
    if record.locations:
        abort(409, description='A location is already saved. Use Delete draft to remove your draft and its location.')
    mutate_draft(record, consents=[consent('location_immediate_storage', False)], extra_filter={'location': {'$exists': False}})
    return jsonify(message='Location sharing declined. You can continue your registration.')


@bp.post('/api/registration/photo')
@limiter.limit('10 per minute')
def photo():
    record = bound_draft(request.form.get('draft_token', ''))
    upload = request.files.get('photo')
    if not upload or not upload.filename:
        abort(400, description='Choose a photograph.')
    photo = prepare_image(upload)
    mutate_draft(record, {'photo': photo, 'profile_image_path': photo['key']})
    return jsonify(message='Photograph securely saved.')


@bp.post('/api/registration/submit')
@limiter.limit('10 per minute')
def submit():
    data = payload()
    record = bound_draft(data.get('draft_token', ''), allow_submitted=True)
    if record.status != 'submitted':
        values = validate_fields(data, final=True)
        if data.get('accuracy_confirmed') is not True or data.get('processing_consent') is not True:
            raise ValueError('Confirm accuracy and agree to the privacy notice before submitting.')
        if not record.locations:
            raise ValueError('A confirmed current location is required before submitting this registration.')
        now = utcnow()
        updates = {**encode_fields(values, record), 'status': 'submitted', 'submitted_at': now,
            'expires_at': now + timedelta(days=current_app.config['SUBMISSION_RETENTION_DAYS'])}
        try:
            record = mutate_draft(record, updates, [consent('registration_processing'), consent('accuracy_confirmation')])
        except Exception as exc:
            from werkzeug.exceptions import Conflict
            if not isinstance(exc, Conflict):
                raise
            # A concurrent successful final submission is idempotent.
            record = bound_draft(data.get('draft_token', ''), allow_submitted=True)
            if record.status != 'submitted':
                raise
    track('registration_completed', '/register', f'completed:{record.id}')
    return jsonify(reference=record.reference_number, redirect='/success')


@bp.post('/api/registration/delete')
def delete_draft():
    data = payload()
    record = bound_draft(data.get('draft_token', ''))
    delete_draft_record(record)
    session.pop('draft_token', None)
    return jsonify(message='Your draft and its saved information have been deleted.')
