from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from plight_server.models import Account, PlayerSession, utc_now

password_hasher = PasswordHasher()
SESSION_LIFETIME = timedelta(hours=12)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return password_hasher.verify(stored_hash, password)
    except VerifyMismatchError:
        return False


def create_session(db: Session, account: Account) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = utc_now() + SESSION_LIFETIME
    db.add(
        PlayerSession(
            id=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            account_id=account.id,
            expires_at=expires_at,
        )
    )
    db.commit()
    return token, expires_at


def authenticate_token(db: Session, token: str | None) -> Account | None:
    if not token or len(token) > 256:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    player_session = db.scalar(
        select(PlayerSession).where(
            PlayerSession.id == token_hash,
            PlayerSession.revoked_at.is_(None),
            PlayerSession.expires_at > utc_now(),
        )
    )
    return db.get(Account, player_session.account_id) if player_session else None
