import secrets
import time
import click
from flask import Flask, request, redirect, jsonify, render_template, g
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError, DuplicateKeyError
from config import configuration
from db import db, mongo
from models import AdminUser, encrypt, utcnow
from extensions import login_manager, csrf, limiter


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(configuration(app.instance_path))
    if test_config:
        app.config.update(test_config)
    if app.config['TRUSTED_PROXY_HOPS']:
        hops = app.config['TRUSTED_PROXY_HOPS']
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)
    mongo.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'
    csrf.init_app(app)
    limiter.init_app(app)

    from routes.public import bp as public_bp
    from routes.registration import bp as registration_bp
    from routes.admin import bp as admin_bp
    for bp in [public_bp, registration_bp, admin_bp]:
        app.register_blueprint(bp)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            document = db.admin_users.find_one({'_id': ObjectId(user_id)})
            user = AdminUser(document) if document else None
            return user if user and user.is_active else None
        except (ValueError, TypeError, InvalidId):
            return None

    @app.before_request
    def before_request():
        g.nonce = secrets.token_urlsafe(24)
        if app.config['PRODUCTION'] and not request.is_secure:
            return redirect(request.url.replace('http://', 'https://', 1), code=308)
        if not app.testing and not app.config['PRODUCTION'] and not app.extensions.get('mongo_indexes_ready'):
            mongo.init_indexes()
            app.extensions['mongo_indexes_ready'] = True
        # Scheduled cleanup is authoritative; this also handles local/low-volume use.
        if not app.testing and time.monotonic() - app.extensions.get('last_purge', 0) > 3600:
            from services.database_service import purge_expired
            purge_expired()
            app.extensions['last_purge'] = time.monotonic()

    @app.after_request
    def security_headers(response):
        response.headers['Content-Security-Policy'] = (
            f"default-src 'self'; script-src 'self' 'nonce-{getattr(g, 'nonce', '')}' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "font-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: blob: https://tile.openstreetmap.org; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(self), camera=(), microphone=()'
        response.headers['Cache-Control'] = 'no-store, private'
        if app.config['PRODUCTION']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        if request.path.startswith('/api/'):
            return jsonify(error=exc.description), exc.code
        return render_template('error.html', code=exc.code, message=exc.description), exc.code

    @app.errorhandler(ValueError)
    def validation_error(exc):
        if request.path.startswith('/api/'):
            return jsonify(error=str(exc)), 400
        return render_template('error.html', code=400, message=str(exc)), 400

    @app.errorhandler(PyMongoError)
    def database_error(exc):
        app.logger.error('Database operation failed (%s)', type(exc).__name__)
        if request.path.startswith('/api/'):
            return jsonify(error='We could not save your changes. Please try again shortly.'), 503
        return render_template('error.html', code=503, message='The service is temporarily unavailable. Please try again shortly.'), 503

    @app.errorhandler(500)
    def server_error(exc):
        if request.path.startswith('/api/'):
            return jsonify(error='The service could not complete this request. Please retry shortly.'), 500
        return render_template('error.html', code=500, message='Please try again shortly.'), 500

    @app.cli.command('create-admin')
    @click.option('--username', default=None)
    @click.option('--email', prompt=True)
    @click.option('--role', type=click.Choice(['owner', 'admin', 'viewer']), default='owner')
    @click.option('--password', default=None, help='Omit to be prompted securely.')
    def create_admin(username, email, role, password):
        username = username or click.prompt('Username', default=app.config['DEV_ADMIN_USERNAME'])
        password = password or click.prompt('Password', hide_input=True, confirmation_prompt=True)
        development_password = (not app.config['PRODUCTION'] and username == app.config['DEV_ADMIN_USERNAME']
            and app.config['DEV_ADMIN_PASSWORD'] and password == app.config['DEV_ADMIN_PASSWORD'])
        if (not development_password and len(password) < 14) or len(password) > 256:
            raise click.ClickException('Use a password of 14–256 characters, except for the explicitly configured local development password.')
        if not username.strip() or len(username) > 80 or '@' not in email:
            raise click.ClickException('Provide a valid username and email.')
        mongo.init_indexes()
        if db.admin_users.find_one({'username': username.strip()}):
            raise click.ClickException('That username already exists.')
        try:
            db.admin_users.insert_one(dict(username=username.strip(), email=encrypt(email.strip()), role=role,
                password_hash=generate_password_hash(password), is_active=True, created_at=utcnow(), last_login=None))
        except DuplicateKeyError:
            raise click.ClickException('That username already exists.') from None
        click.echo('Administrator created.')

    @app.cli.command('purge-expired')
    def purge():
        from services.database_service import purge_expired
        total = purge_expired()
        click.echo(f'Deleted {total} expired registrations and their embedded photos/locations; expired analytics removed.')

    @app.cli.command('init-db')
    def init_db():
        try:
            db.command('ping')
            mongo.init_indexes()
        except PyMongoError as exc:
            raise click.ClickException(f'MongoDB connection failed: {type(exc).__name__}. Check MONGODB_URI, DNS, Atlas network access and credentials.') from None
        click.echo('MongoDB connected; CDIGOV indexes initialized.')

    @app.cli.command('bootstrap-admin')
    def bootstrap_admin():
        """Create the first administrator from ADMIN_BOOTSTRAP_* environment values."""
        username = app.config['ADMIN_BOOTSTRAP_USERNAME']
        email = app.config['ADMIN_BOOTSTRAP_EMAIL']
        password = app.config['ADMIN_BOOTSTRAP_PASSWORD']
        if not (username and email and password):
            click.echo('Administrator bootstrap skipped; ADMIN_BOOTSTRAP_* is not fully configured.')
            return
        if '@' not in email or not username or len(username) > 80:
            raise click.ClickException('ADMIN_BOOTSTRAP_USERNAME and ADMIN_BOOTSTRAP_EMAIL are invalid.')
        mongo.init_indexes()
        if db.admin_users.find_one({'username': username}):
            click.echo('Administrator already exists; bootstrap skipped.')
            return
        try:
            db.admin_users.insert_one(dict(username=username, email=encrypt(email), role='owner',
                password_hash=generate_password_hash(password), is_active=True, created_at=utcnow(), last_login=None))
        except DuplicateKeyError:
            click.echo('Administrator already exists; bootstrap skipped.')
            return
        click.echo('Initial administrator created.')

    @app.get('/health')
    def health():
        db.command('ping')
        return jsonify(status='ok')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
