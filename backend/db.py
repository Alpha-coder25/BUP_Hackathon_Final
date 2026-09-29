"""Database engine, session factory, and schema creation.

Per `DOCS/TRD.md` §2 (PostgreSQL 16) and `erd.md` (physical names). Types are
portable: JSONB on PostgreSQL, JSON elsewhere (SQLite mock-simulator tests).
Sessions are request/loop-scoped; the collector opens one per tick.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import JSON

DB_URL = os.getenv("DB_URL", "sqlite:///./backend/dev.db")

# Portable JSON: JSONB on PostgreSQL, JSON elsewhere (SQLite tests).
JSONVariant = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """Declarative base — lives here so models.py can import it without a cycle."""

_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DB_URL, future=True)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables (hackathon-scale; Alembic is a deliberate skip)."""
    from . import models  # noqa: F401 — register mappings

    Base.metadata.create_all(get_engine())
