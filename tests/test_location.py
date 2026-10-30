from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from pymongo.errors import AutoReconnect
from db import db
from models import Registration, utcnow
from conftest import draft,post,login,csrf


def location(token,**updates):
    return {'draft_token':token,'latitude':5.6037,'longitude':-.187,'accuracy_meters':12.5,
        'captured_at':datetime.now(timezone.utc).isoformat(),'consent':True,'confirmed':True,**updates}


def test_primary_acceptance_location_saved_before_submission(app,client):
    token=draft(client)
    result=post(client,'/api/registration/location',location(token))
    assert result.status_code==200
    assert result.json['message']=='Your location has been securely saved to your registration draft.'
    with app.app_context():
        raw=db.registrations.find_one();record=Registration(raw)
        assert record.full_name=='Ama Mensah'
        assert record.status=='location_saved' and record.submitted_at is None
        assert float(record.locations[0].latitude)==5.6037
        assert record.locations[0].consent.consent_granted
        assert '5.6037' not in raw['location']['latitude']
    admin=app.test_client();login(admin)
    result=admin.get('/admin/locations')
    assert result.status_code==200
    assert b'Ama Mensah' in result.data and b'Incomplete draft' in result.data and b'5.6037' in result.data


def test_location_before_name(app,client):
    token=post(client,'/api/registration/draft',{}).json['draft_token']
    assert post(client,'/api/registration/location',location(token)).status_code==200
    assert post(client,'/api/registration/draft',{'draft_token':token,'first_names':'Kofi','surname':'Boateng'}).status_code==200
    with app.app_context():
        record=Registration(db.registrations.find_one())
        assert record.full_name=='Kofi Boateng' and record.locations


def test_cross_session_and_wrong_token_rejected(app,client):
    token=draft(client);other=app.test_client();own=draft(other,first_names='Kofi')
    assert post(other,'/api/registration/location',location(token)).status_code==403
    assert post(client,'/api/registration/location',location(own)).status_code==403
    assert post(client,'/api/registration/location',location('forged')).status_code==403
    assert post(app.test_client(),'/api/registration/location',location(token)).status_code==403
    with app.app_context():
        assert db.registrations.count_documents({'location':{'$exists':True}})==0


def test_consent_confirmation_and_ranges_required(app,client):
    token=draft(client)
    for changes in [{'consent':False},{'confirmed':False},{'latitude':91},{'longitude':-181},{'accuracy_meters':-1},{'latitude':'5.6'},{'captured_at':'invalid'},{'latitude':True}]:
        assert post(client,'/api/registration/location',location(token,**changes)).status_code==400
    with app.app_context():
        assert 'location' not in db.registrations.find_one()


def test_decline_and_delete(app,client):
    token=draft(client)
    assert post(client,'/api/registration/location/decline',{'draft_token':token}).status_code==200
    with app.app_context():
        assert db.registrations.find_one()['consents'][0]['consent_granted'] is False
    assert post(client,'/api/registration/location',location(token)).status_code==200
    assert post(client,'/api/registration/delete',{'draft_token':token}).status_code==200
    with app.app_context():
        assert db.registrations.count_documents({})==0


def test_expired_location_purged(app,client):
    token=draft(client)
    assert post(client,'/api/registration/location',location(token)).status_code==200
    with app.app_context():
        db.registrations.update_one({}, {'$set':{'expires_at':utcnow()-timedelta(days=1)}})
    assert post(client,'/api/registration/location',location(token)).status_code==410
    assert app.test_cli_runner().invoke(args=['purge-expired']).exit_code==0
    with app.app_context():
        assert db.registrations.count_documents({})==0


def test_failed_write_never_claims_location_saved(app,client):
    token=draft(client);csrf_token=csrf(client)
    with app.app_context():
        collection=db.registrations
    with patch.object(collection,'find_one_and_update',side_effect=AutoReconnect('offline')):
        result=post(client,'/api/registration/location',location(token),token=csrf_token)
    assert result.status_code==503 and 'securely saved' not in result.get_data(as_text=True)
    with app.app_context():
        record=db.registrations.find_one()
        assert record['status']=='in_progress' and 'location' not in record and not record['consents']


def test_stale_update_cannot_overwrite_submitted_location(app,client):
    from services.database_service import bound_draft,mutate_draft
    from flask import session
    from werkzeug.exceptions import Conflict
    import pytest
    token=draft(client)
    with app.test_request_context('/'):
        session['draft_token']=token
        record=bound_draft(token)
        mutate_draft(record,{'status':'submitted','submitted_at':utcnow()})
        with pytest.raises(Conflict):
            mutate_draft(record,{'status':'location_saved'})
