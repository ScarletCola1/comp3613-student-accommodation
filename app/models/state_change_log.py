from typing import Optional

from sqlmodel import Field, SQLModel


class StateChangeLog(SQLModel, table=True):
    """One row for every successful lifecycle change (FR-17)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    listing_id: int = Field(index=True)
    actor_id: int = Field(index=True)
    actor_role: str
    action: str
    old_state: str
    new_state: str
    reason: str = ""
    created_at: str
