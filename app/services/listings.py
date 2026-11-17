"""Listing CRUD, browse filters, messaging, and lifecycle transitions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.database import engine
from app.models.listing import Listing
from app.models.message import Message
from app.models.state_change_log import StateChangeLog
from app.services.housing_auth import get_user
from app.services.lifecycle import (
    ACTIONS,
    ListingLifecycle,
    apply_action,
    visible_to_students,
)

ALLOWED_AREAS = {"st_augustine", "mount_hope"}

# Who may perform each lifecycle action (FR-14, FR-15)
ADMIN_ONLY = {"verify", "reject", "force_deactivate", "restore"}
OWNER_OR_ADMIN = {"submit", "activate", "deactivate", "resubmit", "withdraw"}
# Actions that must carry a reason
REASON_REQUIRED = {"reject", "force_deactivate"}
# Editing these fields on an active listing sends it back to Re-review (FR-12)
SIGNIFICANT_FIELDS = {"price", "amenities", "area"}
EDITABLE_FIELDS = {
    "title", "area", "price", "amenities", "contact_phone", "contact_email", "photos",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _eligible_student(student: dict[str, Any]) -> bool:
    """Registered student ID or provisional incoming pathway (ACCEPTANCE 1)."""
    return bool(student.get("student_id")) or bool(student.get("provisional"))


def _parse_amenities(raw: str) -> list[str]:
    return [a.strip().lower() for a in (raw or "").split(",") if a.strip()]


def submit_listing(
    landlord_id: int,
    *,
    title: str,
    area: str,
    price: int,
    amenities: str,
    contact_phone: str,
    contact_email: str,
    photos: str = "",
) -> dict[str, Any]:
    user = get_user(landlord_id)
    if not user or user["role"] != "landlord":
        return {"ok": False, "error": "landlords only"}
    area = (area or "").strip().lower()
    if area not in ALLOWED_AREAS:
        return {"ok": False, "error": "area must be st_augustine or mount_hope"}
    if price <= 0:
        return {"ok": False, "error": "price must be positive"}
    if not _parse_amenities(amenities):
        return {"ok": False, "error": "at least one amenity is required"}
    if not title.strip() or not contact_phone.strip() or not contact_email.strip():
        return {"ok": False, "error": "title and contact details are required"}

    with Session(engine) as session:
        listing = Listing(
            landlord_id=landlord_id,
            title=title,
            area=area,
            price=price,
            amenities=amenities,
            contact_phone=contact_phone,
            contact_email=contact_email,
            photos=photos,
            status="pending",
            flag_pending=1,
            flag_verified=0,
            flag_active=0,
            flag_rejected=0,
            created_at=_now(),
        )
        session.add(listing)
        session.commit()
        session.refresh(listing)
        return {"ok": True, "listing": listing.model_dump()}


def transition(
    actor_id: int, listing_id: int, action: str, reason: str | None = None
) -> dict[str, Any]:
    actor = get_user(actor_id)
    if not actor:
        return {"ok": False, "error": "unknown user"}
    if action not in ACTIONS:
        return {"ok": False, "error": f"action must be one of {ACTIONS}"}

    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}
        row = listing.model_dump()

        # Role and ownership gates
        if action in ADMIN_ONLY and actor["role"] != "admin":
            return {"ok": False, "error": "admin only"}
        if action in OWNER_OR_ADMIN:
            if actor["role"] == "landlord":
                if listing.landlord_id != actor_id:
                    return {"ok": False, "error": "not your listing"}
            elif actor["role"] != "admin":
                return {"ok": False, "error": "landlord/admin only"}
        if action == "request_review":
            return {"ok": False, "error": "request_review happens through editing"}

        # Some actions must say why, so the history is useful (FR-8, FR-17)
        if action in REASON_REQUIRED and not (reason or "").strip():
            return {"ok": False, "error": f"a reason is required to {action}"}

        old_status = listing.status
        result = apply_action(row, action)
        if not result.get("ok"):
            return result

        updated = result["row"]
        listing.status = updated["status"]
        listing.flag_pending = updated["flag_pending"]
        listing.flag_verified = updated["flag_verified"]
        listing.flag_active = updated["flag_active"]
        listing.flag_rejected = updated["flag_rejected"]
        session.add(listing)
        # One history row per change: who, when, old -> new state, reason (FR-17)
        session.add(
            StateChangeLog(
                listing_id=listing_id,
                actor_id=actor_id,
                actor_role=actor["role"],
                action=action,
                old_state=old_status,
                new_state=updated["status"],
                reason=(reason or "").strip(),
                created_at=_now(),
            )
        )
        session.commit()
        session.refresh(listing)
        return {"ok": True, "listing": listing.model_dump()}


def edit_listing(
    actor_id: int, listing_id: int, changes: dict[str, Any]
) -> dict[str, Any]:
    """Edit a listing. Rules by state (FR-10, FR-11, FR-12):

    - pending / verified / re_review: refused (under review)
    - force_deactivated: refused (admin must restore it first)
    - active: a minor edit keeps it active; a significant edit (price, amenities,
      area) hides it at once and sends it to Re-review
    - draft / rejected / inactive: edit allowed, state unchanged
    """
    actor = get_user(actor_id)
    if not actor:
        return {"ok": False, "error": "unknown user"}
    changes = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS and v is not None}
    if not changes:
        return {"ok": False, "error": "nothing to change"}

    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}
        if actor["role"] == "landlord":
            if listing.landlord_id != actor_id:
                return {"ok": False, "error": "not your listing"}
        elif actor["role"] != "admin":
            return {"ok": False, "error": "landlord/admin only"}

        status = listing.status
        if status in {"pending", "verified", "re_review"}:
            return {"ok": False, "error": "listing is under review and cannot be edited"}
        if status == "force_deactivated":
            return {"ok": False, "error": "listing was force-deactivated by the admin"}
        if "price" in changes and int(changes["price"]) <= 0:
            return {"ok": False, "error": "price must be positive"}
        if "area" in changes:
            changes["area"] = str(changes["area"]).strip().lower()
            if changes["area"] not in ALLOWED_AREAS:
                return {"ok": False, "error": "area must be st_augustine or mount_hope"}
        if "amenities" in changes and not _parse_amenities(changes["amenities"]):
            return {"ok": False, "error": "at least one amenity is required"}

        significant = any(
            getattr(listing, f) != changes[f] for f in SIGNIFICANT_FIELDS if f in changes
        )
        for field, value in changes.items():
            setattr(listing, field, value)

        new_status = status
        reason = "minor edit"
        if status == "active" and significant:
            lifecycle = ListingLifecycle(status)
            new_status = lifecycle.apply("request_review")
            listing.status = new_status
            for flag, val in lifecycle.flags().items():
                setattr(listing, flag, val)
            reason = "significant edit: " + ", ".join(sorted(changes))
        session.add(listing)
        session.add(
            StateChangeLog(
                listing_id=listing_id,
                actor_id=actor_id,
                actor_role=actor["role"],
                action="edit",
                old_state=status,
                new_state=new_status,
                reason=reason,
                created_at=_now(),
            )
        )
        session.commit()
        session.refresh(listing)
        return {"ok": True, "listing": listing.model_dump()}


def get_history(actor_id: int, listing_id: int) -> dict[str, Any]:
    """History of a listing: the admin, or the landlord who owns it."""
    actor = get_user(actor_id)
    if not actor:
        return {"ok": False, "error": "unknown user"}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}
        if actor["role"] == "landlord":
            if listing.landlord_id != actor_id:
                return {"ok": False, "error": "not your listing"}
        elif actor["role"] != "admin":
            return {"ok": False, "error": "admin or owning landlord only"}
        rows = session.exec(
            select(StateChangeLog)
            .where(StateChangeLog.listing_id == listing_id)
            .order_by(StateChangeLog.id)
        ).all()
        return {"ok": True, "history": [r.model_dump() for r in rows]}


def browse_for_students(
    student_id: int,
    *,
    area: str | None = None,
    max_price: int | None = None,
    amenity: str | None = None,
) -> dict[str, Any]:
    student = get_user(student_id)
    if not student or student["role"] != "student":
        return {"ok": False, "error": "students only"}
    if not _eligible_student(student):
        return {"ok": False, "error": "only eligible students can browse listings"}

    wanted_area = (area or "").strip().lower()
    wanted_amenities = set(_parse_amenities(amenity or ""))

    with Session(engine) as session:
        rows = session.exec(select(Listing).order_by(Listing.id)).all()
        items = [r.model_dump() for r in rows]

    results = []
    for item in items:
        if not visible_to_students(item):
            continue
        if item["area"] not in ALLOWED_AREAS:  # St. Augustine / Mount Hope only
            continue
        if wanted_area and item["area"] != wanted_area:
            continue
        if max_price is not None and int(item["price"]) > max_price:
            continue
        # every requested amenity must match exactly, ignoring case
        if wanted_amenities and not wanted_amenities <= set(
            _parse_amenities(item["amenities"])
        ):
            continue
        results.append(item)
    return {"ok": True, "listings": results}


def list_all(*, status: str | None = None) -> list[dict[str, Any]]:
    with Session(engine) as session:
        stmt = select(Listing).order_by(Listing.id)
        if status:
            stmt = stmt.where(Listing.status == status)
        return [r.model_dump() for r in session.exec(stmt).all()]


def send_message(student_id: int, listing_id: int, body: str) -> dict[str, Any]:
    student = get_user(student_id)
    if not student or student["role"] != "student":
        return {"ok": False, "error": "students only"}
    if not body.strip():
        return {"ok": False, "error": "body required"}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}
        # Only listings the student may see can be messaged (ACCEPTANCE 10, FR-21)
        if not _eligible_student(student):
            return {"ok": False, "error": "only eligible students can message"}
        if not visible_to_students(listing.model_dump()):
            return {"ok": False, "error": "this listing is no longer available"}
        message = Message(
            listing_id=listing_id,
            student_id=student_id,
            body=body,
            created_at=_now(),
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        return {"ok": True, "message_id": message.id}
