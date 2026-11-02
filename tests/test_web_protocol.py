"""Protocol / state-sync / room-lifecycle regression tests for the web server.

Each test pins down a bug found by fuzzing the multiplayer server
(tests/fuzz_multiplayer.py) or by review. They talk to the app exactly like
static/app.js does: REST to create/join, then the /ws/{code}?token=... socket.
"""

from __future__ import annotations

import asyncio
import random
import time
from contextlib import ExitStack, contextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import ibflip_web.main as main
import ibflip_web.rooms as rooms
from ibflip.ai.agents import HeuristicAgent, model_available
from ibflip.state import GameState, Phase, Player
from ibflip_web.main import app, registry

pytestmark = pytest.mark.web

# card ids: rank * 4 + suit; ranks 3,4,5,6,7,8,9,10,J,Q,K,A,2
J = [32, 33, 34, 35]
Q = [36, 37, 38, 39]
K = [40, 41, 42, 43]
A_PICKUP, A_REVEAL, A_END, A_FACEDOWN = 52, 54, 55, 67


# ----------------------------------------------------------------- helpers
def recv_until(ws, pred, limit=3000):
    for _ in range(limit):
        message = ws.receive_json()
        if pred(message):
            return message
    raise AssertionError("expected message not received")


def is_state(pred=lambda g: True):
    return lambda m: m["type"] == "state" and "game" in m and pred(m["game"])


def ui_options(game):
    """The moves app.js lets a player click for this state."""
    legal = game.get("legal") or {}
    opts = list(legal.get("cards", []))
    opts += [A_PICKUP] if legal.get("pick_up") else []
    opts += [A_REVEAL] if legal.get("reveal") else []
    opts += [A_END] if legal.get("end_group") else []
    opts += [A_FACEDOWN + s for s in legal.get("face_down", [])]
    return opts


@contextmanager
def lobby(client, humans=2):
    host = client.post("/api/rooms", json={"name": "H0"}).json()
    code = host["code"]
    creds = [host] + [client.post(f"/api/rooms/{code}/join", json={"name": f"H{i}"}).json() for i in range(1, humans)]
    with ExitStack() as stack:
        socks = [stack.enter_context(client.websocket_connect(f"/ws/{code}?token={c['token']}")) for c in creds]
        for ws in socks:
            recv_until(ws, lambda m: m["type"] == "state" and sum(s["connected"] for s in m["room"]["seats"]) == humans)
        yield registry.get(code), socks, creds


@contextmanager
def playing(client, humans=1, bots=1, bot_delay=60.0):
    """A room in the playing phase. Bots are slowed right down so a test can
    put the engine in any position before anybody moves."""
    with lobby(client, humans) as (room, socks, creds):
        room.bot_delay = bot_delay
        for _ in range(bots):
            socks[0].send_json({"type": "add_bot", "level": "medium"})
        if bots:
            for ws in socks:
                recv_until(ws, lambda m: m["type"] == "state" and len(m["room"]["seats"]) == humans + bots)
        socks[0].send_json({"type": "start"})
        for ws in socks:
            recv_until(ws, is_state(lambda g: g["status"] == "fixing"))
            ws.send_json({"type": "fix", "op": "done"})
        for ws in socks:
            recv_until(ws, is_state(lambda g: g["status"] == "playing"))
        yield room, socks, creds


def set_position(client, room, *, current, hands, live=(), draw=(), face_up=None):
    """Replace the engine state (keeping all 52 cards accounted for) and push it."""
    n = len(room.seats)
    used = set(live) | set(draw) | {c for h in hands for c in h}
    if face_up:
        used |= {c for slots in face_up for slot in slots for c in slot}
    rest = [c for c in range(52) if c not in used]
    players = []
    for i in range(n):
        players.append(
            Player(
                hand=list(hands[i]),
                face_up_slots=[list(s) for s in face_up[i]] if face_up else [[], [], []],
                face_down_slots=[rest.pop(), rest.pop(), rest.pop()],
                fixing_done=True,
            )
        )
    state = GameState(
        players=players,
        draw_pile=list(draw),
        live_cards=list(live),
        discard_pile=rest,
        phase=Phase.EARLY_GAME if draw else Phase.MIDDLE_GAME,
        current_player=current,
    )

    def apply():
        room.engine.set_state(state)
        room.engine.events = []
        room.status = "playing"
        room.turn_started = time.time()
        room.touch()
        return room.broadcast()

    client.portal.call(apply)


def play(ws, action):
    ws.send_json({"type": "action", "action": action})


# ------------------------------------------------------------ the Q reports
@pytest.mark.parametrize("draw", [(), (K[3], 0, 1, 2)], ids=["middle-game", "early-game"])
def test_two_queens_in_one_turn_from_hand(draw):
    with TestClient(app) as client, playing(client) as (room, (ws,), _):
        set_position(client, room, current=0, hands=[[Q[0], Q[1], K[0]], [K[1], K[2]]], live=[J[0]], draw=draw)
        g = recv_until(ws, is_state(lambda g: g["current"] == 0))["game"]
        assert {Q[0], Q[1]} <= set(g["legal"]["cards"])
        play(ws, Q[0])
        g = recv_until(ws, is_state(lambda g: g["group_count"] == 1))["game"]
        assert g["legal"]["cards"] == [Q[1]] and g["legal"]["end_group"] and g["current"] == 0
        play(ws, Q[1])
        g = recv_until(ws, is_state(lambda g: g["group_count"] == 2))["game"]
        assert g["legal"]["cards"] == [] and g["legal"]["end_group"]
        play(ws, A_END)
        g = recv_until(ws, is_state(lambda g: g["current"] == 1))["game"]
        assert g["live"][-2:] == [Q[0], Q[1]]


def test_queen_on_queen_on_consecutive_turns():
    with TestClient(app) as client, playing(client, humans=2, bots=0) as (room, (a, b), _):
        set_position(client, room, current=0, hands=[[Q[0], K[0], K[1]], [Q[1], K[2], K[3]]], live=[J[0]])
        recv_until(a, is_state(lambda g: g["current"] == 0))
        play(a, Q[0])
        recv_until(a, is_state(lambda g: g["group_count"] == 1))
        play(a, A_END)
        g = recv_until(b, is_state(lambda g: g["current"] == 1))["game"]
        assert Q[1] in g["legal"]["cards"]
        play(b, Q[1])
        recv_until(b, is_state(lambda g: g["group_count"] == 1))
        play(b, A_END)
        g = recv_until(a, is_state(lambda g: g["current"] == 0))["game"]
        assert g["live"][-2:] == [Q[0], Q[1]]


def test_two_queens_stacked_in_one_face_up_slot_play_together():
    slots = [[Q[0], Q[1]], [K[0]], [K[1]]]
    with TestClient(app) as client, playing(client) as (room, (ws,), _):
        set_position(client, room, current=0, hands=[[], [K[2]]], live=[J[0]], face_up=[slots, [[], [], []]])
        g = recv_until(ws, is_state(lambda g: g["current"] == 0))["game"]
        assert g["source"] == "face_up" and {Q[0], Q[1]} <= set(g["legal"]["cards"])
        play(ws, Q[0])
        g = recv_until(ws, is_state(lambda g: g["group_count"] == 1))["game"]
        assert g["legal"]["cards"] == [Q[1]]
        play(ws, Q[1])
        recv_until(ws, is_state(lambda g: g["group_count"] == 2))
        play(ws, A_END)
        recv_until(ws, is_state(lambda g: g["current"] == 1))


def test_queens_in_separate_face_up_slots_cannot_be_played_together():
    """User ruling: same-rank face-up cards play together only if stacked in one slot."""
    slots = [[Q[0]], [Q[1]], [K[0]]]
    with TestClient(app) as client, playing(client) as (room, (ws,), _):
        set_position(client, room, current=0, hands=[[], [K[2]]], live=[J[0]], face_up=[slots, [[], [], []]])
        g = recv_until(ws, is_state(lambda g: g["current"] == 0))["game"]
        assert {Q[0], Q[1]} <= set(g["legal"]["cards"])
        play(ws, Q[0])
        g = recv_until(ws, is_state(lambda g: g["group_count"] == 1))["game"]
        assert Q[1] not in g["legal"]["cards"] and g["legal"]["end_group"]


def test_queen_drawn_after_playing_a_queen_can_follow_it():
    """Rules: 'If a player draws a card that they just played, they may play that card as well'."""
    with TestClient(app) as client, playing(client) as (room, (ws,), _):
        # Early game: play Q from a full hand; the next card on the deck is another Q.
        set_position(client, room, current=0, hands=[[Q[0], K[0], K[1]], [K[2]]], live=[J[0]], draw=(Q[1], 0, 1, 2))
        recv_until(ws, is_state(lambda g: g["current"] == 0))
        play(ws, Q[0])
        g = recv_until(ws, is_state(lambda g: g["group_count"] == 1 and Q[1] in g["hand"]))["game"]
        assert g["current"] == 0 and Q[1] in g["legal"]["cards"]
        play(ws, Q[1])
        recv_until(ws, is_state(lambda g: g["group_count"] == 2))


# -------------------------------------------------- message validation
def test_malformed_messages_get_an_error_and_keep_the_socket_open():
    """Before: a non-object JSON message raised AttributeError in handle_message,
    the bare `except Exception: pass` in the socket loop swallowed it and the
    server closed the socket (the UI then shows 'Reconnecting…')."""
    with TestClient(app) as client, lobby(client, humans=1) as (room, (ws,), _):
        for bad in ("hello", "[1, 2, 3]", "not json", '{"type": 5}', '{"type": "action"}',
                    '{"type": "action", "action": "x"}', '{"type": "action", "action": 1e9}',
                    '{"type": "fix", "op": "swap", "card": 3, "slot": 9}', '{"type": "set_bot", "seat": -1}'):
            ws.send_text(bad)
            assert ws.receive_json()["type"] == "error", bad
        ws.send_bytes(b"\xff\xfe")
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "ping"})
        assert recv_until(ws, lambda m: m["type"] in ("pong", "state"))["type"] == "pong"


def test_unexpected_server_error_is_reported_not_fatal(monkeypatch):
    with TestClient(app) as client, lobby(client, humans=1) as (room, (ws,), _):
        def boom(*a, **k):
            raise RuntimeError("bug")

        monkeypatch.setattr(rooms.Room, "add_bot", boom)
        ws.send_json({"type": "add_bot"})
        assert recv_until(ws, lambda m: m["type"] == "error")["message"] == "Something went wrong on the server"
        ws.send_json({"type": "ping"})
        assert recv_until(ws, lambda m: m["type"] == "pong")


def test_non_ascii_token_is_rejected_cleanly():
    """secrets.compare_digest raised TypeError on non-ASCII str tokens."""
    with TestClient(app) as client:
        code = client.post("/api/rooms", json={"name": "Solo"}).json()["code"]
        with client.websocket_connect(f"/ws/{code}?token=%C3%A9t%C3%A9") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error" and msg["fatal"]


def test_set_bot_is_bounds_checked_and_lobby_only():
    with TestClient(app) as client, lobby(client, humans=1) as (room, (ws,), _):
        ws.send_json({"type": "add_bot", "level": "easy"})
        recv_until(ws, lambda m: m["type"] == "state" and len(m["room"]["seats"]) == 2)
        ws.send_json({"type": "set_bot", "seat": -1, "level": "hard"})  # used to hit seats[-1]
        assert recv_until(ws, lambda m: m["type"] in ("error", "state"))["type"] == "error"
        assert room.seats[1].level == "easy"
        ws.send_json({"type": "start"})
        recv_until(ws, is_state())
        ws.send_json({"type": "set_bot", "seat": 1, "level": "hard"})
        assert recv_until(ws, lambda m: m["type"] in ("error", "state"))["type"] == "error"
        assert room.seats[1].level == "easy"


def test_autostart_without_bots_does_not_leave_a_room_behind():
    with TestClient(app) as client:
        before = len(registry.rooms)
        r = client.post("/api/rooms", json={"name": "x", "autostart": True})
        assert r.status_code == 400 and len(registry.rooms) == before


def test_player_names_are_sanitized():
    assert rooms.clean_name("  Al\x00i​\n\tce   Bob ") == "Alice Bob"
    assert rooms.clean_name("\x07\n ") == "Player"
    assert len(rooms.clean_name("x" * 40)) == 18
    with TestClient(app) as client:
        code = client.post("/api/rooms", json={"name": "a\x1b[31mb\n"}).json()["code"]
        assert registry.get(code).seats[0].name == "a[31mb"


# ---------------------------------------------------------- bots / runner
def _play_randomly_until_over(ws, rng, limit=20000, seen=None):
    for _ in range(limit):
        m = ws.receive_json()
        if seen is not None:
            seen.extend(m.get("events", []))
        if m["type"] != "state" or "game" not in m:
            continue
        if m["game"]["status"] == "over":
            return m
        opts = ui_options(m["game"])
        # Pickup is now offered next to reveal/plays; picking up at random drags games out for minutes.
        plays = [o for o in opts if o != A_PICKUP]
        if plays and rng.random() < 0.9:
            opts = plays
        if opts:
            play(ws, rng.choice(opts))
    raise AssertionError("game did not finish")


def test_a_crashing_bot_does_not_freeze_the_room(monkeypatch, caplog):
    """Before: any exception in _auto_step killed Room.run silently -> bots never moved again."""
    calls = {"n": 0}

    def flaky(self, engine):
        calls["n"] += 1
        raise RuntimeError("bot bug")

    monkeypatch.setattr(HeuristicAgent, "choose", flaky)
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["medium"], "autostart": True}).json()
        registry.get(created["code"]).bot_delay = 0.0
        with client.websocket_connect(f"/ws/{created['code']}?token={created['token']}") as ws:
            ws.send_json({"type": "fix", "op": "done"})
            _play_randomly_until_over(ws, random.Random(1))
    assert calls["n"] > 0
    assert "bot move failed" in caplog.text


def test_dead_runner_restarts_on_next_message():
    with TestClient(app) as client, playing(client, bots=1, bot_delay=0.0) as (room, (ws,), _):
        client.portal.call(room.runner.cancel)
        time.sleep(0.05)
        assert room.runner.done()
        ws.send_json({"type": "hint"})  # any message
        recv_until(ws, lambda m: m["type"] == "hint")
        ws.send_json({"type": "fix", "op": "done"})  # a state-changing path (error here) is fine too
        recv_until(ws, lambda m: m["type"] == "error")
        ws.send_json({"type": "speed", "delay": 0.2})
        recv_until(ws, lambda m: m["type"] == "state")
        assert not room.runner.done()


def test_idle_connected_player_is_autopiloted_with_a_notice(monkeypatch):
    monkeypatch.setattr(rooms, "IDLE_TURN_TIMEOUT_SECONDS", 0.3)
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["medium"], "autostart": True}).json()
        registry.get(created["code"]).bot_delay = 0.0
        with client.websocket_connect(f"/ws/{created['code']}?token={created['token']}") as ws:
            # never readies up and never moves, but stays connected
            notes = []
            for _ in range(2000):
                m = ws.receive_json()
                notes += [e for e in m.get("events", []) if e.get("kind") == "autopilot"]
                if len({e["reason"] for e in notes}) and m.get("game", {}).get("status") == "playing" and len(notes) >= 2:
                    break
            assert notes and all(e["player"] == 0 and e["reason"] == "idle" for e in notes)


def test_human_moving_at_the_autopilot_deadline_keeps_their_move(monkeypatch):
    """The runner must re-check the deadline under the lock instead of stepping
    for whoever is current once its timer fired."""
    monkeypatch.setattr(rooms, "IDLE_TURN_TIMEOUT_SECONDS", 0.25)
    with TestClient(app) as client, playing(client, bots=1) as (room, (ws,), _):
        set_position(client, room, current=0, hands=[[Q[0], K[0], K[1]], [K[2]]], live=[J[0]])
        recv_until(ws, is_state(lambda g: g["current"] == 0))
        time.sleep(0.2)
        play(ws, Q[0])
        g = recv_until(ws, is_state(lambda g: g["group_count"] >= 1 or g["current"] != 0))["game"]
        assert g["live"][-1] == Q[0]


def test_hint_is_deterministic():
    with TestClient(app) as client, playing(client) as (room, (ws,), _):
        set_position(client, room, current=0, hands=[[Q[0], Q[1], K[0], 0, 4], [K[2]]], live=[J[0]])
        recv_until(ws, is_state(lambda g: g["current"] == 0))
        hints = set()
        for _ in range(6):
            ws.send_json({"type": "hint"})
            hints.add(recv_until(ws, lambda m: m["type"] == "hint")["action"])
        assert len(hints) == 1 and hints.pop() in {Q[0], Q[1], K[0], 0, 4}


@pytest.mark.skipif(not model_available(), reason="no trained model")
def test_each_hard_bot_has_its_own_agent_but_shares_weights():
    room = rooms.Room(code="TESTAA")
    room.add_human("me")
    room.add_bot("hard")
    room.add_bot("hard")
    room.start()
    a, b = room.agents[1], room.agents[2]
    assert a is not b and a.guard is not b.guard and a.policy is b.policy is rooms.shared_policy()


# ------------------------------------------------------------- lifecycle
def test_rematch_after_game_over_starts_a_fresh_game():
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["easy"], "autostart": True}).json()
        room = registry.get(created["code"])
        room.bot_delay = 0.0
        with client.websocket_connect(f"/ws/{created['code']}?token={created['token']}") as ws:
            ws.send_json({"type": "fix", "op": "done"})
            over = _play_randomly_until_over(ws, random.Random(2))
            ws.send_json({"type": "rematch"})
            m = recv_until(ws, is_state(lambda g: g["status"] == "fixing"))
            assert m["room"]["game_no"] == over["room"]["game_no"] + 1
            assert len(m["game"]["hand"]) == 3 and m["game"]["live"] == []


def test_reconnect_mid_game_with_saved_token_keeps_seat_and_hand():
    with TestClient(app) as client, playing(client, humans=2, bots=0) as (room, (a, b), creds):
        set_position(client, room, current=1, hands=[[Q[0], K[0]], [Q[1], K[1]]], live=[J[0]])
        recv_until(b, is_state(lambda g: g["current"] == 1))
        b.close()
        with client.websocket_connect(f"/ws/{room.code}?token={creds[1]['token']}") as b2:
            m = recv_until(b2, is_state())
            assert m["you"] == 1 and sorted(m["game"]["hand"]) == [Q[1], K[1]]
            assert Q[1] in m["game"]["legal"]["cards"]
            play(b2, Q[1])
            recv_until(b2, is_state(lambda g: g["group_count"] == 1))


def test_double_clicking_remove_does_not_kick_the_next_player():
    """Seat indexes shift after a removal, so the second click of a double-click
    on a ✕ used to remove (and kick) whoever moved into that index."""
    with TestClient(app) as client, lobby(client, humans=3) as (room, (h0, h1, h2), _):
        h0.send_json({"type": "remove", "seat": 1})
        h0.send_json({"type": "remove", "seat": 1})
        assert recv_until(h1, lambda m: m["type"] in ("kicked",))["type"] == "kicked"
        recv_until(h0, lambda m: m["type"] == "state" and len(m["room"]["seats"]) == 2)
        h2.send_json({"type": "chat", "text": "still here?"})
        m = recv_until(h2, lambda m: m["type"] in ("kicked", "chat"))
        assert m["type"] == "chat"
        assert [s.name for s in room.seats] == ["H0", "H2"]


def test_remove_with_a_stale_name_is_refused():
    with TestClient(app) as client, lobby(client, humans=2) as (room, (h0, h1), _):
        h0.send_json({"type": "remove", "seat": 1, "name": "Somebody else"})
        assert recv_until(h0, lambda m: m["type"] == "error")
        assert len(room.seats) == 2


def test_leave_in_lobby_frees_the_seat_and_passes_host_on():
    with TestClient(app) as client, lobby(client, humans=3) as (room, (h0, h1, h2), _):
        h0.send_json({"type": "leave"})
        assert recv_until(h0, lambda m: m["type"] == "left")
        m = recv_until(h1, lambda m: m["type"] == "state" and len(m["room"]["seats"]) == 2)
        assert m["you"] == 0 and m["room"]["host"] == 0  # H1 hosts now
        h1.send_json({"type": "add_bot"})
        recv_until(h2, lambda m: m["type"] == "state" and len(m["room"]["seats"]) == 3)


def test_leaving_mid_game_hands_seat_to_autopilot_and_frees_it_for_the_rematch(monkeypatch):
    monkeypatch.setattr(rooms, "LEFT_AUTOPILOT_SECONDS", 0.0)
    with TestClient(app) as client, playing(client, humans=2, bots=0, bot_delay=0.0) as (room, (a, b), _):
        a.send_json({"type": "leave"})  # the host leaves
        recv_until(a, lambda m: m["type"] == "left")
        m = recv_until(b, lambda m: m["type"] == "state" and m["room"]["seats"][0]["left"])
        assert m["room"]["host"] == 1
        seen = []
        _play_randomly_until_over(b, random.Random(3), seen=seen)
        assert {(e["player"], e["reason"]) for e in seen if e.get("kind") == "autopilot"} == {(0, "left")}
        b.send_json({"type": "lobby"})
        m = recv_until(b, lambda m: m["type"] == "state" and m["room"]["status"] == "lobby")
        assert [s["name"] for s in m["room"]["seats"]] == ["H1"] and m["you"] == 0 and m["room"]["host"] == 0


def test_host_role_passes_on_when_the_host_disappears(monkeypatch):
    monkeypatch.setattr(rooms, "HOST_HANDOFF_SECONDS", 0.2)
    with TestClient(app) as client, lobby(client, humans=2) as (room, (h0, h1), _):
        h0.close()
        m = recv_until(h1, lambda m: m["type"] == "state" and m["room"]["host"] == 1)
        assert m["you"] == 1


def test_idle_sockets_are_not_kicked_and_rooms_with_people_are_not_collected():
    """Backgrounded tabs throttle app pings; the server must not time them out,
    and room GC must never delete a room somebody is sitting in."""
    with TestClient(app) as client, lobby(client, humans=2) as (room, (h0, h1), _):
        time.sleep(1.5)  # no pings at all
        room.touched -= rooms.ROOM_TTL_SECONDS * 2
        for s in room.seats:
            s.last_seen -= rooms.ROOM_TTL_SECONDS * 2
        registry.gc()
        assert registry.get(room.code) is room
        h1.send_json({"type": "ping"})
        assert recv_until(h1, lambda m: m["type"] in ("pong", "kicked", "error"))["type"] == "pong"
        # and the runner is still alive for when they start the game
        assert not room.runner.done()


def test_gc_collects_abandoned_rooms():
    room = registry.create()
    room.add_human("x")
    room.touched -= rooms.IDLE_LOBBY_TTL_SECONDS + 1
    room.seats[0].last_seen -= rooms.IDLE_LOBBY_TTL_SECONDS + 1
    registry.gc()
    assert registry.get(room.code) is None


# ------------------------------------------------------------- slow socket
def test_a_slow_client_cannot_stall_the_room(monkeypatch):
    monkeypatch.setattr(rooms, "SEND_TIMEOUT_SECONDS", 0.2)

    class Stuck:
        closed = False

        async def send_json(self, message):
            await asyncio.sleep(3600)

        async def close(self):
            self.closed = True

    class Fine:
        def __init__(self):
            self.got = []

        async def send_json(self, message):
            self.got.append(message)

        async def close(self):
            pass

    async def scenario():
        room = rooms.Room(code="SLOWAA")
        room.add_human("slow")
        room.add_human("fine")
        stuck, fine = Stuck(), Fine()
        room.seats[0].sockets.append(rooms.Conn(stuck))
        room.seats[1].sockets.append(rooms.Conn(fine))
        t = time.monotonic()
        async with room.lock:
            await room.broadcast()
            await room.broadcast()
        assert time.monotonic() - t < 0.05  # broadcasting never waits on the network
        await asyncio.sleep(0.4)
        assert len(fine.got) == 2
        assert room.seats[0].sockets[0].closed and stuck.closed  # dropped after the timeout

    asyncio.run(scenario())


# ------------------------------------------------------------- abuse limits
def test_room_codes_are_six_unambiguous_letters_and_join_is_case_insensitive():
    with TestClient(app) as client:
        code = client.post("/api/rooms", json={"name": "a"}).json()["code"]
        assert len(code) == 6 and set(code) <= set(rooms.CODE_ALPHABET) and not set(code) & set("IOL01")
        assert client.post(f"/api/rooms/{code.lower()}/join", json={"name": "b"}).status_code == 200


def test_room_creation_is_rate_limited_per_ip(monkeypatch):
    monkeypatch.setattr(main, "CREATE_LIMIT", main.RateLimiter(capacity=2, per_minute=0.001))
    with TestClient(app) as client:
        hdr = {"X-Forwarded-For": "6.6.6.6, 203.0.113.9"}
        assert client.post("/api/rooms", json={}, headers=hdr).status_code == 200
        assert client.post("/api/rooms", json={}, headers=hdr).status_code == 200
        assert client.post("/api/rooms", json={}, headers=hdr).status_code == 429
        # a spoofed left-most entry doesn't buy a fresh bucket...
        assert client.post("/api/rooms", json={}, headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.9"}).status_code == 429
        # ...but a different real client does
        assert client.post("/api/rooms", json={}, headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200


def test_room_cap_returns_a_friendly_503(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setattr(rooms, "MAX_ROOMS", len(registry.rooms))
        r = client.post("/api/rooms", json={"name": "a"})
        assert r.status_code == 503 and "try again" in r.json()["detail"]


def test_chat_and_hint_are_rate_limited():
    with TestClient(app) as client, lobby(client, humans=1) as (room, (ws,), _):
        for i in range(40):
            ws.send_json({"type": "chat", "text": f"spam {i}"})
        ws.send_json({"type": "add_bot"})  # a state message marks the end
        chats = 0
        while True:
            m = ws.receive_json()
            if m["type"] == "chat":
                chats += 1
            if m["type"] == "state" and len(m["room"]["seats"]) == 2:
                break
        assert 5 <= chats <= 12
