"""Validate and encrypt bounded photos for atomic embedding in MongoDB registrations."""
import io
import secrets
import warnings
from pathlib import Path
from bson.binary import Binary
from PIL import Image, ImageOps, UnidentifiedImageError
from cryptography.fernet import InvalidToken
from flask import current_app, abort
from db import db
from models import cipher
from services.database_service import retained_condition


def prepare_image(upload):
    raw = upload.read(current_app.config['MAX_IMAGE_BYTES'] + 1)
    if len(raw) > current_app.config['MAX_IMAGE_BYTES']:
        raise ValueError('Choose a photograph smaller than 5 MB.')
    if Path(upload.filename or '').suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
        raise ValueError('Choose a JPG, PNG or WebP photograph.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ValueError('The file content must be JPG, PNG or WebP.')
                if image.width * image.height > 20_000_000:
                    raise ValueError('Photograph resolution must be under 20 megapixels.')
                image.load()
                clean = ImageOps.exif_transpose(image).convert('RGB')
                clean.thumbnail((1600, 1600))
                output = io.BytesIO()
                clean.save(output, 'JPEG', quality=88)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('This photograph could not be read. Choose a valid image.') from exc
    encrypted = cipher().encrypt(output.getvalue())
    if len(encrypted) > 8 * 1024 * 1024:
        raise ValueError('The processed photograph is too large. Choose a smaller image.')
    return {'key': secrets.token_hex(24), 'data': Binary(encrypted)}


def read_image(key):
    document = db.registrations.find_one({'photo.key': key, **retained_condition()}, {'photo.data': 1})
    if not document:
        abort(404)
    try:
        return cipher().decrypt(bytes(document['photo']['data']))
    except InvalidToken:
        abort(404)
