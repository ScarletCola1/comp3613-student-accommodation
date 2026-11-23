"""Database table models.

Import every table model here so ``SQLModel.metadata.create_all`` sees them.
"""

from app.models.listing import Listing
from app.models.message import Message
from app.models.notification import Notification
from app.models.state_change_log import StateChangeLog
from app.models.user import User

__all__ = [
    "User",
    "Listing",
    "Message",
    "Notification",
    "StateChangeLog",
]
