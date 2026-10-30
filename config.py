import os
from pathlib import Path
from datetime import timedelta
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()


def configuration(instance_path):
    production = os.getenv('APP_ENV') == 'production'
    root = Path(instance_path)
    root.mkdir(parents=True, exist_ok=True)

    def secret(name, generator):
        value = os.getenv(name)
        if value:
            return value
        if production:
            raise RuntimeError(f'{name} is required in production.')
        path = root / name.lower()
        if not path.exists():
            path.write_text(generator(), encoding='utf-8')
        return path.read_text(encoding='utf-8').strip()

    import secrets
    database = os.getenv('MONGODB_URI') or os.getenv('MONGO_URI') or 'mongodb://127.0.0.1:27017/'
    config = dict(
        SECRET_KEY=secret('SECRET_KEY', lambda: secrets.token_hex(48)),
        ENCRYPTION_KEY=secret('ENCRYPTION_KEY', lambda: Fernet.generate_key().decode()),
        SEARCH_KEY=secret('SEARCH_KEY', lambda: secrets.token_hex(48)),
        MONGODB_URI=database,
        MONGODB_DB=os.getenv('MONGODB_DB') or os.getenv('MONGO_DB_NAME') or 'cdigov',
        MONGO_MAX_POOL_SIZE=int(os.getenv('MONGO_MAX_POOL_SIZE', '30')),
        MONGO_TIMEOUT_MS=int(os.getenv('MONGO_SERVER_SELECTION_TIMEOUT_MS', '10000')),
        PRODUCTION=production,
        SESSION_COOKIE_SECURE=production,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        MAX_IMAGE_BYTES=5 * 1024 * 1024,
        UPLOAD_BACKEND='mongodb',
        RATELIMIT_STORAGE_URI=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'),
        DRAFT_RETENTION_DAYS=int(os.getenv('DRAFT_RETENTION_DAYS', '7')),
        SUBMISSION_RETENTION_DAYS=int(os.getenv('SUBMISSION_RETENTION_DAYS', '365')),
        ANALYTICS_RETENTION_DAYS=int(os.getenv('ANALYTICS_RETENTION_DAYS', '30')),
        PRIVACY_NOTICE_VERSION=os.getenv('PRIVACY_NOTICE_VERSION', '2026-10-30'),
        OPERATOR_NAME=os.getenv('OPERATOR_NAME', 'Independent registration operator (configure before launch)'),
        CONTACT_EMAIL=os.getenv('CONTACT_EMAIL', 'support@cdi.gov'),
        REGISTRATION_PURPOSE=os.getenv('REGISTRATION_PURPOSE', "Registration for the operator's community programme"),
        TRUSTED_HOSTS=[host.strip() for host in os.getenv(
            'TRUSTED_HOSTS', 'localhost,127.0.0.1'
        ).split(',') if host.strip()],
        TRUSTED_PROXY_HOPS=int(os.getenv('TRUSTED_PROXY_HOPS', '0')),
        DEV_ADMIN_USERNAME=os.getenv('DEV_ADMIN_USERNAME', 'admin'),
        DEV_ADMIN_PASSWORD=os.getenv('DEV_ADMIN_PASSWORD', ''),
        DEV_ADMIN_AUTH_DISABLED=os.getenv('DEV_ADMIN_AUTH_DISABLED', '').lower() in {'1', 'true', 'yes'},
    )
    if production:
        if not database.startswith(('mongodb://', 'mongodb+srv://')):
            raise RuntimeError('Configure a MongoDB URI.')
        from urllib.parse import parse_qs, urlsplit
        options = {key.lower(): value[-1].lower() for key, value in parse_qs(urlsplit(database).query).items()}
        if not (database.startswith('mongodb+srv://') or options.get('tls') == 'true') or options.get('tls') == 'false':
            raise RuntimeError('Production MongoDB connections must enable TLS.')
        if any(options.get(key) == 'true' for key in ('tlsinsecure', 'tlsallowinvalidcertificates', 'tlsallowinvalidhostnames')):
            raise RuntimeError('MongoDB TLS certificate validation must remain enabled.')
        if not config['RATELIMIT_STORAGE_URI'].startswith(('redis://', 'rediss://')):
            raise RuntimeError('Production requires shared Redis rate-limit storage.')
        if 'configure before launch' in config['OPERATOR_NAME'] or config['CONTACT_EMAIL'].endswith('.invalid'):
            raise RuntimeError('Configure the actual operator and contact email before launch.')
        if len(config['SECRET_KEY']) < 32 or len(config['SEARCH_KEY']) < 32:
            raise RuntimeError('Secrets must have at least 32 characters.')
        if config['DEV_ADMIN_PASSWORD']:
            raise RuntimeError('DEV_ADMIN_PASSWORD must not be configured in production.')
        if config['DEV_ADMIN_AUTH_DISABLED']:
            raise RuntimeError('DEV_ADMIN_AUTH_DISABLED must not be enabled in production.')
    if min(config[k] for k in ('DRAFT_RETENTION_DAYS', 'SUBMISSION_RETENTION_DAYS', 'ANALYTICS_RETENTION_DAYS')) < 1:
        raise RuntimeError('Retention periods must be positive.')
    Fernet(config['ENCRYPTION_KEY'].encode())
    return config
