from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import hashlib
from io import BytesIO
import logging
import os
import random
import re
import threading
import time
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from plight_server.database import SessionLocal, get_db
from plight_server.content import (
    WorldContentUpdate,
    read_world_content,
    world_content_dict,
    write_world_content,
)
from plight_server.game import (
    award_experience,
    enemy_strike,
    initial_area,
    initialize_quest_step,
    resolve_command,
    snapshot,
)
from plight_server.models import (
    Account,
    ChatMessage,
    Character,
    Command,
    EventCounter,
    EnemySpawn,
    FriendRequest,
    PlayerSession,
    utc_now,
)
from plight_server.schemas import (
    ChatSendRequest,
    CharacterCreateRequest,
    CommandRequest,
    DialogueChoiceRequest,
    FriendRequestCreate,
    FriendRequestUpdate,
    LoginRequest,
    ProfileUpdateRequest,
    QuestChoiceRequest,
    RegisterRequest,
)
from plight_server.security import authenticate_token, create_session, hash_password, verify_password

LOCAL_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
LOGGER = logging.getLogger(__name__)
PRODUCTION_ORIGIN = os.getenv("PLIGHT_UI_ORIGIN", "").strip()
ALLOWED_ORIGINS = {PRODUCTION_ORIGIN} if PRODUCTION_ORIGIN else LOCAL_ORIGINS
MAX_REQUEST_BYTES = 1_048_576
MAX_WEBSOCKET_FRAME_CHARS = 4_096
MAX_PROFILE_IMAGE_BYTES = 512 * 1024
MAX_PROFILE_IMAGE_PIXELS = 4_000_000


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_prune = 0.0

    def check(self, key: str, bucket: str, limit: int, period: int) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_prune > 60:
                for event_key, timestamps in list(self._events.items()):
                    while timestamps and timestamps[0] <= now - 900:
                        timestamps.popleft()
                    if not timestamps:
                        del self._events[event_key]
                self._last_prune = now
            events = self._events[(key, bucket)]
            while events and events[0] <= now - period:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
        return True


class LiveConnection:
    def __init__(self, account_id: str, websocket: WebSocket) -> None:
        self.account_id = account_id
        self.websocket = websocket
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self.channels: set[str] = set()


class LiveHub:
    def __init__(self) -> None:
        self._connections: set[LiveConnection] = set()
        self._lock = threading.Lock()

    def add(self, connection: LiveConnection) -> None:
        with self._lock:
            self._connections.add(connection)

    def remove(self, connection: LiveConnection) -> None:
        with self._lock:
            self._connections.discard(connection)

    def active_accounts(self, channel_id: str) -> set[str]:
        with self._lock:
            return {
                connection.account_id
                for connection in self._connections
                if channel_id in connection.channels
            }

    def active_account_ids(self) -> set[str]:
        with self._lock:
            return {connection.account_id for connection in self._connections}

    def publish(self, account_id: str, channel_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            targets = [
                connection
                for connection in self._connections
                if connection.account_id == account_id and channel_id in connection.channels
            ]
        for connection in targets:
            def enqueue(target: LiveConnection = connection) -> None:
                if target.queue.full():
                    target.websocket.app.state.live_hub.remove(target)
                    asyncio.create_task(target.websocket.close(code=1013, reason="Client is too slow"))
                    return
                target.queue.put_nowait(event)

            connection.loop.call_soon_threadsafe(enqueue)


limiter = RateLimiter()
live_hub = LiveHub()
_character_locks: dict[str, threading.RLock] = {}
_character_locks_guard = threading.Lock()
_enemy_world_lock = threading.RLock()
_enemy_spawn_rng = random.SystemRandom()


def _character_lock(account_id: str) -> threading.RLock:
    with _character_locks_guard:
        return _character_locks.setdefault(account_id, threading.RLock())


def _initial_enemy_spawn_id(location_id: str, enemy_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"plight:initial-enemy:{location_id}:{enemy_id}"))


def _enemy_spawn_state(
    db: Session,
    content: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[EnemySpawn]]:
    entities = {entity["id"]: entity for entity in content["entities"]}
    allowed_by_location = {
        location["id"]: set(location["enemy_ids"])
        for location in content["locations"]
    }
    rows = db.scalars(
        select(EnemySpawn).where(EnemySpawn.is_alive.is_(True))
    ).all()
    initial_spawn_ids = set(
        db.scalars(
            select(EnemySpawn.id).where(EnemySpawn.is_initial.is_(True))
        ).all()
    )
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if (
            row.enemy_id not in allowed_by_location.get(row.location_id, set())
            or row.enemy_id not in entities
        ):
            row.is_alive = False
        else:
            counts[row.location_id] += 1
    for location in content["locations"]:
        spawn_limit = location["enemy_spawn_limit"]
        for enemy_id in dict.fromkeys(location["enemy_ids"]):
            if counts[location["id"]] >= spawn_limit:
                break
            spawn_id = _initial_enemy_spawn_id(location["id"], enemy_id)
            if spawn_id not in initial_spawn_ids:
                enemy = entities[enemy_id]
                db.add(
                    EnemySpawn(
                        id=spawn_id,
                        location_id=location["id"],
                        enemy_id=enemy_id,
                        health=enemy["attributes"]["health"],
                        is_initial=True,
                    )
                )
                initial_spawn_ids.add(spawn_id)
                counts[location["id"]] += 1
    db.flush()
    rows = db.scalars(
        select(EnemySpawn).where(EnemySpawn.is_alive.is_(True))
    ).all()
    by_location: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_location[row.location_id].append(
            {
                "id": row.id,
                "enemy_id": row.enemy_id,
                "health": row.health,
                "is_alive": row.is_alive,
            }
        )
    for spawns in by_location.values():
        spawns.sort(key=lambda spawn: spawn["id"])
    return dict(by_location), rows


def _active_enemy_spawns_for_location(
    db: Session,
    content: dict[str, Any],
    location_id: str,
) -> list[dict[str, Any]]:
    entities = {entity["id"]: entity for entity in content["entities"]}
    location = next(
        (item for item in content["locations"] if item["id"] == location_id),
        None,
    )
    if location is None:
        return []
    allowed_enemy_ids = set(location["enemy_ids"])
    rows = db.scalars(
        select(EnemySpawn).where(
            EnemySpawn.location_id == location_id,
            EnemySpawn.is_alive.is_(True),
        )
    ).all()
    spawns = []
    for row in rows:
        if (
            row.enemy_id not in allowed_enemy_ids
            or row.enemy_id not in entities
            or entities[row.enemy_id]["type"] != "enemy"
        ):
            row.is_alive = False
            continue
        spawns.append(
            {
                "id": row.id,
                "enemy_id": row.enemy_id,
                "health": row.health,
                "is_alive": True,
            }
        )
    spawns.sort(key=lambda spawn: spawn["id"])
    return spawns


def _persist_enemy_spawn_state(
    rows: list[EnemySpawn],
    spawns_by_location: dict[str, list[dict[str, Any]]],
) -> set[str]:
    spawn_by_id = {
        spawn["id"]: spawn
        for spawns in spawns_by_location.values()
        for spawn in spawns
    }
    changed_locations: set[str] = set()
    for row in rows:
        spawn = spawn_by_id.get(row.id)
        if spawn is None:
            continue
        if row.health != spawn["health"] or row.is_alive != spawn["is_alive"]:
            row.health = spawn["health"]
            row.is_alive = spawn["is_alive"]
            changed_locations.add(row.location_id)
    return changed_locations


def _publish_world_update(
    db: Session,
    location_id: str,
    messages: list[str] | None = None,
    exclude_account_ids: set[str] | None = None,
) -> None:
    active_accounts = live_hub.active_account_ids()
    if not active_accounts:
        return
    players = db.scalars(
        select(Character.account_id).where(
            Character.area_id == location_id,
            Character.account_id.in_(active_accounts),
        )
    ).all()
    event = {
        "type": "world.updated",
        "payload": {"id": str(uuid4()), "messages": messages or []},
    }
    for account_id in set(players) - (exclude_account_ids or set()):
        live_hub.publish(account_id, f"account:{account_id}", event)


def _snapshot_for_character(character: Character, db: Session) -> dict[str, Any]:
    with _character_lock(character.account_id), _enemy_world_lock:
        content = world_content_dict()
        spawns_by_location, _ = _enemy_spawn_state(db, content)
        db.commit()
        return snapshot(character, spawns_by_location)


def _error_response(status_code: int, code: str, message: str, request_id: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    return supplied[:64] if supplied else str(uuid4())


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_rate(request: Request, bucket: str, limit: int, seconds: int) -> None:
    if not limiter.check(_client_key(request), bucket, limit, seconds):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again shortly.")


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, credentials = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return None
    return credentials.strip()


def require_account(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Account:
    account = authenticate_token(db, _bearer_token(authorization))
    if account is None:
        raise HTTPException(status_code=401, detail="A valid bearer session is required.")
    return account


def _next_event_id(db: Session, account_id: str) -> int:
    counter = db.get(EventCounter, account_id)
    if counter is None:
        counter = EventCounter(account_id=account_id, value=1)
        db.add(counter)
    else:
        counter.value += 1
    db.flush()
    return counter.value


def _publish(
    db: Session,
    channel_id: str,
    event_type: str,
    payload: dict[str, Any],
    account_ids: set[str],
) -> None:
    occurred_at = utc_now().isoformat() + "Z"
    events = [
        (
            account_id,
            {
                "event_id": _next_event_id(db, account_id),
                "type": event_type,
                "occurred_at": occurred_at,
                "payload": payload,
            },
        )
        for account_id in account_ids
    ]
    db.commit()
    for account_id, event in events:
        live_hub.publish(account_id, channel_id, event)


def _private_channel_members(channel_id: str) -> set[str] | None:
    match = re.fullmatch(r"private:([0-9a-fA-F-]{36}):([0-9a-fA-F-]{36})", channel_id)
    return {match.group(1), match.group(2)} if match else None


def _can_access_channel(db: Session, account_id: str, channel_id: str) -> bool:
    if channel_id == "global":
        return True
    if channel_id == f"account:{account_id}":
        return True
    if channel_id.startswith("private:"):
        members = _private_channel_members(channel_id)
        return (
            members is not None
            and account_id in members
            and all(db.get(Account, member) is not None for member in members)
        )
    return False


def _message_dict(message: ChatMessage) -> dict[str, str]:
    return {
        "message_id": message.id,
        "sender_account_id": message.sender_account_id,
        "sender": message.sender_name,
        "text": message.text,
        "created_at": message.created_at.isoformat() + "Z",
    }


def _cleanup_expired_chat() -> None:
    cutoff = utc_now() - timedelta(days=90)
    with SessionLocal() as db:
        db.query(ChatMessage).filter(ChatMessage.created_at < cutoff).delete()
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    cleanup_task = asyncio.create_task(_chat_retention_loop())
    enemy_task = asyncio.create_task(_enemy_world_loop())
    try:
        yield
    finally:
        for task in (cleanup_task, enemy_task):
            task.cancel()
        for task in (cleanup_task, enemy_task):
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _chat_retention_loop() -> None:
    while True:
        await asyncio.to_thread(_cleanup_expired_chat)
        await asyncio.sleep(24 * 60 * 60)


async def _enemy_world_loop() -> None:
    next_spawn = time.monotonic() + 15
    next_aggression = time.monotonic() + 5
    while True:
        now = time.monotonic()
        await asyncio.sleep(max(0, min(next_spawn, next_aggression) - now))
        now = time.monotonic()
        if now >= next_spawn:
            try:
                await asyncio.to_thread(_run_enemy_spawn_tick)
            except Exception:
                LOGGER.exception("Enemy spawn tick failed.")
            next_spawn += 15 * (int((now - next_spawn) // 15) + 1)
        if now >= next_aggression:
            try:
                await asyncio.to_thread(_run_enemy_aggression_tick)
            except Exception:
                LOGGER.exception("Enemy aggression tick failed.")
            next_aggression += 5 * (int((now - next_aggression) // 5) + 1)


def _run_enemy_spawn_tick() -> None:
    content = world_content_dict()
    entities = {entity["id"]: entity for entity in content["entities"]}
    with _enemy_world_lock, SessionLocal() as db:
        spawns_by_location, rows = _enemy_spawn_state(db, content)
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            if row.is_alive:
                counts[row.location_id] += 1
        messages_by_location: dict[str, list[str]] = defaultdict(list)
        for location in content["locations"]:
            spawn_limit = location["enemy_spawn_limit"]
            if counts[location["id"]] >= spawn_limit:
                continue
            for enemy_id in dict.fromkeys(location["enemy_ids"]):
                if counts[location["id"]] >= spawn_limit:
                    break
                enemy = entities[enemy_id]
                chance = enemy["respawn_chance_percent"]
                if chance <= 0 or _enemy_spawn_rng.random() * 100 >= chance:
                    continue
                spawn = EnemySpawn(
                    location_id=location["id"],
                    enemy_id=enemy_id,
                    health=enemy["attributes"]["health"],
                )
                db.add(spawn)
                db.flush()
                spawns_by_location.setdefault(location["id"], []).append(
                    {
                        "id": spawn.id,
                        "enemy_id": enemy_id,
                        "health": spawn.health,
                        "is_alive": True,
                    }
                )
                counts[location["id"]] += 1
                messages_by_location[location["id"]].append(
                    f"{enemy['name']} appears."
                )
        db.commit()
        for location_id, messages in messages_by_location.items():
            _publish_world_update(db, location_id, messages)


def _run_enemy_aggression_tick() -> None:
    active_accounts = live_hub.active_account_ids()
    if not active_accounts:
        return
    content = world_content_dict()
    entities = {entity["id"]: entity for entity in content["entities"]}
    areas = {location["id"]: location for location in content["locations"]}
    now = utc_now()
    for account_id in sorted(active_accounts):
        with _character_lock(account_id), _enemy_world_lock, SessionLocal() as db:
            character = db.scalar(
                select(Character).where(Character.account_id == account_id)
            )
            if character is None or character.area_id not in areas:
                continue
            location_id = character.area_id
            location_spawns = _active_enemy_spawns_for_location(
                db, content, location_id
            )
            attack_times = dict(
                (character.combat_state or {}).get("enemy_attack_at", {})
            )
            aggressive_spawn_ids = {
                spawn["id"]
                for spawn in location_spawns
                if entities.get(spawn["enemy_id"], {}).get("behavior", "neutral")
                == "aggressive"
            }
            original_attack_times = dict(attack_times)
            messages: list[str] = []
            for spawn in location_spawns:
                enemy = entities.get(spawn["enemy_id"])
                if enemy is None or enemy.get("behavior", "neutral") != "aggressive":
                    continue
                last_attack = attack_times.get(spawn["id"])
                if last_attack:
                    try:
                        if not isinstance(last_attack, str):
                            raise ValueError
                        elapsed = (now - datetime.fromisoformat(last_attack)).total_seconds()
                    except (TypeError, ValueError):
                        LOGGER.warning("Discarding invalid enemy attack timestamp for %s.", spawn["id"])
                        elapsed = 30
                    if elapsed < 30:
                        continue
                messages.extend(enemy_strike(character, enemy, areas))
                attack_times[spawn["id"]] = now.isoformat()
                if character.area_id != location_id:
                    break
            attack_times = {
                spawn_id: attacked_at
                for spawn_id, attacked_at in attack_times.items()
                if spawn_id in aggressive_spawn_ids
            }
            if messages or attack_times != original_attack_times:
                state = dict(character.combat_state or {})
                state["enemy_attack_at"] = attack_times
                character.combat_state = state
            if db.new or db.dirty:
                db.commit()
            if messages:
                live_hub.publish(
                    account_id,
                    f"account:{account_id}",
                    {
                        "type": "world.updated",
                        "payload": {"id": str(uuid4()), "messages": messages},
                    },
                )


app = FastAPI(title="Plight API", version="1.0.0", lifespan=lifespan)
app.state.live_hub = live_hub
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "ngrok-skip-browser-warning",
    ],
)


class RequestSizeLimitMiddleware:
    def __init__(self, app_instance: Any) -> None:
        self.app = app_instance

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = next(
            (value.decode("latin-1") for key, value in scope["headers"] if key == b"content-length"),
            None,
        )
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BYTES:
                    response = _error_response(413, "request_too_large", "Request body exceeds the size limit.")
                    await response(scope, receive, send)
                    return
            except ValueError:
                response = _error_response(400, "invalid_content_length", "Invalid Content-Length header.")
                await response(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_REQUEST_BYTES:
                response = _error_response(413, "request_too_large", "Request body exceeds the size limit.")
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_body() -> dict[str, Any]:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_body, send)


app.add_middleware(RequestSizeLimitMiddleware)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    mapping = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        413: "request_too_large",
        429: "rate_limited",
    }
    return _error_response(
        exc.status_code,
        mapping.get(exc.status_code, "request_failed"),
        str(exc.detail),
        _request_id(request),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    message = "One or more request fields are invalid."
    if request.url.path == "/api/v1/content":
        reasons = [str(error.get("msg", "")) for error in exc.errors()[:5] if error.get("msg")]
        if reasons:
            message = " ".join(reasons)
    return _error_response(
        422,
        "validation_error",
        message,
        _request_id(request),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/register", status_code=201)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    _check_rate(request, "register", 5, 900)
    if db.scalar(select(Account).where(Account.email == body.email)):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    account = Account(email=body.email, password_hash=hash_password(body.password))
    db.add(account)
    db.commit()
    return {"account_created": True, "account_id": account.id}


@app.post("/api/v1/auth/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    _check_rate(request, "login", 5, 900)
    account = db.scalar(select(Account).where(Account.email == body.email))
    if account is None or not verify_password(body.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    token, expires_at = create_session(db, account)
    return {"token": token, "expires_at": expires_at.isoformat() + "Z", "account_id": account.id}


@app.post("/api/v1/characters", status_code=201)
def create_character(
    body: CharacterCreateRequest,
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_rate(request, "character_create", 5, 900)
    if account.character is not None:
        raise HTTPException(status_code=409, detail="This account already has a character.")
    name_key = body.name.casefold()
    if db.scalar(select(Character.id).where(Character.name_key == name_key)):
        raise HTTPException(status_code=409, detail="That character name is already taken.")
    character = Character(
        account_id=account.id,
        name=body.name,
        name_key=name_key,
        species=body.species,
        area_id=initial_area(body.species),
        appearance=body.appearance.model_dump(),
        inventory={},
    )
    try:
        db.add(character)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if db.scalar(select(Character.id).where(Character.name_key == name_key)):
            raise HTTPException(status_code=409, detail="That character name is already taken.") from error
        raise HTTPException(status_code=409, detail="A character already exists for this account.") from error
    return _snapshot_for_character(character, db)


@app.post("/api/v1/auth/logout", status_code=204)
def logout(
    account: Account = Depends(require_account),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Response:
    token_hash = hashlib.sha256((_bearer_token(authorization) or "").encode()).hexdigest()
    player_session = db.get(PlayerSession, token_hash)
    if player_session and player_session.account_id == account.id:
        player_session.revoked_at = utc_now()
        db.commit()
    return Response(status_code=204)


@app.get("/api/v1/me")
def me(account: Account = Depends(require_account)) -> dict[str, Any]:
    character = account.character
    if character is None:
        raise HTTPException(status_code=409, detail="This account does not have a character.")
    return {"account_id": account.id, "email": account.email, **snapshot(character)["character"]}


def _profile_dict(character: Character) -> dict[str, Any]:
    world_character = snapshot(character)["character"]
    return {
        "account_id": character.account_id,
        "name": character.name,
        "species": character.species,
        "area_name": world_character["area_name"],
        "pronouns": character.profile_pronouns,
        "lore": character.profile_lore or "",
        "profile_picture_url": (
            f"/api/v1/players/{character.account_id}/profile-picture"
            if character.profile_picture_data
            else None
        ),
    }


def _require_character(account: Account) -> Character:
    if account.character is None:
        raise HTTPException(status_code=409, detail="Create a character before using player profiles.")
    return account.character


def _quest_by_id(content: dict[str, Any], quest_id: str) -> dict[str, Any]:
    quest = next((item for item in content.get("quests", []) if item["id"] == quest_id), None)
    if quest is None:
        raise HTTPException(status_code=404, detail="That quest does not exist.")
    return quest


def _require_quest_giver_here(
    character: Character,
    quest: dict[str, Any],
    content: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    entities = {entity["id"]: entity for entity in content["entities"]}
    areas = {location["id"]: location for location in content["locations"]}
    giver = entities[quest["giver_npc_id"]]
    area = areas.get(character.area_id)
    if (
        area is None
        or giver["id"] not in area["npc_ids"]
        or character.species not in giver["present_for"]
    ):
        raise HTTPException(status_code=409, detail=f"You must be with {giver['name']} to do that.")
    return giver, entities


@app.post("/api/v1/quests/{quest_id}/accept")
def accept_quest(
    quest_id: str,
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_rate(request, "quest_actions", 30, 60)
    character = _require_character(account)
    with _character_lock(account.id):
        db.refresh(character)
        content = world_content_dict()
        quest = _quest_by_id(content, quest_id)
        giver, _ = _require_quest_giver_here(character, quest, content)
        state = dict(character.quest_state or {})
        current = state.get(quest_id, {}).get("status")
        if current == "completed":
            raise HTTPException(status_code=409, detail="You have already completed this quest.")
        if current == "active":
            return {
                "message": f"You have already accepted “{quest['title']}”.",
                "snapshot": _snapshot_for_character(character, db),
            }
        state[quest_id] = initialize_quest_step(
            quest,
            {
                "status": "active",
                "current_step_id": quest["start_step_id"],
                "progress": {},
                "items_to_turn_in": {},
            },
            character.area_id,
        )
        character.quest_state = state
        db.commit()
        _publish(
            db,
            f"account:{account.id}",
            "quest.updated",
            {"quest_id": quest_id, "status": "active"},
            {account.id},
        )
        return {
            "message": f"You accept “{quest['title']}” from {giver['name']}.",
            "snapshot": _snapshot_for_character(character, db),
        }


@app.post("/api/v1/quests/{quest_id}/choose")
def choose_quest_step(
    quest_id: str,
    body: QuestChoiceRequest,
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_rate(request, "quest_actions", 30, 60)
    character = _require_character(account)
    with _character_lock(account.id):
        db.refresh(character)
        content = world_content_dict()
        quest = _quest_by_id(content, quest_id)
        state = dict(character.quest_state or {})
        quest_state = dict(state.get(quest_id, {}))
        if quest_state.get("status") != "active":
            raise HTTPException(status_code=409, detail="Accept this quest before choosing a step.")
        if quest_state.get("ready_to_turn_in"):
            raise HTTPException(status_code=409, detail="This quest is ready to turn in.")
        step_id = quest_state.get("current_step_id") or quest["start_step_id"]
        if body.step_id != step_id:
            raise HTTPException(status_code=409, detail="That quest step is no longer active.")
        step = next((item for item in quest["steps"] if item["id"] == step_id), None)
        if step is None:
            raise HTTPException(status_code=409, detail="The active quest step no longer exists.")
        choice = next((item for item in step["choices"] if item["id"] == body.choice_id), None)
        if choice is None:
            raise HTTPException(status_code=409, detail="That quest choice is no longer available.")

        inventory = character.inventory or {}
        progress = (quest_state.get("progress") or {}).get(step_id, {})
        objectives_complete = all(
            (
                inventory.get(objective["target_id"], 0)
                if objective["type"] == "collect"
                else progress.get(objective["id"], 0)
            )
            >= objective["quantity"]
            for objective in step["objectives"]
        )
        if not objectives_complete:
            raise HTTPException(status_code=409, detail="Complete this step's objectives before choosing.")

        items_to_turn_in = dict(quest_state.get("items_to_turn_in") or {})
        for objective in step["objectives"]:
            if objective["type"] == "collect":
                item_id = objective["target_id"]
                items_to_turn_in[item_id] = (
                    items_to_turn_in.get(item_id, 0) + objective["quantity"]
                )

        next_step_id = choice["next_step_id"]
        if next_step_id is None:
            quest_state = {
                **quest_state,
                "current_step_id": None,
                "ready_to_turn_in": True,
                "items_to_turn_in": items_to_turn_in,
            }
        else:
            quest_state = initialize_quest_step(
                quest,
                {
                    **quest_state,
                    "current_step_id": next_step_id,
                    "ready_to_turn_in": False,
                    "items_to_turn_in": items_to_turn_in,
                },
                character.area_id,
            )
        state[quest_id] = quest_state
        character.quest_state = state
        db.commit()
        _publish(
            db,
            f"account:{account.id}",
            "quest.updated",
            {
                "quest_id": quest_id,
                "status": "active",
                "step_id": quest_state.get("current_step_id"),
            },
            {account.id},
        )
        return {
            "message": f"You choose: {choice['text']}",
            "snapshot": _snapshot_for_character(character, db),
        }


@app.post("/api/v1/quests/{quest_id}/turn-in")
def turn_in_quest(
    quest_id: str,
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_rate(request, "quest_actions", 30, 60)
    character = _require_character(account)
    with _character_lock(account.id):
        db.refresh(character)
        content = world_content_dict()
        quest = _quest_by_id(content, quest_id)
        giver, entities = _require_quest_giver_here(character, quest, content)
        state = dict(character.quest_state or {})
        quest_state = dict(state.get(quest_id, {}))
        if quest_state.get("status") == "completed":
            raise HTTPException(status_code=409, detail="You have already completed this quest.")
        if quest_state.get("status") != "active":
            raise HTTPException(status_code=409, detail="Accept this quest before turning it in.")
        if not quest_state.get("ready_to_turn_in"):
            raise HTTPException(
                status_code=409,
                detail="Complete the active step and choose to return to the quest giver first.",
            )

        inventory = dict(character.inventory or {})
        missing = [
            (
                entities[item_id]["name"],
                quantity - inventory.get(item_id, 0),
            )
            for item_id, quantity in quest_state.get("items_to_turn_in", {}).items()
            if inventory.get(item_id, 0) < quantity
        ]
        if missing:
            details = ", ".join(f"{quantity} more {name}" for name, quantity in missing)
            raise HTTPException(status_code=409, detail=f"You still need {details}.")

        for item_id, quantity in quest_state.get("items_to_turn_in", {}).items():
            remainder = inventory.get(item_id, 0) - quantity
            if remainder:
                inventory[item_id] = remainder
            else:
                inventory.pop(item_id, None)
        for reward in quest.get("reward_items", []):
            item_id = reward["item_id"]
            inventory[item_id] = inventory.get(item_id, 0) + reward["quantity"]
        character.inventory = inventory
        state[quest_id] = {
            **quest_state,
            "status": "completed",
            "ready_to_turn_in": False,
            "completed_at": utc_now().isoformat() + "Z",
        }
        character.quest_state = state
        messages = [
            f"{giver['name']} accepts your completed quest. “{quest['title']}” is complete."
        ]
        messages.extend(
            f"Reward: {reward['quantity']} {entities[reward['item_id']]['name']}."
            for reward in quest.get("reward_items", [])
        )
        messages.extend(award_experience(character, quest["reward_experience"]))
        db.commit()
        _publish(
            db,
            f"account:{account.id}",
            "quest.updated",
            {"quest_id": quest_id, "status": "completed"},
            {account.id},
        )
        return {
            "messages": messages,
            "snapshot": _snapshot_for_character(character, db),
        }


@app.get("/api/v1/profile")
def get_own_profile(account: Account = Depends(require_account)) -> dict[str, Any]:
    return _profile_dict(_require_character(account))


@app.put("/api/v1/profile")
def update_own_profile(
    body: ProfileUpdateRequest,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    character = _require_character(account)
    character.profile_pronouns = body.pronouns
    character.profile_lore = body.lore
    db.commit()
    return _profile_dict(character)


@app.put("/api/v1/profile/picture")
async def upload_profile_picture(
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_rate(request, "profile_picture_upload", 10, 3600)
    character = _require_character(account)
    body = await request.body()
    if not body or len(body) > MAX_PROFILE_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Profile images must be between 1 byte and 512 KiB.")
    declared_mime = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    expected_formats = {
        "image/png": "PNG",
        "image/jpeg": "JPEG",
        "image/webp": "WEBP",
    }
    if declared_mime not in expected_formats:
        raise HTTPException(status_code=415, detail="Upload a PNG, JPEG, or WebP image.")
    try:
        with Image.open(BytesIO(body)) as image:
            if image.format != expected_formats[declared_mime]:
                raise HTTPException(status_code=415, detail="The image content does not match its MIME type.")
            if image.width * image.height > MAX_PROFILE_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="Profile images may not exceed four million pixels.")
            image.load()
            safe_image = image.convert(
                "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
            )
            clean = BytesIO()
            safe_image.save(clean, format="PNG", optimize=True)
    except Image.DecompressionBombError:
        raise HTTPException(status_code=413, detail="Profile images may not exceed four million pixels.") from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=415, detail="The uploaded file is not a valid supported image.") from None
    character.profile_picture_data = clean.getvalue()
    character.profile_picture_mime = "image/png"
    db.commit()
    return _profile_dict(character)


@app.delete("/api/v1/profile/picture", status_code=204)
def delete_profile_picture(
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> Response:
    character = _require_character(account)
    character.profile_picture_data = None
    character.profile_picture_mime = None
    db.commit()
    return Response(status_code=204)


@app.get("/api/v1/players/{account_id}/profile-picture")
def profile_picture(
    account_id: str,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> Response:
    character = db.scalar(select(Character).where(Character.account_id == account_id))
    if character is None or character.profile_picture_data is None:
        raise HTTPException(status_code=404, detail="That player has no profile picture.")
    return Response(
        content=character.profile_picture_data,
        media_type=character.profile_picture_mime or "image/png",
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/v1/players/{account_id}/profile")
def get_player_profile(
    account_id: str,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    character = db.scalar(select(Character).where(Character.account_id == account_id))
    if character is None:
        raise HTTPException(status_code=404, detail="That player was not found.")
    return _profile_dict(character)


@app.get("/api/v1/world/snapshot")
def world_snapshot(
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if account.character is None:
        raise HTTPException(status_code=409, detail="This account does not have a character.")
    return _snapshot_for_character(account.character, db)


def _is_content_editor(account: Account) -> bool:
    editor_email = os.getenv("PLIGHT_CONTENT_EDITOR_EMAIL", "").strip().casefold()
    return bool(editor_email) and account.email.casefold() == editor_email


@app.get("/api/v1/content/permission")
def content_permission(account: Account = Depends(require_account)) -> dict[str, bool]:
    return {"can_edit": _is_content_editor(account)}


@app.get("/api/v1/content")
def get_content(
    account: Account = Depends(require_account),
) -> dict[str, Any]:
    if not _is_content_editor(account):
        raise HTTPException(status_code=403, detail="World content editing is not enabled for this account.")
    content, revision = read_world_content()
    return {"revision": revision, "content": content.model_dump(mode="json")}


@app.put("/api/v1/content")
def update_content(
    body: WorldContentUpdate,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not _is_content_editor(account):
        raise HTTPException(status_code=403, detail="World content editing is not enabled for this account.")
    location_ids = {location.id for location in body.content.locations}
    occupied_location_ids = set(db.scalars(select(Character.area_id).distinct()).all())
    removed_occupied_locations = occupied_location_ids - location_ids
    if removed_occupied_locations:
        names = ", ".join(sorted(removed_occupied_locations))
        raise HTTPException(
            status_code=409,
            detail=f"Move characters out of these locations before removing them: {names}.",
        )
    try:
        revision = write_world_content(body.content, body.revision)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"revision": revision, "saved": "World content is now active."}


@app.post("/api/v1/dialogue/choice")
def select_dialogue_choice(
    body: DialogueChoiceRequest,
    request: Request,
    account: Account = Depends(require_account),
) -> dict[str, Any]:
    _check_rate(request, "dialogue_choices", 60, 60)
    character = account.character
    if character is None:
        raise HTTPException(status_code=409, detail="Create a character before talking to NPCs.")

    content = world_content_dict()
    entities = {entity["id"]: entity for entity in content["entities"]}
    npc = entities.get(body.npc_id)
    area = next(
        (location for location in content["locations"] if location["id"] == character.area_id),
        None,
    )
    if (
        npc is None
        or npc["type"] != "npc"
        or area is None
        or body.npc_id not in area["npc_ids"]
        or character.species not in npc["present_for"]
    ):
        raise HTTPException(status_code=404, detail="That NPC is not available here.")

    dialogue = npc["dialogue"]
    nodes = {node["id"]: node for node in dialogue["nodes"]}
    node = nodes.get(body.node_id)
    choice = next(
        (entry for entry in node["choices"] if entry["id"] == body.choice_id),
        None,
    ) if node else None
    if choice is None:
        raise HTTPException(status_code=409, detail="That dialogue choice is no longer available.")
    next_node = nodes[choice["next_node_id"]]
    return {
        "npc_id": npc["id"],
        "npc_name": npc["name"],
        "node_id": next_node["id"],
        "title": next_node["title"],
        "text": next_node["text"],
        "choices": next_node["choices"],
    }


@app.get("/api/v1/players")
def players(
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, max_length=32),
) -> list[dict[str, Any]]:
    _require_character(account)
    query = select(Character).where(Character.account_id != account.id)
    if q and q.strip():
        query = query.where(Character.name_key.contains(q.strip().casefold(), autoescape=True))
    rows = db.scalars(query.order_by(Character.name).limit(50)).all()
    counterpart_ids = {row.account_id for row in rows}
    relationships = db.scalars(
        select(FriendRequest).where(
            or_(
                (FriendRequest.sender_account_id == account.id)
                & FriendRequest.recipient_account_id.in_(counterpart_ids),
                (FriendRequest.recipient_account_id == account.id)
                & FriendRequest.sender_account_id.in_(counterpart_ids),
            )
        )
    ).all() if counterpart_ids else []
    relation_by_account: dict[str, str] = {}
    for relation in relationships:
        other = (
            relation.recipient_account_id
            if relation.sender_account_id == account.id
            else relation.sender_account_id
        )
        if relation.status == "accepted":
            relation_by_account[other] = "friends"
        elif relation.status == "pending":
            relation_by_account[other] = (
                "outgoing_pending" if relation.sender_account_id == account.id else "incoming_pending"
            )
    results = []
    for character in rows:
        result = _profile_dict(character)
        result["friend_status"] = relation_by_account.get(character.account_id)
        results.append(result)
    return results


def _friend_request_dict(request: FriendRequest, account_id: str, db: Session) -> dict[str, Any]:
    is_sender = request.sender_account_id == account_id
    other_id = request.recipient_account_id if is_sender else request.sender_account_id
    character = db.scalar(select(Character).where(Character.account_id == other_id))
    return {
        "request_id": request.id,
        "status": request.status,
        "direction": "outgoing" if is_sender else "incoming",
        "created_at": request.created_at.isoformat() + "Z",
        "player": _profile_dict(character) if character else None,
    }


@app.get("/api/v1/friends")
def friends(
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_character(account)
    accepted = db.scalars(
        select(FriendRequest).where(
            FriendRequest.status == "accepted",
            or_(
                FriendRequest.sender_account_id == account.id,
                FriendRequest.recipient_account_id == account.id,
            ),
        )
    ).all()
    return [_friend_request_dict(item, account.id, db)["player"] for item in accepted]


@app.get("/api/v1/friend-requests")
def friend_requests(
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    _require_character(account)
    rows = db.scalars(
        select(FriendRequest).where(
            FriendRequest.status == "pending",
            or_(
                FriendRequest.sender_account_id == account.id,
                FriendRequest.recipient_account_id == account.id,
            ),
        ).order_by(FriendRequest.created_at.desc())
    ).all()
    return {
        "incoming": [
            _friend_request_dict(item, account.id, db)
            for item in rows
            if item.recipient_account_id == account.id
        ],
        "outgoing": [
            _friend_request_dict(item, account.id, db)
            for item in rows
            if item.sender_account_id == account.id
        ],
    }


@app.post("/api/v1/friend-requests", status_code=201)
def send_friend_request(
    body: FriendRequestCreate,
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_rate(request, "friend_requests", 20, 60)
    _require_character(account)
    recipient = db.scalar(select(Character).where(Character.account_id == body.recipient_account_id))
    if recipient is None:
        raise HTTPException(status_code=404, detail="That player was not found.")
    if recipient.account_id == account.id:
        raise HTTPException(status_code=409, detail="You cannot send a friend request to yourself.")
    existing = db.scalar(
        select(FriendRequest).where(
            or_(
                (FriendRequest.sender_account_id == account.id)
                & (FriendRequest.recipient_account_id == recipient.account_id),
                (FriendRequest.sender_account_id == recipient.account_id)
                & (FriendRequest.recipient_account_id == account.id),
            )
        )
    )
    if existing and existing.status == "accepted":
        raise HTTPException(status_code=409, detail="You are already friends.")
    if existing and existing.status == "pending":
        if existing.sender_account_id == account.id:
            raise HTTPException(status_code=409, detail="A friend request is already pending.")
        raise HTTPException(status_code=409, detail="Accept the friend request already waiting for you.")
    if existing and existing.sender_account_id == account.id:
        existing.status = "pending"
        existing.created_at = utc_now()
        existing.responded_at = None
        request_row = existing
    else:
        request_row = FriendRequest(
            sender_account_id=account.id,
            recipient_account_id=recipient.account_id,
        )
        db.add(request_row)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A friend request already exists for those players.") from error
    return _friend_request_dict(request_row, account.id, db)


@app.patch("/api/v1/friend-requests/{request_id}")
def respond_to_friend_request(
    request_id: str,
    body: FriendRequestUpdate,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request_row = db.get(FriendRequest, request_id)
    if (
        request_row is None
        or request_row.recipient_account_id != account.id
        or request_row.status != "pending"
    ):
        raise HTTPException(status_code=404, detail="That incoming friend request is not available.")
    request_row.status = body.status
    request_row.responded_at = utc_now()
    db.commit()
    return _friend_request_dict(request_row, account.id, db)


def _submit_command_locked(
    body: CommandRequest,
    account: Account,
    db: Session,
) -> dict[str, Any]:
    prior = db.scalar(
        select(Command).where(Command.account_id == account.id, Command.request_id == str(body.request_id))
    )
    if prior is not None:
        if prior.raw_text != body.text:
            raise HTTPException(status_code=409, detail="That request ID was already used for different text.")
        return {
            "request_id": prior.request_id,
            "status": prior.status,
            "result": prior.result,
        }
    if account.character is None:
        raise HTTPException(status_code=409, detail="Create a character before submitting commands.")
    command = Command(
        account_id=account.id,
        request_id=str(body.request_id),
        raw_text=body.text,
        status="queued",
    )
    changed_locations: set[str] = set()
    try:
        db.add(command)
        db.flush()
        command.status = "completed"
        spawns_by_location, spawn_rows = _enemy_spawn_state(db, world_content_dict())
        nearby_players = db.scalars(
            select(Character).where(
                Character.area_id == account.character.area_id,
                Character.account_id != account.id,
            )
        ).all()
        command.result = resolve_command(
            body.text,
            account.character,
            nearby_players,
            spawns_by_location,
        )
        changed_locations = _persist_enemy_spawn_state(spawn_rows, spawns_by_location)
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(
            select(Command).where(
                Command.account_id == account.id,
                Command.request_id == str(body.request_id),
            )
        )
        if prior is None:
            raise HTTPException(status_code=409, detail="The command conflicted with another update.")
        if prior.raw_text != body.text:
            raise HTTPException(status_code=409, detail="That request ID was already used for different text.")
        return {
            "request_id": prior.request_id,
            "status": prior.status,
            "result": prior.result,
        }
    _publish(
        db,
        f"account:{account.id}",
        "command.completed",
        {"request_id": command.request_id, "status": command.status, "result": command.result},
        {account.id},
    )
    for location_id in changed_locations:
        _publish_world_update(db, location_id, exclude_account_ids={account.id})
    return {"request_id": command.request_id, "status": command.status, "result": command.result}


@app.post("/api/v1/commands", status_code=202)
def submit_command(
    body: CommandRequest,
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_rate(request, "commands", 30, 60)
    character = _require_character(account)
    with _character_lock(account.id):
        db.refresh(character)
        with _enemy_world_lock:
            return _submit_command_locked(body, account, db)


@app.get("/api/v1/commands/{request_id}")
def get_command(
    request_id: str,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    command = db.scalar(
        select(Command).where(Command.account_id == account.id, Command.request_id == request_id)
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Command request was not found.")
    return {"request_id": command.request_id, "status": command.status, "result": command.result}


@app.get("/api/v1/chat/{channel_id}/messages")
def chat_history(
    channel_id: str,
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
    before: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=50),
) -> dict[str, Any]:
    _check_rate(request, "chat_history", 60, 60)
    if channel_id.startswith("account:") or not _can_access_channel(db, account.id, channel_id):
        raise HTTPException(status_code=403, detail="You are not a member of that chat channel.")
    query = select(ChatMessage).where(ChatMessage.channel_id == channel_id)
    if before:
        cursor = db.get(ChatMessage, before)
        if cursor is None or cursor.channel_id != channel_id:
            raise HTTPException(status_code=400, detail="The chat history cursor is invalid.")
        query = query.where(
            or_(
                ChatMessage.created_at < cursor.created_at,
                (ChatMessage.created_at == cursor.created_at) & (ChatMessage.id < cursor.id),
            )
        )
    messages = db.scalars(
        query.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)
    ).all()
    messages.reverse()
    return {
        "messages": [_message_dict(message) for message in messages],
        "next_before": messages[0].id if len(messages) == limit else None,
    }


@app.post("/api/v1/chat/messages", status_code=201)
def send_chat_message(
    body: ChatSendRequest,
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_rate(request, "chat_send", 20, 60)
    if body.channel_id.startswith("account:") or not _can_access_channel(db, account.id, body.channel_id):
        raise HTTPException(status_code=403, detail="You are not a member of that chat channel.")
    if body.channel_id != "global":
        members = _private_channel_members(body.channel_id)
        if members is None or not all(
            db.scalar(select(Character.id).where(Character.account_id == member)) is not None
            for member in members
        ):
            raise HTTPException(status_code=404, detail="The private conversation is unavailable.")
    character = account.character
    if character is None:
        raise HTTPException(status_code=409, detail="Create a character before sending chat messages.")
    message = ChatMessage(
        channel_id=body.channel_id,
        sender_account_id=account.id,
        sender_name=character.name,
        text=body.text,
    )
    db.add(message)
    db.commit()
    payload = {"channel_id": body.channel_id, **_message_dict(message)}
    recipients = live_hub.active_accounts(body.channel_id)
    if account.id not in recipients:
        recipients.add(account.id)
    _publish(db, body.channel_id, "chat.message", payload, recipients)
    return _message_dict(message)


async def _authenticate_websocket(websocket: WebSocket, token: str) -> str | None:
    def lookup() -> str | None:
        with SessionLocal() as db:
            account = authenticate_token(db, token)
            return account.id if account else None

    return await asyncio.to_thread(lookup)


async def _authorize_subscription(account_id: str, channel_id: str) -> bool:
    def check() -> bool:
        with SessionLocal() as db:
            return _can_access_channel(db, account_id, channel_id)

    return await asyncio.to_thread(check)


@app.websocket("/api/v1/live")
async def live(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin", "")
    if origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008, reason="Origin is not allowed")
        return
    client_key = websocket.client.host if websocket.client else "unknown"
    if not limiter.check(client_key, "websocket_auth", 10, 60):
        await websocket.close(code=1013, reason="Too many connection attempts")
        return
    await websocket.accept()
    try:
        raw_auth = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        if len(raw_auth) > MAX_WEBSOCKET_FRAME_CHARS:
            await websocket.close(code=1009, reason="Message too large")
            return
        import json

        auth_message = json.loads(raw_auth)
        if not isinstance(auth_message, dict) or auth_message.get("type") != "auth":
            await websocket.close(code=1008, reason="Authentication must be the first message")
            return
        token = auth_message.get("token")
        if not isinstance(token, str):
            await websocket.close(code=1008, reason="Invalid authentication")
            return
        account_id = await _authenticate_websocket(websocket, token)
        if account_id is None:
            await websocket.close(code=1008, reason="Authentication failed")
            return
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
        await websocket.close(code=1008, reason="Authentication failed")
        return

    connection = LiveConnection(account_id, websocket)
    connection.channels.add(f"account:{account_id}")
    live_hub.add(connection)
    await websocket.send_json({"type": "auth.ok"})

    async def send_events() -> None:
        while True:
            event = await connection.queue.get()
            await websocket.send_json(event)

    async def receive_messages() -> None:
        subscription_times: deque[float] = deque()
        while True:
            raw_message = await websocket.receive_text()
            if len(raw_message) > MAX_WEBSOCKET_FRAME_CHARS:
                await websocket.close(code=1009, reason="Message too large")
                return
            try:
                message = json.loads(raw_message)
            except ValueError:
                await websocket.send_json({"type": "error", "code": "invalid_message"})
                continue
            if not isinstance(message, dict) or message.get("type") != "subscribe":
                await websocket.send_json({"type": "error", "code": "unsupported_message"})
                continue
            now = time.monotonic()
            while subscription_times and subscription_times[0] <= now - 60:
                subscription_times.popleft()
            if len(subscription_times) >= 30:
                await websocket.send_json({"type": "error", "code": "rate_limited"})
                continue
            subscription_times.append(now)
            channel_id = message.get("channel_id")
            if not isinstance(channel_id, str) or not await _authorize_subscription(account_id, channel_id):
                await websocket.send_json({"type": "error", "code": "forbidden_channel"})
                continue
            connection.channels.add(channel_id)
            await websocket.send_json({"type": "subscribed", "channel_id": channel_id})

    sender = asyncio.create_task(send_events())
    receiver = asyncio.create_task(receive_messages())
    try:
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    finally:
        live_hub.remove(connection)
