from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from plight_server.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    character: Mapped[Character | None] = relationship(back_populates="account", uselist=False)
    sessions: Mapped[list[PlayerSession]] = relationship(back_populates="account")


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (
        UniqueConstraint("account_id"),
        UniqueConstraint("name_key", name="uq_characters_name_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(32))
    name_key: Mapped[str] = mapped_column(String(64))
    species: Mapped[str] = mapped_column(String(16))
    area_id: Mapped[str] = mapped_column(String(32))
    appearance: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    inventory: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    combat_stats: Mapped[dict[str, int]] = mapped_column(
        JSON,
        default=lambda: {"health": 100, "max_health": 100, "attack": 3, "defense": 1, "speed": 10},
        server_default=text("'{}'"),
    )
    equipment: Mapped[dict[str, str]] = mapped_column(
        JSON,
        default=lambda: {"left_hand": "fist", "right_hand": "fist"},
        server_default=text("'{}'"),
    )
    combat_state: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=lambda: {"target_id": None, "enemy_health": {}},
        server_default=text("'{}'"),
    )
    account: Mapped[Account] = relationship(back_populates="character")


class PlayerSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    account: Mapped[Account] = relationship(back_populates="sessions")


class Command(Base):
    __tablename__ = "commands"
    __table_args__ = (UniqueConstraint("account_id", "request_id", name="uq_command_account_request"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    raw_text: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    channel_id: Mapped[str] = mapped_column(String(128), index=True)
    sender_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    sender_name: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class EventCounter(Base):
    __tablename__ = "event_counters"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[int] = mapped_column(Integer, default=0)
