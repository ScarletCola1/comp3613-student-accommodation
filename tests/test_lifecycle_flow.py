"""API tests for the full lifecycle: roles, ownership, edits, force-deactivate."""

from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed

client = TestClient(app)


def setup_module() -> None:
    seed(reset=True)


def _login(email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()["user"]["id"]


def _h(uid):
    return {"X-User-Id": str(uid)}


ADMIN = LANDLORD = OTHER = STUDENT = None


def _ids():
    global ADMIN, LANDLORD, OTHER, STUDENT
    ADMIN = _login("admin@example.com", "admin-dev")
    LANDLORD = _login("landlord@example.com", "land-dev")
    OTHER = _login("landlord2@example.com", "land-dev")
    STUDENT = _login("student@example.com", "stud-dev")


def _listing(**over):
    _ids()
    body = {
        "title": "Room", "area": "st_augustine", "price": 1500,
        "amenities": "wifi", "contact_phone": "555", "contact_email": "l@x.com",
    }
    body.update(over)
    r = client.post("/api/landlord/listings", headers=_h(LANDLORD), json=body)
    return r.json()["listing"]["id"]


def _act(uid, lid, action, reason=None):
    return client.post(
        f"/api/listings/{lid}/transition",
        headers=_h(uid), json={"action": action, "reason": reason},
    )


def _status(lid):
    rows = client.get("/api/admin/listings", headers=_h(ADMIN)).json()["listings"]
    return [r for r in rows if r["id"] == lid][0]["status"]


def _make_active():
    lid = _listing()
    assert _act(ADMIN, lid, "verify").status_code == 200
    assert _act(LANDLORD, lid, "activate").status_code == 200
    return lid


def _student_sees(lid):
    r = client.get("/api/student/listings", headers=_h(STUDENT))
    return lid in [x["id"] for x in r.json()["listings"]]


def test_pending_and_rejected_listings_are_hidden_from_students():
    lid = _listing()
    assert not _student_sees(lid)
    _act(ADMIN, lid, "reject", "Missing photos")
    assert _status(lid) == "rejected" and not _student_sees(lid)


def test_active_listing_is_visible_then_hidden_when_inactive():
    lid = _make_active()
    assert _student_sees(lid)
    _act(LANDLORD, lid, "deactivate", "Rented")
    assert _status(lid) == "inactive" and not _student_sees(lid)


def test_cannot_activate_pending_listing():
    lid = _listing()
    assert _act(LANDLORD, lid, "activate").status_code == 400
    assert _status(lid) == "pending"


def test_other_landlord_and_student_cannot_change_a_listing():
    lid = _make_active()
    assert _act(OTHER, lid, "deactivate").status_code == 400
    assert _act(STUDENT, lid, "deactivate").status_code == 400
    assert _status(lid) == "active"


def test_landlord_cannot_use_admin_actions():
    lid = _listing()
    for action in ("verify", "reject", "force_deactivate", "restore"):
        assert _act(LANDLORD, lid, action, "x").status_code == 400
    assert _status(lid) == "pending"


def test_rejected_listing_can_be_edited_and_resubmitted():
    lid = _listing()
    _act(ADMIN, lid, "reject", "Price missing")
    r = client.put(f"/api/landlord/listings/{lid}", headers=_h(LANDLORD), json={"price": 1800})
    assert r.status_code == 200
    assert _act(LANDLORD, lid, "resubmit").status_code == 200
    assert _status(lid) == "pending"


def test_listing_under_review_cannot_be_edited():
    lid = _listing()
    r = client.put(f"/api/landlord/listings/{lid}", headers=_h(LANDLORD), json={"title": "New"})
    assert r.status_code == 400
    _act(ADMIN, lid, "verify")  # now verified/provisional, still under review
    r = client.put(f"/api/landlord/listings/{lid}", headers=_h(LANDLORD), json={"title": "New"})
    assert r.status_code == 400


def test_minor_edit_keeps_listing_active():
    lid = _make_active()
    r = client.put(f"/api/landlord/listings/{lid}", headers=_h(LANDLORD), json={"photos": "a.jpg"})
    assert r.status_code == 200 and _status(lid) == "active" and _student_sees(lid)


def test_significant_edit_hides_listing_until_admin_verifies_again():
    lid = _make_active()
    r = client.put(f"/api/landlord/listings/{lid}", headers=_h(LANDLORD), json={"price": 2500})
    assert r.status_code == 200
    assert _status(lid) == "re_review" and not _student_sees(lid)
    assert _act(ADMIN, lid, "verify").status_code == 200
    assert _status(lid) == "active" and _student_sees(lid)


def test_admin_force_deactivate_and_restore():
    lid = _make_active()
    assert _act(ADMIN, lid, "force_deactivate").status_code == 400  # reason required
    assert _act(ADMIN, lid, "force_deactivate", "Complaint").status_code == 200
    assert _status(lid) == "force_deactivated" and not _student_sees(lid)
    assert _act(LANDLORD, lid, "activate").status_code == 400  # landlord cannot resume
    assert _act(ADMIN, lid, "restore").status_code == 200
    assert _status(lid) == "active" and _student_sees(lid)


def test_landlord_can_withdraw_pending_back_to_draft_and_submit_again():
    lid = _listing()
    assert _act(LANDLORD, lid, "withdraw").status_code == 200
    assert _status(lid) == "draft" and not _student_sees(lid)
    assert _act(LANDLORD, lid, "submit").status_code == 200
    assert _status(lid) == "pending"


def test_edits_are_written_to_history():
    lid = _make_active()
    client.put(f"/api/landlord/listings/{lid}", headers=_h(LANDLORD), json={"price": 3000})
    rows = client.get(f"/api/listings/{lid}/history", headers=_h(ADMIN)).json()["history"]
    assert rows[-1]["action"] == "edit"
    assert (rows[-1]["old_state"], rows[-1]["new_state"]) == ("active", "re_review")


def test_save_as_draft_then_submit_then_hidden_until_active():
    _ids()
    body = {
        "title": "Draft room", "area": "st_augustine", "price": 1800,
        "amenities": "wifi", "contact_phone": "555", "contact_email": "l@x.com",
        "save_as_draft": True,
    }
    r = client.post("/api/landlord/listings", json=body, headers=_h(LANDLORD))
    assert r.status_code == 200
    listing = r.json()["listing"]
    assert listing["status"] == "draft"
    assert listing["flag_pending"] == 0
    lid = listing["id"]
    # draft is hidden from students and cannot be verified by an admin yet
    r = client.post(f"/api/listings/{lid}/transition", json={"action": "verify"}, headers=_h(ADMIN))
    assert r.status_code == 400
    # landlord submits the draft, then it follows the normal lifecycle
    r = client.post(f"/api/listings/{lid}/transition", json={"action": "submit"}, headers=_h(LANDLORD))
    assert r.status_code == 200
    assert r.json()["listing"]["status"] == "pending"


def test_default_create_is_still_pending():
    _ids()
    body = {
        "title": "Normal room", "area": "st_augustine", "price": 1800,
        "amenities": "wifi", "contact_phone": "555", "contact_email": "l@x.com",
    }
    r = client.post("/api/landlord/listings", json=body, headers=_h(LANDLORD))
    assert r.json()["listing"]["status"] == "pending"


def test_landlord_inbox_shows_only_own_listing_messages():
    lid = _make_active()
    other_lid = _listing()
    assert _act(ADMIN, other_lid, "verify").status_code == 200
    # message on LANDLORD's active listing
    r = client.post("/api/student/messages", headers=_h(STUDENT),
                    json={"listing_id": lid, "body": "Is it still free?"})
    assert r.status_code == 200
    mine = client.get("/api/landlord/messages", headers=_h(LANDLORD)).json()["messages"]
    assert any(m["listing_id"] == lid and m["body"] == "Is it still free?" for m in mine)
    # the other landlord must not see it
    theirs = client.get("/api/landlord/messages", headers=_h(OTHER)).json()["messages"]
    assert all(m["listing_id"] != lid for m in theirs)


def test_inbox_is_landlords_only():
    _ids()
    assert client.get("/api/landlord/messages", headers=_h(STUDENT)).status_code == 403
    assert client.get("/api/landlord/messages", headers=_h(ADMIN)).status_code == 403
