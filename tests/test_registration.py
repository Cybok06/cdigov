import io
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from PIL import Image
from pymongo.errors import AutoReconnect
from db import db, mongo
from models import Registration, utcnow, cipher
from conftest import draft, post, csrf, login


def photo_upload(client,token,content=None):
    if content is None:
        content=io.BytesIO();Image.new('RGB',(50,50),'navy').save(content,'PNG');content.seek(0)
    return client.post('/api/registration/photo',data={'draft_token':token,'photo':(content,'photo.png')},headers={'X-CSRFToken':csrf(client)})


def test_draft_creation_update_and_encryption(app,client):
    token=draft(client)
    assert post(client,'/api/registration/draft',{'draft_token':token,'middle_names':'Akua'}).status_code==200
    with app.app_context():
        raw=db.registrations.find_one();record=Registration(raw)
        assert record.surname=='Mensah' and record.middle_names=='Akua'
        assert record.status=='in_progress' and record.submitted_at is None
        assert token not in record.draft_token_hash
        assert 'Mensah' not in raw['surname'] and raw['surname'].startswith('gAAAA')


def test_validation(client):
    for data in [{'surname':7},{'date_of_birth':'2999-01-01'},{'surname':'x'*151},{'dual_citizenship':'yes'},{'sex':'invalid'}]:
        assert post(client,'/api/registration/draft',data).status_code==400
    token=draft(client)
    assert post(client,'/api/registration/submit',{'draft_token':token}).status_code==400


def test_submission_idempotent(app,client):
    token=draft(client)
    location = {'draft_token':token,'latitude':5.6037,'longitude':-.187,'accuracy_meters':12.5,
        'captured_at':datetime.now(timezone.utc).isoformat(),'consent':True,'confirmed':True}
    assert post(client,'/api/registration/location',location).status_code == 200
    payload={'draft_token':token,'first_names':'Ama','surname':'Mensah','accuracy_confirmed':True,'processing_consent':True}
    first=post(client,'/api/registration/submit',payload);second=post(client,'/api/registration/submit',payload)
    assert first.status_code==second.status_code==200 and first.json==second.json
    assert client.get('/success').status_code==200
    assert post(client,'/api/registration/draft',{'draft_token':token}).status_code==409
    with app.app_context():
        record=db.registrations.find_one()
        assert record['status']=='submitted' and record['submitted_at']
        assert len(record['consents'])==3
        assert db.analytics.count_documents({'event_type':'registration_completed'})==1
        assert record['expires_at']>record['submitted_at']+timedelta(days=364)


def test_processing_consent_and_name_required(client):
    token=draft(client)
    for data in [{'first_names':'','surname':'Mensah','processing_consent':True,'accuracy_confirmed':True},
                 {'first_names':'Ama','surname':'Mensah','processing_consent':False,'accuracy_confirmed':True}]:
        assert post(client,'/api/registration/submit',{'draft_token':token,**data}).status_code==400


def test_image_validation_storage_and_protection(app,client):
    token=draft(client)
    assert photo_upload(client,token,io.BytesIO(b'not an image')).status_code==400
    assert photo_upload(client,token,io.BytesIO(b'x'*(5*1024*1024+1))).status_code==400
    assert photo_upload(client,token).status_code==200
    with app.app_context():
        raw=db.registrations.find_one();record_id=str(raw['_id']); key=raw['photo']['key']
        data=bytes(raw['photo']['data']); assert data.startswith(b'gAAAA')
        assert cipher().decrypt(data).startswith(b'\xff\xd8')
    assert client.get('/admin/registrations/'+record_id+'/photo').status_code==302
    assert client.get('/static/'+key).status_code==404
    admin=app.test_client();login(admin)
    response=admin.get('/admin/registrations/'+record_id+'/photo')
    assert response.status_code==200 and response.mimetype=='image/jpeg'


def test_expiration_and_deletion(app,client):
    token=draft(client)
    with app.app_context():
        db.registrations.update_one({}, {'$set':{'expires_at':utcnow()-timedelta(days=1)}})
    assert post(client,'/api/registration/draft',{'draft_token':token}).status_code==410
    assert app.test_cli_runner().invoke(args=['purge-expired']).exit_code==0
    with app.app_context():
        assert db.registrations.count_documents({})==0


def test_csrf_and_security_headers(client):
    assert client.post('/api/registration/draft',json={'surname':'Mensah'}).status_code==400
    result=client.get('/')
    assert "frame-ancestors 'none'" in result.headers['Content-Security-Policy']
    assert result.headers['Cache-Control']=='no-store, private'


def test_visitor_counts(app,client):
    client.get('/');client.get('/');app.test_client().get('/')
    with app.app_context():
        assert db.analytics.count_documents({'event_type':'page_view'})==3
        assert len(db.analytics.distinct('anonymous_visitor_id'))==2
        assert 'ip_address' not in db.analytics.find_one()


def test_photo_replacement_and_delete_are_atomic(app,client):
    token=draft(client);assert photo_upload(client,token).status_code==200
    with app.app_context():
        old_key=db.registrations.find_one()['photo']['key']
    assert photo_upload(client,token).status_code==200
    with app.app_context():
        raw=db.registrations.find_one()
        assert raw['photo']['key']!=old_key
        assert db.registrations.count_documents({'photo.key':old_key})==0
    assert post(client,'/api/registration/delete',{'draft_token':token}).status_code==200
    with app.app_context():
        assert db.registrations.count_documents({})==0


def test_failed_photo_write_keeps_existing_photo(app,client):
    token=draft(client);photo_upload(client,token)
    with app.app_context():
        old=db.registrations.find_one()['photo']
        collection=db.registrations
    csrf_token=csrf(client)
    image=io.BytesIO();Image.new('RGB',(10,10)).save(image,'PNG');image.seek(0)
    with patch.object(collection,'find_one_and_update',side_effect=AutoReconnect('offline')):
        result=client.post('/api/registration/photo',data={'draft_token':token,'photo':(image,'photo.png')},headers={'X-CSRFToken':csrf_token})
    assert result.status_code==503
    with app.app_context():
        assert db.registrations.find_one()['photo']==old


def test_indexes_and_init_command(app):
    assert app.test_cli_runner().invoke(args=['init-db']).exit_code==0
    with app.app_context():
        indexes=db.registrations.index_information()
        assert indexes['draft_token_hash_1']['unique']
        assert indexes['expires_at_1']['expireAfterSeconds']==0
        mongo.init_indexes()
