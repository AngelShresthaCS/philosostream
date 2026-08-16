# PhilosoStream — Architecture Review, Approaches & Roadmap

> A decision guide for the FastAPI + MongoDB backend at `backend/app/`.
> Every option below is scored on **beginner friendliness**, **learning value**,
> **operational excellence**, and **business efficiency**, with a recommended pick
> and copy-pasteable steps.

**Written against the code as of 2026-08-15.** Facts in "Where you are today" were
verified by reading the source and inspecting `backend/.venv` — not assumed.

---

## Table of contents

1. [How to use this document](#1-how-to-use-this-document)
2. [Where you are today](#2-where-you-are-today)
3. [The scorecard method](#3-the-scorecard-method)
4. [Phase 0 — Stop the bleeding](#4-phase-0--stop-the-bleeding)
5. [The eleven decisions](#5-the-eleven-decisions)
   - [D1 — Configuration & secrets](#d1--configuration--secrets)
   - [D2 — Database connection & injection](#d2--database-connection--injection)
   - [D3 — Data access layer](#d3--data-access-layer)
   - [D4 — Document modelling & indexes](#d4--document-modelling--indexes)
   - [D5 — Authentication](#d5--authentication)
   - [D6 — Testing](#d6--testing)
   - [D7 — Dependency management](#d7--dependency-management)
   - [D8 — Errors, logging & observability](#d8--errors-logging--observability)
   - [D9 — Frontend](#d9--frontend)
   - [D10 — Deployment](#d10--deployment)
   - [D11 — CI/CD](#d11--cicd)
6. [The recommended path (sequenced)](#6-the-recommended-path-sequenced)
7. [Command cheat sheet](#7-command-cheat-sheet)
8. [How to find help](#8-how-to-find-help)
9. [Glossary](#9-glossary)

---

## 1. How to use this document

This is **not** a "rewrite everything" plan. Your architecture is a reasonable
beginner FastAPI layout, and most of it should survive. The document is organised
as a series of **independent decisions**. Each one has:

- **The situation** — what your code does today
- **Approach A / B / C** — the realistic options, not a strawman list
- **Scorecard** — 1–5 on the four criteria
- **Verdict** — one pick, with the reason
- **Steps** — the actual commands and code

Read §4 first (it is short and urgent). Then work through §6, which puts the
decisions in dependency order. You can stop at any phase boundary and still have
a working, coherent app — that is deliberate.

**Rule of thumb used throughout:** prefer the option that teaches you a
transferable concept over the one that hides it, *unless* the hidden thing is
security-critical. You should hand-roll a repository layer (learning value); you
should not hand-roll a password hash (operational risk).

---

## 2. Where you are today

### 2.1 The map

```
philosostream/
├── backend/
│   ├── .env                      MONGODB_URL only          ⚠ not gitignored (no repo yet)
│   ├── .venv/                    Python 3.12.10
│   ├── requirements.txt          ⚠ drifted from .venv (see 2.3)
│   ├── CLAUDE.md                 accurate architecture notes
│   ├── Readme.md                 2 lines
│   ├── documentations/           ← you are here
│   └── app/
│       ├── main.py               FastAPI(), 3 routers, @on_event startup/shutdown
│       ├── core/
│       │   ├── database.py       module-global `client`, lazy-imported by handlers
│       │   └── oauth2.py         HS256 JWT mint/verify   ⚠ SECRET_KEY hardcoded
│       ├── routers/
│       │   ├── notes.py          GET /notes/  POST /notes/
│       │   ├── auth.py           POST /login
│       │   └── users.py          POST /users
│       ├── schemas/              Pydantic v2 models (4 files)
│       ├── utils/hashing.py      passlib CryptContext + bcrypt, 72-byte truncation
│       └── tests/                ⚠ two stub files, neither runs
└── frontend/                     empty directory
```

### 2.2 A request, traced end to end

`POST /notes/` is the most interesting path — follow it once and the whole
codebase makes sense:

```
 1. Client sends  { "content": "..." }  + header  Authorization: Bearer <jwt>
 2. FastAPI matches app/routers/notes.py:39  create_note
 3. Depends(oauth2.get_current_user)
      → OAuth2PasswordBearer pulls the token out of the header
      → verify_access_token decodes HS256, reads the "user_id" claim
      → returns TokenData(id="<mongo objectid as string>")
      → NOTE: it never loads the user document
 4. Body is validated into NoteCreate  (content: str, time: datetime = now UTC)
 5. `from ..core.database import client`  ← INSIDE the function, deliberately
 6. Handler queries db.users itself to get username (because step 3 didn't)
 7. note.model_dump() → dict, + username → collection.insert_one
 8. Re-reads the inserted doc, stringifies _id, returns it
 9. NoteResponse serialises;  response_model_by_alias=False turns _id into id
```

Three patterns are **load-bearing** and you should keep them until D2 replaces
them wholesale:

- **The lazy import in step 5.** `client` is `None` at import time and only gets a
  value when `connect_to_mongo()` runs on startup. A module-level
  `from ..core.database import client` would bind `None` forever. This is why
  every handler repeats the import and the `if client is None` guard.
- **Manual ObjectId stringification.** BSON `ObjectId` is not JSON-serialisable,
  so handlers cast `_id` to `str` before returning.
- **Symmetric 72-byte truncation** in `hashing.hash()` and `hashing.verify()`.
  bcrypt ignores bytes past 72; both functions must truncate *identically* or
  existing hashes stop verifying.

### 2.3 Verified drift between `requirements.txt` and `.venv`

I ran `pip list` inside `backend/.venv` and compared. This matters more than it
looks — a fresh `pip install -r requirements.txt` today produces a **broken app**:

| Package | `requirements.txt` | Actually installed | Consequence |
|---|---|---|---|
| `bcrypt` | `5.0.0` | **`3.2.2`** | 🔴 passlib 1.7.4 breaks on bcrypt ≥ 4.1 (`AttributeError: module 'bcrypt' has no attribute '__about__'`). Your venv was pinned back to 3.2.2 to work around it; the file was not. Reinstalling from the file breaks login. |
| `pymongo` | *absent* | `4.17.0` | 🔴 The database driver is not declared at all. Fresh install → `ImportError`. |
| `pytest` | *absent* | `9.1.1` | 🟠 Tests can't run from a clean env. |
| `httpx` | *absent* | *absent* | 🔴 `fastapi.testclient.TestClient` requires it. This is why `app/tests/` cannot work. |
| `SQLAlchemy`, `psycopg2-binary` | present | present | 🟡 Dead weight from an abandoned Postgres design. Nothing imports them. |

### 2.4 Correctness and security issues found while reading

Ranked by how much they'd hurt. Each links to the decision that fixes it.

| # | Where | Issue | Fix in |
|---|---|---|---|
| 1 | `app/core/oauth2.py:12` | `SECRET_KEY` is a hardcoded literal in source. Anyone who sees the file can mint valid tokens for any user. | [D1](#d1--configuration--secrets) |
| 2 | `app/schemas/user_schema.py` `UserOut` | Declares `password: str`, so **`POST /users` returns the bcrypt hash** in the response body. | [Phase 0](#4-phase-0--stop-the-bleeding) |
| 3 | `app/schemas/user_schema.py` `UserOut` | `name: str` is required, but `User.name` is `Optional[str] = None`. Registering without a name → `ResponseValidationError` → 500 **after** the user was already written. | [Phase 0](#4-phase-0--stop-the-bleeding) |
| 4 | repo root | No git repo, no `.gitignore`, and `.env` holds a live Atlas URI. The first `git add .` commits your database credentials. | [Phase 0](#4-phase-0--stop-the-bleeding) |
| 5 | `app/routers/notes.py:56` | Notes store `username` but **no `owner_id`**. You cannot reliably list "my notes", enforce ownership on edit/delete, or survive a username change. | [D4](#d4--document-modelling--indexes) |
| 6 | `app/routers/notes.py:32` | `to_list(length=100)` with no `skip`/`limit` params and no sort. Silently truncates at 100 and returns them in unspecified order. | [D4](#d4--document-modelling--indexes) |
| 7 | `app/routers/users.py` | No uniqueness constraint on `email` or `username`. Two accounts can share an email; `/login`'s `find_one` then picks an arbitrary one. | [D4](#d4--document-modelling--indexes) |
| 8 | `app/core/oauth2.py:16` | `datetime.utcnow()` is deprecated in Python 3.12 and returns a *naive* datetime. Use `datetime.now(timezone.utc)`. | [D5](#d5--authentication) |
| 9 | `app/core/oauth2.py:9` | `OAuth2PasswordBearer(tokenUrl='login')` promises a form-encoded token endpoint, but `/login` takes a JSON body. Swagger's **Authorize** button is therefore broken. | [D5](#d5--authentication) |
| 10 | `app/main.py:13,17` | `@app.on_event(...)` is deprecated in favour of `lifespan`. | [D2](#d2--database-connection--injection) |
| 11 | `app/routers/users.py:31`, `notes.py:66` | `print()` used as logging. Unstructured, unfilterable, invisible in most hosts' log tooling. | [D8](#d8-errors-logging--observability) |
| 12 | `app/schemas/` | `TokenData` defined twice (`auth_schema.py`, `oauth2_schema.py`); `oauth2_schema.Post` and the `orm_mode` configs are dead Postgres-era code. | [D3](#d3--data-access-layer) |
| 13 | `app/` subpackages | Only `app/__init__.py` exists; `core/`, `routers/`, `schemas/`, `utils/`, `tests/` have none. Works via implicit namespace packages, but breaks some packaging and test-discovery setups. | [D6](#d6--testing) |

> **None of this means the code is bad.** Items 1–4 are the kind of thing every
> self-taught backend has at this stage. They are listed bluntly because they're
> cheap to fix now and expensive to fix after you have real users.

---

## 3. The scorecard method

Every option is rated **1 (poor) to 5 (excellent)** on your four criteria:

| Criterion | The question it answers |
|---|---|
| 🟢 **Beginner friendly** | How likely are you to get stuck for hours? How much new vocabulary before the first win? |
| 🔵 **Learning value** | Does doing it teach a concept that transfers to your next job / next project? Magic that "just works" scores low here even when it's a fine choice. |
| 🟣 **Operational excellence** | When it breaks at 2am, can you tell *why*? Is it secure, observable, reproducible, testable? |
| 🟠 **Business efficiency** | Time-to-feature and cost. Does it get a working product in front of users sooner and keep the bill small? |

These conflict on purpose. An ODM scores high on business efficiency and low on
learning value. Hand-rolled auth is the reverse. The **Verdict** line says which
criterion won and why — disagree with the weighting and you should pick
differently.

---

## 4. Phase 0 — Stop the bleeding

**Do these five things before anything else in this document.** Total time: ~30
minutes. They are not architecture; they are the fire extinguisher.

### 0.1 — Initialise git *with* a `.gitignore` (before the first commit)

Order matters. Create the ignore file first, or the secret lands in history where
deleting the file won't remove it.

```powershell
cd C:\Users\angel\Desktop\philosostream
```

Create `.gitignore` at the repo root:

```gitignore
# Secrets
.env
.env.*
!.env.example

# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/

# Node
node_modules/
dist/
.next/

# Editors / OS
.vscode/
.idea/
.DS_Store
Thumbs.db
```

Then:

```powershell
git init
git add .gitignore
git commit -m "chore: add gitignore before anything else"
git status          # CONFIRM .env is NOT listed
git add .
git commit -m "chore: initial commit of FastAPI + MongoDB backend"
```

> ⚠ If `git status` shows `.env` at any point, **stop** and fix `.gitignore`
> before committing. Removing a secret from git history later requires
> `git filter-repo` and a force-push — and you'd still have to rotate the
> credential because it may already be cached.

### 0.2 — Add `.env.example`

The template that *is* committed, so future-you (and any collaborator) knows what
to fill in. Values are placeholders, never real.

```dotenv
# backend/.env.example
MONGODB_URL=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
DB_NAME=philosostream
SECRET_KEY=generate-with-python-c-import-secrets-print-secrets-token_hex-32
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

### 0.3 — Rotate the hardcoded JWT secret

The literal in `app/core/oauth2.py:12` is in your source and (until Phase 0.1)
was unprotected. Treat it as compromised. Generate a real one:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Put the output in `backend/.env` as `SECRET_KEY=...`. [D1](#d1--configuration--secrets)
wires it in properly. Rotating invalidates all existing tokens — harmless now,
disruptive later, which is exactly why you do it today.

### 0.4 — Stop returning the password hash

`UserOut` currently serialises `password`. Two fields change:

```python
# app/schemas/user_schema.py
class UserOut(BaseModel):
    id: Optional[str] = Field(alias="_id", default=None)
    username: str
    name: Optional[str] = None      # was: name: str  → 500 when name is omitted
    email: EmailStr
    # password removed — never send a hash to a client, not even your own frontend

    model_config = {"populate_by_name": True}
```

This fixes issues **#2 and #3** together. Verify:

```powershell
# should show id, username, name, email — and no password
curl -X POST http://127.0.0.1:8000/users -H "Content-Type: application/json" `
  -d '{\"username\":\"t1\",\"email\":\"t1@example.com\",\"password\":\"password123\"}'
```

### 0.5 — Make `requirements.txt` describe reality

Right now it is actively misleading (see [§2.3](#23-verified-drift-between-requirementstxt-and-venv)).
A one-line stopgap until [D7](#d7--dependency-management) does it properly:

```powershell
cd C:\Users\angel\Desktop\philosostream\backend
.\.venv\Scripts\Activate.ps1
pip install httpx pytest-asyncio pydantic-settings
pip uninstall -y SQLAlchemy psycopg2-binary
pip freeze > requirements.txt
```

> **Leave `bcrypt` at 3.2.2 for now.** Do not "upgrade" it to match the old file —
> passlib 1.7.4 (last released 2020) breaks on bcrypt ≥ 4.1.
> [D5](#d5--authentication) removes passlib entirely, which is the real fix.

---

## 5. The eleven decisions

### D1 — Configuration & secrets

**Situation.** `database.py` does `os.environ["MONGODB_URL"]` at import time;
`oauth2.py` hardcodes `SECRET_KEY`, `ALGORITHM`, and the token TTL as module
constants. Config is scattered across two files in two different styles, and one
of them is a secret in source control.

| | Approach A: `os.environ` everywhere *(today)* | Approach B: `pydantic-settings` ✅ | Approach C: Cloud secret manager |
|---|---|---|---|
| What | Read env vars where needed | One typed `Settings` class, validated at startup | AWS Secrets Manager / Doppler / Infisical |
| 🟢 Beginner | 5 | 4 | 2 |
| 🔵 Learning | 2 | 5 | 3 |
| 🟣 Ops | 2 | 4 | 5 |
| 🟠 Business | 3 | 5 | 2 |

**Verdict → B.** `pydantic-settings` is the same Pydantic you already use for
request bodies, pointed at environment variables. You get typed config
(`access_token_expire_minutes` is an `int`, not a string), defaults, and — the
real win — the app **fails at startup with a clear message** if a variable is
missing, instead of at 3am inside a request handler. C is correct for a funded
team; it is overhead you don't need until you have more than one deployed
environment.

**Steps.**

```powershell
pip install pydantic-settings
```

Create `app/core/config.py`:

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every environment variable the app needs, in one typed place.

    Names are case-insensitive: MONGODB_URL in .env fills mongodb_url here.
    A missing variable without a default raises ValidationError at import,
    which is exactly what you want — fail loud, fail at boot.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongodb_url: str
    db_name: str = "philosostream"

    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed once per process, not per import."""
    return Settings()


settings = get_settings()
```

Then replace the constants:

```python
# app/core/oauth2.py  — delete the three module constants, import instead
from .config import settings

# ... and use settings.secret_key / settings.algorithm /
#     settings.access_token_expire_minutes at the call sites
```

**Verify** it fails correctly — this is the whole point:

```powershell
# temporarily rename .env, then start the app
Rename-Item .env .env.bak
uvicorn app.main:app          # expect: ValidationError naming the missing field
Rename-Item .env.bak .env
```

📖 https://docs.pydantic.dev/latest/concepts/pydantic_settings/

---

### D2 — Database connection & injection

**Situation.** A module-level `client` global, `None` until `connect_to_mongo()`
runs in an `@app.on_event("startup")` handler. Every handler works around this
with a function-body import plus a `client is None` guard, then rebuilds
`db = client.philosostream` by hand. The `@on_event` decorator is deprecated.

| | Approach A: global + lazy import *(today)* | Approach B: `lifespan` + `Depends(get_db)` ✅ | Approach C: ODM-managed (Beanie) |
|---|---|---|---|
| Boilerplate per handler | 5 lines | 0 | 0 |
| Swappable in tests | ✗ (monkeypatch a global) | ✓ (`dependency_overrides`) | partial |
| 🟢 Beginner | 3 | 4 | 3 |
| 🔵 Learning | 2 | 5 | 2 |
| 🟣 Ops | 2 | 5 | 4 |
| 🟠 Business | 2 | 5 | 4 |

**Verdict → B.** This is the single highest-leverage change in the document. It
deletes the lazy-import workaround, the `None` guard, and the repeated
`client.philosostream` in *every* handler — and, critically, it makes the
database **overridable in tests** via `app.dependency_overrides`, which is the
prerequisite for [D6](#d6--testing). Dependency injection is also the concept
FastAPI is built around; learning it here pays off in every future handler.

**Steps.**

Rewrite `app/core/database.py`:

```python
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once on startup (before yield) and once on shutdown (after).

    Replaces the deprecated @app.on_event pair. Connecting here means the app
    refuses to start against an unreachable database, rather than serving 503s.
    """
    client = AsyncMongoClient(settings.mongodb_url)
    await client.admin.command("ping")      # fail fast if Atlas is unreachable
    app.state.mongo_client = client

    db = client[settings.db_name]
    await _ensure_indexes(db)               # see D4

    yield                                   # ---- app serves requests here ----

    await client.close()


async def _ensure_indexes(db: AsyncDatabase) -> None:
    """Idempotent: creating an index that already exists is a no-op."""
    await db.users.create_index("email", unique=True)
    await db.users.create_index("username", unique=True)
    await db.notes.create_index([("owner_id", ASCENDING), ("time", DESCENDING)])


def get_db(request: Request) -> AsyncDatabase:
    """FastAPI dependency. The client lives on app.state, so there is no
    module-level global to be None, and tests can override this function."""
    return request.app.state.mongo_client[settings.db_name]


# Reusable annotated type so handlers read as:  async def f(db: DB):
DB = Annotated[AsyncDatabase, Depends(get_db)]
```

Update `app/main.py`:

```python
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .core.database import lifespan
from .routers import auth, notes, users

app = FastAPI(
    title="PhilosoStream API",
    version="0.1.0",
    lifespan=lifespan,          # replaces both @app.on_event handlers
)

app.include_router(notes.router)
app.include_router(auth.router)
app.include_router(users.router)


@app.get("/health", tags=["ops"])
async def health():
    """Liveness only — no DB call. Load balancers hit this constantly."""
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready():
    """Readiness — verifies the dependency chain. Use this for deploy gates."""
    from .core.database import get_db  # noqa: PLC0415
    try:
        await app.state.mongo_client.admin.command("ping")
        return {"ready": True}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"ready": False, "error": str(exc)})
```

Now every handler collapses. `get_notes` becomes:

```python
# app/routers/notes.py
from ..core.database import DB

@router.get("/", response_model=List[NoteResponse], response_model_by_alias=False)
async def get_notes(db: DB):
    # no lazy import, no None guard, no client.philosostream
    notes = await db.notes.find({}).to_list(length=100)
    for note in notes:
        note["_id"] = str(note["_id"])
    return notes
```

> **Keep the manual `_id` stringification.** It is still needed — `lifespan` and
> DI change *how you reach* the collection, not how BSON serialises.
> [D3](#d3--data-access-layer) is where that repetition goes away.

📖 https://fastapi.tiangolo.com/advanced/events/ · https://fastapi.tiangolo.com/tutorial/dependencies/

---

### D3 — Data access layer

**Situation.** No layer at all. Handlers build queries, run them, reshape
`ObjectId`s, and return. HTTP concerns and database concerns are the same twelve
lines. `create_note` additionally re-queries `db.users` because
`get_current_user` doesn't load the user.

| | Approach A: inline in handlers *(today)* | Approach B: repository functions ✅ | Approach C: ODM (Beanie / ODMantic) |
|---|---|---|---|
| Lines to add a CRUD endpoint | ~20 | ~8 | ~4 |
| Query reuse across handlers | none | high | high |
| Testable without HTTP | ✗ | ✓ | ✓ |
| 🟢 Beginner | 5 | 4 | 3 |
| 🔵 Learning | 2 | 5 | 2 |
| 🟣 Ops | 2 | 4 | 4 |
| 🟠 Business | 3 | 4 | 5 |

**Verdict → B.** A repository is just *"a module of plain async functions that
take a `db` and return dicts"* — no framework, no magic, maybe 40 lines. You get
the payoff (reuse, unit-testable queries, one place where `ObjectId` is handled)
while still writing the Mongo queries yourself, which is where the learning is.

Approach C is genuinely good and you should revisit it later. Beanie gives you
Pydantic models that *are* Mongo documents, with `Note.find(Note.owner_id == x)`
instead of dicts. It scores lower here only on learning value: adopting it before
you have written raw queries means you learn Beanie, not MongoDB. Once queries
feel routine, migrating is a reasonable weekend.

**Steps.** Create `app/repositories/note_repo.py`:

```python
from typing import Any, Optional

from bson import ObjectId
from pymongo import DESCENDING
from pymongo.asynchronous.database import AsyncDatabase


def _serialise(doc: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The ONE place ObjectId → str happens. Handlers never do this again."""
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    if isinstance(doc.get("owner_id"), ObjectId):
        doc["owner_id"] = str(doc["owner_id"])
    return doc


async def list_notes(db: AsyncDatabase, *, skip: int = 0, limit: int = 20) -> list[dict]:
    cursor = db.notes.find({}).sort("time", DESCENDING).skip(skip).limit(limit)
    return [_serialise(d) for d in await cursor.to_list(length=limit)]


async def list_notes_by_owner(
    db: AsyncDatabase, owner_id: str, *, skip: int = 0, limit: int = 20
) -> list[dict]:
    cursor = (
        db.notes.find({"owner_id": ObjectId(owner_id)})
        .sort("time", DESCENDING)
        .skip(skip)
        .limit(limit)
    )
    return [_serialise(d) for d in await cursor.to_list(length=limit)]


async def create_note(db: AsyncDatabase, data: dict, owner_id: str, username: str) -> dict:
    data["owner_id"] = ObjectId(owner_id)
    data["username"] = username                  # denormalised for read speed — see D4
    result = await db.notes.insert_one(data)
    return _serialise(await db.notes.find_one({"_id": result.inserted_id}))


async def get_note(db: AsyncDatabase, note_id: str) -> Optional[dict]:
    if not ObjectId.is_valid(note_id):           # guard: bad id → 404, not 500
        return None
    return _serialise(await db.notes.find_one({"_id": ObjectId(note_id)}))


async def delete_note(db: AsyncDatabase, note_id: str, owner_id: str) -> bool:
    """Ownership is part of the FILTER, not a separate check.
    An attacker deleting someone else's note simply matches zero documents —
    there is no window between 'check owner' and 'delete'."""
    if not ObjectId.is_valid(note_id):
        return False
    result = await db.notes.delete_one(
        {"_id": ObjectId(note_id), "owner_id": ObjectId(owner_id)}
    )
    return result.deleted_count == 1
```

The handler is now about HTTP and nothing else:

```python
@router.get("/", response_model=List[NoteResponse], response_model_by_alias=False)
async def get_notes(db: DB, skip: int = 0, limit: int = Query(20, le=100)):
    return await note_repo.list_notes(db, skip=skip, limit=limit)
```

**Also do the cleanup while you're here:** delete `app/schemas/oauth2_schema.py`'s
`Post` class and both `orm_mode` configs (dead Postgres-era code), and collapse
the duplicate `TokenData` into `auth_schema.py`, updating `oauth2.py`'s import.

---

### D4 — Document modelling & indexes

**Situation.** This is the decision with the largest business impact and it is
currently unmade. Notes store `username` as their only link to a user. There are
no indexes beyond Mongo's automatic `_id`. `GET /notes/` returns an unsorted,
silently-truncated 100 documents.

**Why it matters, concretely.** With no index on `notes`, every "show me user
X's notes" query is a `COLLSCAN` — Mongo reads *every document in the
collection* and discards the non-matches. At 500 notes you won't notice. At
500,000 you're paying Atlas for full-collection reads on every page load, and
the fix (adding an index to a large live collection) is a maintenance window
rather than a one-liner. **Indexes are cheap now and expensive later.**

| | Approach A: username only *(today)* | Approach B: `owner_id` + denormalised `username` ✅ | Approach C: strict normalisation, `$lookup` on read |
|---|---|---|---|
| Rename a username | breaks note ownership | ownership survives; display name goes stale | always correct |
| Reads per note list | 1 | 1 | 2 (or an aggregation) |
| 🟢 Beginner | 5 | 4 | 2 |
| 🔵 Learning | 1 | 5 | 4 |
| 🟣 Ops | 1 | 4 | 4 |
| 🟠 Business | 1 | 5 | 3 |

**Verdict → B.** Store the immutable `ObjectId` as the *source of truth* for
ownership, and keep the mutable `username` alongside it as a **read cache**. This
is the standard document-database tradeoff — you accept that a username change
leaves stale copies (fixable with one background `update_many`) in exchange for
never joining on the read path. C is the relational instinct; in MongoDB it costs
you a `$lookup` on your hottest query to solve a problem you rarely have.

**Steps.**

1. **Create indexes at startup** — already wired into `_ensure_indexes()` in
   [D2](#d2--database-connection--injection). `create_index` is idempotent, so
   calling it on every boot is safe and self-documenting.

2. **Add `owner_id` to new notes** — done by `note_repo.create_note` in
   [D3](#d3--data-access-layer).

3. **Backfill existing notes.** Run once, from `backend/` with the venv active:

   ```python
   # scripts/backfill_owner_id.py
   import asyncio
   from pymongo import AsyncMongoClient
   from app.core.config import settings

   async def main():
       client = AsyncMongoClient(settings.mongodb_url)
       db = client[settings.db_name]
       users = {u["username"]: u["_id"] async for u in db.users.find({}, {"username": 1})}

       patched = orphaned = 0
       async for note in db.notes.find({"owner_id": {"$exists": False}}):
           owner = users.get(note.get("username"))
           if owner is None:
               orphaned += 1
               continue
           await db.notes.update_one({"_id": note["_id"]}, {"$set": {"owner_id": owner}})
           patched += 1

       print(f"patched={patched} orphaned={orphaned}")
       await client.close()

   asyncio.run(main())
   ```

   ```powershell
   python -m scripts.backfill_owner_id
   ```

   > Orphans are notes whose `username` no longer matches any user. Decide
   > deliberately: delete them, or assign a tombstone user. Don't leave them —
   > they'll surface later as `KeyError` in a handler.

4. **Update the schema** so the API exposes it:

   ```python
   class NoteResponse(BaseModel):
       id: Optional[str] = Field(alias="_id", default=None)
       owner_id: Optional[str] = None
       username: str
       content: str
       time: datetime
       model_config = {"populate_by_name": True}
   ```

5. **Paginate properly.** Replace the hardcoded `length=100`:

   ```python
   from fastapi import Query

   @router.get("/", response_model=List[NoteResponse], response_model_by_alias=False)
   async def get_notes(db: DB, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
       return await note_repo.list_notes(db, skip=skip, limit=limit)
   ```

   > `skip`/`limit` is the beginner-correct choice and fine to thousands of
   > documents. Be aware Mongo must walk and discard `skip` documents, so deep
   > pages get slower — at scale you switch to keyset pagination
   > (`{"time": {"$lt": last_seen_time}}`). Not now; just know the name.

6. **Verify the index is actually used** — the skill worth having:

   ```powershell
   # in mongosh, connected to your cluster
   db.notes.find({ owner_id: ObjectId("...") }).sort({ time: -1 }).explain("executionStats")
   ```

   Look at `winningPlan.stage`. **`IXSCAN`** = using the index. **`COLLSCAN`** =
   full scan, index missing or unusable for this query shape.

📖 https://www.mongodb.com/docs/manual/core/data-model-design/ · https://www.mongodb.com/docs/manual/indexes/

---

### D5 — Authentication

**Situation.** Hand-rolled and *structurally sound* — bcrypt hashes, HS256 JWT,
`Depends`-based extraction. The problems are in the details: hardcoded secret
(→ D1), `datetime.utcnow()` deprecation, a broken Swagger Authorize button,
30-minute tokens with no refresh, and passlib — a library whose last release was
2020 and which is the direct cause of your pinned-back `bcrypt==3.2.2`.

| | Approach A: keep + fix *(recommended)* ✅ | Approach B: `fastapi-users` | Approach C: managed (Auth0 / Clerk / Supabase) |
|---|---|---|---|
| Time to production-ready | ~3 hours | ~1 day (incl. fighting conventions) | ~2 hours |
| Cost at 10k users | $0 | $0 | $0–$250/mo |
| You understand the failure modes | fully | partly | barely |
| Social login, MFA, reset emails | build each | mostly included | included |
| 🟢 Beginner | 3 | 3 | 4 |
| 🔵 Learning | 5 | 2 | 1 |
| 🟣 Ops | 4 | 4 | 5 |
| 🟠 Business | 4 | 4 | 4 |

**Verdict → A.** You have already built 80% of it and it's *correct*. Finishing
it teaches you what a JWT actually is — which you need regardless of what you
adopt later. Revisit C the moment a real requirement appears that you'd otherwise
build yourself: "log in with Google", MFA, SOC 2. Buying auth is a fine decision;
buying it *before* you understand it means you can't debug it.

**Steps.**

**5.1 — Replace passlib with `bcrypt` directly.** This unpins your bcrypt version
and removes an unmaintained dependency. The 72-byte truncation stays — it is
still required, and it must remain symmetric.

```powershell
pip uninstall -y passlib
pip install --upgrade bcrypt
```

```python
# app/utils/hashing.py
import bcrypt

BCRYPT_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    """bcrypt silently ignores bytes past 72. Truncating explicitly — and
    IDENTICALLY in hash and verify — is what keeps old hashes verifying.
    Slicing bytes can split a multi-byte UTF-8 char, hence errors='ignore'
    on the round-trip; this matches the previous passlib-based behaviour."""
    raw = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return raw.decode("utf-8", errors="ignore").encode("utf-8")


def hash(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(_prepare(plain_password), hashed_password.encode("utf-8"))
```

> ⚠ **Verify against an existing account before deploying this.** Log in as a
> user created under the passlib version. Both libraries produce standard
> `$2b$` hashes so they interoperate, but confirm it rather than trusting me:
> a silent regression here locks out every existing user.

**5.2 — Fix the deprecated timestamp and read config from settings:**

```python
# app/core/oauth2.py
from datetime import datetime, timedelta, timezone

from .config import settings


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
```

**5.3 — Make Swagger's Authorize button work.** Today `/login` accepts JSON while
`OAuth2PasswordBearer(tokenUrl='login')` advertises a form endpoint, so the
button can't drive it. Accept the OAuth2 form shape:

```python
# app/routers/auth.py
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated

@router.post("")
async def login(db: DB, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    # OAuth2 calls the identity field "username"; you're putting an email in it
    user = await db.users.find_one({"email": form_data.username})
    if not user or not hashing.verify(form_data.password, user["password"]):
        # ONE message for both cases — never reveal whether the email exists
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    token = oauth2.create_access_token(data={"user_id": str(user["_id"])})
    return {"access_token": token, "token_type": "bearer"}
```

Requires `python-multipart` (already in `requirements.txt`). Two behaviour changes
worth noting: **403 → 401** (401 is the correct code for failed authentication;
403 means *authenticated but not permitted*), and the response no longer leaks
`user_id` — the client can read it from the token or `GET /users/me`.

> If your frontend needs JSON login, keep both: a `/login` form endpoint for
> Swagger and a `/login/json` that reuses the same body. Don't silently break
> the OAuth2 contract again.

**5.4 — Add a `get_current_active_user` that actually loads the user.** Today
every handler needing a username re-queries `db.users` by hand:

```python
# app/core/oauth2.py
async def get_current_user(db: DB, token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token_data = verify_access_token(token, credentials_exception)
    user = await db.users.find_one({"_id": ObjectId(token_data.id)})
    if user is None:
        raise credentials_exception          # token valid, user deleted since
    user["_id"] = str(user["_id"])
    return user


CurrentUser = Annotated[dict, Depends(get_current_user)]
```

`create_note` loses its manual user lookup:

```python
async def create_note(note: NoteCreate, db: DB, user: CurrentUser):
    return await note_repo.create_note(
        db, note.model_dump(), owner_id=user["_id"], username=user["username"]
    )
```

**5.5 — Later, not now:** refresh tokens (so access tokens can drop to 15
minutes without logging users out), and moving the token to an `httpOnly` cookie
(JWTs in `localStorage` are readable by any XSS on your page). Both are real
improvements; neither blocks shipping.

📖 https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/ · https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

---

### D6 — Testing

**Situation.** `app/tests/` contains two files, **neither of which runs**.
`test_auth.py` is bare imports. `test_notes.py` references an undefined `client`
(`NameError`). There is no `conftest.py`, and `httpx` — required by
`TestClient` — isn't installed. Effectively: zero coverage.

| | Approach A: none *(today)* | Approach B: `httpx.AsyncClient` + test DB ✅ | Approach C: full mocks (`mongomock`) |
|---|---|---|---|
| Catches real Mongo behaviour | — | ✓ | ✗ (mock drifts from reality) |
| Speed | — | fast (~1s local) | fastest |
| Setup cost | — | one `conftest.py` | fighting mock gaps |
| 🟢 Beginner | 5 | 4 | 2 |
| 🔵 Learning | 1 | 5 | 2 |
| 🟣 Ops | 1 | 5 | 3 |
| 🟠 Business | 2 | 5 | 2 |

**Verdict → B.** Run tests against a **real MongoDB, separate database name**.
Mocking a database teaches you your mock, not MongoDB — and every non-trivial
bug you'll hit (index behaviour, `ObjectId` coercion, upsert semantics) is
exactly what a mock papers over. A second database on your existing free Atlas
cluster costs nothing.

This decision **depends on [D2](#d2--database-connection--injection)** — without
`Depends(get_db)` there is no clean seam to point at a test database.

**Steps.**

```powershell
pip install pytest pytest-asyncio httpx
```

First, add the missing `__init__.py` files (issue #13) so test discovery is
unambiguous:

```powershell
cd C:\Users\angel\Desktop\philosostream\backend
"core","routers","schemas","utils","tests","repositories" | ForEach-Object {
    $p = "app\$_\__init__.py"
    if (-not (Test-Path $p)) { New-Item -ItemType File $p }
}
```

`backend/pytest.ini`:

```ini
[pytest]
testpaths = app/tests
asyncio_mode = auto
addopts = -v --strict-markers
```

> `asyncio_mode = auto` means you don't need `@pytest.mark.asyncio` on every
> test. Without it, async tests are silently *skipped* — they report as passing
> while running nothing. This is the single most common pytest-asyncio trap.

`backend/app/tests/conftest.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from pymongo import AsyncMongoClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app

TEST_DB_NAME = "philosostream_test"


@pytest.fixture
async def db():
    """A real Mongo database, wiped between tests. Never points at prod."""
    assert TEST_DB_NAME != settings.db_name, "refusing to run tests against the real DB"
    client = AsyncMongoClient(settings.mongodb_url)
    database = client[TEST_DB_NAME]

    await database.users.create_index("email", unique=True)
    await database.notes.create_index([("owner_id", 1), ("time", -1)])

    yield database

    await client.drop_database(TEST_DB_NAME)
    await client.close()


@pytest.fixture
async def client(db):
    """An HTTP client wired to the app, with get_db swapped for the test DB.

    dependency_overrides is the payoff from D2 — one line redirects every
    handler's database without touching a single handler."""
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def auth_client(client):
    """A client already carrying a valid Bearer token."""
    await client.post("/users", json={
        "username": "tester", "email": "tester@example.com", "password": "password123",
    })
    res = await client.post("/login", data={
        "username": "tester@example.com", "password": "password123",
    })
    client.headers["Authorization"] = f"Bearer {res.json()['access_token']}"
    return client
```

`backend/app/tests/test_notes.py` — replacing the broken stub:

```python
async def test_health(client):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_create_note_requires_auth(client):
    res = await client.post("/notes/", json={"content": "unauthenticated"})
    assert res.status_code == 401


async def test_create_and_list_note(auth_client):
    created = await auth_client.post("/notes/", json={"content": "hello world"})
    assert created.status_code == 201

    body = created.json()
    assert body["content"] == "hello world"
    assert body["username"] == "tester"
    assert "owner_id" in body

    listed = await auth_client.get("/notes/")
    assert listed.status_code == 200
    assert any(n["content"] == "hello world" for n in listed.json())


async def test_user_response_never_leaks_password(client):
    res = await client.post("/users", json={
        "username": "leaky", "email": "leaky@example.com", "password": "password123",
    })
    assert res.status_code == 201
    assert "password" not in res.json()      # regression guard for issue #2


async def test_login_with_wrong_password_is_401(auth_client):
    res = await auth_client.post("/login", data={
        "username": "tester@example.com", "password": "wrong-password",
    })
    assert res.status_code == 401
```

Run:

```powershell
python -m pytest                                   # everything
python -m pytest app/tests/test_notes.py -v        # one file
python -m pytest -k "password"                     # by name substring
python -m pytest -x --lf                           # stop at first failure, rerun last failures
```

> **Sanity-check that the tests are real.** Break something on purpose — change
> an assertion to `== 999` — and confirm it fails. A suite that passes when the
> code is wrong is worse than no suite, because it manufactures confidence.

📖 https://fastapi.tiangolo.com/advanced/async-tests/ · https://fastapi.tiangolo.com/advanced/testing-dependencies/

---

### D7 — Dependency management

**Situation.** `requirements.txt` is a `pip freeze` snapshot that has drifted
badly from the venv (see [§2.3](#23-verified-drift-between-requirementstxt-and-venv)) —
missing `pymongo`, missing `httpx`, wrong `bcrypt`, carrying two dead Postgres
packages. It cannot currently reproduce a working environment.

| | Approach A: `pip freeze` *(today)* | Approach B: split direct/locked | Approach C: `uv` ✅ |
|---|---|---|---|
| Distinguishes "I asked for it" from "it came along" | ✗ | ✓ | ✓ |
| Install speed (cold) | ~45s | ~45s | ~3s |
| Manages Python versions too | ✗ | ✗ | ✓ |
| One extra tool to learn | — | — | yes |
| 🟢 Beginner | 4 | 3 | 4 |
| 🔵 Learning | 2 | 4 | 4 |
| 🟣 Ops | 1 | 4 | 5 |
| 🟠 Business | 2 | 3 | 5 |

**Verdict → C, with B as the no-new-tools fallback.** `uv` replaces pip, venv,
and pyproject wrangling with one fast tool, and — the part that matters here —
`uv.lock` records exact resolved versions for *everything* while `pyproject.toml`
records only what you actually asked for. That distinction is precisely what your
current file lacks. It's also a genuinely small tool to learn; the commands map
1:1 onto pip's.

If you'd rather not add a tool right now, B is honest and sufficient: keep a
hand-written `requirements.in` (direct deps, loosely pinned) and generate
`requirements.txt` from it with `pip-compile`.

**Steps (Approach C).**

```powershell
# install uv (one-time, machine-wide)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

cd C:\Users\angel\Desktop\philosostream\backend
uv init --no-workspace          # creates pyproject.toml without touching your code
uv add fastapi uvicorn[standard] pymongo pydantic pydantic-settings python-jose[cryptography] bcrypt python-multipart email-validator
uv add --dev pytest pytest-asyncio httpx ruff

uv sync                         # creates .venv and uv.lock from pyproject.toml
uv run uvicorn app.main:app --reload
uv run pytest
```

Commit both `pyproject.toml` and `uv.lock`. Then delete `requirements.txt` — two
sources of truth is worse than either one alone.

> Note that `SQLAlchemy` and `psycopg2-binary` simply don't appear in the `uv add`
> list. That's the point: you declare what you use, and the dead Postgres
> dependencies disappear without a separate cleanup step.

📖 https://docs.astral.sh/uv/ · https://docs.astral.sh/uv/guides/projects/

---

### D8 — Errors, logging & observability

**Situation.** `print()` in two handlers. No log configuration, no request IDs,
no error tracking. Error responses are inconsistent: `/notes/` returns 503 for a
missing DB while `create_note` returns 500 for the identical condition, and
`/login` returns 403 where 401 is correct.

| | Approach A: `print` *(today)* | Approach B: stdlib `logging` + exception handlers ✅ | Approach C: B + Sentry + structured JSON |
|---|---|---|---|
| Find why a specific request failed | ✗ | partly | ✓ |
| Alerted before a user complains | ✗ | ✗ | ✓ |
| Cost | $0 | $0 | $0 (free tier) |
| 🟢 Beginner | 5 | 4 | 3 |
| 🔵 Learning | 1 | 4 | 4 |
| 🟣 Ops | 1 | 3 | 5 |
| 🟠 Business | 1 | 3 | 5 |

**Verdict → B now, C at deploy time.** Logging is cheap and immediately useful.
Add Sentry the same day you deploy — not before (there's nothing to observe on
localhost), not after (you'll find out about errors from users).

**Steps.**

```python
# app/core/logging_config.py
import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        stream=sys.stdout,          # stdout, not a file — hosts capture stdout
    )
    logging.getLogger("pymongo").setLevel(logging.WARNING)   # very chatty at INFO
```

Call `configure_logging()` at the top of `lifespan`, then replace every `print`:

```python
import logging
logger = logging.getLogger(__name__)

logger.info("note created", extra={"note_id": created["_id"], "owner_id": user["_id"]})
```

> **Never log the request body on user or auth routes.** `print(user.password)`
> in `app/routers/users.py:31` currently writes plaintext passwords to stdout —
> delete that line specifically, don't just convert it to `logger.info`.

Add a catch-all handler so unexpected exceptions produce a logged 500 instead of
a raw traceback in the response:

```python
# app/main.py
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

**Standardise your status codes** while you're here:

| Situation | Use | Not |
|---|---|---|
| Bad credentials on login | `401` | `403` |
| Valid token, someone else's note | `403` | `404` |
| Note doesn't exist | `404` | `500` |
| Malformed body | `422` (automatic) | — |
| Duplicate email | `409` | `500` |
| Database unreachable | `503` | `500` |

📖 https://fastapi.tiangolo.com/tutorial/handling-errors/ · https://docs.sentry.io/platforms/python/integrations/fastapi/

---

### D9 — Frontend

**Situation.** `frontend/` is an empty directory. Fully greenfield — the one
decision here with no legacy.

| | Approach A: Vite + React + TS ✅ | Approach B: Next.js (App Router) | Approach C: server-rendered Jinja2 |
|---|---|---|---|
| Keeps your FastAPI backend meaningful | ✓ | partly (pulls logic into Next) | ✓ |
| Deploy complexity | 2 services | 2 services (or 1 + API routes) | 1 service |
| SEO / social previews | needs work | excellent | good |
| 🟢 Beginner | 4 | 3 | 5 |
| 🔵 Learning | 5 | 4 | 2 |
| 🟣 Ops | 4 | 4 | 5 |
| 🟠 Business | 4 | 5 | 3 |

**Verdict → A.** Vite + React keeps a clean boundary: your FastAPI app stays the
whole backend, and the frontend is a pure consumer of it. That boundary is what
makes the API you've been building *worth* building. Next.js is the stronger
business choice for a content site that needs SEO — but its gravity pulls data
fetching into server components, which would slowly hollow out the API you're
learning to write. Pick B deliberately if SEO is a launch requirement; otherwise A.

**Steps.**

```powershell
cd C:\Users\angel\Desktop\philosostream
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install @tanstack/react-query
npm run dev            # http://localhost:5173
```

Then enable CORS on the backend — without this every browser request fails with
an opaque CORS error while `curl` works fine, which is a classic multi-hour
beginner trap:

```python
# app/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],   # exact origins; NOT ["*"] with credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

> Move that list into `Settings` as `cors_origins: list[str]` before you deploy —
> your production frontend will be on a different origin.

📖 https://vite.dev/guide/ · https://tanstack.com/query/latest · https://fastapi.tiangolo.com/tutorial/cors/

---

### D10 — Deployment

**Situation.** Runs on your laptop only. `uvicorn --reload`, no container, no
process manager, no hosted environment.

| | Approach A: PaaS from repo (Render / Railway / Fly) ✅ | Approach B: Docker → VPS | Approach C: AWS ECS / Kubernetes |
|---|---|---|---|
| Time to first deploy | ~30 min | ~4 hrs | ~2 days |
| Monthly cost (hobby) | $0–7 | $5–10 | $30+ |
| You manage the OS, TLS, restarts | no | yes | partly |
| 🟢 Beginner | 5 | 3 | 1 |
| 🔵 Learning | 3 | 5 | 4 |
| 🟣 Ops | 4 | 3 | 5 |
| 🟠 Business | 5 | 3 | 2 |

**Verdict → A, but write the `Dockerfile` anyway.** A PaaS gets you a real HTTPS
URL today, which is worth more than any amount of infrastructure sophistication.
Writing the Dockerfile regardless (a) makes the deploy reproducible, (b) means
you're never locked to one host, and (c) is the learning-value part of the
exercise. MongoDB stays on Atlas — self-hosting a database is a job, not a task.

**Steps.**

`backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim

# Don't buffer stdout — otherwise your logs arrive late or not at all
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy deps first so Docker caches the install layer across code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

# No --reload in production. Start with 2 workers and measure before raising.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

`backend/.dockerignore` — without this you ship your `.env` and `.venv` into the
image:

```
.venv/
__pycache__/
*.pyc
.env
.env.*
.pytest_cache/
.git/
documentations/
```

Test locally before trusting a host with it:

```powershell
docker build -t philosostream-api ./backend
docker run --rm -p 8000:8000 --env-file ./backend/.env philosostream-api
curl http://localhost:8000/health
```

**Then, on the host (Render used as the example):**

1. Push to GitHub → New **Web Service** → connect the repo.
2. Root directory `backend`, environment **Docker**.
3. Add env vars from `.env.example` — `MONGODB_URL`, `SECRET_KEY`, `DB_NAME`.
   **Generate a fresh `SECRET_KEY` for production**; never reuse the dev one.
4. Health check path: `/health`.
5. In **Atlas → Network Access**, allowlist the host's outbound IPs. This is the
   #1 cause of "works locally, times out in production".

📖 https://fastapi.tiangolo.com/deployment/docker/ · https://render.com/docs/deploy-fastapi · https://fly.io/docs/languages-and-frameworks/python/

---

### D11 — CI/CD

**Situation.** None. Nothing runs your tests but you, manually.

| | Approach A: none *(today)* | Approach B: GitHub Actions ✅ | Approach C: B + auto-deploy on green |
|---|---|---|---|
| Catches a broken push | ✗ | ✓ | ✓ |
| Setup time | — | 20 min | +20 min |
| 🟢 Beginner | 5 | 4 | 3 |
| 🔵 Learning | 1 | 4 | 4 |
| 🟣 Ops | 1 | 4 | 5 |
| 🟠 Business | 2 | 4 | 5 |

**Verdict → B immediately after [D6](#d6--testing), C once the suite is trusted.**
CI is worthless without tests and close to magical with them. Note C's ordering:
auto-deploy is only safe when a red build genuinely means "broken".

**Steps.** `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      mongo:
        image: mongo:7
        ports: ["27017:27017"]

    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install dependencies
        working-directory: backend
        run: uv sync --all-extras --dev

      - name: Lint
        working-directory: backend
        run: uv run ruff check .

      - name: Test
        working-directory: backend
        env:
          MONGODB_URL: mongodb://localhost:27017
          SECRET_KEY: test-secret-not-used-anywhere-real
          DB_NAME: philosostream_ci
        run: uv run pytest
```

> The `services: mongo` block gives CI a **throwaway MongoDB container** — so
> your test suite never touches Atlas, needs no production credentials, and can't
> be broken by someone else's data.

Add `ruff` for linting (fast, zero-config to start, replaces flake8 + isort +
black):

```powershell
uv add --dev ruff
uv run ruff check . --fix        # fix what's safe
uv run ruff format .             # format
```

📖 https://docs.github.com/en/actions · https://docs.astral.sh/ruff/

---

## 6. The recommended path (sequenced)

Ordered by dependency, not by importance. Each phase ends with a working app —
stop anywhere.

### Phase 0 — Safety (30 min) 🔴 do today
- [ ] `.gitignore` → `git init` → verify `.env` untracked — [§4.1](#01--initialise-git-with-a-gitignore-before-the-first-commit)
- [ ] `.env.example` committed — [§4.2](#02--add-envexample)
- [ ] Rotate `SECRET_KEY` into `.env` — [§4.3](#03--rotate-the-hardcoded-jwt-secret)
- [ ] Remove `password` from `UserOut`; make `name` optional — [§4.4](#04--stop-returning-the-password-hash)
- [ ] `requirements.txt` matches the venv — [§4.5](#05--make-requirementstxt-describe-reality)

### Phase 1 — Foundations (half a day)
- [ ] `app/core/config.py` with `Settings` — [D1](#d1--configuration--secrets)
- [ ] `lifespan` + `get_db` dependency; delete every lazy import and `None` guard — [D2](#d2--database-connection--injection)
- [ ] `/health` and `/ready` split — [D2](#d2--database-connection--injection)
- [ ] Delete dead code: `oauth2_schema.Post`, both `orm_mode`, duplicate `TokenData` — [D3](#d3--data-access-layer)

*Checkpoint: `uvicorn app.main:app --reload`, hit `/docs`, exercise all four endpoints.*

### Phase 2 — Data integrity (half a day)
- [ ] Unique indexes on `users.email` / `users.username`; compound index on notes — [D4](#d4--document-modelling--indexes)
- [ ] Add `owner_id` to new notes — [D3](#d3--data-access-layer)
- [ ] Backfill script for existing notes — [D4](#d4--document-modelling--indexes)
- [ ] `skip`/`limit` pagination with `Query` bounds — [D4](#d4--document-modelling--indexes)
- [ ] `app/repositories/note_repo.py`; handlers get thin — [D3](#d3--data-access-layer)

*Checkpoint: `explain("executionStats")` shows `IXSCAN`, not `COLLSCAN`.*

### Phase 3 — Auth hardening (half a day)
- [ ] passlib → `bcrypt` direct; **verify an existing account still logs in** — [D5](#d5--authentication)
- [ ] `datetime.now(timezone.utc)`; config from `settings` — [D5](#d5--authentication)
- [ ] `OAuth2PasswordRequestForm` so Swagger Authorize works — [D5](#d5--authentication)
- [ ] `get_current_user` loads the user; add `GET /users/me` — [D5](#d5--authentication)
- [ ] 401/403/404/409 used correctly — [D8](#d8--errors-logging--observability)

*Checkpoint: click **Authorize** in `/docs`, log in, call `POST /notes/` from the UI.*

### Phase 4 — Confidence (1 day)
- [ ] `__init__.py` in every subpackage — [D6](#d6--testing)
- [ ] `pytest.ini` with `asyncio_mode = auto` — [D6](#d6--testing)
- [ ] `conftest.py` with `db` / `client` / `auth_client` fixtures — [D6](#d6--testing)
- [ ] Tests for: auth required, create+list, no password leak, wrong password — [D6](#d6--testing)
- [ ] Migrate to `uv`; commit `uv.lock` — [D7](#d7--dependency-management)
- [ ] `ruff check` clean — [D11](#d11--cicd)
- [ ] GitHub Actions CI green — [D11](#d11--cicd)

*Checkpoint: break an assertion on purpose; confirm CI goes red.*

### Phase 5 — Ship (1–2 days)
- [ ] `logging_config.py`; delete every `print` (especially the password one) — [D8](#d8--errors-logging--observability)
- [ ] Global exception handler — [D8](#d8--errors-logging--observability)
- [ ] `Dockerfile` + `.dockerignore`; build and run locally — [D10](#d10--deployment)
- [ ] Deploy to Render/Fly; fresh prod `SECRET_KEY`; Atlas IP allowlist — [D10](#d10--deployment)
- [ ] Sentry — [D8](#d8--errors-logging--observability)
- [ ] Vite frontend + CORS from settings — [D9](#d9--frontend)

### Phase 6 — Later, on evidence
Revisit only when something actually hurts. Writing these down now stops them
from becoming premature work:

- Refresh tokens + `httpOnly` cookies — when 30-minute logouts annoy real users
- Rate limiting on `/login` — before public launch
- Keyset pagination — when `skip` gets slow (thousands of notes deep)
- Redis caching — when Atlas metrics show a hot repeated query
- Beanie ODM — when raw queries feel routine, not before
- Full-text search on notes — Atlas Search, when users ask for it

---

## 7. Command cheat sheet

Run from `backend/` with the venv active. **Two shells, two syntaxes** — Claude
Code gives you PowerShell *and* a Bash tool; don't mix them.

```powershell
# ── Environment ──────────────────────────────────────────
.\.venv\Scripts\Activate.ps1          # PowerShell (Readme.md's .bat is cmd.exe)
deactivate

# ── Run ──────────────────────────────────────────────────
uvicorn app.main:app --reload                      # dev, auto-restart
uvicorn app.main:app --host 0.0.0.0 --port 8000    # reachable from your phone
uvicorn app.main:app --workers 2                   # production shape (no reload)

# ── Explore the API ──────────────────────────────────────
start http://127.0.0.1:8000/docs      # Swagger — interactive, use this
start http://127.0.0.1:8000/redoc     # ReDoc — nicer to read
start http://127.0.0.1:8000/openapi.json

# ── Test ─────────────────────────────────────────────────
python -m pytest                       # all
python -m pytest -k "login"            # by name substring
python -m pytest -x --lf               # stop at first fail; rerun last failures
python -m pytest --durations=5         # what's slow

# ── Dependencies ─────────────────────────────────────────
pip list                               # what's ACTUALLY installed
pip show fastapi                       # version, location, what requires it
pip install --upgrade fastapi

# ── Quality ──────────────────────────────────────────────
ruff check . --fix
ruff format .

# ── Inspect without running the server ───────────────────
python -c "from app.main import app; print([r.path for r in app.routes])"
python -c "from app.core.config import settings; print(settings.db_name)"
python -c "import secrets; print(secrets.token_hex(32))"
```

**Talking to the API from the terminal.** In PowerShell, `curl` is an alias for
`Invoke-WebRequest`, *not* real curl — the flags differ and it will confuse you.
Use `curl.exe` explicitly, or PowerShell-native:

```powershell
# PowerShell-native
Invoke-RestMethod http://127.0.0.1:8000/notes/ | ConvertTo-Json -Depth 5

$body = @{ username="alice"; email="alice@example.com"; password="password123" } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/users -Method Post -Body $body -ContentType "application/json"

# real curl
curl.exe -X POST http://127.0.0.1:8000/login -d "username=alice@example.com&password=password123"
```

**MongoDB directly** (install `mongosh` from https://www.mongodb.com/docs/mongodb-shell/):

```powershell
mongosh "<your MONGODB_URL>"
```
```javascript
use philosostream
db.notes.countDocuments()
db.notes.find().sort({ time: -1 }).limit(5).pretty()
db.notes.getIndexes()
db.notes.find({ owner_id: ObjectId("...") }).explain("executionStats")   // IXSCAN or COLLSCAN?
db.users.find({}, { password: 0 })                                       // never print hashes
```

---

## 8. How to find help

The skill that separates a beginner from an intermediate developer isn't knowing
answers — it's knowing **which source answers which kind of question**, and in
what order to try them.

### 8.1 The escalation ladder

Work down it. Most problems die at step 2 or 3.

| # | Source | Best for | Time |
|---|---|---|---|
| 1 | **The traceback** | 60% of your errors | 30s |
| 2 | **`/docs` (Swagger)** | "is my endpoint even shaped right?" | 1 min |
| 3 | **Official docs** (§8.3) | API syntax, config, "how do I…" | 5 min |
| 4 | **Context7 MCP** (§8.4) | Same, but current, without leaving Claude Code | 1 min |
| 5 | **GitHub issues/discussions** | "is this a bug or me?" | 10 min |
| 6 | **Stack Overflow** | Common errors with known fixes | 10 min |
| 7 | **Community forums/Discord** | Design questions, "is this sane?" | hours |

### 8.2 Read the traceback properly

Python tracebacks read **bottom-up for the error, and you scan upward for the
last line that is *your* file**:

```
File ".../site-packages/pydantic/main.py", line 253, in __init__     ← library, ignore
File ".../app/routers/users.py", line 38, in create_user             ← YOUR CODE. start here.
    created_user["_id"] = str(created_user["_id"])
TypeError: 'NoneType' object is not subscriptable                    ← WHAT went wrong
```

Three questions, in order: **What** (last line) → **Where** (last frame in
`app/`) → **Why** (what could make that value `None`?). Here: `find_one` returned
`None`, so the insert didn't land where you thought.

When you search, **paste the exception type and message, not the whole trace**,
and strip your own paths and variable names:
`fastapi pydantic ResponseValidationError field required` beats
`why does my app crash`.

### 8.3 Documentation, by what you're trying to do

**FastAPI** — https://fastapi.tiangolo.com

| Question | Page |
|---|---|
| Project layout, routers | https://fastapi.tiangolo.com/tutorial/bigger-applications/ |
| `Depends`, DI | https://fastapi.tiangolo.com/tutorial/dependencies/ |
| Startup/shutdown, `lifespan` | https://fastapi.tiangolo.com/advanced/events/ |
| JWT auth end-to-end | https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/ |
| Error handling, custom handlers | https://fastapi.tiangolo.com/tutorial/handling-errors/ |
| `response_model`, aliases | https://fastapi.tiangolo.com/tutorial/response-model/ |
| Async tests | https://fastapi.tiangolo.com/advanced/async-tests/ |
| Overriding deps in tests | https://fastapi.tiangolo.com/advanced/testing-dependencies/ |
| CORS | https://fastapi.tiangolo.com/tutorial/cors/ |
| Docker deployment | https://fastapi.tiangolo.com/deployment/docker/ |
| **`async def` vs `def`** (read this one) | https://fastapi.tiangolo.com/async/ |

**Pydantic v2** — https://docs.pydantic.dev/latest/
- Migration from v1 (`orm_mode` → `from_attributes`, `Config` → `model_config`): https://docs.pydantic.dev/latest/migration/
- Settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- Field validators: https://docs.pydantic.dev/latest/concepts/validators/

**MongoDB / PyMongo**
- PyMongo async docs: https://www.mongodb.com/docs/languages/python/pymongo-driver/current/
- API reference: https://pymongo.readthedocs.io/en/stable/
- Query operators (`$gt`, `$in`, `$regex`…): https://www.mongodb.com/docs/manual/reference/operator/query/
- Indexes: https://www.mongodb.com/docs/manual/indexes/
- Schema design patterns: https://www.mongodb.com/docs/manual/data-modeling/design-patterns/
- Atlas: https://www.mongodb.com/docs/atlas/
- University (free courses): https://learn.mongodb.com/

**Tooling** — pytest https://docs.pytest.org/en/stable/ · pytest-asyncio https://pytest-asyncio.readthedocs.io/ · httpx https://www.python-httpx.org/ · uv https://docs.astral.sh/uv/ · ruff https://docs.astral.sh/ruff/ · Docker https://docs.docker.com/

**Concepts worth reading once** — Twelve-Factor App https://12factor.net/ · OWASP API Top 10 https://owasp.org/API-Security/editions/2023/en/0x11-t10/ · HTTP status codes https://developer.mozilla.org/en-US/docs/Web/HTTP/Status

### 8.4 Context7 MCP — docs without leaving Claude Code

You already have Context7 configured (`~/.claude/rules/context7.md`). It fetches
**current** library docs, which matters because your `fastapi==0.135.2` and
`pymongo==4.17.0` are newer than most tutorials and much of any model's training
data. Just ask naturally:

```
> How do I create a unique compound index with AsyncMongoClient in pymongo?
> What replaced @app.on_event in current FastAPI?
> Show me pydantic-settings reading a nested .env value
```

Use it for: API syntax, config options, version migrations, setup steps.
Don't use it for: your business logic, refactoring, or debugging *your* code —
that's a normal conversation.

### 8.5 In Claude Code specifically

```
/help                          list commands
claude --help                  CLI flags
/code-review                   review your changes for bugs before committing
/security-review               security pass on the current diff
/init                          regenerate CLAUDE.md (yours is already good)
```

`backend/CLAUDE.md` is loaded automatically every session — it's why Claude
already knows about your lazy-import pattern. **Keep it updated as you work
through this document**, especially [D2](#d2--database-connection--injection),
which invalidates the lazy-import guidance it currently gives.

### 8.6 Asking a good question

A question that gets answered contains, in order: **what you're trying to do** →
**what you did** (minimal code) → **what happened** (exact error) → **what you
already tried** → **versions** (`pip list | Select-String fastapi`). Leave any of
those out and the first reply is a request for it.

Where to ask:
- FastAPI Q&A: https://github.com/fastapi/fastapi/discussions/categories/questions
- MongoDB forums: https://www.mongodb.com/community/forums/
- Python Discord: https://discord.gg/python
- r/FastAPI: https://reddit.com/r/FastAPI

**Search issues before posting** — someone has almost certainly hit it:
```
site:github.com/fastapi/fastapi ResponseValidationError
```

---

## 9. Glossary

Terms used above that are worth being able to define out loud.

| Term | Meaning |
|---|---|
| **ASGI** | Async Server Gateway Interface — the contract between uvicorn and FastAPI. `ASGITransport` in tests speaks it directly, skipping the network entirely. |
| **Lifespan** | An async context manager wrapping the app's whole life. Before `yield` = startup, after = shutdown. |
| **Dependency injection** | Declaring what a function *needs* (`db: DB`) and letting the framework supply it — which is what makes it swappable in tests. |
| **Repository** | A module owning all queries for one collection. Handlers call it; they don't write queries. |
| **Denormalisation** | Deliberately duplicating data (`username` on each note) to avoid a join on read. Trades write complexity and staleness for read speed. |
| **`COLLSCAN` / `IXSCAN`** | Mongo read every document / used an index. `explain()` tells you which. |
| **Idempotent** | Safe to run repeatedly. `create_index` is; that's why it can live in startup. |
| **Fixture** | A pytest function providing test setup and teardown, requested by name as a parameter. |
| **Drift** | When the declared environment (`requirements.txt`) stops matching the real one. Your §2.3 table is drift. |
| **Backfill** | A one-off script bringing existing data up to a new schema. |
| **Keyset pagination** | Paging by "everything after this value" rather than `skip(n)`. Stays fast at depth. |

---

*Generated 2026-08-15 · Verified against `backend/app/` and `backend/.venv` (Python 3.12.10, FastAPI 0.135.2, pymongo 4.17.0).*
*When you complete a phase, update `backend/CLAUDE.md` so the next session starts from the new reality.*