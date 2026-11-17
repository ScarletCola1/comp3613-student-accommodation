"""Tests for the other starter defects: input rules, eligibility, filters, messaging."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.database import engine
from app.main import app
from app.models.user import User
from app.seed import seed
from app.utilities.security import encrypt_password

client = TestClient(app)


def setup_module() -> None:
    seed(reset=True)
    with Session(engine) as session:
        session.add(
            User(
                username="ghost", email="ghost@example.com",
                password=encrypt_password("x"), role="student",
                display_name="No ID", student_id=None, provisional=0,
            )
        )
        session.commit()


def _login(email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()["user"]["id"]


def _h(uid):
    return {"X-User-Id": str(uid)}


def _new(landlord, **over):
    body = {
        "title": "Room", "area": "st_augustine", "price": 1500,
        "amenities": "wifi,parking", "contact_phone": "555", "contact_email": "l@x.com",
    }
    body.update(over)
    return client.post("/api/landlord/listings", headers=_h(landlord), json=body)


def _active(landlord, admin, **over):
    lid = _new(landlord, **over).json()["listing"]["id"]
    client.post(f"/api/listings/{lid}/transition", headers=_h(admin), json={"action": "verify"})
    client.post(f"/api/listings/{lid}/transition", headers=_h(landlord), json={"action": "activate"})
    return lid


def test_listing_area_must_be_st_augustine_or_mount_hope():
    landlord = _login("landlord@example.com", "land-dev")
    assert _new(landlord, area="port_of_spain").status_code == 400
    assert _new(landlord, area="Mount_Hope").status_code == 200  # case-insensitive


def test_listing_needs_amenities_and_contact_details():
    landlord = _login("landlord@example.com", "land-dev")
    assert _new(landlord, amenities="").status_code == 400
    assert _new(landlord, contact_phone=" ").status_code == 400
    assert _new(landlord, price=0).status_code == 400


def test_student_without_id_or_provisional_pathway_cannot_browse_or_message():
    ghost = _login("ghost@example.com", "x")
    r = client.get("/api/student/listings", headers=_h(ghost))
    assert r.status_code == 403
    r = client.post("/api/student/messages", headers=_h(ghost), json={"listing_id": 1, "body": "hi"})
    assert r.status_code == 400


def test_registered_and_provisional_incoming_students_can_browse():
    for email in ("student@example.com", "incoming@example.com"):
        uid = _login(email, "stud-dev")
        assert client.get("/api/student/listings", headers=_h(uid)).status_code == 200


def test_amenity_filter_is_case_insensitive_and_exact():
    landlord = _login("landlord@example.com", "land-dev")
    admin = _login("admin@example.com", "admin-dev")
    student = _login("student@example.com", "stud-dev")
    lid = _active(landlord, admin, amenities="WiFi,Parking", title="Amenity test")

    def ids(**q):
        r = client.get("/api/student/listings", headers=_h(student), params=q)
        return [x["id"] for x in r.json()["listings"]]

    assert lid in ids(amenity="wifi")
    assert lid in ids(amenity="PARKING")
    assert lid in ids(amenity="wifi,parking")  # all requested amenities match
    assert lid not in ids(amenity="wif")  # no substring match
    assert lid not in ids(amenity="pool")


def test_price_and_area_filters_narrow_results():
    landlord = _login("landlord@example.com", "land-dev")
    admin = _login("admin@example.com", "admin-dev")
    student = _login("student@example.com", "stud-dev")
    lid = _active(landlord, admin, area="mount_hope", price=900, title="Cheap")

    def ids(**q):
        r = client.get("/api/student/listings", headers=_h(student), params=q)
        return [x["id"] for x in r.json()["listings"]]

    assert lid in ids(area="mount_hope", max_price=1000)
    assert lid not in ids(max_price=800)
    assert lid not in ids(area="st_augustine")


def test_students_see_landlord_contact_on_visible_listings():
    student = _login("student@example.com", "stud-dev")
    r = client.get("/api/student/listings", headers=_h(student))
    first = r.json()["listings"][0]
    assert first["contact_phone"] and first["contact_email"]


def test_student_cannot_message_a_hidden_listing_but_can_message_an_active_one():
    landlord = _login("landlord@example.com", "land-dev")
    admin = _login("admin@example.com", "admin-dev")
    student = _login("student@example.com", "stud-dev")

    pending = _new(landlord).json()["listing"]["id"]
    r = client.post("/api/student/messages", headers=_h(student), json={"listing_id": pending, "body": "hi"})
    assert r.status_code == 400 and "no longer available" in r.json()["detail"]

    active = _active(landlord, admin)
    r = client.post("/api/student/messages", headers=_h(student), json={"listing_id": active, "body": "hi"})
    assert r.status_code == 200

    # once the landlord pauses it, messaging is refused again
    client.post(f"/api/listings/{active}/transition", headers=_h(landlord), json={"action": "deactivate", "reason": "Rented"})
    r = client.post("/api/student/messages", headers=_h(student), json={"listing_id": active, "body": "hi"})
    assert r.status_code == 400


def test_empty_message_is_refused():
    student = _login("student@example.com", "stud-dev")
    r = client.post("/api/student/messages", headers=_h(student), json={"listing_id": 1, "body": "  "})
    assert r.status_code == 400
