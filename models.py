"""Encrypted MongoDB document adapters for templates and Flask-Login."""
import hashlib
import hmac
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from cryptography.fernet import Fernet
from flask import current_app
from flask_login import UserMixin
from db import db

PERSONAL_FIELDS = ['surname', 'first_names', 'middle_names', 'former_names', 'date_of_birth',
    'sex', 'nationality', 'second_nationality', 'country_of_birth', 'region_of_birth',
    'district_of_birth', 'town_of_birth', 'residential_address', 'residential_region',
    'residential_district', 'residential_town', 'digital_address', 'father_full_name',
    'father_hometown', 'father_nationality', 'mother_full_name', 'mother_hometown', 'mother_nationality']


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def cipher():
    return Fernet(current_app.config['ENCRYPTION_KEY'].encode())


def encrypt(value):
    return cipher().encrypt(str(value).encode()).decode() if value is not None else None


def decrypt(value):
    return cipher().decrypt(value.encode()).decode() if value is not None else None


def name_tokens(value):
    return re.findall(r'[^\W_]+', value.casefold(), re.UNICODE)


def search_hash(value):
    return hmac.new(current_app.config['SEARCH_KEY'].encode(), value.encode(), hashlib.sha256).hexdigest()


class Registration:
    def __init__(self, document):
        self.document = document
        self.id = str(document['_id'])
        for field in PERSONAL_FIELDS:
            setattr(self, field, decrypt(document.get(field)))
        for field in ['reference_number', 'draft_token_hash', 'status', 'created_at', 'updated_at', 'submitted_at', 'profile_image_path']:
            setattr(self, field, document.get(field))
        self.dual_citizenship = document.get('dual_citizenship', False)
        self.consents = [SimpleNamespace(**item) for item in document.get('consents', [])]
        self.locations = []
        if document.get('location'):
            point = document['location'].copy()
            for key in ('latitude', 'longitude', 'accuracy_meters'):
                point[key] = decrypt(point[key])
            point['consent'] = next((item for item in self.consents if item.id == point['consent_record_id']), None)
            self.locations = [SimpleNamespace(**point)]

    @property
    def full_name(self):
        return ' '.join(filter(None, [self.first_names, self.middle_names, self.surname])) or 'Name not supplied'


class AdminUser(UserMixin):
    def __init__(self, document):
        self.id = str(document['_id'])
        self.username = document['username']
        self.email = decrypt(document['email'])
        self.password_hash = document['password_hash']
        self.role = document['role']
        self.active = document.get('is_active', True)
        self.last_login = document.get('last_login')

    @property
    def is_active(self):
        return self.active


class DevelopmentAdmin(UserMixin):
    """Synthetic local-only administrator for the explicitly enabled dev bypass."""
    id = 'development-admin'
    username = 'admin'
    role = 'owner'
    active = True

    @property
    def is_active(self):
        return True

    @property
    def password_hash(self):
        return ''
