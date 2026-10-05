from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from plight_server.database import Base


DEFAULT_EQUIPMENT = {
    "helm": "",
    "tunic": "",
    "pants": "",
    "sleeves": "",
    "gloves": "",
    "boots": "",
    "ring_1": "",
    "ring_2": "",
    "ring_3": "",
    "ring_4": "",
    "ring_5": "",
    "necklace_1": "",
    "necklace_2": "",
    "left_hand": "fist",
    "right_hand": "fist",
}


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
        JSON, default=lambda: dict(DEFAULT_EQUIPMENT),
        server_default=text("'{}'"),
    )
    combat_state: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=lambda: {"target_id": None, "enemy_health": {}},
        server_default=text("'{}'"),
    )
    experience: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    quest_state: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    profile_pronouns: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_lore: Mapped[str] = mapped_column(Text, default="", server_default="")
    profile_picture_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    profile_picture_mime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    account: Mapped[Account] = relationship(back_populates="character")


class EnemySpawn(Base):
    __tablename__ = "enemy_spawns"
    __table_args__ = (
        CheckConstraint("health >= 0", name="ck_enemy_spawns_nonnegative_health"),
        Index("ix_enemy_spawns_location_alive", "location_id", "is_alive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    location_id: Mapped[str] = mapped_column(String(64), index=True)
    enemy_id: Mapped[str] = mapped_column(String(64), index=True)
    health: Mapped[int] = mapped_column(Integer)
    is_alive: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    is_initial: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    spawned_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class FriendRequest(Base):
    __tablename__ = "friend_requests"
    __table_args__ = (
        UniqueConstraint("sender_account_id", "recipient_account_id", name="uq_friend_request_pair"),
        CheckConstraint("sender_account_id != recipient_account_id", name="ck_friend_request_not_self"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="ck_friend_request_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sender_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    recipient_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
