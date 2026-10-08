from __future__ import annotations

import json
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from time import monotonic, sleep, time
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import event
from PIL import Image

import plight_server.app as api
import plight_server.audio_assets as audio_assets
import plight_server.content as content_store
import plight_server.game as game
from plight_server.database import Base, get_db
from plight_server.game import initial_area
from plight_server.models import (
    Account,
    Character,
    ChatMessage,
    CombatAction,
    CombatEncounter,
    Command,
    EnemySpawn,
    PlayerSession,
)

DEFAULT_APPEARANCE = {
    "build": "average",
    "complexion": "tan",
    "hair_style": "short",
    "hair_color": "brown",
    "eye_color": "brown",
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def configure_sqlite(connection: Any, _: Any) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionLocal", factory)

    def override_db():
        with factory() as db:
            yield db

    api.app.dependency_overrides[get_db] = override_db
    with api.limiter._lock:
        api.limiter._events.clear()
    with TestClient(api.app) as test_client:
        yield test_client
    api.app.dependency_overrides.clear()
    test_engine.dispose()


def register(client: TestClient, email: str, name: str, species: str = "human") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "a-long-test-password",
        },
    )
    assert response.status_code == 201, response.text
    account_id = response.json()["account_id"]
    with api.SessionLocal() as db:
        db.add(
            Character(
                account_id=account_id,
                name=name,
                name_key=name.casefold(),
                species=species,
                area_id=initial_area(species),
                appearance=DEFAULT_APPEARANCE,
                inventory={},
            )
        )
        db.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "a-long-test-password"},
    )
    assert login.status_code == 200, login.text
    return {"account_id": account_id, "token": login.json()["token"]}


@contextmanager
def live_as(client: TestClient, player: dict[str, str]):
    with client.websocket_connect(
        "/api/v1/live",
        headers={"Origin": "http://localhost:5173"},
    ) as websocket:
        websocket.send_json({"type": "auth", "token": player["token"]})
        assert websocket.receive_json() == {"type": "auth.ok"}
        channel_id = f"account:{player['account_id']}"
        websocket.send_json({"type": "subscribe", "channel_id": channel_id})
        subscribed = websocket.receive_json()
        while subscribed.get("type") == "party.updated":
            subscribed = websocket.receive_json()
        assert subscribed == {
            "type": "subscribed",
            "channel_id": channel_id,
        }
        yield websocket


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_production_ui_origin_keeps_local_ui_origins() -> None:
    production_origin = "https://game.example"
    assert api._allowed_ui_origins(production_origin) == api.LOCAL_ORIGINS | {
        production_origin
    }


def test_cors_allows_ngrok_browser_warning_bypass_header(client: TestClient) -> None:
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "authorization,content-type,ngrok-skip-browser-warning"
            ),
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "ngrok-skip-browser-warning" in allowed_headers


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", "/api/v1/friend-requests/ff3de713-8f38-4f8a-95a4-6e306e7bb568"),
        ("DELETE", "/api/v1/profile/picture"),
    ],
)
def test_cors_allows_friend_and_profile_mutation_preflights(
    client: TestClient, method: str, path: str
) -> None:
    response = client.options(
        path,
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert method in response.headers["access-control-allow-methods"]


def test_registration_creates_account_without_character_or_session(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "one@example.com", "password": "a-long-test-password"},
    )
    assert response.status_code == 201
    assert response.json()["account_created"] is True
    assert "token" not in response.json()
    with api.SessionLocal() as db:
        account = db.get(Account, response.json()["account_id"])
        assert account is not None
        assert account.password_hash != "a-long-test-password"
        assert account.character is None
        assert db.scalar(select(PlayerSession)) is None

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "one@example.com", "password": "a-long-test-password"},
    )
    assert login.status_code == 200
    headers = auth(login.json()["token"])
    world = client.get("/api/v1/world/snapshot", headers=headers)
    assert world.status_code == 409
    assert world.json()["error"]["code"] == "conflict"
    created = client.post(
        "/api/v1/characters",
        headers=headers,
        json={
            "name": "Ash",
            "species": "goblin",
            "appearance": {**DEFAULT_APPEARANCE, "hair_style": "braided"},
        },
    )
    assert created.status_code == 201
    assert created.json()["character"]["species"] == "goblin"
    assert created.json()["character"]["area_id"] == "goblin_town"
    assert created.json()["character"]["appearance"]["hair_style"] == "braided"
    assert client.get("/api/v1/world/snapshot", headers=headers).status_code == 200
    second_character = client.post(
        "/api/v1/characters",
        headers=headers,
        json={"name": "Another", "species": "human", "appearance": DEFAULT_APPEARANCE},
    )
    assert second_character.status_code == 409


def test_character_names_are_globally_unique_without_case_sensitivity(client: TestClient) -> None:
    register(client, "first@example.com", "Ash")
    account = client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "a-long-test-password"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "second@example.com", "password": "a-long-test-password"},
    )

    response = client.post(
        "/api/v1/characters",
        headers=auth(login.json()["token"]),
        json={"name": "aSH", "species": "human", "appearance": DEFAULT_APPEARANCE},
    )

    assert account.status_code == 201
    assert login.status_code == 200
    assert response.status_code == 409
    assert "already taken" in response.json()["error"]["message"]


def test_invalid_login_does_not_reveal_whether_email_exists(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "absent@example.com", "password": "a-long-test-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_logout_revokes_bearer_session(client: TestClient) -> None:
    registered = register(client, "two@example.com", "Briar")

    logout = client.post("/api/v1/auth/logout", headers=auth(registered["token"]))

    assert logout.status_code == 204
    me = client.get("/api/v1/me", headers=auth(registered["token"]))
    assert me.status_code == 401


def test_commands_are_persisted_and_idempotent(client: TestClient) -> None:
    registered = register(client, "three@example.com", "Rowan")
    request_id = "adf0f265-edca-449a-8ce5-100000000001"
    body = {"request_id": request_id, "text": "Run east"}
    with client.websocket_connect(
        "/api/v1/live",
        headers={"Origin": "http://localhost:5173"},
    ) as websocket:
        websocket.send_json({"type": "auth", "token": registered["token"]})
        assert websocket.receive_json() == {"type": "auth.ok"}
        first = client.post("/api/v1/commands", json=body, headers=auth(registered["token"]))
        event = websocket.receive_json()
        retry = client.post("/api/v1/commands", json=body, headers=auth(registered["token"]))

    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert first.json()["status"] == "completed"
    assert event["type"] == "command.completed"
    assert event["payload"]["request_id"] == request_id
    status = client.get(f"/api/v1/commands/{request_id}", headers=auth(registered["token"]))
    assert status.json() == first.json()
    with api.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Command)) == 1


def test_reusing_command_id_for_different_text_conflicts(client: TestClient) -> None:
    registered = register(client, "four@example.com", "Fern")
    request_id = "adf0f265-edca-449a-8ce5-100000000002"
    headers = auth(registered["token"])
    client.post("/api/v1/commands", json={"request_id": request_id, "text": "look"}, headers=headers)

    response = client.post(
        "/api/v1/commands",
        json={"request_id": request_id, "text": "wait"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_chat_history_and_live_delivery_use_authorized_channels(client: TestClient) -> None:
    first = register(client, "five@example.com", "Maple")
    second = register(client, "six@example.com", "Willow", "goblin")
    headers = {"Origin": "http://localhost:5173"}

    with client.websocket_connect("/api/v1/live", headers=headers) as websocket:
        websocket.send_json({"type": "auth", "token": first["token"]})
        assert websocket.receive_json() == {"type": "auth.ok"}
        websocket.send_json({"type": "subscribe", "channel_id": "global"})
        assert websocket.receive_json() == {"type": "subscribed", "channel_id": "global"}

        sent = client.post(
            "/api/v1/chat/messages",
            headers=auth(second["token"]),
            json={"channel_id": "global", "text": "Welcome to the road."},
        )
        assert sent.status_code == 201
        event = websocket.receive_json()
        assert event["type"] == "chat.message"
        assert event["payload"]["text"] == "Welcome to the road."
        assert isinstance(event["event_id"], int)

    history = client.get("/api/v1/chat/global/messages", headers=auth(first["token"]))
    assert history.json()["messages"] == [
        {
            "message_id": sent.json()["message_id"],
            "sender_account_id": second["account_id"],
            "sender": "Willow",
            "text": "Welcome to the road.",
            "created_at": sent.json()["created_at"],
        }
    ]


def test_private_chat_history_rejects_nonparticipants(client: TestClient) -> None:
    first = register(client, "seven@example.com", "Cedar")
    second = register(client, "eight@example.com", "Lark")
    outsider = register(client, "nine@example.com", "Wren")
    channel = f"private:{first['account_id']}:{second['account_id']}"

    denied = client.get(f"/api/v1/chat/{channel}/messages", headers=auth(outsider["token"]))

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"


def test_validation_errors_use_consistent_error_envelope(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "bad", "password": "tiny"},
    )

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "validation_error"


def test_public_login_attempts_are_rate_limited(client: TestClient) -> None:
    body = {"email": "absent@example.com", "password": "a-long-test-password"}
    attempts = [
        client.post("/api/v1/auth/login", json=body)
        for _ in range(6)
    ]

    assert [response.status_code for response in attempts] == [401, 401, 401, 401, 401, 429]
    assert attempts[-1].json()["error"]["code"] == "rate_limited"


def test_declared_oversized_request_body_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        content=b"x" * (api.MAX_REQUEST_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_chat_history_is_limited_to_fifty_messages(client: TestClient) -> None:
    registered = register(client, "ten@example.com", "Alder")
    with api.SessionLocal() as db:
        for index in range(51):
            db.add(
                ChatMessage(
                    channel_id="global",
                    sender_account_id=registered["account_id"],
                    sender_name="Alder",
                    text=f"Message {index}",
                )
            )
        db.commit()

    history = client.get(
        "/api/v1/chat/global/messages?limit=50",
        headers=auth(registered["token"]),
    )
    payload = history.json()
    assert len(payload["messages"]) == 50
    assert payload["next_before"]
    with api.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatMessage)) == 51


def test_content_editor_is_restricted_and_publishes_active_world_data(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = content_store.WORLD_CONTENT_PATH.read_bytes()
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", tmp_path / "world_content.json")
    content_store.WORLD_CONTENT_PATH.write_bytes(source)
    monkeypatch.setenv("PLIGHT_CONTENT_EDITOR_EMAIL", "builder@example.com")
    builder = register(client, "builder@example.com", "Builder")
    player = register(client, "player@example.com", "Player")

    permission = client.get("/api/v1/content/permission", headers=auth(builder["token"]))
    denied_permission = client.get("/api/v1/content/permission", headers=auth(player["token"]))
    loaded = client.get("/api/v1/content", headers=auth(builder["token"]))

    assert permission.json() == {"can_edit": True}
    assert denied_permission.json() == {"can_edit": False}
    assert loaded.status_code == 200
    update = loaded.json()
    update["content"]["locations"][0]["description"] = "A newly authored active description."
    update["content"]["locations"][0]["ambience"] = ["Lanterns sway over the market square."]
    update["content"]["locations"][0]["enemy_ids"].append("forest_rat")
    guide = next(entity for entity in update["content"]["entities"] if entity["id"] == "old_guide")
    guide["ambience"] = ["The old guide hums softly to themself."]
    guide["present_for"] = ["human", "goblin"]
    if "old_guide" not in update["content"]["locations"][0]["npc_ids"]:
        update["content"]["locations"][0]["npc_ids"].append("old_guide")
    rat = next(entity for entity in update["content"]["entities"] if entity["id"] == "forest_rat")
    rat["ambience"] = ["A small shape rustles under the cart."]
    saved = client.put("/api/v1/content", headers=auth(builder["token"]), json=update)
    assert saved.status_code == 200
    assert saved.json()["saved"] == "World content is now active."

    world = client.get("/api/v1/world/snapshot", headers=auth(builder["token"]))
    stale = client.put("/api/v1/content", headers=auth(builder["token"]), json=update)
    forbidden = client.put("/api/v1/content", headers=auth(player["token"]), json=update)

    assert world.json()["area"]["description"] == "A newly authored active description."
    assert set(world.json()["area"]["ambience_lines"]) == {
        "Lanterns sway over the market square.",
        "The old guide hums softly to themself.",
        "A small shape rustles under the cart.",
    }
    assert stale.status_code == 409
    assert forbidden.status_code == 403

    latest = client.get("/api/v1/content", headers=auth(builder["token"])).json()
    latest["content"]["locations"][0]["exits"] = {"north": "goblin_town"}
    latest["content"]["locations"][1]["exits"] = {"south": "human_city"}
    published = client.put("/api/v1/content", headers=auth(builder["token"]), json=latest)
    traveled = client.post(
        "/api/v1/commands",
        headers=auth(builder["token"]),
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000010", "text": "Run north"},
    )
    assert published.status_code == 200
    assert traveled.json()["result"]["snapshot"]["character"]["area_id"] == "goblin_town"


def test_content_audio_uploads_are_editor_only_and_playable(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = content_store.WORLD_CONTENT_PATH.read_bytes()
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", tmp_path / "world_content.json")
    content_store.WORLD_CONTENT_PATH.write_bytes(source)
    monkeypatch.setattr(audio_assets, "AUDIO_ASSET_DIR", tmp_path / "audio_assets")
    monkeypatch.setenv("PLIGHT_CONTENT_EDITOR_EMAIL", "audio-builder@example.com")
    builder = register(client, "audio-builder@example.com", "Builder")
    player = register(client, "audio-player@example.com", "Player")
    mp3 = bytes.fromhex("fffb9064") + bytes(32)

    upload = client.post(
        "/api/v1/content/audio",
        headers={**auth(builder["token"]), "Content-Type": "audio/mpeg"},
        content=mp3,
    )
    assert upload.status_code == 201, upload.text
    asset_id = upload.json()["asset_id"]
    served = client.get(f"/api/v1/content/audio/{asset_id}")
    assert served.status_code == 200
    assert served.content == mp3
    assert served.headers["content-type"] == "audio/mpeg"
    assert served.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get(f"/api/v1/content/audio/{uuid4()}").status_code == 404

    forbidden = client.post(
        "/api/v1/content/audio",
        headers={**auth(player["token"]), "Content-Type": "audio/mpeg"},
        content=mp3,
    )
    invalid = client.post(
        "/api/v1/content/audio",
        headers={**auth(builder["token"]), "Content-Type": "audio/mpeg"},
        content=b"not an mp3 file",
    )
    oversized_general_request = client.post(
        "/api/v1/content/audio",
        headers={**auth(builder["token"]), "Content-Type": "audio/mpeg"},
        content=b"x" * (api.MAX_REQUEST_BYTES + 1),
    )
    assert forbidden.status_code == 403
    assert invalid.status_code == 415
    assert oversized_general_request.status_code == 415
    monkeypatch.setattr(api, "MAX_AUDIO_ASSET_BYTES", len(mp3))
    oversized_audio = client.post(
        "/api/v1/content/audio",
        headers={**auth(builder["token"]), "Content-Type": "audio/mpeg"},
        content=mp3 + b"x",
    )
    assert oversized_audio.status_code == 413

    content_update = client.get("/api/v1/content", headers=auth(builder["token"])).json()
    current_area_id = client.get(
        "/api/v1/world/snapshot",
        headers=auth(builder["token"]),
    ).json()["area"]["id"]
    current_area = next(
        location
        for location in content_update["content"]["locations"]
        if location["id"] == current_area_id
    )
    current_area["music_asset_id"] = asset_id
    content_update["content"]["action_sounds"] = {"attack": asset_id}
    published = client.put(
        "/api/v1/content",
        headers=auth(builder["token"]),
        json=content_update,
    )
    assert published.status_code == 200, published.text
    snapshot_response = client.get("/api/v1/world/snapshot", headers=auth(builder["token"]))
    assert snapshot_response.json()["area"]["music_asset_id"] == asset_id
    assert snapshot_response.json()["action_sounds"] == {"attack": asset_id}

    invalid_action_sound = client.get("/api/v1/content", headers=auth(builder["token"])).json()
    invalid_action_sound["content"]["action_sounds"] = {"unknown_action": asset_id}
    rejected = client.put(
        "/api/v1/content",
        headers=auth(builder["token"]),
        json=invalid_action_sound,
    )
    assert rejected.status_code == 422


def test_content_editor_rejects_broken_world_references(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", tmp_path / "world_content.json")
    content_store.WORLD_CONTENT_PATH.write_bytes(
        (Path(__file__).resolve().parents[1] / "plight_server" / "world_content.json").read_bytes()
    )
    monkeypatch.setenv("PLIGHT_CONTENT_EDITOR_EMAIL", "builder@example.com")
    builder = register(client, "builder@example.com", "Builder")
    loaded = client.get("/api/v1/content", headers=auth(builder["token"]))
    update = loaded.json()
    update["content"]["locations"][0]["enemy_ids"] = ["not_a_real_enemy"]

    response = client.put("/api/v1/content", headers=auth(builder["token"]), json=update)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "missing or non-enemy" in response.json()["error"]["message"]


def test_npc_race_visibility_and_branching_dialogue(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = content_store.WORLD_CONTENT_PATH.read_bytes()
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", tmp_path / "world_content.json")
    content_store.WORLD_CONTENT_PATH.write_bytes(source)
    monkeypatch.setenv("PLIGHT_CONTENT_EDITOR_EMAIL", "builder@example.com")
    builder = register(client, "builder@example.com", "Builder", "human")
    goblin = register(client, "goblin@example.com", "Glim", "goblin")
    update = client.get("/api/v1/content", headers=auth(builder["token"])).json()
    guide = next(entity for entity in update["content"]["entities"] if entity["id"] == "old_guide")
    guide.update(
        {
            "race": "dryad",
            "present_for": ["human"],
            "dialogue": {
                "start_node_id": "greeting",
                "nodes": [
                    {
                        "id": "greeting",
                        "title": "Greeting",
                        "text": "Welcome. What would you like to know?",
                        "choices": [
                            {"id": "ask_town", "text": "Ask about town", "next_node_id": "town"},
                        ],
                    },
                    {
                        "id": "town",
                        "title": "The town",
                        "text": "Mossback grew beneath the forest canopy.",
                        "choices": [],
                    },
                ],
            },
        }
    )
    for location in update["content"]["locations"]:
        if location["id"] in {"human_city", "goblin_town"}:
            if "old_guide" not in location["npc_ids"]:
                location["npc_ids"].append("old_guide")
    saved = client.put("/api/v1/content", headers=auth(builder["token"]), json=update)
    assert saved.status_code == 200

    human_world = client.get("/api/v1/world/snapshot", headers=auth(builder["token"])).json()
    goblin_world = client.get("/api/v1/world/snapshot", headers=auth(goblin["token"])).json()
    human_guide = next(npc for npc in human_world["area"]["npcs"] if npc["id"] == "old_guide")
    assert human_guide["race"] == "dryad"
    assert "old_guide" not in {npc["id"] for npc in goblin_world["area"]["npcs"]}

    started = client.post(
        "/api/v1/commands",
        headers=auth(builder["token"]),
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000011", "text": "Talk to the old man"},
    )
    dialogue = started.json()["result"]["dialogues"][0]
    assert dialogue["node_id"] == "greeting"
    assert dialogue["text"] == "Welcome. What would you like to know?"

    advanced = client.post(
        "/api/v1/dialogue/choice",
        headers=auth(builder["token"]),
        json={"npc_id": "old_guide", "node_id": "greeting", "choice_id": "ask_town"},
    )
    denied = client.post(
        "/api/v1/dialogue/choice",
        headers=auth(goblin["token"]),
        json={"npc_id": "old_guide", "node_id": "greeting", "choice_id": "ask_town"},
    )
    assert advanced.status_code == 200
    assert advanced.json()["node_id"] == "town"
    assert advanced.json()["text"] == "Mossback grew beneath the forest canopy."
    assert denied.status_code == 404

    invalid_update = client.get("/api/v1/content", headers=auth(builder["token"])).json()
    invalid_guide = next(
        entity for entity in invalid_update["content"]["entities"] if entity["id"] == "old_guide"
    )
    invalid_guide["dialogue"]["nodes"][0]["choices"][0]["next_node_id"] = "missing_node"
    rejected = client.put("/api/v1/content", headers=auth(builder["token"]), json=invalid_update)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "validation_error"


def test_authored_world_locations_are_reachable_and_combat_content_is_ready() -> None:
    content, _ = content_store.read_world_content()
    locations = {location.id: location for location in content.locations}
    for species in ("human", "goblin"):
        start = next(location.id for location in content.locations if species in location.starting_species)
        reached = {start}
        pending = [start]
        while pending:
            current = pending.pop()
            for destination in locations[current].exits.values():
                if destination not in reached:
                    reached.add(destination)
                    pending.append(destination)
        assert reached == set(locations)

    assert locations["human_city"].exits["west"] == "new_location_2"
    assert locations["new_location_2"].exits["west"] == "new_location"
    assert all(
        entity.attack_die_sides is not None
        for entity in content.entities
        if entity.type == "enemy"
    )
    assert next(entity for entity in content.entities if entity.id == "new_enemy").attack_die_sides == 2


def test_player_can_travel_to_authored_enemy_and_npc_and_talk(client: TestClient) -> None:
    player = register(client, "worldwalk@example.com", "Mira")
    headers = auth(player["token"])
    initial = client.get("/api/v1/world/snapshot", headers=headers).json()
    assert initial["character"]["stats"] == {
        "health": 100,
        "max_health": 100,
        "attack": 3,
        "defense": 1,
        "speed": 10,
    }
    assert initial["character"]["equipment"] == game.DEFAULT_EQUIPMENT

    path = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000023", "text": "Travel west"},
    ).json()["result"]["snapshot"]
    assert path["area"]["name"] == "Path to Oblivion"
    assert path["area"]["enemies"][0]["name"] == "Slug"

    plain = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000024", "text": "Travel west"},
    ).json()["result"]["snapshot"]
    assert plain["area"]["npcs"][0]["name"] == "The Old Man"
    dialogue = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000025", "text": "Talk to the old man"},
    ).json()["result"]["dialogues"][0]
    assert dialogue["text"].startswith("Ah. Another one has been sent down")


def test_observe_command_resolves_present_entity_target(client: TestClient) -> None:
    registered = register(client, "intentmapping@example.com", "Mira", "goblin")
    headers = auth(registered["token"])

    observed = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000027", "text": "look at the forest rat"},
    ).json()["result"]

    assert observed["interpretation"]["occurrences"][0]["arguments"]["subject"] == "forest rat"
    assert observed["messages"] == [
        "Forest rat: A wary rat, at home beneath the forest canopy."
    ]


def test_environment_interactions_restore_health_and_set_character_respawn(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = json.loads(content_store.WORLD_CONTENT_PATH.read_text(encoding="utf-8"))
    start_area = next(
        location for location in document["locations"]
        if "human" in location["starting_species"]
    )
    away_area = next(
        location for location in document["locations"]
        if location["id"] != start_area["id"]
    )
    start_area["enemy_ids"] = []
    campfire = {
        "id": "test_campfire",
        "type": "furniture",
        "name": "Test Campfire",
        "description": "A warm fire.",
        "attributes": {},
        "interaction_effect": "restore_health",
    }
    bed = {
        "id": "test_bed",
        "type": "object",
        "name": "Test Bed",
        "description": "A sturdy bed.",
        "attributes": {},
        "interaction_effect": "set_respawn",
    }
    document["entities"].extend((campfire, bed))
    start_area["object_ids"] = [campfire["id"], bed["id"]]
    world_path = tmp_path / "world_content.json"
    world_path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", world_path)

    player = register(client, "environment-effects@example.com", "Ember")
    headers = auth(player["token"])
    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        character.combat_stats = {
            **game.PLAYER_BASE_STATS,
            "health": 23,
        }
        db.commit()

    rested = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": str(uuid4()), "text": "rest at Test Campfire"},
    ).json()["result"]
    assert any("restore your health to full (100/100)" in message for message in rested["messages"])
    assert rested["snapshot"]["character"]["stats"]["health"] == 100

    set_respawn = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": str(uuid4()), "text": "set my spawn at the Test Bed"},
    ).json()["result"]
    assert any("set Test Bed" in message for message in set_respawn["messages"])
    assert set_respawn["snapshot"]["character"]["respawn_area_id"] == start_area["id"]

    class MinimumRoll:
        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

    monkeypatch.setattr(game, "combat_rng", MinimumRoll())
    areas = {
        location["id"]: {"name": location["name"]}
        for location in document["locations"]
    }
    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        assert character.respawn_area_id == start_area["id"]
        character.area_id = away_area["id"]
        character.combat_stats = {
            **game.PLAYER_BASE_STATS,
            "health": 1,
        }
        messages = game.enemy_strike(
            character,
            {
                "name": "Test Enemy",
                "attributes": {"attack": 10},
                "attack_die_sides": 2,
            },
            areas,
        )
        db.commit()
        assert character.area_id == start_area["id"], (
            character.respawn_area_id,
            areas.keys(),
            messages,
        )
        assert character.respawn_area_id == start_area["id"]
        assert character.combat_stats["health"] == character.combat_stats["max_health"]
        assert any(start_area["name"] in message for message in messages)


def test_interaction_effect_is_restricted_to_environment_entities() -> None:
    document = content_store.read_world_content()[0].model_dump(mode="json")
    furniture = next(entity for entity in document["entities"] if entity["type"] == "furniture")
    furniture["interaction_effect"] = "restore_health"
    valid_world = content_store.WorldContent.model_validate(document)
    assert next(
        entity for entity in valid_world.entities if entity.id == furniture["id"]
    ).interaction_effect == "restore_health"

    enemy = next(entity for entity in document["entities"] if entity["type"] == "enemy")
    enemy["interaction_effect"] = "set_respawn"
    with pytest.raises(ValueError, match="Interaction effects only apply to furniture and objects"):
        content_store.WorldContent.model_validate(document)


def test_observe_without_target_describes_area_and_missing_target_fails(
    client: TestClient,
) -> None:
    registered = register(client, "observearea@example.com", "Mira", "goblin")
    headers = auth(registered["token"])

    area_result = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000029", "text": "look around"},
    ).json()["result"]
    missing_result = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000030", "text": "look at the dragon"},
    ).json()["result"]

    assert area_result["interpretation"]["occurrences"][0]["arguments"] == {}
    assert area_result["messages"] == [
        "Moss-covered homes gather beneath the old forest canopy."
    ]
    assert missing_result["messages"] == ["There is no dragon here to observe."]


def test_observe_self_returns_own_profile_account(client: TestClient) -> None:
    registered = register(client, "observeself@example.com", "Mira", "goblin")

    result = client.post(
        "/api/v1/commands",
        headers=auth(registered["token"]),
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000031", "text": "look at myself"},
    ).json()["result"]

    assert result["interpretation"]["occurrences"][0]["arguments"]["subject"] == "self"
    assert result["messages"] == ["You look over your character profile."]
    assert result["profile_account_ids"] == [registered["account_id"]]


def test_observe_inventory_phrases_open_canonical_menu_views(client: TestClient) -> None:
    registered = register(client, "inventory-view@example.com", "Mira", "goblin")
    headers = auth(registered["token"])
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        character.inventory = {"iron_sword": 1, "wood": 2}
        db.commit()

    examples = [
        ("observe my inventory", "all"),
        ("look in my inventory", "all"),
        ("what am I carrying?", "all"),
        ("observe armor", "armor"),
        ("observe hands", "hands"),
        ("observe weapons", "hands"),
    ]
    for index, (text, expected_view) in enumerate(examples, start=31):
        result = client.post(
            "/api/v1/commands",
            headers=headers,
            json={"request_id": f"adf0f265-edca-449a-8ce5-1000000000{index:02}", "text": text},
        ).json()["result"]
        occurrence = result["interpretation"]["occurrences"][0]
        assert occurrence["action_id"] == "observe"
        assert result["inventory_view"] == expected_view
        assert result["snapshot"]["character"]["inventory_items"] == [
            {
                "id": "iron_sword",
                "name": "Iron sword",
                "quantity": 1,
                "type": "weapon",
                "equipable_slots": ["right_hand"],
                "can_use": False,
            },
            {
                "id": "wood",
                "name": "Wood",
                "quantity": 2,
                "type": "item",
                "equipable_slots": [],
                "can_use": False,
            },
        ]


def test_equip_unequip_validate_ownership_slot_and_item_definition(client: TestClient) -> None:
    registered = register(client, "equip-items@example.com", "Briar", "goblin")
    headers = auth(registered["token"])
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        character.inventory = {"iron_sword": 1, "wood": 1}
        character.equipment = {"left_hand": "fist", "right_hand": "fist"}
        db.commit()

    def command(text: str, request_id: str):
        response = client.post(
            "/api/v1/commands",
            headers=headers,
            json={"request_id": request_id, "text": text},
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]

    left_hand = command("equip the iron sword in my left hand", "adf0f265-edca-449a-8ce5-100000000041")
    assert left_hand["interpretation"]["occurrences"][0]["action_id"] == "equip_item"
    assert left_hand["messages"] == ["Iron sword cannot be equipped in your left hand."]
    assert left_hand["snapshot"]["character"]["equipment"]["left_hand"] == ""
    persisted_snapshot = client.get("/api/v1/world/snapshot", headers=headers).json()
    assert persisted_snapshot["character"]["equipment"]["left_hand"] == ""
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        assert character.equipment["left_hand"] == "fist"

    non_owned = command("equip wooden club in my right hand", "adf0f265-edca-449a-8ce5-100000000042")
    assert non_owned["messages"] == ["You are not carrying a Wooden club."]

    unsupported = command("equip wood in my right hand", "adf0f265-edca-449a-8ce5-100000000043")
    assert unsupported["messages"] == [
        "Wood cannot be equipped; this item type has no equipment definition."
    ]

    invalid_slot = command("equip iron sword in my helm", "adf0f265-edca-449a-8ce5-100000000044")
    assert invalid_slot["messages"] == ["Iron sword cannot be equipped in your helm."]

    unknown_slot = command("equip iron sword in my backpack", "adf0f265-edca-449a-8ce5-100000000048")
    assert "Choose an equipment slot:" in unknown_slot["messages"][0]

    command("equip iron sword in my right hand", "adf0f265-edca-449a-8ce5-100000000046")
    named_unequip = command("unequip the iron sword", "adf0f265-edca-449a-8ce5-100000000045")
    assert named_unequip["interpretation"]["occurrences"][0]["action_id"] == "unequip_item"
    assert named_unequip["messages"] == ["You unequip Iron sword from your right hand."]
    command("equip iron sword in my right hand", "adf0f265-edca-449a-8ce5-100000000047")
    unequipped = command("unequip from my right hand", "adf0f265-edca-449a-8ce5-100000000049")
    assert unequipped["interpretation"]["occurrences"][0]["action_id"] == "unequip_item"
    assert unequipped["messages"] == ["You unequip Iron sword from your right hand."]
    assert unequipped["snapshot"]["character"]["equipment"]["right_hand"] == "fist"

    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        assert character.equipment["left_hand"] == ""
        assert character.equipment["right_hand"] == "fist"
        assert character.inventory == {"iron_sword": 1, "wood": 1}


def test_existing_two_hand_equipment_is_completed_with_empty_slots() -> None:
    class LegacyCharacter:
        account_id = "legacy-account"
        id = "legacy-character"
        name = "Legacy"
        species = "goblin"
        area_id = "goblin_town"
        appearance = {}
        inventory = {}
        combat_stats = {}
        equipment = {"left_hand": "iron_sword", "right_hand": "fist"}
        combat_state = {}

    result = game.snapshot(LegacyCharacter())
    assert result["character"]["equipment"] == game.DEFAULT_EQUIPMENT


def test_combat_uses_only_right_hand_and_enemy_attack_die(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    registered = register(client, "combat@example.com", "Briar", "goblin")

    class FixedRoll:
        @staticmethod
        def randint(_: int, __: int) -> int:
            return 1

    monkeypatch.setattr(game, "combat_rng", FixedRoll())
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        character.inventory = {"iron_sword": 1, "wooden_club": 1}
        character.combat_stats = {**game.PLAYER_BASE_STATS, "speed": 11}
        db.commit()

    headers = auth(registered["token"])
    with live_as(client, registered):
        left_equipped = client.post(
            "/api/v1/commands",
            headers=headers,
            json={"request_id": "adf0f265-edca-449a-8ce5-100000000020", "text": "Equip the iron sword in my left hand"},
        )
        equipped = client.post(
            "/api/v1/commands",
            headers=headers,
            json={"request_id": "adf0f265-edca-449a-8ce5-100000000021", "text": "Equip the wooden club in my right hand"},
        )
        attacked = client.post(
            "/api/v1/commands",
            headers=headers,
            json={"request_id": "adf0f265-edca-449a-8ce5-100000000022", "text": "Attack the forest rat"},
        )
        assert attacked.status_code == 200
        assert attacked.json()["status"] == "completed"

    assert "cannot be equipped in your left hand" in left_equipped.json()["result"]["messages"][0]
    assert "equip Wooden club in your right hand" in equipped.json()["result"]["messages"][0]
    result = attacked.json()["result"]
    assert any("right hand Wooden club for 6 damage" in message for message in result["messages"]), result["messages"]
    assert not any("left hand" in message for message in result["messages"])
    assert any("rolls D2 (1) and hits you for 2 damage" in message for message in result["messages"])
    assert result["snapshot"]["character"]["equipment"] == {
        **game.DEFAULT_EQUIPMENT,
        "right_hand": "wooden_club",
    }
    assert result["snapshot"]["character"]["stats"]["health"] == 98
    enemy = result["snapshot"]["area"]["enemies"][0]
    assert enemy["health"] == 6
    assert enemy["attack_die_sides"] == 2


def test_equal_speed_attack_waits_for_player_roll_and_rerolls_ties(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = register(client, "initiative-roll@example.com", "Briar", "goblin")

    class SequenceRoll:
        def __init__(self) -> None:
            self.values = iter((5, 5, 2, 10, 1))

        def randint(self, minimum: int, maximum: int) -> int:
            value = next(self.values)
            assert minimum <= value <= maximum
            return value

    monkeypatch.setattr(game, "combat_rng", SequenceRoll())
    headers = auth(registered["token"])
    request_id = "adf0f265-edca-449a-8ce5-100000000032"
    submitted = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": request_id, "text": "attack the forest rat"},
    ).json()

    assert submitted["status"] == "awaiting_roll"
    assert submitted["result"]["action_events"] == []
    assert submitted["result"]["messages"] == ["Roll for initiative against Forest rat."]
    tied = client.post(
        "/api/v1/roll",
        headers=headers,
        json={
            "roll_id": "adf0f265-edca-449a-8ce5-100000000033",
            "request_id": request_id,
        },
    ).json()
    assert tied["status"] == "awaiting_roll"
    assert "Tie—click Roll to try again." in tied["result"]["messages"][-1]
    assert tied["result"]["roll_animation"]["is_tie"] is True

    resolved = client.post(
        "/api/v1/roll",
        headers=headers,
        json={
            "roll_id": "adf0f265-edca-449a-8ce5-100000000034",
            "request_id": request_id,
        },
    ).json()
    messages = resolved["result"]["messages"]
    assert resolved["status"] == "completed"
    assert any("Roll for initiative:\nPlayer: 2\nForest rat: 10" in message for message in messages)
    assert next(index for index, message in enumerate(messages) if "rolls D2" in message) < next(
        index for index, message in enumerate(messages) if "You strike Forest rat" in message
    )
    assert resolved["result"]["action_events"] == ["attack"]


@pytest.mark.parametrize(
    ("text", "action_id", "expected_order"),
    [
        ("quick attack the forest rat", "light_attack", ("strike", "rolls D2")),
        ("smash the forest rat", "heavy_attack", ("rolls D2", "strike")),
    ],
)
def test_attack_style_speed_modifier_orders_player_and_enemy(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    action_id: str,
    expected_order: tuple[str, str],
) -> None:
    registered = register(client, f"{action_id}@example.com", "Briar", "goblin")

    class FixedRoll:
        @staticmethod
        def randint(_: int, __: int) -> int:
            return 1

    monkeypatch.setattr(game, "combat_rng", FixedRoll())
    result = client.post(
        "/api/v1/commands",
        headers=auth(registered["token"]),
        json={"request_id": str(uuid4()), "text": text},
    ).json()
    messages = result["result"]["messages"]

    assert result["status"] == "completed"
    assert result["result"]["action_events"] == [action_id]
    assert not any(message.startswith("Roll for initiative") for message in messages)
    assert next(index for index, message in enumerate(messages) if expected_order[0] in message) < next(
        index for index, message in enumerate(messages) if expected_order[1] in message
    )


def test_faster_enemy_can_defeat_player_before_attack_is_resolved(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = register(client, "initiative-defeat@example.com", "Briar", "goblin")

    class SequenceRoll:
        def __init__(self) -> None:
            self.values = iter((2, 10, 1))

        def randint(self, minimum: int, maximum: int) -> int:
            value = next(self.values)
            assert minimum <= value <= maximum
            return value

    monkeypatch.setattr(game, "combat_rng", SequenceRoll())
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        character.combat_stats = {**game.PLAYER_BASE_STATS, "health": 1, "speed": 10}
        db.commit()

    headers = auth(registered["token"])
    request_id = "adf0f265-edca-449a-8ce5-100000000035"
    submitted = client.post(
        "/api/v1/commands",
        headers=headers,
        json={"request_id": request_id, "text": "attack the forest rat"},
    ).json()
    result = client.post(
        "/api/v1/roll",
        headers=headers,
        json={
            "roll_id": "adf0f265-edca-449a-8ce5-100000000036",
            "request_id": request_id,
        },
    ).json()

    messages = result["result"]["messages"]
    assert submitted["status"] == "awaiting_roll"
    assert result["status"] == "completed"
    assert any("You are defeated." in message for message in messages)
    assert any("Your attack is cancelled because you were defeated before acting." == message for message in messages), messages
    assert not any("You strike Forest rat" in message for message in messages)
    assert result["result"]["action_events"] == []


def test_standalone_roll_returns_a_logged_d20_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = register(client, "standalone-roll@example.com", "Briar", "goblin")

    class FixedRoll:
        @staticmethod
        def randint(_: int, __: int) -> int:
            return 17

    monkeypatch.setattr(game, "combat_rng", FixedRoll())
    result = client.post(
        "/api/v1/roll",
        headers=auth(registered["token"]),
        json={"roll_id": "adf0f265-edca-449a-8ce5-100000000037"},
    ).json()

    assert result["status"] == "completed"
    assert result["result"]["messages"] == ["You roll a D20: 17."]
    assert result["result"]["roll_animation"]["rolls"] == [{"label": "Player", "value": 17}]


def test_defend_reduces_the_immediate_enemy_response(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(tmp_path, monkeypatch, behavior="neutral", respawn_chance=0)
    registered = register(client, "guard@example.com", "Briar")

    class FixedRoll:
        @staticmethod
        def randint(_: int, __: int) -> int:
            return 1

    monkeypatch.setattr(game, "combat_rng", FixedRoll())
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        character.area_id = "spawn_room"
        character.combat_state = {"target_id": None, "enemy_health": {}}
        db.commit()

    with live_as(client, registered):
        first_attack = client.post(
            "/api/v1/commands",
            headers=auth(registered["token"]),
            json={"request_id": "adf0f265-edca-449a-8ce5-100000000026", "text": "Attack the test rat"},
        )
        defended = client.post(
            "/api/v1/commands",
            headers=auth(registered["token"]),
            json={"request_id": "adf0f265-edca-449a-8ce5-100000000027", "text": "Defend"},
        )
    assert first_attack.status_code == 200
    assert any("hits you for 1 damage (99/100 health)" in message for message in first_attack.json()["result"]["messages"])
    assert defended.status_code == 200
    assert any("hits you for 0 damage (99/100 health)" in message for message in defended.json()["result"]["messages"])


def test_defeat_restores_player_and_enemy_at_species_start(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    registered = register(client, "defeat@example.com", "Ash", "human")

    class MaximumRoll:
        @staticmethod
        def randint(_: int, maximum: int) -> int:
            return maximum

    monkeypatch.setattr(game, "combat_rng", MaximumRoll())
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        character.area_id = "goblin_town"
        character.combat_stats = {
            "health": 1,
            "max_health": 100,
            "attack": 3,
            "defense": 1,
            "speed": 9,
        }
        db.commit()

    with live_as(client, registered):
        defeated = client.post(
            "/api/v1/commands",
            headers=auth(registered["token"]),
            json={"request_id": "adf0f265-edca-449a-8ce5-100000000022", "text": "Attack the forest rat"},
        )
        result = defeated.json()["result"]
    assert any("You are defeated" in message for message in result["messages"])
    assert result["snapshot"]["character"]["area_id"] == initial_area("human")
    assert result["snapshot"]["character"]["stats"]["health"] == 100
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        assert character.combat_state["target_id"] is None
        spawn = db.scalar(
            select(EnemySpawn).where(
                EnemySpawn.scope_type == "solo",
                EnemySpawn.scope_id == registered["account_id"],
                EnemySpawn.location_id == "goblin_town",
            )
        )
        assert spawn is not None and spawn.is_alive


def test_content_editor_validates_enemy_attack_die(client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", tmp_path / "world_content.json")
    content_store.WORLD_CONTENT_PATH.write_bytes(
        (Path(__file__).resolve().parents[1] / "plight_server" / "world_content.json").read_bytes()
    )
    monkeypatch.setenv("PLIGHT_CONTENT_EDITOR_EMAIL", "builder@example.com")
    builder = register(client, "builder@example.com", "Builder")
    update = client.get("/api/v1/content", headers=auth(builder["token"])).json()
    enemy = next(entity for entity in update["content"]["entities"] if entity["type"] == "enemy")
    assert enemy["attack_die_sides"] == 2
    enemy["attack_die_sides"] = 1

    response = client.put("/api/v1/content", headers=auth(builder["token"]), json=update)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

    enemy["attack_die_sides"] = 2
    enemy["aggressive_attack_chance_percent"] = 101
    invalid_chance = client.put(
        "/api/v1/content",
        headers=auth(builder["token"]),
        json=update,
    )

    assert invalid_chance.status_code == 422
    assert invalid_chance.json()["error"]["code"] == "validation_error"


def test_profile_edit_search_and_authenticated_picture_upload(client: TestClient) -> None:
    owner = register(client, "profile-owner@example.com", "Fern")
    viewer = register(client, "profile-viewer@example.com", "Mira", "goblin")
    owner_headers = auth(owner["token"])
    viewer_headers = auth(viewer["token"])

    updated = client.put(
        "/api/v1/profile",
        headers=owner_headers,
        json={"pronouns": "they/them", "lore": "A cartographer seeking lost roads."},
    )
    assert updated.status_code == 200
    assert updated.json()["pronouns"] == "they/them"
    assert updated.json()["lore"] == "A cartographer seeking lost roads."
    assert client.get("/api/v1/profile").status_code == 401

    png = BytesIO()
    Image.new("RGB", (8, 8), "purple").save(png, format="PNG")
    upload = client.put(
        "/api/v1/profile/picture",
        headers={**owner_headers, "Content-Type": "image/png"},
        content=png.getvalue(),
    )
    assert upload.status_code == 200, upload.text
    picture_url = upload.json()["profile_picture_url"]
    served = client.get(picture_url, headers=viewer_headers)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert Image.open(BytesIO(served.content)).format == "PNG"
    assert client.get(picture_url).status_code == 401
    assert client.get("/api/v1/players?q=Fern").status_code == 401
    assert client.get(f"/api/v1/players/{owner['account_id']}/profile").status_code == 401
    mismatch = client.put(
        "/api/v1/profile/picture",
        headers={**owner_headers, "Content-Type": "image/jpeg"},
        content=png.getvalue(),
    )
    assert mismatch.status_code == 415
    executable = client.put(
        "/api/v1/profile/picture",
        headers={**owner_headers, "Content-Type": "image/png"},
        content=b"MZ executable payload",
    )
    assert executable.status_code == 415
    too_large = client.put(
        "/api/v1/profile/picture",
        headers={**owner_headers, "Content-Type": "image/png"},
        content=b"x" * (512 * 1024 + 1),
    )
    assert too_large.status_code == 413
    large_image = BytesIO()
    Image.new("RGB", (2001, 2000), "black").save(large_image, format="PNG", optimize=True)
    oversized_dimensions = client.put(
        "/api/v1/profile/picture",
        headers={**owner_headers, "Content-Type": "image/png"},
        content=large_image.getvalue(),
    )
    assert oversized_dimensions.status_code == 413

    results = client.get("/api/v1/players?q=er", headers=viewer_headers)
    assert results.status_code == 200
    assert results.json() == [
        {
            "account_id": owner["account_id"],
            "name": "Fern",
            "species": "human",
            "area_name": "Dawnmere",
            "pronouns": "they/them",
            "lore": "A cartographer seeking lost roads.",
            "profile_picture_url": picture_url,
            "friend_status": None,
        }
    ]


def test_friend_requests_require_recipient_acceptance(client: TestClient) -> None:
    alice = register(client, "friend-alice@example.com", "Alice")
    bob = register(client, "friend-bob@example.com", "Bobbins")
    alice_headers = auth(alice["token"])
    bob_headers = auth(bob["token"])

    sent = client.post(
        "/api/v1/friend-requests",
        headers=alice_headers,
        json={"recipient_account_id": bob["account_id"]},
    )
    assert sent.status_code == 201
    assert sent.json()["status"] == "pending"
    assert sent.json()["direction"] == "outgoing"
    assert client.get("/api/v1/friends", headers=alice_headers).json() == []
    assert client.get("/api/v1/friends", headers=bob_headers).json() == []
    assert client.get("/api/v1/friend-requests", headers=bob_headers).json()["incoming"][0]["player"]["name"] == "Alice"

    duplicate = client.post(
        "/api/v1/friend-requests",
        headers=alice_headers,
        json={"recipient_account_id": bob["account_id"]},
    )
    assert duplicate.status_code == 409
    sender_cannot_accept = client.patch(
        f"/api/v1/friend-requests/{sent.json()['request_id']}",
        headers=alice_headers,
        json={"status": "accepted"},
    )
    assert sender_cannot_accept.status_code == 404
    accepted = client.patch(
        f"/api/v1/friend-requests/{sent.json()['request_id']}",
        headers=bob_headers,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert [friend["name"] for friend in client.get("/api/v1/friends", headers=alice_headers).json()] == ["Bobbins"]
    assert [friend["name"] for friend in client.get("/api/v1/friends", headers=bob_headers).json()] == ["Alice"]
    self_request = client.post(
        "/api/v1/friend-requests",
        headers=alice_headers,
        json={"recipient_account_id": alice["account_id"]},
    )
    assert self_request.status_code == 409


def test_party_invites_require_acceptance_and_party_chat_is_member_only(client: TestClient) -> None:
    leader = register(client, "party-leader@example.com", "Mira")
    invitee = register(client, "party-invitee@example.com", "Sable")
    outsider = register(client, "party-outsider@example.com", "Rook")
    leader_headers = auth(leader["token"])
    invitee_headers = auth(invitee["token"])
    outsider_headers = auth(outsider["token"])

    created = client.post("/api/v1/party", headers=leader_headers)
    assert created.status_code == 201
    party = created.json()["party"]
    assert party["leader_account_id"] == leader["account_id"]
    assert [member["account_id"] for member in party["members"]] == [leader["account_id"]]

    invitation = client.post(
        "/api/v1/party/invitations",
        headers=leader_headers,
        json={"recipient_account_id": invitee["account_id"]},
    )
    assert invitation.status_code == 201
    invitee_state = client.get("/api/v1/party", headers=invitee_headers).json()
    assert invitee_state["party"] is None
    assert invitee_state["incoming_invitations"][0]["player"]["name"] == "Mira"
    channel_id = party["channel_id"]

    outsider_chat = client.post(
        "/api/v1/chat/messages",
        headers=outsider_headers,
        json={"channel_id": channel_id, "text": "Should not reach the party."},
    )
    assert outsider_chat.status_code == 403

    accepted = client.patch(
        f"/api/v1/party/invitations/{invitee_state['incoming_invitations'][0]['invite_id']}",
        headers=invitee_headers,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["party"]["party_id"] == party["party_id"]
    assert {member["account_id"] for member in accepted.json()["party"]["members"]} == {
        leader["account_id"],
        invitee["account_id"],
    }

    sent = client.post(
        "/api/v1/chat/messages",
        headers=invitee_headers,
        json={"channel_id": channel_id, "text": "Glad to join."},
    )
    assert sent.status_code == 201
    history = client.get(
        f"/api/v1/chat/{channel_id}/messages",
        headers=leader_headers,
    )
    assert history.status_code == 200
    assert [message["text"] for message in history.json()["messages"]] == ["Glad to join."]

    removed = client.delete(
        f"/api/v1/party/members/{invitee['account_id']}",
        headers=leader_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["party"]["members"][0]["account_id"] == leader["account_id"]
    assert client.get("/api/v1/party", headers=invitee_headers).json()["party"] is None
    kicked_chat = client.post(
        "/api/v1/chat/messages",
        headers=invitee_headers,
        json={"channel_id": channel_id, "text": "I am no longer a member."},
    )
    assert kicked_chat.status_code == 403


def test_party_updates_reach_invited_member_and_leadership_transfers_on_leave(
    client: TestClient,
) -> None:
    leader = register(client, "party-live-leader@example.com", "Mira")
    member = register(client, "party-live-member@example.com", "Sable")
    leader_headers = auth(leader["token"])
    member_headers = auth(member["token"])
    created = client.post("/api/v1/party", headers=leader_headers)
    assert created.status_code == 201
    party_id = created.json()["party"]["party_id"]

    with client.websocket_connect(
        "/api/v1/live",
        headers={"Origin": "http://localhost:5173"},
    ) as websocket:
        websocket.send_json({"type": "auth", "token": member["token"]})
        assert websocket.receive_json() == {"type": "auth.ok"}
        account_channel = f"account:{member['account_id']}"
        websocket.send_json({"type": "subscribe", "channel_id": account_channel})
        assert websocket.receive_json() == {
            "type": "subscribed",
            "channel_id": account_channel,
        }

        invitation = client.post(
            "/api/v1/party/invitations",
            headers=leader_headers,
            json={"recipient_account_id": member["account_id"]},
        )
        assert invitation.status_code == 201
        assert websocket.receive_json()["type"] == "party.updated"
        invitation_id = client.get("/api/v1/party", headers=member_headers).json()[
            "incoming_invitations"
        ][0]["invite_id"]
        accepted = client.patch(
            f"/api/v1/party/invitations/{invitation_id}",
            headers=member_headers,
            json={"status": "accepted"},
        )
        assert accepted.status_code == 200
        assert websocket.receive_json()["type"] == "party.updated"

        left = client.delete("/api/v1/party/membership", headers=leader_headers)
        assert left.status_code == 200
        remaining_party = client.get("/api/v1/party", headers=member_headers).json()["party"]
        assert remaining_party["party_id"] == party_id
        assert remaining_party["leader_account_id"] == member["account_id"]


def test_observe_player_opens_profile_only_for_same_area_player(client: TestClient) -> None:
    watcher = register(client, "observe-watcher@example.com", "Mira")
    observed = register(client, "observe-player@example.com", "Sable")
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == observed["account_id"]))
        character.area_id = "human_city"
        character.inventory = {"iron_sword": 1, "wood": 8}
        character.equipment = {"left_hand": "fist", "right_hand": "iron_sword"}
        db.commit()

    result = client.post(
        "/api/v1/commands",
        headers=auth(watcher["token"]),
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000099", "text": "Observe Sable"},
    ).json()["result"]
    assert result["messages"] == ["You observe Sable."]
    assert result["profile_account_ids"] == [observed["account_id"]]
    assert result["observed_player_equipment"][observed["account_id"]]["right_hand"] == "Iron sword"
    assert "inventory" not in result["observed_player_equipment"][observed["account_id"]]

    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == observed["account_id"]))
        character.area_id = "goblin_town"
        db.commit()
    absent_result = client.post(
        "/api/v1/commands",
        headers=auth(watcher["token"]),
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000098", "text": "Observe Sable"},
    ).json()["result"]
    assert absent_result["messages"] == ["There is no Sable here to observe."]
    assert absent_result["profile_account_ids"] == []
    assert absent_result["observed_player_equipment"] == {}


def test_legacy_fetch_quest_runs_in_builder_and_unlocks_exit_per_character(client: TestClient) -> None:
    player = register(client, "gatekeeper-player@example.com", "Mira")
    other_player = register(client, "gatekeeper-other@example.com", "Rook", "goblin")
    player_headers = auth(player["token"])
    other_headers = auth(other_player["token"])

    for headers, is_goblin in ((player_headers, False), (other_headers, True)):
        if is_goblin:
            town = client.post(
                "/api/v1/commands",
                headers=headers,
                json={"request_id": str(uuid4()), "text": "Travel west"},
            )
            assert town.status_code == 200
        path = client.post(
            "/api/v1/commands",
            headers=headers,
            json={"request_id": str(uuid4()), "text": "Travel west"},
        )
        assert path.status_code == 200
        assert path.json()["result"]["snapshot"]["area"]["id"] == "new_location_2"

    player_world = client.get("/api/v1/world/snapshot", headers=player_headers).json()
    gate = next(exit for exit in player_world["area"]["exit_details"] if exit["direction"] == "south")
    assert gate["accessible"] is False
    assert "Gatekeeper" in gate["reason"]
    assert player_world["area"]["npcs"][0]["quests"][0]["status"] == "available"

    accepted = client.post(
        "/api/v1/quests/mucus_for_the_gatekeeper/accept",
        headers=player_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["snapshot"]["quest_log"][0]["status"] == "active"
    blocked = client.post(
        "/api/v1/commands",
        headers=player_headers,
        json={"request_id": str(uuid4()), "text": "Travel south"},
    ).json()["result"]
    assert blocked["snapshot"]["character"]["area_id"] == "new_location_2"
    assert "10 more Mucus membrane" in blocked["messages"][0]

    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == player["account_id"]))
        character.inventory = {"mucus_membrane": 12}
        db.commit()

    progressed = client.get("/api/v1/world/snapshot", headers=player_headers).json()
    active_quest = progressed["quest_log"][0]
    assert active_quest["can_choose"] is True
    assert active_quest["choices"][0]["text"] == "Return to the quest giver"
    chosen = client.post(
        "/api/v1/quests/mucus_for_the_gatekeeper/choose",
        headers=player_headers,
        json={"step_id": "step_1", "choice_id": "finish"},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["snapshot"]["quest_log"][0]["can_turn_in"] is True

    turned_in = client.post(
        "/api/v1/quests/mucus_for_the_gatekeeper/turn-in",
        headers=player_headers,
    )
    assert turned_in.status_code == 200, turned_in.text
    result = turned_in.json()
    assert result["snapshot"]["character"]["inventory"] == {"mucus_membrane": 2}
    assert result["snapshot"]["character"]["experience"] == 50
    assert result["snapshot"]["quest_log"][0]["status"] == "completed"
    assert next(
        exit for exit in result["snapshot"]["area"]["exit_details"] if exit["direction"] == "south"
    )["accessible"] is True
    assert client.post(
        "/api/v1/quests/mucus_for_the_gatekeeper/turn-in",
        headers=player_headers,
    ).status_code == 409

    other_world = client.get("/api/v1/world/snapshot", headers=other_headers).json()
    other_gate = next(exit for exit in other_world["area"]["exit_details"] if exit["direction"] == "south")
    assert other_gate["accessible"] is False
    assert other_world["quest_log"] == []


def test_multi_step_quest_tracks_talk_visit_kill_choices_and_item_rewards(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoLootRoll:
        @staticmethod
        def randint(_: int, __: int) -> int:
            return 1

        @staticmethod
        def random() -> float:
            return 1.0

    monkeypatch.setattr(game, "combat_rng", NoLootRoll())
    source = content_store.WORLD_CONTENT_PATH.read_bytes()
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", tmp_path / "world_content.json")
    content_store.WORLD_CONTENT_PATH.write_bytes(source)
    monkeypatch.setenv("PLIGHT_CONTENT_EDITOR_EMAIL", "quest-builder@example.com")
    builder = register(client, "quest-builder@example.com", "Builder")
    player = register(client, "branching-quest@example.com", "Mira")
    builder_headers = auth(builder["token"])
    player_headers = auth(player["token"])

    update = client.get("/api/v1/content", headers=builder_headers).json()
    update["content"]["quests"].append({
        "id": "branching_trial",
        "title": "The Path and the Slug",
        "description": "Prove you can follow the trail.",
        "giver_npc_id": "gatekeeper",
        "start_step_id": "speak",
        "steps": [
            {
                "id": "speak",
                "title": "Speak with the keeper",
                "description": "",
                "objectives": [
                    {"id": "talk_keeper", "type": "talk", "target_id": "gatekeeper", "quantity": 1}
                ],
                "choices": [
                    {"id": "continue", "text": "Follow the trail", "next_step_id": "visit"}
                ],
            },
            {
                "id": "visit",
                "title": "Follow the trail",
                "description": "",
                "objectives": [
                    {"id": "visit_plain", "type": "visit", "target_id": "new_location", "quantity": 1}
                ],
                "choices": [
                    {"id": "hunt", "text": "Return and hunt the slug", "next_step_id": "kill"}
                ],
            },
            {
                "id": "kill",
                "title": "Hunt the slug",
                "description": "",
                "objectives": [
                    {"id": "kill_slug", "type": "kill", "target_id": "new_enemy", "quantity": 1}
                ],
                "choices": [
                    {"id": "finish", "text": "Return to the keeper", "next_step_id": None}
                ],
            },
        ],
        "reward_experience": 25,
        "reward_items": [{"item_id": "mucus_membrane", "quantity": 1}],
    })
    enemy = next(entity for entity in update["content"]["entities"] if entity["id"] == "new_enemy")
    enemy["attributes"]["health"] = 1
    enemy["attributes"]["experience"] = 0
    published = client.put("/api/v1/content", headers=builder_headers, json=update)
    assert published.status_code == 200, published.text

    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == player["account_id"]))
        character.area_id = "new_location_2"
        db.commit()
    accepted = client.post(
        "/api/v1/quests/branching_trial/accept",
        headers=player_headers,
    )
    assert accepted.status_code == 200, accepted.text

    talked = client.post(
        "/api/v1/commands",
        headers=player_headers,
        json={"request_id": str(uuid4()), "text": "Talk to Mathew"},
    ).json()["result"]
    assert talked["snapshot"]["quest_log"][0]["can_choose"] is True
    assert talked["snapshot"]["quest_log"][0]["objectives"][0]["current"] == 1

    chose_visit = client.post(
        "/api/v1/quests/branching_trial/choose",
        headers=player_headers,
        json={"step_id": "speak", "choice_id": "continue"},
    )
    assert chose_visit.status_code == 200, chose_visit.text
    traveled = client.post(
        "/api/v1/commands",
        headers=player_headers,
        json={"request_id": str(uuid4()), "text": "Travel west"},
    ).json()["result"]
    assert traveled["snapshot"]["quest_log"][0]["objectives"][0]["current"] == 1
    assert traveled["snapshot"]["quest_log"][0]["can_choose"] is True

    chose_kill = client.post(
        "/api/v1/quests/branching_trial/choose",
        headers=player_headers,
        json={"step_id": "visit", "choice_id": "hunt"},
    )
    assert chose_kill.status_code == 200, chose_kill.text
    returned = client.post(
        "/api/v1/commands",
        headers=player_headers,
        json={"request_id": str(uuid4()), "text": "Travel east"},
    ).json()["result"]
    assert returned["snapshot"]["character"]["area_id"] == "new_location_2"
    defeated = client.post(
        "/api/v1/commands",
        headers=player_headers,
        json={"request_id": str(uuid4()), "text": "Attack the slug"},
    ).json()["result"]
    assert defeated["snapshot"]["quest_log"][0]["objectives"][0]["current"] == 1
    assert defeated["snapshot"]["quest_log"][0]["can_choose"] is True

    finished = client.post(
        "/api/v1/quests/branching_trial/choose",
        headers=player_headers,
        json={"step_id": "kill", "choice_id": "finish"},
    )
    assert finished.status_code == 200, finished.text
    turned_in = client.post(
        "/api/v1/quests/branching_trial/turn-in",
        headers=player_headers,
    )
    assert turned_in.status_code == 200, turned_in.text
    assert turned_in.json()["snapshot"]["character"]["experience"] == 25
    assert turned_in.json()["snapshot"]["character"]["inventory"]["mucus_membrane"] == 1


def test_slug_defeat_awards_configured_experience_and_loot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = register(client, "slug-reward@example.com", "Mira")

    class FixedRewardRoll:
        @staticmethod
        def randint(_: int, __: int) -> int:
            return 1

        @staticmethod
        def random() -> float:
            return 0.0

    monkeypatch.setattr(game, "combat_rng", FixedRewardRoll())
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == player["account_id"]))
        character.area_id = "new_location_2"
        character.combat_stats = {**game.PLAYER_BASE_STATS, "speed": 11}
        character.combat_state = {"target_id": None, "enemy_health": {}}
        db.commit()

    result = None
    with live_as(client, player):
        for _ in range(8):
            request_id = str(uuid4())
            response = client.post(
                "/api/v1/commands",
                headers=auth(player["token"]),
                json={"request_id": request_id, "text": "Attack the slug"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "completed"
            result = response.json()["result"]
            if any("Slug is defeated." in message for message in result["messages"]):
                break

    assert any("Slug is defeated." in message for message in result["messages"])
    assert "You gain 15 experience." in result["messages"]
    assert "Loot: 1 Mucus membrane." in result["messages"]
    assert result["snapshot"]["character"]["experience"] == 15
    assert result["snapshot"]["character"]["inventory"]["mucus_membrane"] == 1


def test_enemy_rewards_report_zero_xp_no_drops_and_authored_quantity_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MaximumQuantityRoll:
        @staticmethod
        def randint(_: int, maximum: int) -> int:
            return maximum

        @staticmethod
        def random() -> float:
            return 0.0

    monkeypatch.setattr(game, "combat_rng", MaximumQuantityRoll())
    character = SimpleNamespace(experience=0, combat_stats={}, inventory={})
    enemy = {
        "attributes": {"experience": 0},
        "loot_table": [
            {
                "item_id": "healing_potion",
                "chance": 1.0,
                "minimum_quantity": 2,
                "maximum_quantity": 5,
            }
        ],
    }
    entities = {"healing_potion": {"name": "Healing potion"}}

    messages = game._reward_enemy_defeat(character, enemy, entities)
    assert messages == ["You gain 0 experience.", "Loot: 5 Healing potions."]
    assert character.inventory == {"healing_potion": 5}

    enemy["loot_table"] = []
    assert game._reward_enemy_defeat(character, enemy, entities) == [
        "You gain 0 experience.",
        "No items dropped.",
    ]


def _write_enemy_world(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    behavior: str | None = "neutral",
    respawn_chance: int | None = 0,
    aggressive_attack_chance: int | None = 0,
    spawn_limit: int | None = 2,
) -> content_store.WorldContent:
    location: dict[str, Any] = {
        "id": "spawn_room",
        "name": "Spawn room",
        "description": "A small testing room.",
        "position": {"x": 50, "y": 50},
        "starting_species": ["human", "goblin"],
        "enemy_ids": ["test_rat"],
    }
    if spawn_limit is not None:
        location["enemy_spawn_limit"] = spawn_limit
    enemy: dict[str, Any] = {
        "id": "test_rat",
        "type": "enemy",
        "name": "Test rat",
        "description": "A test enemy.",
        "attributes": {"health": 12, "attack": 1, "defense": 0, "experience": 0},
    }
    if behavior is not None:
        enemy["behavior"] = behavior
    if respawn_chance is not None:
        enemy["respawn_chance_percent"] = respawn_chance
    if aggressive_attack_chance is not None:
        enemy["aggressive_attack_chance_percent"] = aggressive_attack_chance
    world = content_store.WorldContent.model_validate(
        {"locations": [location], "entities": [enemy]}
    )
    world_path = tmp_path / "world_content.json"
    world_path.write_text(world.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", world_path)
    return world


def test_enemy_spawn_settings_default_to_safe_values(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _write_enemy_world(
        tmp_path,
        monkeypatch,
        behavior=None,
        respawn_chance=None,
        aggressive_attack_chance=None,
        spawn_limit=None,
    )

    assert world.entities[0].behavior == "neutral"
    assert world.entities[0].respawn_chance_percent == 0
    assert world.entities[0].aggressive_attack_chance_percent == 0
    assert world.locations[0].enemy_spawn_limit == 1


def _write_gathering_world(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> content_store.WorldContent:
    world = content_store.WorldContent.model_validate(
        {
            "locations": [
                {
                    "id": "test_room",
                    "name": "Test room",
                    "description": "A test room.",
                    "position": {"x": 50, "y": 50},
                    "starting_species": ["human", "goblin"],
                    "enemy_ids": [],
                    "object_ids": ["test_workbench"],
                    "resource_ids": ["blueberry_bush"],
                },
                {
                    "id": "other_room",
                    "name": "Other room",
                    "description": "Another test room.",
                    "position": {"x": 70, "y": 50},
                    "starting_species": [],
                    "enemy_ids": [],
                },
            ],
            "entities": [
                {
                    "id": "blueberry",
                    "type": "item",
                    "name": "Blueberry",
                    "description": "A ripe berry.",
                },
                {
                    "id": "party_tonic",
                    "type": "item",
                    "name": "Party tonic",
                    "description": "A test potion.",
                    "item_use": {
                        "target_scope": "party",
                        "consume_on_use": True,
                        "effects": [
                            {"type": "heal", "mode": "fixed", "amount": 20},
                            {
                                "type": "stat_buff",
                                "stat": "attack",
                                "mode": "flat",
                                "amount": 2,
                                "duration_seconds": 60,
                            },
                            {
                                "type": "luck",
                                "drop_chance_bonus_percent": 25,
                                "gathering_yield_bonus_percent": 50,
                                "duration_seconds": 60,
                            },
                            {"type": "teleport", "destination_area_id": "other_room"},
                        ],
                    },
                },
                {
                    "id": "raw_material",
                    "type": "resource",
                    "name": "Raw material",
                    "description": "A crafting ingredient.",
                },
                {
                    "id": "crafted_ring",
                    "type": "item",
                    "name": "Crafted ring",
                    "description": "A test recipe output.",
                },
                {
                    "id": "test_hatchet",
                    "type": "weapon",
                    "name": "Test hatchet",
                    "description": "A small gathering tool.",
                    "attributes": {"damage": 1, "harvest_power": 2},
                },
                {
                    "id": "test_buckler",
                    "type": "shield",
                    "name": "Test buckler",
                    "description": "A small shield.",
                    "attributes": {"defense": 5},
                },
                {
                    "id": "test_workbench",
                    "type": "furniture",
                    "name": "Test workbench",
                    "description": "A crafting station.",
                },
                {
                    "id": "blueberry_bush",
                    "type": "resource",
                    "name": "Blueberry bush",
                    "description": "A bush full of berries.",
                    "gathering": {
                        "skill": "foraging",
                        "skill_level": 1,
                        "health": 1,
                        "tool_stat": "harvest_power",
                        "minimum_tool_power": 2,
                        "respawn_seconds": 60,
                        "loot_table": [
                            {
                                "item_id": "blueberry",
                                "chance": 1,
                                "minimum_quantity": 1,
                                "maximum_quantity": 1,
                            }
                        ],
                    },
                },
            ],
            "recipes": [
                {
                    "id": "test_ring_recipe",
                    "name": "Crafted ring",
                    "output_item_id": "crafted_ring",
                    "output_quantity": 2,
                    "ingredients": [{"item_id": "raw_material", "quantity": 2}],
                    "station_id": "test_workbench",
                    "skill": "woodworking",
                    "skill_level": 1,
                }
            ],
        }
    )
    world_path = tmp_path / "world_content.json"
    world_path.write_text(world.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", world_path)
    return world


def test_party_item_effects_heal_buff_boost_loot_and_teleport(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _write_gathering_world(tmp_path, monkeypatch)
    content = world.model_dump(mode="json")
    entities = {entity["id"]: entity for entity in content["entities"]}
    areas = {location["id"]: location for location in content["locations"]}
    actor = SimpleNamespace(
        account_id="actor",
        name="Ari",
        area_id="test_room",
        inventory={"party_tonic": 1},
        combat_stats={"health": 50, "max_health": 100, "attack": 3, "defense": 1, "speed": 10},
        equipment={"left_hand": "", "right_hand": "fist"},
        active_effects=[],
    )
    party_member = SimpleNamespace(
        account_id="party-member",
        name="Bea",
        area_id="test_room",
        inventory={},
        combat_stats={"health": 60, "max_health": 100, "attack": 4, "defense": 1, "speed": 10},
        equipment={"left_hand": "", "right_hand": "fist"},
        active_effects=[],
    )

    messages, recipient_messages = game._use_item(
        actor,
        "party tonic",
        content,
        areas,
        entities,
        [actor, party_member],
        now=100,
    )

    assert actor.inventory == {}
    assert actor.combat_stats["health"] == 70
    assert party_member.combat_stats["health"] == 80
    assert actor.area_id == party_member.area_id == "other_room"
    assert game._effective_stats(actor, entities, now=101)["attack"] == 5
    assert game._luck_bonuses(actor, now=101) == (25, 50)
    assert "party-member" in recipient_messages
    assert any("reach you and 1 online party member here" in message for message in messages)


def test_item_gather_and_craft_actions_resolve_through_commands(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_gathering_world(tmp_path, monkeypatch)
    player = register(client, "item-gather-craft@example.com", "Ari")
    headers = auth(player["token"])
    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        character.area_id = "test_room"
        character.inventory = {
            "party_tonic": 1,
            "raw_material": 2,
            "test_hatchet": 1,
        }
        character.equipment = {"left_hand": "", "right_hand": "test_hatchet"}
        character.combat_stats = {
            **game.PLAYER_BASE_STATS,
            "health": 50,
        }
        db.commit()

    def command(text: str) -> dict[str, Any]:
        response = client.post(
            "/api/v1/commands",
            headers=headers,
            json={"request_id": str(uuid4()), "text": text},
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]

    used = command("use party tonic")
    assert used["snapshot"]["character"]["area_id"] == "other_room"
    assert used["snapshot"]["character"]["stats"]["health"] == 70
    assert any("You use Party tonic" in message for message in used["messages"])

    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        character.area_id = "test_room"
        character.inventory = {"raw_material": 2, "test_hatchet": 1}
        db.commit()

    crafted = command("craft a crafted ring")
    assert crafted["snapshot"]["character"]["inventory_items"]
    assert any("You craft 2 Crafted rings." in message for message in crafted["messages"])

    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        character.inventory = {"test_hatchet": 1}
        db.commit()
    started = command("gather the blueberry bush")
    assert started["snapshot"]["character"]["gathering"]["resource_id"] == "blueberry_bush"
    cancelled = command("stop")
    assert cancelled["snapshot"]["character"]["gathering"] is None
    assert cancelled["messages"] == [
        "You stop gathering Blueberry bush. Nothing is collected."
    ]


def test_party_splash_reaches_only_online_party_members_in_the_same_location(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_gathering_world(tmp_path, monkeypatch)
    leader = register(client, "party-splash-leader@example.com", "Ari")
    member = register(client, "party-splash-member@example.com", "Bea")
    outsider = register(client, "party-splash-outsider@example.com", "Cy")
    leader_headers = auth(leader["token"])
    member_headers = auth(member["token"])
    outsider_headers = auth(outsider["token"])
    created = client.post("/api/v1/party", headers=leader_headers)
    assert created.status_code == 201
    invited = client.post(
        "/api/v1/party/invitations",
        headers=leader_headers,
        json={"recipient_account_id": member["account_id"]},
    )
    assert invited.status_code == 201
    invite_id = client.get("/api/v1/party", headers=member_headers).json()[
        "incoming_invitations"
    ][0]["invite_id"]
    accepted = client.patch(
        f"/api/v1/party/invitations/{invite_id}",
        headers=member_headers,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200
    with api.SessionLocal() as db:
        for account_id in (leader["account_id"], member["account_id"], outsider["account_id"]):
            character = db.scalar(
                select(Character).where(Character.account_id == account_id)
            )
            character.area_id = "test_room"
            character.combat_stats = {
                **game.PLAYER_BASE_STATS,
                "health": 50,
            }
        leader_character = db.scalar(
            select(Character).where(Character.account_id == leader["account_id"])
        )
        leader_character.inventory = {"party_tonic": 1}
        db.commit()

    with live_as(client, leader):
        with live_as(client, member) as member_socket:
            with live_as(client, outsider):
                response = client.post(
                    "/api/v1/commands",
                    headers=leader_headers,
                    json={"request_id": str(uuid4()), "text": "use party tonic"},
                )
                assert response.status_code == 200, response.text
                event = member_socket.receive_json()
                assert event["type"] == "world.updated"
                assert any(
                    "receive the effects of Ari's Party tonic" in message
                    for message in event["payload"]["messages"]
                )

    with api.SessionLocal() as db:
        leader_character = db.scalar(
            select(Character).where(Character.account_id == leader["account_id"])
        )
        member_character = db.scalar(
            select(Character).where(Character.account_id == member["account_id"])
        )
        outsider_character = db.scalar(
            select(Character).where(Character.account_id == outsider["account_id"])
        )
        assert leader_character.combat_stats["health"] == 70
        assert member_character.combat_stats["health"] == 70
        assert leader_character.area_id == member_character.area_id == "other_room"
        assert outsider_character.combat_stats["health"] == 50
        assert outsider_character.area_id == "test_room"


def test_gathering_uses_tool_duration_and_per_player_respawn(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _write_gathering_world(tmp_path, monkeypatch)
    content = world.model_dump(mode="json")
    areas = {location["id"]: location for location in content["locations"]}
    entities = {entity["id"]: entity for entity in content["entities"]}
    character = SimpleNamespace(
        area_id="test_room",
        inventory={},
        equipment={"left_hand": "", "right_hand": "test_hatchet"},
        skills={"foraging": 1},
        skill_experience={},
        resource_state={},
        gathering_state=None,
        active_effects=[],
        quest_state={},
        experience=0,
        combat_stats={"health": 100, "max_health": 100, "attack": 3, "defense": 1, "speed": 10},
    )

    started = game._start_gathering(
        character,
        {"resource": "blueberry bush"},
        areas,
        entities,
        now=100,
    )
    assert character.gathering_state["duration_seconds"] == 20
    assert "20 seconds" in started[0]
    assert game._cancel_gathering(character).startswith("You stop gathering")
    assert character.resource_state == {}

    game._start_gathering(
        character,
        {"resource": "blueberry bush"},
        areas,
        entities,
        now=200,
    )
    character.gathering_state["completes_at"] = 200
    current_time = time()
    game._apply_timed_effect(
        character,
        {
            "type": "luck",
            "drop_chance_bonus_percent": 50,
            "gathering_yield_bonus_percent": 50,
            "duration_seconds": 60,
        },
        now=current_time,
    )

    class FixedRoll:
        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

        @staticmethod
        def random() -> float:
            return 0.8

    monkeypatch.setattr(game, "combat_rng", FixedRoll())
    messages = game._complete_gathering(character, content, now=current_time + 1)
    assert character.inventory == {"blueberry": 2}
    assert character.resource_state["test_room:blueberry_bush"]["health"] == 0
    assert character.skills["foraging"] == 1
    assert character.skill_experience["foraging"] == 10
    assert any("You gather 2 Blueberries." in message for message in messages)
    rewards = game._reward_enemy_defeat(
        character,
        {
            "id": "test_rat",
            "type": "enemy",
            "name": "Test rat",
            "attributes": {"health": 1, "experience": 0},
            "loot_table": [
                {
                    "item_id": "blueberry",
                    "chance": 0.6,
                    "minimum_quantity": 1,
                    "maximum_quantity": 1,
                }
            ],
        },
        entities,
        content,
    )
    assert character.inventory == {"blueberry": 3}
    assert any("Loot: 1 Blueberry." in message for message in rewards)

    other_character = SimpleNamespace(
        area_id="test_room",
        inventory={},
        equipment={"left_hand": "", "right_hand": "test_hatchet"},
        skills={"foraging": 1},
        skill_experience={},
        resource_state={},
        gathering_state=None,
        active_effects=[],
    )
    assert game._resource_status(
        other_character, "test_room", entities["blueberry_bush"], now=current_time + 2
    )["available"]
    assert not game._resource_status(
        character, "test_room", entities["blueberry_bush"], now=current_time + 2
    )["available"]


def test_gathering_tick_completes_and_disconnect_cancels(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _write_gathering_world(tmp_path, monkeypatch)
    player = register(client, "gathering-tick@example.com", "Ari")
    current_time = time()
    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        character.area_id = "test_room"
        character.gathering_state = {
            "resource_id": "blueberry_bush",
            "resource_name": "Blueberry bush",
            "location_id": "test_room",
            "skill": "foraging",
            "duration_seconds": 1,
            "started_at": current_time - 2,
            "completes_at": current_time - 1,
        }
        character.inventory = {}
        db.commit()

    monkeypatch.setattr(
        api.live_hub,
        "active_account_ids",
        lambda: {player["account_id"]},
    )

    class FixedRoll:
        @staticmethod
        def random() -> float:
            return 0

        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

    monkeypatch.setattr(game, "combat_rng", FixedRoll())
    api._run_gathering_completion_tick()
    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        assert character.gathering_state is None
        assert character.inventory == {"blueberry": 1}
        character.gathering_state = {
            "resource_id": "blueberry_bush",
            "resource_name": "Blueberry bush",
            "location_id": "test_room",
            "skill": "foraging",
            "duration_seconds": 10,
            "started_at": current_time,
            "completes_at": current_time + 10,
        }
        character.resource_state = {}
        db.commit()

    monkeypatch.setattr(api.live_hub, "active_account_ids", lambda: set())
    api._cleanup_party_after_disconnect(player["account_id"])
    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        assert character.gathering_state is None
        assert character.resource_state == {}


def test_recipe_crafting_consumes_ingredients_and_awards_skill_xp(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _write_gathering_world(tmp_path, monkeypatch)
    content = world.model_dump(mode="json")
    areas = {location["id"]: location for location in content["locations"]}
    entities = {entity["id"]: entity for entity in content["entities"]}
    character = SimpleNamespace(
        area_id="test_room",
        inventory={"raw_material": 2},
        skills={"woodworking": 1},
        skill_experience={},
        quest_state={},
    )

    messages = game._craft(
        character,
        {"product": "crafted ring"},
        content,
        areas,
        entities,
    )

    assert character.inventory == {"crafted_ring": 2}
    assert character.skill_experience["woodworking"] == 10
    assert messages[0] == "You craft 2 Crafted rings."


def test_shield_equipment_and_timed_absorption_affect_enemy_damage(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _write_gathering_world(tmp_path, monkeypatch)
    entities = {entity.id: entity.model_dump(mode="json") for entity in world.entities}
    character = SimpleNamespace(
        area_id="test_room",
        combat_stats={"health": 100, "max_health": 100, "attack": 3, "defense": 1, "speed": 10},
        equipment={"left_hand": "test_buckler", "right_hand": "fist"},
        active_effects=[],
        combat_state={},
        species="human",
        respawn_area_id=None,
        gathering_state=None,
    )
    now = time()
    game._apply_timed_effect(
        character,
        {"type": "shield", "mode": "damage_reduction", "amount": 2, "duration_seconds": 60},
        now=now,
    )
    game._apply_timed_effect(
        character,
        {"type": "shield", "mode": "damage_pool", "amount": 2, "duration_seconds": 60},
        now=now,
    )

    class FixedRoll:
        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

    monkeypatch.setattr(game, "combat_rng", FixedRoll())
    messages = game.enemy_strike(
        character,
        {"name": "Test rat", "attributes": {"attack": 10}, "attack_die_sides": 2},
        {"test_room": {"name": "Test room"}},
        entities=entities,
    )

    assert game._effective_stats(character, entities, now=now + 1)["defense"] == 6
    assert character.combat_stats["health"] == 99
    assert any("absorbs 2 damage" in message for message in messages)


def test_temporary_health_is_extra_hp_and_absorbs_damage_before_regular_health(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _write_gathering_world(tmp_path, monkeypatch)
    entities = {entity.id: entity.model_dump(mode="json") for entity in world.entities}
    character = SimpleNamespace(
        account_id=1,
        id=1,
        name="Shield Tester",
        species="human",
        area_id="test_room",
        appearance={},
        inventory={},
        combat_stats={"health": 100, "max_health": 100, "attack": 3, "defense": 1, "speed": 10},
        equipment={"left_hand": "", "right_hand": "fist"},
        active_effects=[],
        combat_state={},
        skills={},
        skill_experience={},
        experience=0,
        quest_state={},
        gathering_state=None,
        respawn_area_id=None,
    )
    game._apply_timed_effect(
        character,
        {"type": "shield", "mode": "temporary_health", "amount": 5, "duration_seconds": 60},
    )

    before_strike = game._snapshot(character, world.model_dump(mode="json"))
    assert before_strike["character"]["stats"]["health"] == 105
    assert before_strike["character"]["stats"]["max_health"] == 100
    assert before_strike["character"]["active_effects"][0]["remaining"] == 5

    class FixedRoll:
        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

    monkeypatch.setattr(game, "combat_rng", FixedRoll())
    messages = game.enemy_strike(
        character,
        {"name": "Test rat", "attributes": {"attack": 1}, "attack_die_sides": 2},
        {"test_room": {"name": "Test room"}},
        entities=entities,
    )

    after_strike = game._snapshot(character, world.model_dump(mode="json"))
    assert character.combat_stats["health"] == 100
    assert after_strike["character"]["stats"]["health"] == 104
    assert character.active_effects[0]["remaining"] == 4
    assert any("temporary health absorbs 1 damage" in message for message in messages)


def test_enemy_spawn_tick_obeys_scoped_location_cap_and_allows_duplicates(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(tmp_path, monkeypatch, respawn_chance=100, spawn_limit=2)
    player = register(client, "spawn-test@example.com", "Spawn Tester")

    class AlwaysSpawn:
        @staticmethod
        def random() -> float:
            return 0.0

    monkeypatch.setattr(api, "_enemy_spawn_rng", AlwaysSpawn())
    scope = ("solo", player["account_id"])
    api._run_enemy_spawn_tick([scope])
    api._run_enemy_spawn_tick([scope])

    with api.SessionLocal() as db:
        rows = db.scalars(
            select(EnemySpawn).where(
                EnemySpawn.location_id == "spawn_room",
                EnemySpawn.scope_type == scope[0],
                EnemySpawn.scope_id == scope[1],
                EnemySpawn.is_alive.is_(True),
            )
        ).all()
        assert len(rows) == 2
        assert len({row.id for row in rows}) == 2
        assert sum(row.is_initial for row in rows) == 1
        duplicate = next(row for row in rows if not row.is_initial)
        duplicate.is_alive = False
        db.commit()

    api._run_enemy_spawn_tick([scope])

    with api.SessionLocal() as db:
        living = db.scalars(
            select(EnemySpawn).where(
                EnemySpawn.location_id == "spawn_room",
                EnemySpawn.scope_type == scope[0],
                EnemySpawn.scope_id == scope[1],
                EnemySpawn.is_alive.is_(True),
            )
        ).all()
        assert len(living) == 2
        assert len({row.enemy_id for row in living}) == 1


def test_enemy_health_is_scoped_per_solo_character(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(tmp_path, monkeypatch, behavior="passive", respawn_chance=0)
    first = register(client, "shared-first@example.com", "First")
    second = register(client, "shared-second@example.com", "Second", "goblin")
    first_headers = auth(first["token"])

    initial = client.get("/api/v1/world/snapshot", headers=first_headers).json()
    assert initial["area"]["enemies"][0]["health"] == 12
    attacked = client.post(
        "/api/v1/commands",
        headers=first_headers,
        json={"request_id": str(uuid4()), "text": "Attack the test rat"},
    )
    assert attacked.status_code == 200
    assert attacked.json()["status"] == "completed"

    second_snapshot = client.get(
        "/api/v1/world/snapshot",
        headers=auth(second["token"]),
    ).json()
    assert second_snapshot["area"]["enemies"][0]["health"] == 12


def test_party_members_share_encounter_enemy_population(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(tmp_path, monkeypatch, behavior="neutral", respawn_chance=0)
    leader = register(client, "party-spawn-leader@example.com", "Leader")
    member = register(client, "party-spawn-member@example.com", "Member", "goblin")
    solo = register(client, "party-spawn-solo@example.com", "Solo")
    leader_headers = auth(leader["token"])
    member_headers = auth(member["token"])

    created = client.post("/api/v1/party", headers=leader_headers)
    invite = client.post(
        "/api/v1/party/invitations",
        headers=leader_headers,
        json={"recipient_account_id": member["account_id"]},
    )
    assert created.status_code == 201
    assert invite.status_code == 201
    invite_id = client.get("/api/v1/party", headers=member_headers).json()[
        "incoming_invitations"
    ][0]["invite_id"]
    accepted = client.patch(
        f"/api/v1/party/invitations/{invite_id}",
        headers=member_headers,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200

    class MinimumRoll:
        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

    monkeypatch.setattr(game, "combat_rng", MinimumRoll())

    leader_snapshot = client.get(
        "/api/v1/world/snapshot",
        headers=leader_headers,
    ).json()
    member_snapshot = client.get(
        "/api/v1/world/snapshot",
        headers=member_headers,
    ).json()
    solo_snapshot = client.get(
        "/api/v1/world/snapshot",
        headers=auth(solo["token"]),
    ).json()
    assert leader_snapshot["area"]["enemies"][0]["id"] == member_snapshot["area"]["enemies"][0]["id"]
    assert leader_snapshot["area"]["enemies"][0]["id"] != solo_snapshot["area"]["enemies"][0]["id"]

    with live_as(client, leader), live_as(client, member):
        command = client.post(
            "/api/v1/commands",
            headers=leader_headers,
            json={"request_id": str(uuid4()), "text": "Attack the test rat"},
        )
        assert command.status_code == 200
        assert command.json()["status"] == "completed"
        leader_after = client.get(
            "/api/v1/world/snapshot",
            headers=leader_headers,
        ).json()
        member_after = client.get(
            "/api/v1/world/snapshot",
            headers=member_headers,
        ).json()
        solo_after = client.get(
            "/api/v1/world/snapshot",
            headers=auth(solo["token"]),
        ).json()
        assert leader_after["area"]["enemies"][0]["health"] == 9
        assert member_after["area"]["enemies"][0]["health"] == 9
        assert solo_after["area"]["enemies"][0]["health"] == 12
        assert leader_after["character"]["stats"]["health"] == 99
        assert member_after["character"]["stats"]["health"] == 100


def test_combat_sentence_resolves_each_action_immediately(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(tmp_path, monkeypatch, behavior="passive", respawn_chance=0)
    player = register(client, "combat-queue@example.com", "Queue")
    headers = auth(player["token"])

    with live_as(client, player):
        request_id = str(uuid4())
        submitted = client.post(
            "/api/v1/commands",
            headers=headers,
            json={
                "request_id": request_id,
                "text": (
                    "Attack the test rat and attack the test rat "
                    "and attack the test rat"
                ),
            },
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "completed"
        messages = submitted.json()["result"]["messages"]
        assert not any("queued" in message.casefold() for message in messages)
        assert submitted.json()["result"]["action_events"] == ["attack", "attack", "attack"]
        assert sum("You strike Test rat" in message for message in messages) == 3
        assert submitted.json()["result"]["snapshot"]["area"]["enemies"][0]["health"] == 3
        with api.SessionLocal() as db:
            command = db.scalar(
                select(Command).where(Command.request_id == request_id)
            )
            assert command is not None
            assert command.status == "completed"
            actions = db.scalars(
                select(CombatAction).where(CombatAction.command_id == command.id)
            ).all()
            assert len(actions) == 3
            assert all(action.status == "resolved" for action in actions)
            assert db.scalar(
                select(CombatAction.id).where(
                    CombatAction.account_id == player["account_id"],
                    CombatAction.status == "queued",
                )
            ) is None


def test_party_reinforcement_rolls_and_only_the_actor_takes_enemy_response(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(tmp_path, monkeypatch, behavior="neutral", respawn_chance=0)
    leader = register(client, "reinforcement-leader@example.com", "Leader")
    member = register(client, "reinforcement-member@example.com", "Member", "goblin")
    leader_headers = auth(leader["token"])
    member_headers = auth(member["token"])
    created = client.post("/api/v1/party", headers=leader_headers)
    invite = client.post(
        "/api/v1/party/invitations",
        headers=leader_headers,
        json={"recipient_account_id": member["account_id"]},
    )
    assert created.status_code == 201
    invitation_id = client.get("/api/v1/party", headers=member_headers).json()[
        "incoming_invitations"
    ][0]["invite_id"]
    assert invite.status_code == 201
    accepted = client.patch(
        f"/api/v1/party/invitations/{invitation_id}",
        headers=member_headers,
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200
    party_id = accepted.json()["party"]["party_id"]
    client.get("/api/v1/world/snapshot", headers=leader_headers)

    with api.SessionLocal() as db:
        db.add(
            EnemySpawn(
                location_id="spawn_room",
                enemy_id="test_rat",
                scope_type="party",
                scope_id=party_id,
                health=12,
            )
        )
        db.commit()

    class ReinforcementRoll:
        @staticmethod
        def random() -> float:
            return 0.12

    class MinimumCombatRoll:
        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

    monkeypatch.setattr(api, "_enemy_spawn_rng", ReinforcementRoll())
    monkeypatch.setattr(game, "combat_rng", MinimumCombatRoll())
    with live_as(client, leader), live_as(client, member):
        submitted = client.post(
            "/api/v1/commands",
            headers=leader_headers,
            json={"request_id": str(uuid4()), "text": "Attack the test rat"},
        )
        assert submitted.status_code == 200
        first_round = submitted.json()["result"]
        assert any("joins the fight" in message for message in first_round["messages"])
        with api.SessionLocal() as db:
            leader_character = db.scalar(
                select(Character).where(Character.account_id == leader["account_id"])
            )
            member_character = db.scalar(
                select(Character).where(Character.account_id == member["account_id"])
            )
            assert leader_character.combat_stats["health"] == 99
            assert member_character.combat_stats["health"] == 100

        member_turn = client.post(
            "/api/v1/commands",
            headers=member_headers,
            json={"request_id": str(uuid4()), "text": "Attack the test rat"},
        )
        assert member_turn.status_code == 200
        with api.SessionLocal() as db:
            leader_character = db.scalar(
                select(Character).where(Character.account_id == leader["account_id"])
            )
            member_character = db.scalar(
                select(Character).where(Character.account_id == member["account_id"])
            )
            assert leader_character.combat_stats["health"] == 99
            assert member_character.combat_stats["health"] == 98


def test_travel_inside_combat_uses_a_turn_and_ends_solo_encounter(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _write_enemy_world(tmp_path, monkeypatch, behavior="passive", respawn_chance=0)
    world_data = world.model_dump(mode="json")
    world_data["locations"][0]["exits"] = {"east": "other_room"}
    world_data["locations"].append(
        {
            **world_data["locations"][0],
            "id": "other_room",
            "name": "Other room",
            "position": {"x": 55, "y": 50},
            "starting_species": [],
            "enemy_ids": [],
            "exits": {},
            "exit_requirements": {},
        }
    )
    updated_world = content_store.WorldContent.model_validate(world_data)
    content_store.WORLD_CONTENT_PATH.write_text(
        updated_world.model_dump_json(),
        encoding="utf-8",
    )
    player = register(client, "combat-travel@example.com", "Traveler")
    headers = auth(player["token"])

    with live_as(client, player):
        attack_id = str(uuid4())
        travel_id = str(uuid4())
        attack = client.post(
            "/api/v1/commands",
            headers=headers,
            json={"request_id": attack_id, "text": "Attack the test rat"},
        )
        travel = client.post(
            "/api/v1/commands",
            headers=headers,
            json={"request_id": travel_id, "text": "Travel east"},
        )
        assert attack.status_code == 200
        assert travel.status_code == 200
        assert attack.json()["status"] == "completed"
        finished = travel.json()
        assert finished["status"] == "completed"
        assert finished["result"]["snapshot"]["character"]["area_id"] == "other_room"
        assert any("You travel east to Other room." in message for message in finished["result"]["messages"])
        with api.SessionLocal() as db:
            assert db.scalar(select(CombatEncounter.id)) is None


def test_action_after_travel_uses_destination_enemy_state(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _write_enemy_world(tmp_path, monkeypatch, behavior="passive", respawn_chance=0)
    world_data = world.model_dump(mode="json")
    world_data["locations"][0]["exits"] = {"east": "other_room"}
    world_data["locations"].append(
        {
            **world_data["locations"][0],
            "id": "other_room",
            "name": "Other room",
            "position": {"x": 55, "y": 50},
            "starting_species": [],
            "exits": {},
            "exit_requirements": {},
        }
    )
    updated_world = content_store.WorldContent.model_validate(world_data)
    content_store.WORLD_CONTENT_PATH.write_text(
        updated_world.model_dump_json(),
        encoding="utf-8",
    )
    player = register(client, "travel-attack@example.com", "Traveler")

    with live_as(client, player):
        submitted = client.post(
            "/api/v1/commands",
            headers=auth(player["token"]),
            json={
                "request_id": str(uuid4()),
                "text": "Travel east and attack the test rat",
            },
        )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "completed"
    result = submitted.json()["result"]
    assert "You travel east to Other room." in result["messages"]
    assert any("You strike Test rat" in message for message in result["messages"])
    assert result["snapshot"]["character"]["area_id"] == "other_room"
    assert result["snapshot"]["area"]["enemies"][0]["health"] == 9


def test_solo_disconnect_does_not_delay_or_rewrite_completed_actions(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(tmp_path, monkeypatch, behavior="passive", respawn_chance=0)
    player = register(client, "combat-disconnect@example.com", "Disconnect")
    headers = auth(player["token"])
    request_id = str(uuid4())

    with live_as(client, player):
        submitted = client.post(
            "/api/v1/commands",
            headers=headers,
            json={
                "request_id": request_id,
                "text": "Attack the test rat and attack the test rat",
            },
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "completed"

    command_url = f"/api/v1/commands/{request_id}"
    completed = client.get(command_url, headers=headers).json()
    assert completed["status"] == "completed"
    assert not any("cancelled" in message.casefold() for message in completed["result"]["messages"])
    assert completed["result"]["snapshot"]["area"]["enemies"][0]["health"] == 6
    deadline = monotonic() + 2
    with api.SessionLocal() as db:
        encounter_id = db.scalar(
            select(CombatEncounter.id).where(
                CombatEncounter.solo_account_id == player["account_id"]
            )
        )
    while encounter_id is not None and monotonic() < deadline:
        sleep(0.01)
        with api.SessionLocal() as db:
            encounter_id = db.scalar(
                select(CombatEncounter.id).where(
                    CombatEncounter.solo_account_id == player["account_id"]
                )
            )
    assert encounter_id is None
    with api.SessionLocal() as db:
        assert db.scalar(
            select(CombatAction.id).where(
                CombatAction.account_id == player["account_id"],
                CombatAction.status == "queued",
            )
        ) is None


def test_party_removal_and_disband_preserve_completed_actions(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(tmp_path, monkeypatch, behavior="passive", respawn_chance=0)
    leader = register(client, "combat-party-leader@example.com", "Leader")
    member = register(client, "combat-party-member@example.com", "Member", "goblin")
    leader_headers = auth(leader["token"])
    member_headers = auth(member["token"])
    assert client.post("/api/v1/party", headers=leader_headers).status_code == 201
    assert client.post(
        "/api/v1/party/invitations",
        headers=leader_headers,
        json={"recipient_account_id": member["account_id"]},
    ).status_code == 201
    invite_id = client.get("/api/v1/party", headers=member_headers).json()[
        "incoming_invitations"
    ][0]["invite_id"]
    assert client.patch(
        f"/api/v1/party/invitations/{invite_id}",
        headers=member_headers,
        json={"status": "accepted"},
    ).status_code == 200

    member_request_id = str(uuid4())
    with live_as(client, member):
        submitted = client.post(
            "/api/v1/commands",
            headers=member_headers,
            json={
                "request_id": member_request_id,
                "text": "Attack the test rat",
            },
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "completed"
        removed = client.delete(
            f"/api/v1/party/members/{member['account_id']}",
            headers=leader_headers,
        )
        assert removed.status_code == 200

    member_command = client.get(
        f"/api/v1/commands/{member_request_id}",
        headers=member_headers,
    ).json()
    assert member_command["status"] == "completed"
    assert not any("cancelled" in message.casefold() for message in member_command["result"]["messages"])

    leader_request_id = str(uuid4())
    with live_as(client, leader):
        submitted = client.post(
            "/api/v1/commands",
            headers=leader_headers,
            json={
                "request_id": leader_request_id,
                "text": "Attack the test rat",
            },
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "completed"
        disbanded = client.delete("/api/v1/party", headers=leader_headers)
        assert disbanded.status_code == 200

    leader_command = client.get(
        f"/api/v1/commands/{leader_request_id}",
        headers=leader_headers,
    ).json()
    assert leader_command["status"] == "completed"
    assert not any("queued" in message.casefold() for message in leader_command["result"]["messages"])
    with api.SessionLocal() as db:
        assert db.scalar(select(CombatEncounter.id)) is None


@pytest.mark.parametrize(
    ("behavior", "expected_health", "expected_message"),
    [
        ("passive", 100, "Test rat does not fight back."),
        ("neutral", 99, "hits you for 1 damage"),
    ],
)
def test_enemy_behavior_controls_retaliation(
    behavior: str,
    expected_health: int,
    expected_message: str,
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(tmp_path, monkeypatch, behavior=behavior, respawn_chance=0)
    player = register(client, f"{behavior}@example.com", behavior.title())

    class MinimumRoll:
        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

        @staticmethod
        def random() -> float:
            return 1.0

    monkeypatch.setattr(game, "combat_rng", MinimumRoll())
    with live_as(client, player):
        submitted = client.post(
            "/api/v1/commands",
            headers=auth(player["token"]),
            json={"request_id": "adf0f265-edca-449a-8ce5-100000000123", "text": "Attack the test rat"},
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "completed"
        result = submitted.json()["result"]

    assert any(expected_message in message for message in result["messages"])
    assert result["snapshot"]["character"]["stats"]["health"] == expected_health


def test_aggressive_enemy_attacks_connected_players_every_15_seconds_at_full_chance(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(
        tmp_path,
        monkeypatch,
        behavior="aggressive",
        respawn_chance=0,
        aggressive_attack_chance=100,
    )
    player = register(client, "aggressive@example.com", "Rill")
    assert client.get(
        "/api/v1/world/snapshot",
        headers=auth(player["token"]),
    ).status_code == 200

    class MinimumRoll:
        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

    monkeypatch.setattr(game, "combat_rng", MinimumRoll())
    headers = {"Origin": "http://localhost:5173"}
    with client.websocket_connect("/api/v1/live", headers=headers) as websocket:
        websocket.send_json({"type": "auth", "token": player["token"]})
        assert websocket.receive_json() == {"type": "auth.ok"}
        api._run_enemy_aggression_tick()
        with api.SessionLocal() as db:
            character = db.scalar(
                select(Character).where(Character.account_id == player["account_id"])
            )
            assert character.combat_stats["health"] == 100
            attack_times = dict(character.combat_state["enemy_aggression_check_at"])
            character.combat_state = {
                **character.combat_state,
                "enemy_aggression_check_at": {
                    spawn_id: "2000-01-01T00:00:00"
                    for spawn_id in attack_times
                },
            }
            db.commit()

        api._run_enemy_aggression_tick()
        first_update = websocket.receive_json()
        assert first_update["type"] == "world.updated"
        assert any("hits you for 1 damage" in message for message in first_update["payload"]["messages"])

        api._run_enemy_aggression_tick()

    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        assert character.combat_stats["health"] == 99


def test_aggressive_enemy_does_not_attack_with_default_zero_chance(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(
        tmp_path,
        monkeypatch,
        behavior="aggressive",
        respawn_chance=0,
    )
    player = register(client, "aggressive-zero-chance@example.com", "Rill")
    assert client.get(
        "/api/v1/world/snapshot",
        headers=auth(player["token"]),
    ).status_code == 200

    class NoChanceRoll:
        @staticmethod
        def random() -> float:
            raise AssertionError("A zero hit chance must not roll.")

    monkeypatch.setattr(api, "_enemy_aggression_rng", NoChanceRoll())
    with client.websocket_connect(
        "/api/v1/live",
        headers={"Origin": "http://localhost:5173"},
    ) as websocket:
        websocket.send_json({"type": "auth", "token": player["token"]})
        assert websocket.receive_json() == {"type": "auth.ok"}
        api._run_enemy_aggression_tick()

    with api.SessionLocal() as db:
        character = db.scalar(
            select(Character).where(Character.account_id == player["account_id"])
        )
        assert character.combat_stats["health"] == 100


def test_aggressive_attack_chance_rolls_independently_per_player_every_15_seconds(
    client: TestClient,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_enemy_world(
        tmp_path,
        monkeypatch,
        behavior="aggressive",
        respawn_chance=0,
        aggressive_attack_chance=50,
    )
    players = [
        register(client, "aggressive-chance-one@example.com", "Pine"),
        register(client, "aggressive-chance-two@example.com", "Fern"),
    ]
    for player in players:
        assert client.get(
            "/api/v1/world/snapshot",
            headers=auth(player["token"]),
        ).status_code == 200

    class MinimumRoll:
        @staticmethod
        def randint(minimum: int, _: int) -> int:
            return minimum

    class SequenceRoll:
        def __init__(self) -> None:
            self.values = iter((0.99, 0.0, 0.0, 0.99))
            self.calls = 0

        def random(self) -> float:
            self.calls += 1
            return next(self.values)

    chance_rng = SequenceRoll()
    monkeypatch.setattr(game, "combat_rng", MinimumRoll())
    monkeypatch.setattr(api, "_enemy_aggression_rng", chance_rng)

    def make_checks_due(account_id: str) -> None:
        with api.SessionLocal() as db:
            character = db.scalar(
                select(Character).where(Character.account_id == account_id)
            )
            checks = dict(character.combat_state["enemy_aggression_check_at"])
            character.combat_state = {
                **character.combat_state,
                "enemy_aggression_check_at": {
                    spawn_id: "2000-01-01T00:00:00"
                    for spawn_id in checks
                },
            }
            db.commit()

    ordered_accounts = sorted(player["account_id"] for player in players)
    with client.websocket_connect(
        "/api/v1/live",
        headers={"Origin": "http://localhost:5173"},
    ) as first_socket:
        first_socket.send_json({"type": "auth", "token": players[0]["token"]})
        assert first_socket.receive_json() == {"type": "auth.ok"}
        with client.websocket_connect(
            "/api/v1/live",
            headers={"Origin": "http://localhost:5173"},
        ) as second_socket:
            second_socket.send_json({"type": "auth", "token": players[1]["token"]})
            assert second_socket.receive_json() == {"type": "auth.ok"}

            api._run_enemy_aggression_tick()
            for account_id in ordered_accounts:
                make_checks_due(account_id)
            api._run_enemy_aggression_tick()
            assert chance_rng.calls == 2

            api._run_enemy_aggression_tick()
            assert chance_rng.calls == 2
            with api.SessionLocal() as db:
                health_by_account = {
                    character.account_id: character.combat_stats["health"]
                    for character in db.scalars(select(Character)).all()
                }
            assert health_by_account[ordered_accounts[0]] == 100
            assert health_by_account[ordered_accounts[1]] == 99

            for account_id in ordered_accounts:
                make_checks_due(account_id)
            api._run_enemy_aggression_tick()
            assert chance_rng.calls == 4

    with api.SessionLocal() as db:
        health_by_account = {
            character.account_id: character.combat_stats["health"]
            for character in db.scalars(select(Character)).all()
        }
    assert health_by_account[ordered_accounts[0]] == 99
    assert health_by_account[ordered_accounts[1]] == 99


def test_level_thresholds_grant_health_and_attack_increases() -> None:
    character = SimpleNamespace(
        experience=0,
        combat_stats={"health": 80, "max_health": 100, "attack": 3, "defense": 1, "speed": 10},
    )

    assert game.award_experience(character, 99) == ["You gain 99 experience."]
    assert character.combat_stats["attack"] == 3
    assert game.award_experience(character, 1)[1].startswith("You reached level 2!")
    assert character.combat_stats["attack"] == 4
    assert character.combat_stats["max_health"] == 110
    assert character.combat_stats["health"] == 90

    game.award_experience(character, 199)
    assert character.experience == 299
    assert character.combat_stats["attack"] == 4
    game.award_experience(character, 1)
    assert character.experience == 300
    assert character.combat_stats["attack"] == 5
    assert character.combat_stats["max_health"] == 120


def _currency_world(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    world = content_store.WorldContent.model_validate(
        {
            "currencies": [{"id": "gold", "name": "Gold", "symbol": "g"}],
            "locations": [
                {
                    "id": "market",
                    "name": "Market",
                    "description": "A market.",
                    "position": {"x": 50, "y": 50},
                    "starting_species": ["human", "goblin"],
                    "enemy_ids": ["rat"],
                    "npc_ids": ["trader"],
                }
            ],
            "entities": [
                {"id": "tonic", "type": "item", "name": "Tonic", "description": "Tasty."},
                {
                    "id": "trader",
                    "type": "npc",
                    "name": "Trader",
                    "description": "Sells.",
                    "present_for": ["human"],
                    "stock": [
                        {
                            "item_id": "tonic",
                            "price": 5,
                            "quantity": 2,
                            "currency_id": "gold",
                            "restock_seconds": 60,
                        }
                    ],
                },
                {
                    "id": "rat",
                    "type": "enemy",
                    "name": "Rat",
                    "description": "Squeak.", "attributes": {"health": 3, "attack": 1, "defense": 0},
                    "currency_drops": [
                        {"currency_id": "gold", "chance": 1, "minimum_amount": 3, "maximum_amount": 3}
                    ],
                },
            ],
        }
    )
    world_path = tmp_path / "world_content.json"
    world_path.write_text(world.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(content_store, "WORLD_CONTENT_PATH", world_path)
    return world.model_dump(mode="json")


def test_currency_validation_rejects_unknown_references() -> None:
    with pytest.raises(ValueError):
        content_store.WorldContent.model_validate(
            {
                "locations": [],
                "entities": [
                    {
                        "id": "rat",
                        "type": "enemy",
                        "name": "Rat",
                        "description": "x",
                        "currency_drops": [
                            {"currency_id": "nope", "chance": 1, "minimum_amount": 1, "maximum_amount": 1}
                        ],
                    }
                ],
            }
        )


def test_currency_drop_and_per_player_shop_restock(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _currency_world(tmp_path, monkeypatch)
    entities = {entity["id"]: entity for entity in content["entities"]}
    areas = {location["id"]: location for location in content["locations"]}
    character = SimpleNamespace(
        area_id="market", species="human", inventory={}, wallet={}, shop_state={}, quest_state={}
    )
    messages = game._reward_enemy_defeat(character, entities["rat"], entities, content)
    assert "Currency: g3." in messages
    assert "No items dropped." not in messages
    assert character.wallet == {"gold": 3}

    args = {"item": {"name": "tonic", "quantity": 1}}
    assert "need" in game._buy(character, args, content, areas, entities, now=100)[0]
    character.wallet = {"gold": 12}
    assert game._buy(character, args, content, areas, entities, now=100)[0].startswith("You buy 1 Tonic")
    assert character.wallet == {"gold": 7}
    assert game._buy(character, args, content, areas, entities, now=110)[0].startswith("You buy")
    assert character.wallet == {"gold": 2}
    assert "out of Tonic" in game._buy(character, args, content, areas, entities, now=120)[0]
    character.wallet = {"gold": 50}
    assert game._buy(character, args, content, areas, entities, now=161)[0].startswith("You buy")
    assert character.inventory == {"tonic": 3}
    other = SimpleNamespace(
        area_id="market", species="human", inventory={}, wallet={"gold": 5}, shop_state={}, quest_state={}
    )
    assert game._buy(other, args, content, areas, entities, now=120)[0].startswith("You buy")


