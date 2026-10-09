from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[1]:
            raise ValueError("Enter a valid email address.")
        return normalized

class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class AppearanceRequest(BaseModel):
    build: Literal["slender", "average", "broad", "stocky"]
    complexion: Literal["pale", "light", "olive", "tan", "brown", "deep"]
    hair_style: Literal["short", "long", "tied_back", "braided", "bald"]
    hair_color: Literal["black", "brown", "blond", "red", "gray", "white"]
    eye_color: Literal["brown", "blue", "green", "gray", "amber"]


class CharacterCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=32)
    species: Literal["human", "goblin"]
    appearance: AppearanceRequest

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = " ".join(value.split())
        if not name or any(not (character.isalpha() or character in " -'") for character in name):
            raise ValueError("Use letters, spaces, hyphens, or apostrophes in the character name.")
        return name


class ProfileUpdateRequest(BaseModel):
    pronouns: str | None = Field(default=None, max_length=64)
    lore: str = Field(default="", max_length=2000)

    @field_validator("pronouns")
    @classmethod
    def normalize_pronouns(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("lore")
    @classmethod
    def normalize_lore(cls, value: str) -> str:
        return value.strip()


class FriendRequestCreate(BaseModel):
    recipient_account_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


class FriendRequestUpdate(BaseModel):
    status: Literal["accepted", "rejected"]


class PartyInviteCreate(BaseModel):
    recipient_account_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


class PartyInviteUpdate(BaseModel):
    status: Literal["accepted", "declined"]


class SessionResponse(BaseModel):
    token: str
    expires_at: str


class CommandRequest(BaseModel):
    request_id: UUID
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def trim_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Command text cannot be blank.")
        return text


class RollRequest(BaseModel):
    roll_id: UUID
    request_id: UUID | None = None


class DialogueChoiceRequest(BaseModel):
    npc_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    choice_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class ShopBuyRequest(BaseModel):
    npc_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    item_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    quantity: int = Field(default=1, ge=1, le=99)


class QuestChoiceRequest(BaseModel):
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    choice_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class ChatSendRequest(BaseModel):
    channel_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def trim_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Message text cannot be blank.")
        return text


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: str
    sender: str
    text: str
    created_at: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class DevGiveRequest(BaseModel):
    kind: Literal["item", "die_skin", "spell"]
    id: str = Field(max_length=64)
    quantity: int = Field(default=1, ge=1, le=9999)


class DieSkinRequest(BaseModel):
    skin_id: str | None = Field(default=None, max_length=64)


class SpellbookSlotRequest(BaseModel):
    book_id: str = Field(max_length=64)
    slot: int = Field(ge=0, le=39)
    spell_id: str | None = Field(default=None, max_length=64)
