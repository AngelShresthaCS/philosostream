# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run from `backend/` with the venv active (Python 3.12).

```powershell
.venv\Scripts\activate          # Readme.md documents this as the first step

uvicorn app.main:app --reload   # dev server (http://127.0.0.1:8000, docs at /docs)

python -m pytest app/tests                          # all tests
python -m pytest app/tests/test_notes.py::test_root  # a single test
```

No linter or formatter is configured.

`MONGODB_URL` must be set in `backend/.env`; `app/core/database.py` reads it via
`os.environ[...]` at import time, so the app fails immediately if it's missing.
`GET /ping-db` is the liveness check for the Mongo connection.

## Architecture

FastAPI backend for a notes app, backed by MongoDB through pymongo's async
`AsyncMongoClient`. `app/main.py` mounts three routers (`notes`, `auth`, `users`)
and manages the Mongo connection with `startup`/`shutdown` events.

There is no ORM, model, or repository layer. Each route handler reaches into
Mongo directly: `db = client.philosostream`, then `db.notes` / `db.users`.

**The lazy `client` import is load-bearing.** `app/core/database.py` holds a
module-level global `client` that is `None` until `connect_to_mongo()` runs on
startup. Handlers therefore do `from ..core.database import client` *inside the
function body* and guard on `client is None` — a module-level import would
capture `None` permanently. Preserve this pattern in new handlers.

**ObjectId handling is manual.** Handlers stringify `note["_id"]` /
`created_user["_id"]` before returning. Response schemas (`NoteResponse`,
`UserOut`) declare `id` with `alias="_id"`, and the routes pass
`response_model_by_alias=False` so the client sees `id`.

**Auth flow.** `POST /login` verifies credentials and mints an HS256 JWT whose
`user_id` claim is the stringified Mongo `ObjectId`. `oauth2.get_current_user`
only validates the token and returns a `TokenData` carrying that id — it does
*not* load the user, so handlers needing user fields query `db.users` themselves
(see `create_note` in `app/routers/notes.py`).

Note two rough edges here: `SECRET_KEY` is hardcoded in `app/core/oauth2.py`,
and `oauth2_scheme` is declared as `OAuth2PasswordBearer(tokenUrl='login')`
while `/login` actually accepts a JSON body (`auth_schema.ValidateUser`), not
form data — so Swagger's Authorize button cannot drive the real login endpoint.

**Password hashing.** `app/utils/hashing.py` truncates passwords to 72 bytes in
*both* `hash()` and `verify()` to stay under bcrypt's limit. The two must apply
identical encode/truncate/decode logic or existing hashes stop verifying.
Schemas also cap `password` at `max_length=72`.

## Known drift

- `requirements.txt` is out of sync with the venv: `pymongo` (installed, 4.17)
  and `pytest` (9.1.1) are missing from it, while `SQLAlchemy` and
  `psycopg2-binary` are leftovers from an earlier Postgres design and unused.
  `httpx` is absent entirely, so `fastapi.testclient.TestClient` cannot import.
- `app/tests/` are stubs: `test_auth.py` is a bare import and `test_notes.py`
  references an undefined `client`, so it raises `NameError`. There is no
  `conftest.py` or `TestClient` fixture yet.
- `TokenData` is defined twice (`schemas/auth_schema.py` and
  `schemas/oauth2_schema.py`); `oauth2.py` uses the `oauth2_schema` one.
  `oauth2_schema.Post` and the `orm_mode` configs are dead Postgres-era code.
- Subpackages under `app/` have no `__init__.py` (only `app/__init__.py` exists);
  imports work via implicit namespace packages.
- `../frontend/` exists but is empty.