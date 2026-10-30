"""Flask-scoped PyMongo connection. No credentials or network calls at import time."""
import threading
from flask import current_app
from pymongo import MongoClient, ASCENDING
from pymongo.server_api import ServerApi
from werkzeug.local import LocalProxy


class MongoDB:
    def init_app(self, app):
        app.extensions['mongodb'] = {'client': app.config.get('MONGO_CLIENT'), 'lock': threading.Lock()}

    def database(self):
        state = current_app.extensions['mongodb']
        if state['client'] is None:
            with state['lock']:
                if state['client'] is None:
                    state['client'] = MongoClient(
                        current_app.config['MONGODB_URI'], server_api=ServerApi('1'),
                        connect=False, appname='CDIGOV', retryWrites=True, w='majority',
                        maxPoolSize=current_app.config['MONGO_MAX_POOL_SIZE'],
                        serverSelectionTimeoutMS=current_app.config['MONGO_TIMEOUT_MS'],
                        connectTimeoutMS=current_app.config['MONGO_TIMEOUT_MS'], socketTimeoutMS=30000)
        return state['client'][current_app.config['MONGODB_DB']]

    def init_indexes(self):
        database = self.database()
        database.registrations.create_index('reference_number', unique=True)
        database.registrations.create_index('draft_token_hash', unique=True)
        database.registrations.create_index([('status', ASCENDING), ('created_at', ASCENDING)])
        database.registrations.create_index('submitted_at')
        database.registrations.create_index('search_tokens')
        database.registrations.create_index('expires_at', expireAfterSeconds=0)
        database.admin_users.create_index('username', unique=True)
        database.analytics.create_index([('event_type', ASCENDING), ('timestamp', ASCENDING)])
        database.analytics.create_index('expires_at', expireAfterSeconds=0)
        database.audit_logs.create_index('timestamp')
        database.audit_logs.create_index('admin_id')
        for name in ['registrations', 'admin_users', 'analytics', 'audit_logs']:
            database[name].create_index('legacy_id', unique=True, sparse=True)


mongo = MongoDB()
db = LocalProxy(mongo.database)
