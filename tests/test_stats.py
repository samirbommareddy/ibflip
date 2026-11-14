"""Anonymous game-activity tracking: off by default, never breaks games, sends only counters."""

import json
import random
import re
import time

import pytest
from fastapi.testclient import TestClient

import ibflip_web.stats as stats
from ibflip_web.main import app, registry
from ibflip_web.stats import COUNTER_METRICS, PEAK_METRICS, GameShape, Stats

pytestmark = pytest.mark.web

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHAPE_RE = re.compile(r"^[2-5]p-[0-5]h$")
LEVELS = {"easy", "medium", "hard"}


def _drain_until(ws, predicate, limit=400):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message not received")


def _play_to_game_over(client, created, *, seed=0):
    room = registry.get(created["code"])
    room.bot_delay = 0.0
    rng = random.Random(seed)
    with client.websocket_connect(f"/ws/{created['code']}?token={created['token']}") as ws:
        _drain_until(ws, lambda m: m["type"] == "state" and "game" in m)
        ws.send_json({"type": "fix", "op": "done"})
        for _ in range(5000):
            message = ws.receive_json()
            if message["type"] != "state":
                continue
            game = message["game"]
            if game["status"] == "over":
                return room
            legal = game.get("legal", {})
            options = list(legal.get("cards", []))
            options += [52] if legal.get("pick_up") else []
            options += [54] if legal.get("reveal") else []
            options += [55] if legal.get("end_group") else []
            options += [67 + s for s in legal.get("face_down", [])]
            if options:
                ws.send_json({"type": "action", "action": rng.choice(options)})
    raise AssertionError("game did not finish")


def _assert_allowed(batch):
    """The payload contains only allow-listed counters and peaks."""
    assert set(batch) == {"v", "counters", "peaks"}
    for day, metric, dim, n in batch["counters"]:
        assert DAY_RE.match(day)
        allowed = COUNTER_METRICS[metric]
        if allowed is None and metric == "bot_mix":
            assert dim == "none" or set(dim.split("+")) <= LEVELS
        elif allowed is None:
            assert SHAPE_RE.match(dim), dim
        else:
            assert dim in allowed
        assert isinstance(n, int) and n >= 0
    for day, metric, value in batch["peaks"]:
        assert DAY_RE.match(day) and metric in PEAK_METRICS and isinstance(value, int)


def _totals(batches):
    out = {}
    for batch in batches:
        for _day, metric, dim, n in batch["counters"]:
            out[(metric, dim)] = out.get((metric, dim), 0) + n
    return out


@pytest.fixture
def captured(monkeypatch):
    sent = []

    def sender(payload):
        sent.append(json.loads(json.dumps(payload)))  # must be JSON-serializable
        return 204

    tracker = Stats(sender=sender)
    monkeypatch.setattr(stats, "STATS", tracker)
    return tracker, sent


def test_disabled_without_env(monkeypatch):
    monkeypatch.delenv("STATS_INGEST_URL", raising=False)
    monkeypatch.delenv("STATS_INGEST_SECRET", raising=False)
    tracker = Stats.from_env()
    assert not tracker.enabled
    tracker.room_created(True)
    tracker.player_seen("203.0.113.9")
    tracker.sample(1, 1, 1)
    assert tracker.take_batch() is None
    assert tracker.flush_sync() is False
    monkeypatch.setenv("STATS_INGEST_URL", "https://example.invalid/stats/ingest")
    assert not Stats.from_env().enabled  # URL alone is not enough
    monkeypatch.setenv("STATS_INGEST_SECRET", "x" * 32)
    assert Stats.from_env().enabled


def test_gameplay_works_with_tracking_disabled(monkeypatch):
    disabled = Stats("", "")
    monkeypatch.setattr(stats, "STATS", disabled)
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["easy"], "autostart": True}).json()
        room = _play_to_game_over(client, created)
        assert room.status == "over"
    assert disabled._task is None and disabled.take_batch() is None


def test_full_game_sends_only_anonymous_counters(captured):
    tracker, sent = captured
    name = "Zelda Secretname"
    with TestClient(app) as client:
        created = client.post(
            "/api/rooms", json={"name": name, "bots": ["hard", "easy", "easy"], "autostart": True}
        ).json()
        room = _play_to_game_over(client, created, seed=3)
        assert room.status == "over"
        friends = client.post("/api/rooms", json={"name": "Host"}).json()
        client.post(f"/api/rooms/{friends['code']}/join", json={"name": "Guest"})
        assert tracker.flush_sync() is True
    assert sent, "nothing was sent"
    for batch in sent:
        _assert_allowed(batch)
        text = json.dumps(batch)
        for secret in (created["code"], friends["code"], created["token"], friends["token"], name, "testclient"):
            assert secret not in text
    totals = _totals(sent)
    assert totals[("rooms_created", "solo")] == 1
    assert totals[("rooms_created", "friends")] == 1
    assert totals[("games_started", "4p-1h")] == 1
    assert totals[("bot_seats", "easy")] == 2 and totals[("bot_seats", "hard")] == 1
    assert totals[("bot_mix", "easy+hard")] == 1
    assert totals[("games_finished", "4p-1h")] == 1
    assert sum(n for (m, _), n in totals.items() if m == "game_duration") == 1
    # Same TestClient address for all three requests: one first-seen player.
    assert totals[("new_players", "")] == 1


def test_game_left_by_everyone_is_unattended(captured, monkeypatch):
    import ibflip_web.rooms as rooms

    monkeypatch.setattr(rooms, "LEFT_AUTOPILOT_SECONDS", 0.0)
    tracker, sent = captured
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["easy"], "autostart": True}).json()
        room = registry.get(created["code"])
        room.bot_delay = 0.0
        with client.websocket_connect(f"/ws/{created['code']}?token={created['token']}") as ws:
            _drain_until(ws, lambda m: m["type"] == "state" and "game" in m)
            ws.send_json({"type": "leave"})
            _drain_until(ws, lambda m: m["type"] == "left")
        for _ in range(1500):
            if room.status == "over":
                break
            client.get("/health")  # yield to the bot runner
            time.sleep(0.02)
        assert room.status == "over"
        tracker.flush_sync()
    totals = _totals(sent)
    assert totals.get(("games_unattended", "2p-1h")) == 1
    assert ("games_finished", "2p-1h") not in totals


def test_expired_and_shutdown_games_are_abandoned(captured):
    tracker, sent = captured
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["medium"], "autostart": True}).json()
        room = registry.get(created["code"])
        assert room.stats_game is not None
        registry.discard(room)
        assert room.stats_game is None
        registry.discard(room)  # idempotent: counted once
        other = client.post("/api/rooms", json={"name": "Me", "bots": ["medium"], "autostart": True}).json()
        assert registry.get(other["code"]).stats_game is not None
    # Leaving the TestClient context runs the lifespan shutdown (counts + final flush).
    totals = _totals(sent)
    assert totals[("games_abandoned", "2p-1h")] >= 2


def test_tracker_never_raises_into_game_code(monkeypatch):
    def boom(_payload):
        raise ConnectionError("ingest is down")

    tracker = Stats(sender=boom)
    monkeypatch.setattr(stats, "STATS", tracker)
    # Broken internals must not leak either.
    monkeypatch.setattr(tracker, "_add", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    tracker.room_created(True)
    tracker.game_started(GameShape(2, 1, ["easy"], 0.0))
    tracker.game_ended(GameShape(2, 1, ["easy"], 0.0), "finished")
    tracker.player_seen("198.51.100.7")
    tracker.sample(1, 2, 3)
    assert tracker.flush_sync() is False  # peaks were recorded; sending failed quietly
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["easy"], "autostart": True}).json()
        assert _play_to_game_over(client, created).status == "over"


def test_http_failures_are_dropped_not_raised(monkeypatch):
    tracker = Stats("http://127.0.0.1:9/stats/ingest", "s" * 32)  # nothing listens on port 9
    tracker.room_created(False)
    assert tracker.flush_sync() is False
    assert tracker.take_batch() is None  # dropped, not retried


def test_unique_players_are_hashed_in_memory_with_a_daily_key(captured):
    tracker, _sent = captured
    tracker.player_seen("203.0.113.1")
    tracker.player_seen("203.0.113.1")
    tracker.player_seen("203.0.113.2")
    key = tracker._seen_key
    assert len(key) == 32 and all(len(h) == 16 for h in tracker._seen)
    assert b"203.0.113.1" not in b"".join(tracker._seen)
    batch = tracker.take_batch()
    assert [c[1:] for c in batch["counters"]] == [["new_players", "", 2]]
    tracker._seen_day = "2000-01-01"  # next UTC day: new key, fresh set
    tracker.player_seen("203.0.113.1")
    assert tracker._seen_key != key and len(tracker._seen) == 1


def test_peaks_keep_the_maximum(captured):
    tracker, _ = captured
    tracker.sample(3, 1, 2)
    tracker.sample(2, 2, 1)
    peaks = {m: v for _d, m, v in tracker.take_batch()["peaks"]}
    assert peaks == {"peak_rooms": 3, "peak_active_rooms": 2, "peak_players": 2}
