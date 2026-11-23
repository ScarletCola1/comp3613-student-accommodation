"""Notifications for lifecycle changes (FR-19, FR-20)."""
from tests.test_lifecycle_flow import (
    client, _h, _ids, _listing, _act, _make_active,
)
import tests.test_lifecycle_flow as flow


def _notes(uid):
    return client.get("/api/notifications", headers=_h(uid)).json()["notifications"]


def test_admin_is_told_when_a_listing_is_submitted():
    lid = _listing()
    msgs = [n["message"] for n in _notes(flow.ADMIN) if n["listing_id"] == lid]
    assert any("waiting for verification" in m for m in msgs)


def test_landlord_is_told_when_admin_verifies_and_rejects():
    lid = _listing()
    _act(flow.ADMIN, lid, "verify")
    msgs = [n["message"] for n in _notes(flow.LANDLORD) if n["listing_id"] == lid]
    assert any("now verified" in m for m in msgs)
    lid2 = _listing()
    _act(flow.ADMIN, lid2, "reject", "photos missing")
    msgs2 = [n["message"] for n in _notes(flow.LANDLORD) if n["listing_id"] == lid2]
    assert any("rejected" in m and "photos missing" in m for m in msgs2)


def test_landlord_is_told_on_force_deactivate():
    lid = _make_active()
    _act(flow.ADMIN, lid, "force_deactivate", "complaint")
    msgs = [n["message"] for n in _notes(flow.LANDLORD) if n["listing_id"] == lid]
    assert any("force_deactivated" in m and "complaint" in m for m in msgs)


def test_significant_edit_tells_admin_to_re_review():
    lid = _make_active()
    r = client.put(f"/api/landlord/listings/{lid}", headers=_h(flow.LANDLORD),
                   json={"price": 9999})
    assert r.status_code == 200
    msgs = [n["message"] for n in _notes(flow.ADMIN) if n["listing_id"] == lid]
    assert any("needs re-review" in m for m in msgs)


def test_own_action_does_not_notify_yourself_and_others_cannot_read():
    lid = _listing()
    own = [n for n in _notes(flow.LANDLORD) if n["listing_id"] == lid]
    assert own == []  # the landlord submitted it, so nobody tells them
    _act(flow.ADMIN, lid, "verify")
    note = [n for n in _notes(flow.LANDLORD) if n["listing_id"] == lid][0]
    # another user cannot mark it read
    r = client.post(f"/api/notifications/{note['id']}/read", headers=_h(flow.OTHER))
    assert r.status_code == 404
    r = client.post(f"/api/notifications/{note['id']}/read", headers=_h(flow.LANDLORD))
    assert r.status_code == 200
    assert [n for n in _notes(flow.LANDLORD) if n["id"] == note["id"]][0]["is_read"] is True
