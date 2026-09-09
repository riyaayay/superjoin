"""Dependency injection for FastAPI."""

from __future__ import annotations

from sqlalchemy.orm import Session

from fkl.persistence.database import get_session


def get_db() -> Session:
    db = get_session()
    try:
        yield db
    finally:
        db.close()
