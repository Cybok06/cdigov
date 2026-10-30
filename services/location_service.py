import math
from datetime import datetime, timezone, timedelta
from models import utcnow, encrypt
from services.database_service import consent, mutate_draft


def save_location(record, data):
    if data.get('consent') is not True or data.get('confirmed') is not True:
        raise ValueError('Agree to immediate storage and confirm your reported location first.')
    numbers = []
    for field, minimum, maximum in [('latitude', -90, 90), ('longitude', -180, 180), ('accuracy_meters', 0, 10_000_000)]:
        value = data.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f'Invalid {field.replace("_", " ")}.')
        numbers.append(value)
    try:
        captured = datetime.fromisoformat(data.get('captured_at', '').replace('Z', '+00:00'))
        if captured.tzinfo is None:
            raise ValueError()
        captured = captured.astimezone(timezone.utc).replace(tzinfo=None)
        if not utcnow() - timedelta(hours=24) <= captured <= utcnow() + timedelta(minutes=5):
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Capture a fresh location and try again.') from exc
    evidence = consent('location_immediate_storage')
    location = dict(zip(('latitude', 'longitude', 'accuracy_meters'), map(encrypt, numbers)))
    location.update(captured_at=captured, created_at=utcnow(), consent_record_id=evidence['id'])
    return mutate_draft(record, {'location': location, 'status': 'location_saved'}, [evidence])
