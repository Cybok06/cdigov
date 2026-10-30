# CDIGOV

CDIGOV is a Flask registration service backed by MongoDB. Registration drafts, personal fields, consent history, confirmed locations, photographs, administrator accounts, audit records and anonymous analytics are stored in MongoDB. Personal values and coordinates are encrypted before they are written. Photographs are validated, stripped of EXIF metadata, encrypted and embedded in the registration document.

`db.py` is the only database connection layer. The unrelated performance listener and index-manager imports were removed, and the MongoDB URI is read from environment variables only. The URI is not hardcoded in application source and no database connection is made when the module is imported.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `MONGODB_URI` and `MONGODB_DB` in `.env`. For local MongoDB use `mongodb://127.0.0.1:27017/`. For Atlas use the Atlas SRV URI. The `.env` file is ignored by Git. The current workspace `.env` contains the URI you supplied; because that credential was previously exposed in `db.py`, rotate the MongoDB user password in Atlas before using this deployment.

The app generates development encryption/session/search keys in the ignored `instance` directory if they are missing. Keep those keys with the MongoDB data; replacing `ENCRYPTION_KEY` makes encrypted personal fields, coordinates and photographs unreadable.

For local development, `.env` can set `DEV_ADMIN_USERNAME=admin` and `DEV_ADMIN_PASSWORD=12345`. This exception is accepted only when `APP_ENV=development`, only for the configured development username, and only by the `create-admin` command. It is rejected in production. If an account already exists, the command never overwrites its password.

Initialize MongoDB indexes and start the app:

```powershell
python -m flask --app app init-db
python -m flask --app app create-admin --username admin --email admin@example.invalid --password 12345
python app.py
```

Open `http://127.0.0.1:5000`. The root URL displays the registration form directly. `/register` remains as a compatibility URL, while `/admin` redirects to login or the dashboard. The `init-db` command pings MongoDB and creates unique, status, search, retention, analytics and audit indexes. If Atlas reports a DNS, network-access or authentication error, fix that provider setting and rerun `init-db`; the command does not silently fall back to SQLite.

## Storage behavior

When a visitor enters a name, the server creates a browser-session-bound draft using a hashed server token. Location storage requires consent, a browser permission grant, and marker confirmation. The location and consent record are written in one atomic MongoDB document update. A draft with a saved location remains `location_saved` and is visible to administrators as an incomplete draft. Final submission is a conditional versioned update, so retries are idempotent. Drafts and submitted records have `expires_at` and are removed by the retention command.

MongoDB’s single-document atomicity is used deliberately: registration data, embedded consent records, a location and a photograph belong to one registration document. The application uses optimistic version checks so concurrent updates cannot silently overwrite each other. Large media is bounded below MongoDB’s document limit; if photographs grow beyond that constraint, move them to GridFS or private object storage rather than increasing the limit.

Run retention cleanup hourly:

```powershell
python -m flask --app app purge-expired
```

## Tests

```powershell
python -m pytest -q
python -m compileall -q app.py config.py db.py models.py routes services
```

The tests use `mongomock`, so they do not require network access or modify your Atlas database. They cover draft creation, encrypted fields, location-before-submission, consent and token binding, photo validation, duplicate submission, retention, MongoDB indexes, admin authorization, audit records, analytics and failure handling. The current suite passes 27 tests.

## Production

Use MongoDB Atlas or another replica set with TLS certificate validation enabled. Set `APP_ENV=production`, `MONGODB_URI`, `MONGODB_DB`, independent `SECRET_KEY`, `ENCRYPTION_KEY` and `SEARCH_KEY` secrets, `RATELIMIT_STORAGE_URI` backed by Redis, the real operator/contact/purpose, and exact `TRUSTED_HOSTS`. The app rejects production startup when MongoDB TLS is disabled, secrets are short, or the operator configuration is still the development placeholder. Deploy with:

```sh
gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60 app:app
```

Use `render.yaml` as the starting point for Render. Its pre-deploy command is `flask init-db`; it does not create MongoDB, Redis, DNS, HTTPS or credentials. Set those in the hosting provider’s secret manager. Schedule `flask purge-expired` separately and monitor failures. Configure encrypted Atlas backups, restricted database users, IP/network access, recovery testing and operator-approved retention and erasure procedures.

Before accepting real registrations, replace the operator placeholder, review the privacy notice and applicable Ghanaian data protection obligations, confirm your lawful processing basis and parental/children’s data process, and rotate the MongoDB credential that was present in the original `db.py`.
