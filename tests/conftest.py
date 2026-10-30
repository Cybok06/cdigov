import re
import mongomock
import pytest
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash
from app import create_app
from db import db, mongo
from models import encrypt, utcnow


@pytest.fixture
def app():
    application = create_app({'TESTING':True,'MONGO_CLIENT':mongomock.MongoClient(), 'MONGODB_DB':'cdigov_test',
        'SECRET_KEY':'test-session-key','ENCRYPTION_KEY':Fernet.generate_key().decode(),'SEARCH_KEY':'test-search-key',
        'WTF_CSRF_ENABLED':True,'RATELIMIT_ENABLED':False,'TRUSTED_HOSTS':['localhost','127.0.0.1'],
        'DEV_ADMIN_AUTH_DISABLED':False})
    with application.app_context():
        mongo.init_indexes()
        for role in ['owner','admin','viewer']:
            db.admin_users.insert_one(dict(username=role,email=encrypt(role+'@example.com'),role=role,is_active=True,
                created_at=utcnow(),password_hash=generate_password_hash('a-long-test-password')))
    yield application
    application.extensions['mongodb']['client'].close()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client,path='/'):
    content=client.get(path, follow_redirects=True).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"',content).group(1)


def post(client,path,data,token=None):
    return client.post(path,json=data,headers={'X-CSRFToken':token or csrf(client)})


def draft(client,**values):
    result=post(client,'/api/registration/draft',{'first_names':'Ama','surname':'Mensah',**values})
    assert result.status_code==200,result.get_data(as_text=True)
    return result.json['draft_token']


def login(client,role='owner'):
    token=csrf(client,'/admin/login')
    return client.post('/admin/login',data={'username':role,'password':'a-long-test-password','csrf_token':token})
