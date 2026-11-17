"""Tests for the change history log (FR-17) and the reject reason (FR-8)."""

from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed

client = TestClient(app)


def setup_module() -> None:
    seed(reset=True)


def _login(email: str, password: str) -> int:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()["user"]["id"]


def _h(uid: int) -> dict:
    return {"X-User-Id": str(uid)}


def _new_listing(landlord_id: int) -> int:
    r = client.post(
        "/api/landlord/listings",
        headers=_h(landlord_id),
        json={
            "title": "Test room",
            "area": "st_augustine",
            "price": 1500,
            "amenities": "wifi",
            "contact_phone": "555-0100",
            "contact_email": "l@example.com",
        },
    )
    assert r.status_code == 200
    return r.json()["listing"]["id"]


def _act(uid: int, lid: int, action: str, reason: str | None = None):
    return client.post(
        f"/api/listings/{lid}/transition",
        headers=_h(uid),
        json={"action": action, "reason": reason},
    )


def test_reject_without_reason_is_refused_and_state_unchanged():
    admin = _login("admin@example.com", "admin-dev")
    landlord = _login("landlord@example.com", "land-dev")
    lid = _new_listing(landlord)

    r = _act(admin, lid, "reject")
    assert r.status_code == 400
    assert "reason" in r.json()["detail"]

    listing = client.get("/api/admin/listings", headers=_h(admin)).json()["listings"]
    assert [x for x in listing if x["id"] == lid][0]["status"] == "pending"


def test_each_successful_change_writes_one_history_row():
    admin = _login("admin@example.com", "admin-dev")
    landlord = _login("landlord@example.com", "land-dev")
    lid = _new_listing(landlord)

    assert _act(admin, lid, "verify").status_code == 200
    assert _act(landlord, lid, "activate").status_code == 200

    rows = client.get(f"/api/listings/{lid}/history", headers=_h(admin)).json()["history"]
    assert [(r["old_state"], r["new_state"]) for r in rows] == [
        ("pending", "verified"),
        ("verified", "active"),
    ]
    assert rows[0]["actor_id"] == admin and rows[0]["actor_role"] == "admin"
    assert rows[1]["actor_id"] == landlord and rows[1]["created_at"]


def test_refused_change_writes_no_history_row():
    admin = _login("admin@example.com", "admin-dev")
    landlord = _login("landlord@example.com", "land-dev")
    lid = _new_listing(landlord)

    # activate straight from pending is an illegal move
    assert _act(landlord, lid, "activate").status_code == 400
    rows = client.get(f"/api/listings/{lid}/history", headers=_h(admin)).json()["history"]
    assert rows == []


def test_rejection_reason_is_stored_and_visible_to_owning_landlord():
    admin = _login("admin@example.com", "admin-dev")
    landlord = _login("landlord@example.com", "land-dev")
    lid = _new_listing(landlord)

    assert _act(admin, lid, "reject", "Photos missing").status_code == 200
    rows = client.get(f"/api/listings/{lid}/history", headers=_h(landlord)).json()["history"]
    assert rows[-1]["new_state"] == "rejected"
    assert rows[-1]["reason"] == "Photos missing"


def test_history_is_limited_to_admin_and_owning_landlord():
    landlord = _login("landlord@example.com", "land-dev")
    other = _login("landlord2@example.com", "land-dev")
    student = _login("student@example.com", "stud-dev")
    lid = _new_listing(landlord)

    assert client.get(f"/api/listings/{lid}/history", headers=_h(other)).status_code == 403
    assert client.get(f"/api/listings/{lid}/history", headers=_h(student)).status_code == 403
    assert client.get(f"/api/listings/{lid}/history", headers=_h(landlord)).status_code == 200
