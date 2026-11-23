from typing import Optional

from sqlmodel import Field, SQLModel


class Notification(SQLModel, table=True):
    """In-app notice about a listing change, for one user (FR-19, FR-20)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    listing_id: int = Field(index=True)
    message: str
    is_read: bool = False
    created_at: str
