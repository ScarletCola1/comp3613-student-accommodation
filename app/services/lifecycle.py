"""
Listing lifecycle -- State pattern.

Each lifecycle status is a ``ListingState`` object that knows:
  * which actions it allows and which state each action leads to
  * whether listings in that state are visible to students

``ListingLifecycle`` is the Context. It holds the current state and delegates
every action to it, so an illegal move is refused in ONE place and the
status string and the four legacy flags can never disagree (the flags are
derived from the state, not stored independently).

Eight states, fourteen transitions (Sprint 1 lifecycle diagram):
    draft --submit--> pending --withdraw--> draft
    pending --verify--> verified (the "Provisional" box in the diagram)
    pending|verified --reject--> rejected --resubmit--> pending
    verified --activate--> active <--activate/deactivate--> inactive
    active --request_review--> re_review --verify--> active
    active|inactive --force_deactivate--> force_deactivated --restore--> active

Note: "verified" is the Provisional state of the Sprint 1 diagram. The starter
and docs/ACCEPTANCE.md call it verified, and the landlord activates it (Conflict 4).
"""

from __future__ import annotations

from typing import Any

ACTIONS = (
    "submit",
    "verify",
    "reject",
    "activate",
    "deactivate",
    "resubmit",
    "withdraw",
    "force_deactivate",
    "restore",
    "request_review",  # a significant edit to an active listing
)


class IllegalTransition(Exception):
    """Raised when the current state does not allow the requested action."""


class ListingState:
    """Base state: no transitions, not visible."""

    name = ""
    visible = False
    transitions: dict[str, str] = {}

    def handle(self, action: str) -> "ListingState":
        target = self.transitions.get(action)
        if target is None:
            raise IllegalTransition(
                f"cannot {action} a listing that is {self.name}"
            )
        return STATES[target]

    def allowed_actions(self) -> tuple[str, ...]:
        return tuple(self.transitions)


class DraftState(ListingState):
    name = "draft"
    transitions = {"submit": "pending"}


class PendingState(ListingState):
    name = "pending"
    transitions = {
        "verify": "verified",
        "reject": "rejected",
        "withdraw": "draft",
    }


class VerifiedState(ListingState):
    """The Provisional state of the Sprint 1 diagram."""

    name = "verified"
    transitions = {"activate": "active", "reject": "rejected"}


class ActiveState(ListingState):
    name = "active"
    visible = True
    transitions = {
        "deactivate": "inactive",
        "request_review": "re_review",
        "force_deactivate": "force_deactivated",
    }


class InactiveState(ListingState):
    name = "inactive"
    transitions = {"activate": "active", "force_deactivate": "force_deactivated"}


class ReReviewState(ListingState):
    name = "re_review"
    transitions = {"verify": "active"}


class RejectedState(ListingState):
    name = "rejected"
    transitions = {"resubmit": "pending"}


class ForceDeactivatedState(ListingState):
    name = "force_deactivated"
    transitions = {"restore": "active"}


STATES: dict[str, ListingState] = {
    s.name: s
    for s in (
        DraftState(),
        PendingState(),
        VerifiedState(),
        ActiveState(),
        InactiveState(),
        ReReviewState(),
        RejectedState(),
        ForceDeactivatedState(),
    )
}


class ListingLifecycle:
    """Context: holds the current state and delegates actions to it."""

    def __init__(self, status: str) -> None:
        if status not in STATES:
            raise ValueError(f"unknown listing status {status!r}")
        self.state = STATES[status]

    @property
    def status(self) -> str:
        return self.state.name

    @property
    def visible_to_students(self) -> bool:
        return self.state.visible

    def apply(self, action: str) -> str:
        """Move to the next state or raise IllegalTransition (state unchanged)."""
        self.state = self.state.handle(action)
        return self.status

    def flags(self) -> dict[str, int]:
        """Legacy flag columns, always derived from the one current state."""
        s = self.status
        return {
            "flag_pending": int(s == "pending"),
            "flag_verified": int(s == "verified"),
            "flag_active": int(s == "active"),
            "flag_rejected": int(s == "rejected"),
        }


def snapshot(listing: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": listing["id"],
        "status": listing["status"],
        "flag_pending": bool(listing["flag_pending"]),
        "flag_verified": bool(listing["flag_verified"]),
        "flag_active": bool(listing["flag_active"]),
        "flag_rejected": bool(listing["flag_rejected"]),
    }


def apply_action(listing: dict[str, Any], action: str) -> dict[str, Any]:
    """Apply an action to a listing dict; same result shape as the old API."""
    if action not in ACTIONS:
        return {"ok": False, "error": f"unknown action {action!r}"}
    try:
        lifecycle = ListingLifecycle(listing["status"])
        lifecycle.apply(action)
    except (IllegalTransition, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    updated = dict(listing)
    updated["status"] = lifecycle.status
    updated.update(lifecycle.flags())
    return {"ok": True, "listing": snapshot(updated), "row": updated, "changed": True}


def visible_to_students(listing: dict[str, Any]) -> bool:
    """Visibility comes from the one current state, never from stray flags."""
    status = listing.get("status")
    return status in STATES and STATES[status].visible
