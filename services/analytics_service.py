import secrets
from datetime import timedelta
from flask import session, current_app
from pymongo.errors import PyMongoError
from db import db
from models import utcnow


def track(event_type, path, event_id=None):
    session.setdefault('visitor_id', secrets.token_hex(24))
    session.setdefault('analytics_session', secrets.token_hex(24))
    now = utcnow()
    event = dict(anonymous_visitor_id=session['visitor_id'], session_id=session['analytics_session'],
        page_path=path, event_type=event_type, timestamp=now,
        expires_at=now + timedelta(days=current_app.config['ANALYTICS_RETENTION_DAYS']))
    try:
        if event_id:
            db.analytics.update_one({'_id': event_id}, {'$setOnInsert': event}, upsert=True)
        else:
            db.analytics.insert_one(event)
    except PyMongoError as exc:
        # Optional visit counts must never undo or misreport an acknowledged registration write.
        current_app.logger.warning('Analytics event could not be stored (%s)', type(exc).__name__)
