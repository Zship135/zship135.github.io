from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import hashlib
import os
import re
import threading
import time
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
from plight_server.game import initial_area, resolve_command, snapshot
from plight_server.models import (
    Account,
    ChatMessage,
    Character,
    Command,
    EventCounter,
    PlayerSession,
    utc_now,
)
from plight_server.schemas import (
    ChatSendRequest,
    CharacterCreateRequest,
    CommandRequest,
    DialogueChoiceRequest,
    LoginRequest,
    RegisterRequest,
)
from plight_server.security import authenticate_token, create_session, hash_password, verify_password

LOCAL_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
PRODUCTION_ORIGIN = os.getenv("PLIGHT_UI_ORIGIN", "").strip()
ALLOWED_ORIGINS = {PRODUCTION_ORIGIN} if PRODUCTION_ORIGIN else LOCAL_ORIGINS
MAX_REQUEST_BYTES = 1_048_576
MAX_WEBSOCKET_FRAME_CHARS = 4_096


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
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


async def _chat_retention_loop() -> None:
    while True:
        await asyncio.to_thread(_cleanup_expired_chat)
        await asyncio.sleep(24 * 60 * 60)


app = FastAPI(title="Plight API", version="1.0.0", lifespan=lifespan)
app.state.live_hub = live_hub
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
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
    return snapshot(character)


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


@app.get("/api/v1/world/snapshot")
def world_snapshot(account: Account = Depends(require_account)) -> dict[str, Any]:
    if account.character is None:
        raise HTTPException(status_code=409, detail="This account does not have a character.")
    return snapshot(account.character)


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
def players(account: Account = Depends(require_account), db: Session = Depends(get_db)) -> list[dict[str, str]]:
    rows = db.scalars(
        select(Character).where(Character.account_id != account.id).order_by(Character.name)
    ).all()
    return [
        {
            "account_id": character.account_id,
            "name": character.name,
            "species": character.species,
            "area_name": snapshot(character)["character"]["area_name"],
        }
        for character in rows
    ]


@app.post("/api/v1/commands", status_code=202)
def submit_command(
    body: CommandRequest,
    request: Request,
    account: Account = Depends(require_account),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _check_rate(request, "commands", 30, 60)
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
    try:
        db.add(command)
        db.flush()
        command.status = "completed"
        command.result = resolve_command(body.text, account.character)
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
    return {"request_id": command.request_id, "status": command.status, "result": command.result}


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
