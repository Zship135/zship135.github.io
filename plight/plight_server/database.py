from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.getenv("PLIGHT_DATABASE_URL", "sqlite:///./plight.db")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30}
    if DATABASE_URL.startswith("sqlite")
    else {},
)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
