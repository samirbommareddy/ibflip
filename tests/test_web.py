import random

from fastapi.testclient import TestClient

from ibflip_web.main import app, registry


def _drain_until(ws, predicate, limit=400):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message not received")


def test_health():
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"


def test_lobby_join_add_bot_and_hidden_information():
    client = TestClient(app)
    created = client.post("/api/rooms", json={"name": "Alice"}).json()
    code = created["code"]
    joined = client.post(f"/api/rooms/{code}/join", json={"name": "Bob"}).json()
    assert joined["seat"] == 1

    with client.websocket_connect(f"/ws/{code}?token={created['token']}") as alice, client.websocket_connect(
        f"/ws/{code}?token={joined['token']}"
    ) as bob:
        state = _drain_until(alice, lambda m: m["type"] == "state")
        assert [s["name"] for s in state["room"]["seats"]] == ["Alice", "Bob"]
        alice.send_json({"type": "add_bot", "level": "easy"})
        state = _drain_until(alice, lambda m: m["type"] == "state" and len(m["room"]["seats"]) == 3)
        bob.send_json({"type": "start"})  # not host: ignored
        alice.send_json({"type": "start"})
        a = _drain_until(alice, lambda m: m["type"] == "state" and "game" in m)
        b = _drain_until(bob, lambda m: m["type"] == "state" and "game" in m)
        assert a["game"]["status"] == "fixing"
        assert len(a["game"]["hand"]) == 3 and len(b["game"]["hand"]) == 3
        assert set(a["game"]["hand"]).isdisjoint(b["game"]["hand"])
        # Opponents' hands are never sent, only counts.
        assert "hand" not in a["game"]["players"][1]


def test_wrong_token_is_rejected():
    client = TestClient(app)
    code = client.post("/api/rooms", json={"name": "Solo"}).json()["code"]
    with client.websocket_connect(f"/ws/{code}?token=nope") as ws:
        assert ws.receive_json()["type"] == "error"


def test_full_game_against_bots_reaches_game_over():
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["medium", "easy"], "autostart": True}).json()
        room = registry.get(created["code"])
        room.bot_delay = 0.0
        rng = random.Random(0)
        with client.websocket_connect(f"/ws/{created['code']}?token={created['token']}") as ws:
            state = _drain_until(ws, lambda m: m["type"] == "state" and "game" in m)
            assert state["game"]["status"] == "fixing"
            ws.send_json({"type": "fix", "op": "done"})
            for _ in range(5000):
                message = ws.receive_json()
                if message["type"] != "state":
                    continue
                game = message["game"]
                if game["status"] == "over":
                    assert game["winner"] is not None or game["loser"] is not None
                    assert "hand" in game["players"][1]  # revealed at the end
                    return
                legal = game.get("legal", {})
                options = list(legal.get("cards", []))
                options += [52] if legal.get("pick_up") else []
                options += [54] if legal.get("reveal") else []
                options += [55] if legal.get("end_group") else []
                options += [67 + s for s in legal.get("face_down", [])]
                if options:
                    ws.send_json({"type": "action", "action": rng.choice(options)})
            raise AssertionError("game did not finish")
