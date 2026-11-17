"""Unit tests for the State pattern (app/services/lifecycle.py)."""

import pytest

from app.services.lifecycle import (
    ACTIONS,
    STATES,
    IllegalTransition,
    ListingLifecycle,
    apply_action,
    visible_to_students,
)

# The 14 allowed transitions of the Sprint 1 lifecycle diagram.
ALLOWED = [
    ("draft", "submit", "pending"),
    ("pending", "withdraw", "draft"),
    ("pending", "verify", "verified"),
    ("pending", "reject", "rejected"),
    ("verified", "activate", "active"),
    ("verified", "reject", "rejected"),
    ("active", "deactivate", "inactive"),
    ("inactive", "activate", "active"),
    ("active", "request_review", "re_review"),
    ("re_review", "verify", "active"),
    ("active", "force_deactivate", "force_deactivated"),
    ("inactive", "force_deactivate", "force_deactivated"),
    ("force_deactivated", "restore", "active"),
    ("rejected", "resubmit", "pending"),
]
FORBIDDEN = [
    (state, action)
    for state in STATES
    for action in ACTIONS
    if (state, action) not in {(s, a) for s, a, _ in ALLOWED}
]


def test_there_are_eight_states_and_fourteen_transitions():
    assert len(STATES) == 8
    assert len(ALLOWED) == 14


@pytest.mark.parametrize("state,action,target", ALLOWED)
def test_every_allowed_transition(state, action, target):
    lifecycle = ListingLifecycle(state)
    assert lifecycle.apply(action) == target
    assert lifecycle.status == target


@pytest.mark.parametrize("state,action", FORBIDDEN)
def test_every_forbidden_transition_is_refused_and_state_unchanged(state, action):
    lifecycle = ListingLifecycle(state)
    with pytest.raises(IllegalTransition):
        lifecycle.apply(action)
    assert lifecycle.status == state


def test_only_active_is_visible_to_students():
    visible = [name for name, st in STATES.items() if st.visible]
    assert visible == ["active"]
    assert visible_to_students({"status": "active", "flag_active": 0})
    # a stray flag can no longer make a hidden listing visible
    assert not visible_to_students({"status": "pending", "flag_active": 1})
    assert not visible_to_students({"status": "rejected", "flag_active": 1})


def test_flags_always_match_the_single_state():
    for name in STATES:
        flags = ListingLifecycle(name).flags()
        assert sum(flags.values()) <= 1
        for flag, value in flags.items():
            assert bool(value) == (flag == f"flag_{name}")


def test_unknown_status_and_action_are_rejected():
    with pytest.raises(ValueError):
        ListingLifecycle("sold")
    row = {
        "id": 1, "status": "pending", "flag_pending": 1,
        "flag_verified": 0, "flag_active": 0, "flag_rejected": 0,
    }
    assert apply_action(row, "explode")["ok"] is False


def test_apply_action_returns_consistent_row_and_flags():
    row = {
        "id": 1, "status": "pending", "flag_pending": 1,
        "flag_verified": 0, "flag_active": 0, "flag_rejected": 0,
    }
    out = apply_action(row, "verify")
    assert out["ok"] and out["row"]["status"] == "verified"
    assert out["row"]["flag_pending"] == 0 and out["row"]["flag_verified"] == 1


def test_old_defects_are_gone():
    pending = {
        "id": 1, "status": "pending", "flag_pending": 1,
        "flag_verified": 0, "flag_active": 0, "flag_rejected": 0,
    }
    assert apply_action(pending, "activate")["ok"] is False  # skip verification
    rejected = dict(pending, status="rejected", flag_pending=0, flag_rejected=1)
    assert apply_action(rejected, "verify")["ok"] is False  # verify w/o resubmit
    assert apply_action(rejected, "deactivate")["ok"] is False
