"""SQLAlchemy 2 declarative base.

All ORM models inherit from ``Base`` so Alembic autogenerate sees them.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model in the app."""
