# COMP 3613 Student Accommodation (Phase 2 starter)

Flawed baseline **0.2.0** built on [uwidcit/faststart](https://github.com/uwidcit/faststart) (`96ccfce`).

FastStart provides the SSR shell, JWT cookie auth, SQLModel, `manage.py`, and Render/Docker wiring. The student-accommodation scenario adds domain models/services and a JSON API under `/api` (see `/docs`).

## Quick start

```text
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Windows: Copy-Item .env.example .env
python manage.py init
python manage.py run
```

Open http://127.0.0.1:5000 — SSR auth shell; scenario JSON under `/api` and OpenAPI at `/docs`.

## Seeded API accounts

| Email | Password | Role |
| --- | --- | --- |
| `admin@example.com` | `admin-dev` | admin |
| `student@example.com` | `stud-dev` | student (registered ID) |
| `incoming@example.com` | `stud-dev` | student (provisional incoming) |
| `landlord@example.com` | `land-dev` | landlord |
| `landlord2@example.com` | `land-dev` | landlord |

JSON login: `POST /api/auth/login` with `{"email","password"}`. Other scenario endpoints identify the caller with the `X-User-Id` header (demo auth).

## Demo: the listing lifecycle (State pattern)

Start the app with `python manage.py init` then `python manage.py run`, and open
`http://127.0.0.1:8000/docs`. Every endpoint below takes the caller's id in the `X-User-Id`
header. After `init`, the seeded ids are: admin = 1, student = 2, landlord = 4, other landlord = 5.

| Step | Who (X-User-Id) | Call | Result |
|---|---|---|---|
| 1 | landlord (4) | `POST /api/landlord/listings` with `"save_as_draft": true` | status `draft` |
| 2 | landlord (4) | `POST /api/listings/{id}/transition` `{"action": "submit"}` | `pending` |
| 3 | admin (1) | `POST /api/listings/{id}/transition` `{"action": "verify"}` | `verified` |
| 4 | student (2) | `GET /api/student/listings` | listing is **not** shown (only Active is visible) |
| 5 | landlord (4) | `POST /api/listings/{id}/transition` `{"action": "activate"}` | `active` |
| 6 | student (2) | `GET /api/student/listings` | listing **is** shown |
| 7 | landlord (4) | `PUT /api/landlord/listings/{id}` with a new `price` | `re_review`, hidden again |
| 8 | admin (1) | `POST /api/listings/{id}/transition` `{"action": "verify"}` | back to `active` |
| 9 | admin (1) | `POST /api/listings/{id}/transition` `{"action": "force_deactivate", "reason": "..."}` | `force_deactivated` |
| 10 | landlord (4) | `GET /api/listings/{id}/history` | one row per change above |

Refused moves return HTTP 400 and change nothing, for example a landlord calling `verify`,
or activating a `pending` listing. The state classes are in `app/services/lifecycle.py`.

## Student brief

See [`ASSIGNMENT.md`](ASSIGNMENT.md) and [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md).

## Tests

```bash
python -m pytest tests -q
```
