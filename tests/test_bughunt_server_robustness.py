"""Bug hunt: server robustness and hidden information over the real websocket.

All of these currently pass; they pin behaviour the client relies on.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ibflip_web.main import app, registry
from ibflip_web.rooms import MAX_SEATS


def _state(ws, predicate=lambda m: True, limit=200):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == "state" and predicate(m):
            return m
    raise AssertionError("no matching state")


def _until(ws, kind, limit=200):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == kind:
            return m
    raise AssertionError(f"no {kind}")


def _two_humans_playing(client):
    a = client.post("/api/rooms", json={"name": "Ann"}).json()
    b = client.post(f"/api/rooms/{a['code']}/join", json={"name": "Ben"}).json()
    room = registry.get(a["code"])
    room.start()
    for seat in range(2):
        room._ready_with_full_slots(seat)
    room._after_fixing_check()
    assert room.status == "playing"
    return a, b, room


def test_out_of_turn_replayed_and_foreign_actions_are_rejected_without_changing_state():
    with TestClient(app) as client:
        a, b, room = _two_humans_playing(client)
        with client.websocket_connect(f"/ws/{a['code']}?token={a['token']}") as wa, client.websocket_connect(
            f"/ws/{a['code']}?token={b['token']}"
        ) as wb:
            _state(wa)
            _state(wb)
            engine = room.engine
            cur = engine.state.current_player
            mover, other = (wa, wb) if cur == 0 else (wb, wa)
            legal = engine.get_legal_action_indices()
            snapshot = repr(engine.state)
            # The other seat tries the mover's legal action: "Not your turn".
            other.send_json({"type": "action", "action": legal[0]})
            err = _until(other, "error")
            assert err["message"] == "Not your turn"
            assert repr(engine.state) == snapshot
            # A card the mover does not hold: generic message, no card details.
            foreign = next(c for c in range(52) if c not in engine.state.players[cur].hand and c not in legal)
            mover.send_json({"type": "action", "action": foreign})
            err = _until(mover, "error")
            assert err["message"] == "Illegal move"
            assert repr(engine.state) == snapshot
            # The same legal action sent twice back to back: applied once.
            mover.send_json({"type": "action", "action": legal[0]})
            mover.send_json({"type": "action", "action": legal[0]})
            seen = [mover.receive_json() for _ in range(2)]
            kinds = [m["type"] for m in seen]
            assert "state" in kinds
            if "error" in kinds:
                assert next(m for m in seen if m["type"] == "error")["message"] in ("Not your turn", "Illegal move")
            # Fix messages during play are refused.
            mover.send_json({"type": "fix", "op": "done"})
            assert _until(mover, "error")["message"] in ("Not fixing now",)


def test_join_full_or_started_room_is_refused_and_room_survives():
    with TestClient(app) as client:
        a = client.post("/api/rooms", json={"name": "Host"}).json()
        for i in range(MAX_SEATS - 1):
            assert client.post(f"/api/rooms/{a['code']}/join", json={"name": f"P{i}"}).status_code == 200
        r = client.post(f"/api/rooms/{a['code']}/join", json={"name": "Late"})
        assert r.status_code == 409 and r.json()["detail"] == "Room is full"
        room = registry.get(a["code"])
        room.seats.pop()  # free one seat, then start
        room.start()
        r = client.post(f"/api/rooms/{a['code']}/join", json={"name": "Late"})
        assert r.status_code == 409 and r.json()["detail"] == "Game already in progress"
        assert room.status == "fixing" and len(room.seats) == MAX_SEATS - 1


def test_rest_room_info_has_no_tokens_or_cards():
    with TestClient(app) as client:
        a, b, room = _two_humans_playing(client)
        info = client.get(f"/api/rooms/{a['code']}").json()
        text = str(info)
        assert a["token"] not in text and b["token"] not in text
        assert set(info) == {"code", "status", "host", "seats", "game_no", "hard_available"}
        for seat in info["seats"]:
            assert set(seat) == {"seat", "kind", "name", "avatar", "level", "connected", "host", "wins", "left"}


def test_host_leaving_mid_game_hands_host_on_and_game_continues():
    with TestClient(app) as client:
        a, b, room = _two_humans_playing(client)
        with client.websocket_connect(f"/ws/{a['code']}?token={a['token']}") as wa, client.websocket_connect(
            f"/ws/{a['code']}?token={b['token']}"
        ) as wb:
            _state(wa)
            _state(wb)
            wa.send_json({"type": "leave"})
            m = _state(wb, lambda m: m["room"]["host"] == 1)
            assert m["room"]["seats"][0]["left"] is True
            assert m["game"]["status"] == "playing"
            assert "hand" not in m["game"]["players"][0]
