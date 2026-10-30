from datetime import date
from models import PERSONAL_FIELDS


def validate_fields(data, final=False):
    cleaned = {}
    for key in PERSONAL_FIELDS:
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, str):
            raise ValueError(f'{key.replace("_", " ").title()} must be text.')
        value = value.strip()
        if len(value) > (1000 if key == 'residential_address' else 150):
            raise ValueError(f'{key.replace("_", " ").title()} is too long.')
        if any(ord(char) < 32 for char in value):
            raise ValueError('Fields must not contain control characters.')
        if key == 'date_of_birth' and value:
            try:
                parsed = date.fromisoformat(value)
                if parsed > date.today() or parsed.year < 1900:
                    raise ValueError()
            except ValueError as exc:
                raise ValueError('Enter a valid date of birth between 1900 and today.') from exc
        if key == 'sex' and value not in {'', 'Female', 'Male', 'Other', 'Prefer not to say'}:
            raise ValueError('Choose a valid sex option.')
        cleaned[key] = value or None
    if 'dual_citizenship' in data:
        if type(data['dual_citizenship']) is not bool:
            raise ValueError('Choose Yes or No for dual citizenship.')
        cleaned['dual_citizenship'] = data['dual_citizenship']
    if final and (not cleaned.get('first_names') or not cleaned.get('surname')):
        raise ValueError('First name(s) and surname are required.')
    if final and cleaned.get('dual_citizenship') and not cleaned.get('second_nationality'):
        raise ValueError('Enter your second nationality.')
    if cleaned.get('dual_citizenship') is False:
        cleaned['second_nationality'] = None
    return cleaned

