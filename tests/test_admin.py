from datetime import timedelta
from db import db
from models import utcnow
from conftest import draft,csrf,login


def test_login_required(client):
    for path in ['/admin/dashboard','/admin/registrations','/admin/locations','/admin/visitors','/admin/settings','/admin/registrations/123','/admin/registrations/123/photo']:
        assert client.get(path).status_code==302


def test_admin_authentication_and_pages(app,client):
    token=csrf(client,'/admin/login')
    assert client.post('/admin/login',data={'username':'owner','password':'wrong','csrf_token':token}).status_code==200
    assert client.get('/admin/dashboard').status_code==302
    assert login(client).status_code==302
    for path in ['/admin/dashboard','/admin/registrations','/admin/locations','/admin/visitors','/admin/settings']:
        result=client.get(path);assert result.status_code==200,(path,result.get_data(as_text=True))
    with app.app_context():
        assert db.audit_logs.count_documents({})>=4


def test_sensitive_views_search_and_role_deletion(app):
    visitor=app.test_client();draft(visitor)
    with app.app_context():
        record=db.registrations.find_one();record_id=str(record['_id']);reference=record['reference_number']
    path='/admin/registrations/'+record_id
    viewer=app.test_client();login(viewer,'viewer')
    assert b'Ama Mensah' in viewer.get('/admin/registrations?q=Ama').data
    assert b'Ama Mensah' not in viewer.get('/admin/registrations?q=Kofi').data
    assert viewer.get(path).status_code==200
    token=csrf(viewer,'/admin/settings')
    assert viewer.post(path+'/delete',data={'csrf_token':token,'reference':reference}).status_code==403
    owner=app.test_client();login(owner);token=csrf(owner,'/admin/settings')
    assert owner.post(path+'/delete',data={'csrf_token':token,'reference':reference}).status_code==302
    assert owner.get(path).status_code==404
    assert owner.get('/admin/registrations/not-an-id').status_code==404
    with app.app_context():
        assert db.audit_logs.find_one({'action':'delete_record'})


def test_disabled_user(app,client):
    login(client)
    with app.app_context():
        db.admin_users.update_one({'username':'owner'},{'$set':{'is_active':False}})
    assert client.get('/admin/dashboard').status_code==302


def test_password_change(client):
    login(client);token=csrf(client,'/admin/settings')
    result=client.post('/admin/settings',data={'csrf_token':token,'current_password':'a-long-test-password','new_password':'a-new-long-password'})
    assert result.status_code==200 and b'Password updated' in result.data


def test_create_admin_command(app):
    result=app.test_cli_runner().invoke(args=['create-admin','--username','new','--email','new@example.com','--password','a-new-very-long-password'])
    assert result.exit_code==0,result.output
    duplicate=app.test_cli_runner().invoke(args=['create-admin','--username','new','--email','new@example.com','--password','a-new-very-long-password'])
    assert duplicate.exit_code!=0


def test_date_filters(client):
    login(client)
    assert client.get('/admin/dashboard?start=invalid').status_code==400
    assert client.get('/admin/dashboard?start=2020-01-01&end=2026-01-01').status_code==400


def test_expired_draft_is_not_readable(app,client):
    draft(client)
    with app.app_context():
        record_id=str(db.registrations.find_one()['_id'])
        db.registrations.update_one({}, {'$set':{'expires_at':utcnow()-timedelta(days=1)}})
    login(client)
    assert client.get('/admin/registrations/'+record_id).status_code==404
    assert b'Ama Mensah' not in client.get('/admin/registrations').data


def test_admin_entry_route_and_public_routing(app, client):
    root = client.get('/')
    assert root.status_code == 200
    assert b'Personal information' in root.data
    assert b'Start Registration' not in root.data
    assert b'As you enter your name' not in root.data
    assert b'Delete my draft' not in root.data
    assert b'REGISTRATION SERVICES' not in root.data
    assert b'Operated by' not in root.data
    assert b'Independent service' not in root.data
    assert b'operator@example.invalid' not in root.data
    assert b'National ID update' in root.data
    assert client.get('/register').status_code == 200
    assert client.get('/register/').status_code == 302
    assert client.get('/admin').status_code == 302
    assert client.get('/admin').headers['Location'].endswith('/admin/login')
    login(client)
    assert client.get('/admin').status_code == 302
    assert client.get('/admin').headers['Location'].endswith('/admin/dashboard')


def test_passcode_only_login_uses_configured_admin(app, client):
    token = csrf(client, '/admin/login')
    result = client.post('/admin/login', data={'password': 'a-long-test-password', 'csrf_token': token})
    assert result.status_code == 302
    assert result.headers['Location'].endswith('/admin/dashboard')


def test_local_admin_bypass_opens_dashboard(app, client):
    app.config['DEV_ADMIN_AUTH_DISABLED'] = True
    result = client.get('/admin', follow_redirects=True)
    assert result.status_code == 200
    assert b'At a glance' in result.data
    assert client.get('/admin/dashboard').status_code == 200
