import hashlib
import hmac
import secrets
from datetime import timedelta
from bson import ObjectId
from bson.errors import InvalidId
from flask import current_app, session, abort
from pymongo import ReturnDocument
from db import db
from models import Registration, PERSONAL_FIELDS, utcnow, encrypt, name_tokens, search_hash
from services.validation import validate_fields

NO_PHOTO = {'photo.data': 0}


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def object_id(value):
    try:
        return ObjectId(value)
    except (ValueError, TypeError, InvalidId):
        abort(404)


def retained_condition():
    return {'expires_at': {'$gt': utcnow()}}


def current_draft():
    token = session.get('draft_token')
    return db.registrations.find_one({'draft_token_hash': token_hash(token)}, NO_PHOTO) if token else None


def bound_draft(supplied=None, allow_submitted=False):
    token = session.get('draft_token', '')
    if not token or (supplied is not None and (not isinstance(supplied, str) or not hmac.compare_digest(token, supplied))):
        abort(403, description='This draft does not belong to this browser session.')
    document = current_draft()
    if not document or document['expires_at'] <= utcnow():
        abort(410, description='Your draft has expired. Start a new registration.')
    if document['status'] == 'submitted' and not allow_submitted:
        abort(409, description='This registration has already been submitted.')
    return Registration(document)


def new_draft(values):
    token = secrets.token_urlsafe(48)
    now = utcnow()
    document = {'_id': ObjectId(), 'reference_number': 'CDI-' + secrets.token_hex(8).upper(),
        'draft_token_hash': token_hash(token), 'status': 'in_progress', 'created_at': now,
        'updated_at': now, 'submitted_at': None, 'dual_citizenship': False, 'version': 0,
        'consents': [], 'expires_at': now + timedelta(days=current_app.config['DRAFT_RETENTION_DAYS'])}
    document.update(encode_fields(values))
    db.registrations.insert_one(document)
    session['draft_token'] = token  # Only issue the token after an acknowledged write.
    return Registration(document)


def encode_fields(values, record=None):
    result = {key: encrypt(value) if key in PERSONAL_FIELDS else value for key, value in values.items()}
    if any(key in values for key in ('surname', 'first_names', 'middle_names')):
        full_name = ' '.join(values.get(key, getattr(record, key, '')) or '' for key in ('first_names', 'middle_names', 'surname'))
        result['search_tokens'] = sorted({search_hash(word) for word in name_tokens(full_name)})
    return result


def consent(kind, granted=True):
    return {'id': str(ObjectId()), 'consent_type': kind, 'consent_granted': granted,
        'privacy_notice_version': current_app.config['PRIVACY_NOTICE_VERSION'], 'consent_timestamp': utcnow()}


def mutate_draft(record, values=None, consents=None, extra_filter=None):
    # All related changes (including coordinates AND consent) use one atomic document write.
    if len(record.consents) + len(consents or []) > 500:
        abort(429, description='This draft has reached its update limit. Please contact the operator.')
    query = {'_id': ObjectId(record.id), 'version': record.document['version'],
        'status': {'$in': ['in_progress', 'location_saved']}, **retained_condition(), **(extra_filter or {})}
    updates = {'$set': {**(values or {}), 'updated_at': utcnow()}, '$inc': {'version': 1}}
    if consents:
        updates['$push'] = {'consents': {'$each': consents}}
    document = db.registrations.find_one_and_update(query, updates, projection=NO_PHOTO, return_document=ReturnDocument.AFTER)
    if not document:
        abort(409, description='Your draft changed in another request. Retry to load the latest version.')
    return Registration(document)


def delete_draft_record(record):
    result = db.registrations.delete_one({'_id': ObjectId(record.id), 'version': record.document['version'],
        'status': {'$in': ['in_progress', 'location_saved']}, **retained_condition()})
    if not result.deleted_count:
        abort(409, description='Your draft changed. Refresh the page before deleting it.')


def purge_expired():
    # Photos, location and consents are embedded: deleting a registration deletes them atomically.
    removed = db.registrations.delete_many({'expires_at': {'$lte': utcnow()}}).deleted_count
    db.analytics.delete_many({'expires_at': {'$lte': utcnow()}})
    return removed
