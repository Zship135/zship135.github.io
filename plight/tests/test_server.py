from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import event
from PIL import Image

import plight_server.app as api
import plight_server.content as content_store
import plight_server.game as game
from plight_server.database import Base, get_db
from plight_server.game import initial_area
from plight_server.models import Account, Character, ChatMessage, Command, PlayerSession

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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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

    assert first.status_code == retry.status_code == 202
    assert first.json() == retry.json()
    assert first.json()["status"] == "completed"
    assert first.json()["result"]["snapshot"]["character"]["area_id"] == "goblin_town"
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
            "race": "goblin",
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
    assert human_guide["race"] == "goblin"
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
                "equipable_slots": ["left_hand", "right_hand"],
            },
            {
                "id": "wood",
                "name": "Wood",
                "quantity": 2,
                "type": "item",
                "equipable_slots": [],
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
        assert response.status_code == 202, response.text
        return response.json()["result"]

    equipped = command("equip the iron sword in my left hand", "adf0f265-edca-449a-8ce5-100000000041")
    assert equipped["interpretation"]["occurrences"][0]["action_id"] == "equip_item"
    assert equipped["messages"] == ["You equip Iron sword in your left hand."]
    assert equipped["snapshot"]["character"]["equipment"]["left_hand"] == "iron_sword"
    persisted_snapshot = client.get("/api/v1/world/snapshot", headers=headers).json()
    assert persisted_snapshot["character"]["equipment"]["left_hand"] == "iron_sword"
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        assert character.equipment["left_hand"] == "iron_sword"

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

    named_unequip = command("unequip the iron sword", "adf0f265-edca-449a-8ce5-100000000045")
    assert named_unequip["interpretation"]["occurrences"][0]["action_id"] == "unequip_item"
    assert named_unequip["messages"] == ["You unequip Iron sword from your left hand."]
    command("equip iron sword in my right hand", "adf0f265-edca-449a-8ce5-100000000046")
    unequipped = command("unequip from my right hand", "adf0f265-edca-449a-8ce5-100000000047")
    assert unequipped["interpretation"]["occurrences"][0]["action_id"] == "unequip_item"
    assert unequipped["messages"] == ["You unequip Iron sword from your right hand."]
    assert unequipped["snapshot"]["character"]["equipment"]["right_hand"] == "fist"

    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        assert character.equipment["left_hand"] == "fist"
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
    assert result["character"]["equipment"] == {
        **game.DEFAULT_EQUIPMENT,
        "left_hand": "iron_sword",
    }


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
        db.commit()

    headers = auth(registered["token"])
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

    assert "equip Iron sword in your left hand" in left_equipped.json()["result"]["messages"][0]
    assert "equip Wooden club in your right hand" in equipped.json()["result"]["messages"][0]
    result = attacked.json()["result"]
    assert any("right hand Wooden club for 6 damage" in message for message in result["messages"]), result["messages"]
    assert not any("left hand" in message for message in result["messages"])
    assert any("rolls D2 (1) and hits you for 2 damage" in message for message in result["messages"])
    assert result["snapshot"]["character"]["equipment"] == {
        **game.DEFAULT_EQUIPMENT,
        "left_hand": "iron_sword",
        "right_hand": "wooden_club",
    }
    assert result["snapshot"]["character"]["stats"]["health"] == 98
    enemy = result["snapshot"]["area"]["enemies"][0]
    assert enemy["health"] == 6
    assert enemy["attack_die_sides"] == 2


def test_defend_reduces_the_next_enemy_strike(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    registered = register(client, "guard@example.com", "Briar")

    class FixedRoll:
        @staticmethod
        def randint(_: int, __: int) -> int:
            return 1

    monkeypatch.setattr(game, "combat_rng", FixedRoll())
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        character.area_id = "new_location_2"
        character.combat_state = {"target_id": None, "enemy_health": {}, "defending": True}
        db.commit()

    result = client.post(
        "/api/v1/commands",
        headers=auth(registered["token"]),
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000026", "text": "Attack the slug"},
    ).json()["result"]
    assert any("hits you for 1 damage (99/100 health)" in message for message in result["messages"])


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
            "speed": 10,
        }
        db.commit()

    response = client.post(
        "/api/v1/commands",
        headers=auth(registered["token"]),
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000022", "text": "Attack the forest rat"},
    )

    result = response.json()["result"]
    assert any("You are defeated" in message for message in result["messages"])
    assert result["snapshot"]["character"]["area_id"] == "human_city"
    assert result["snapshot"]["character"]["stats"]["health"] == 100
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == registered["account_id"]))
        assert character.combat_state["enemy_health"]["forest_rat"] == 12


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


def test_observe_player_opens_profile_only_for_same_area_player(client: TestClient) -> None:
    watcher = register(client, "observe-watcher@example.com", "Mira")
    observed = register(client, "observe-player@example.com", "Sable")
    with api.SessionLocal() as db:
        character = db.scalar(select(Character).where(Character.account_id == observed["account_id"]))
        character.area_id = "human_city"
        character.inventory = {"iron_sword": 1, "wood": 8}
        character.equipment = {"left_hand": "iron_sword", "right_hand": "fist"}
        db.commit()

    result = client.post(
        "/api/v1/commands",
        headers=auth(watcher["token"]),
        json={"request_id": "adf0f265-edca-449a-8ce5-100000000099", "text": "Observe Sable"},
    ).json()["result"]
    assert result["messages"] == ["You observe Sable."]
    assert result["profile_account_ids"] == [observed["account_id"]]
    assert result["observed_player_equipment"][observed["account_id"]]["left_hand"] == "Iron sword"
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
