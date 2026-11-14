"""Bug hunt: what the web client offers vs. what the engine allows.

These tests drive ``ibflip_web.rooms.Room`` directly (all seats human, so the
test picks every move), serialize each seat's view exactly as the websocket
does, and compare a Python mirror of the client's legality logic in
``static/app.js`` (renderMe / renderHand / renderPiles / soleLegalAction /
autoActFor) with the engine. ``tests/test_bughunt_client_logic.mjs`` runs the
real app.js functions on the same kind of views, so the mirror is checked too.

Failing tests document real bugs and are marked ``xfail(strict=True)``.
"""

from __future__ import annotations

import asyncio
import random
from collections import Counter

import pytest

import ibflip_web.rooms as rooms
from ibflip import IBFlipEngine, IllegalActionError
from ibflip.actions import (
    ACTION_END_PLAY_GROUP,
    ACTION_PICK_UP_LIVE_PILE,
    ACTION_RESOLVE_NINE_DRAW,
    ACTION_REVEAL_DRAW_PILE_TOP,
)
from ibflip.state import Phase
from ibflip_web.rooms import Room

A_PICKUP, A_REVEAL, A_END, A_FACEDOWN = 52, 54, 55, 67


def cid(rank: str, suit: str) -> int:
    ranks = ["3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A", "2"]
    return ranks.index(rank) * 4 + "hdcs".index(suit)


# --------------------------------------------------------------- client mirror
def client_offered(game: dict, seat: int, group_slot: int | None) -> dict:
    """What static/app.js makes clickable for ``seat`` (pendingAction false).

    Mirrors renderMe() / renderHand() / renderPiles() / the action bar:
      * hand card: ``legalCards.has(id) && g.source === "hand"``
      * face-up card: only the *top* card of a slot, in legal.cards, source
        "face_up", and (while a group is open) only the slot the group
        started from (``S.groupSlot``; None after a reconnect).
      * face-down card k: ``L.face_down.includes(k)`` (element exists only
        when ``face_down[k]``).
      * buttons: Done (end_group), Pick up (pick_up), Flip deck top (reveal).
    """
    mine = game["status"] == "playing" and game["current"] == seat
    legal = (game.get("legal") or {}) if mine else {}
    legal_cards = set(legal.get("cards") or [])
    me = game["players"][seat]
    offered: set[int] = set()
    if not mine:
        return {"actions": offered, "legal": legal}
    if game.get("source") == "hand":
        offered |= {c for c in game["hand"] if c in legal_cards}
    group_open = game.get("group_rank") is not None
    lock = group_slot if (game.get("source") == "face_up" and group_open) else None
    for k, slot in enumerate(me["face_up"]):
        if slot and slot[-1] in legal_cards and game.get("source") == "face_up" and (lock is None or lock == k):
            offered.add(slot[-1])
    for k in legal.get("face_down") or []:
        if me["face_down"][k]:
            offered.add(A_FACEDOWN + k)
    if legal.get("end_group"):
        offered.add(A_END)
    if legal.get("pick_up"):
        offered.add(A_PICKUP)
    if legal.get("reveal"):
        offered.add(A_REVEAL)
    return {"actions": offered, "legal": legal}


def sole_legal_action(game: dict) -> int | None:
    """app.js soleLegalAction()."""
    legal = game.get("legal") or {}
    options = list(legal.get("cards") or []) + [A_FACEDOWN + k for k in legal.get("face_down") or []]
    if legal.get("pick_up"):
        options.append(A_PICKUP)
    if legal.get("reveal"):
        options.append(A_REVEAL)
    if legal.get("end_group"):
        options.append(A_END)
    return options[0] if len(options) == 1 else None


def auto_act_for(game: dict, seat: int) -> int | None:
    """app.js autoActFor(): Done / Pick up when it is the only legal move."""
    if game["status"] != "playing" or game["current"] != seat or game.get("nine_draw"):
        return None
    a = sole_legal_action(game)
    return a if a in (A_END, A_PICKUP) else None


def game_sig(game: dict) -> tuple:
    """app.js gameSig(): if it does not change, apply() keeps pendingAction."""
    return (
        game["status"],
        game["current"],
        tuple(game["live"]),
        game["group_count"],
        tuple(game.get("hand", [])),
        game["draw_count"],
        game["discard_count"],
        tuple((p["hand_count"], tuple(map(tuple, p["face_up"])), tuple(p["face_down"]), p["place"]) for p in game["players"]),
    )


def engine_choices(engine: IBFlipEngine) -> set[int]:
    return {a for a in engine.get_legal_action_indices() if a != ACTION_RESOLVE_NINE_DRAW}


# ------------------------------------------------------------------- drivers
def make_room(n: int, seed: int, monkeypatch) -> Room:
    monkeypatch.setattr(rooms, "IBFlipEngine", lambda num: IBFlipEngine(num, seed=seed))
    room = Room(code="TESTQQ", host=None)
    for i in range(n):
        room.add_human(f"P{i}")
    room.start()
    return room


def random_fixing(room: Room, rng: random.Random, coverage: Counter) -> None:
    """Random legal fix ops through Room.fix (all seats), then everyone ready."""
    engine = room.engine
    n = len(room.seats)
    for _ in range(rng.randrange(0, 40)):
        seat = rng.randrange(n)
        player = engine.state.players[seat]
        if player.fixing_done:
            continue
        ops = []
        for c in player.hand:
            for k in range(3):
                ops += [("swap", c, k), ("stack", c, k)]
        for slot in player.face_up_slots:
            for c in slot:
                for k in range(3):
                    ops.append(("stack", c, k))
        ops += [("unstack", None, k) for k in range(3)]
        rng.shuffle(ops)
        for op, card, slot in ops:
            try:
                room.fix(seat, op, card, slot)
            except IllegalActionError:
                continue
            break
    if not engine.state.draw_pile:
        coverage["deck exhausted during fixing"] += 1
    for seat in range(n):
        if not engine.state.players[seat].fixing_done:
            room._ready_with_full_slots(seat)
    room._after_fixing_check()


def views(room: Room) -> list[dict]:
    return [room.view_for(i, [])["game"] for i in range(len(room.seats))]


# ------------------------------------------------------------- parity tests
def _note_coverage(engine: IBFlipEngine, game: dict, coverage: Counter) -> None:
    legal = game["legal"]
    st = engine.state
    if legal["face_down"]:
        coverage["face-down choice"] += 1
    if game["four_loop"]:
        coverage["4-loop"] += 1
    if legal["reveal"] and legal["pick_up"]:
        coverage["reveal + pick up"] += 1
    if game.get("source") == "face_up" and game["group_rank"] is not None:
        coverage["face-up group open"] += 1
        slot = st.turn_context.face_up_slot
        if slot is not None and len(st.players[st.current_player].face_up_slots[slot]) >= 1:
            coverage["face-up group continuing from a stack"] += 1
    if game.get("source") == "face_up" and st.required_start_card_id is not None and not st.turn_context.played_card_ids:
        coverage["start from face-up"] += 1
    if any(len(s) > 1 for s in st.players[st.current_player].face_up_slots):
        coverage["mover has a face-up stack"] += 1


def play_random_game(room: Room, rng: random.Random, coverage: Counter, problems: list[str], *, max_steps: int = 1500) -> None:
    engine = room.engine
    group_slot: int | None = None
    for _ in range(max_steps):
        if room.status != "playing":
            break
        st = engine.state
        if st.pending is not None and st.pending.kind.name == "NINE_DRAW":
            coverage["nine draw"] += 1
            room.act(st.current_player, ACTION_RESOLVE_NINE_DRAW)
            continue
        seat = st.current_player
        game = room.view_for(seat, [])["game"]
        if game["group_rank"] is None:
            group_slot = None
        _note_coverage(engine, game, coverage)
        engine_set = engine_choices(engine)
        offered = client_offered(game, seat, group_slot)["actions"]
        # 1. The client never offers something the engine rejects.
        if not offered <= engine_set:
            problems.append(f"offered but illegal: {sorted(offered - engine_set)}")
        # 2. Every engine choice is reachable through a client control.
        if engine_set and not offered:
            problems.append(f"no clickable move although engine allows {sorted(engine_set)}")
        for a in engine_set:
            if a >= 52 and a not in offered:
                problems.append(f"engine action {a} has no button")
        # Hand cards are offered one-for-one.
        if game["source"] == "hand":
            missing = {a for a in engine_set if a < 52} - offered
            if missing:
                problems.append(f"legal hand cards not clickable: {sorted(missing)}")
        # Face-up: each slot holding a legal card must offer its top card.
        if game["source"] == "face_up":
            for k, slot in enumerate(st.players[seat].face_up_slots):
                if any(c in engine_set for c in slot) and slot[-1] not in offered:
                    problems.append(f"face-up slot {k} {slot} has legal card(s) {[c for c in slot if c in engine_set]} but its top is not legal")
        # 3. Auto-act only when that action is the single engine choice.
        auto = auto_act_for(game, seat)
        if auto is not None and engine_set != {auto}:
            problems.append(f"auto-act {auto} while engine allows {sorted(engine_set)}")
        if auto is None and engine_set in ({ACTION_END_PLAY_GROUP}, {ACTION_PICK_UP_LIVE_PILE}):
            problems.append(f"no auto-act although only {engine_set} is legal")
        # 4. The hint names something the player can click.
        if engine_set:
            hint = room.hint(seat)
            if hint is not None and hint not in offered:
                problems.append(f"hint {hint} not clickable (offered {sorted(offered)}; slots {st.players[seat].face_up_slots})")
        # Pick a move the way a player can: from the offered set.
        choices = sorted(offered) or sorted(engine_set)
        if not choices:
            problems.append("no legal action at all")
            break
        action = rng.choice(choices)
        if action < 52 and game["source"] == "face_up" and group_slot is None:
            group_slot = next(k for k, s in enumerate(st.players[seat].face_up_slots) if action in s)
        before = game_sig(game)
        room.act(seat, action)
        after_game = room.view_for(seat, [])["game"]
        # 5. An accepted move must change what the actor's client considers
        # "the game moved"; otherwise pendingAction stays set (table frozen
        # until the next moving state or the 8 s safety timer).
        if game_sig(after_game) == before and not after_game["nine_draw"]:
            problems.append(f"accepted action {action} left gameSig unchanged")


@pytest.mark.parametrize("players", [2, 3, 4, 5])
def test_client_offered_moves_match_engine_for_random_games(players, monkeypatch):
    coverage: Counter = Counter()
    problems: list[str] = []
    # Hints run the policy network; keep them but on a subset of seeds.
    for seed in range(12):
        rng = random.Random(1000 * players + seed)
        room = make_room(players, seed=1000 * players + seed, monkeypatch=monkeypatch)
        random_fixing(room, rng, coverage)
        play_random_game(room, rng, coverage, problems)
    real = [p for p in problems if not p.startswith("hint ")]
    assert not real, "\n".join(real[:20])
    for needed in ("face-down choice", "4-loop", "reveal + pick up", "face-up group open", "nine draw"):
        assert coverage[needed] > 0, f"coverage gap: {needed} ({dict(coverage)})"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="BUG: hint names the bottom card of a face-up stack, which the client does not make clickable "
    "(rooms.hint_action returns mapping[compact][0]; compact_legal lists slot cards bottom first)",
)
def test_hint_always_names_a_clickable_card(monkeypatch):
    rng = random.Random(7)
    hits = []
    for seed in range(40):
        room = make_room(3, seed=seed, monkeypatch=monkeypatch)
        engine = room.engine
        # Build a same-rank face-up stack for seat 0 in fixing if possible.
        random_fixing(room, rng, Counter())
        group_slot = None
        for _ in range(800):
            if room.status != "playing":
                break
            st = engine.state
            if st.pending is not None and st.pending.kind.name == "NINE_DRAW":
                room.act(st.current_player, ACTION_RESOLVE_NINE_DRAW)
                continue
            seat = st.current_player
            game = room.view_for(seat, [])["game"]
            if game["group_rank"] is None:
                group_slot = None
            offered = client_offered(game, seat, group_slot)["actions"]
            hint = room.hint(seat)
            if hint is not None and hint not in offered:
                hits.append((seed, hint, [list(x) for x in st.players[seat].face_up_slots]))
            choices = sorted(offered) or sorted(engine_choices(engine))
            action = rng.choice(choices)
            if action < 52 and game["source"] == "face_up" and group_slot is None:
                group_slot = next(k for k, s in enumerate(st.players[seat].face_up_slots) if action in s)
            room.act(seat, action)
        if hits:
            break
    assert not hits, f"hint not clickable: {hits[:3]}"


# ------------------------------------------- start card hidden under a stack
def _rig_five_player_deal() -> dict:
    """A legal 52-card deal for 5 seats (see the test for the plan)."""
    h, d, c, s = "h", "d", "c", "s"
    plan = {
        # seat: (face_down, face_up, hand)
        0: ([cid("4", h), cid("4", d), cid("4", c)], [cid("3", h), cid("K", s), cid("Q", s)], [cid("3", d), cid("K", h), cid("Q", h)]),
        1: ([cid("4", s), cid("5", h), cid("5", d)], [cid("6", h), cid("8", h), cid("A", s)], [cid("6", d), cid("8", d), cid("7", c)]),
        2: ([cid("5", c), cid("5", s), cid("3", c)], [cid("9", h), cid("J", h), cid("A", h)], [cid("9", d), cid("J", d), cid("7", d)]),
        3: ([cid("3", s), cid("6", c), cid("6", s)], [cid("10", h), cid("2", h), cid("A", d)], [cid("10", d), cid("2", d), cid("7", h)]),
        4: ([cid("8", c), cid("8", s), cid("9", c)], [cid("K", d), cid("Q", d), cid("A", c)], [cid("K", c), cid("7", s), cid("2", c)]),
    }
    used = {x for fd, fu, hd in plan.values() for x in fd + fu + hd}
    deck = [x for x in range(52) if x not in used]
    assert len(deck) == 7 and not any(x // 4 == 0 for x in deck), deck  # no 3s in the deck
    return {"plan": plan, "deck": deck}


def _rigged_room() -> Room:
    rig = _rig_five_player_deal()
    room = Room(code="RIGGED", host=None)
    for i in range(5):
        room.add_human(f"P{i}")
    room.start()
    st = room.engine.state
    for seat, (fd, fu, hd) in rig["plan"].items():
        p = st.players[seat]
        p.face_down_slots = list(fd)
        p.face_up_slots = [[x] for x in fu]
        p.hand = list(hd)
        p.known_hand = []
    st.draw_pile = list(rig["deck"])
    return room


def _rigged_start_state() -> tuple[Room, int]:
    """Seat 0 ends fixing with an empty hand and 3h buried under 3d.

    Seats 1-4 drain the 7-card deck with ordinary hand-to-slot stacks (each
    stack draws a replacement card). Seat 0 then stacks all three hand cards
    onto matching face-up cards (no replacement draws: the deck is empty).
    All fix ops go through Room.fix, exactly as {"type": "fix"} messages do.
    """
    room = _rigged_room()
    stacks = [
        (1, cid("6", "d"), 0), (1, cid("8", "d"), 1),
        (2, cid("9", "d"), 0), (2, cid("J", "d"), 1),
        (3, cid("10", "d"), 0), (3, cid("2", "d"), 1),
        (4, cid("K", "c"), 0),
    ]
    for seat, card, slot in stacks:
        room.fix(seat, "stack", card, slot)
    assert not room.engine.state.draw_pile
    room.fix(0, "stack", cid("3", "d"), 0)
    room.fix(0, "stack", cid("K", "h"), 1)
    room.fix(0, "stack", cid("Q", "h"), 2)
    for seat in range(5):
        room.fix(seat, "done", None, None)
    assert room.status == "playing"
    return room, room.engine.state.current_player


def test_rigged_deal_setup_is_valid():
    room, starter = _rigged_start_state()
    st = room.engine.state
    assert starter == 0
    assert st.players[0].hand == []
    assert st.players[0].face_up_slots[0] == [cid("3", "h"), cid("3", "d")]
    assert st.required_start_card_id == cid("3", "h")
    assert room.engine.get_legal_action_indices() == [cid("3", "h")]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="BUG: required start card buried under a same-rank face-up stack is legal but not clickable; "
    "the starter has no clickable move until the 90 s idle autopilot (app.js renderMe offers only slot tops)",
)
def test_start_card_under_a_face_up_stack_is_clickable():
    room, starter = _rigged_start_state()
    game = room.view_for(starter, [])["game"]
    assert game["legal"]["cards"] == [cid("3", "h")]
    assert not game["legal"]["pick_up"] and not game["legal"]["reveal"] and not game["legal"]["end_group"]
    offered = client_offered(game, starter, None)["actions"]
    assert offered, f"no clickable move; legal={game['legal']} face_up={game['players'][starter]['face_up']}"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="BUG: in the same state the hint says 'Shark would play 3h', a card the client will not let you click",
)
def test_hint_for_buried_start_card_is_clickable():
    room, starter = _rigged_start_state()
    game = room.view_for(starter, [])["game"]
    hint = room.hint(starter)
    assert hint in client_offered(game, starter, None)["actions"], hint


# ----------------------------------------------------------- hidden info
ALLOWED_GAME_KEYS = {
    "status", "phase", "current", "direction", "four_loop", "nine_draw", "winner", "loser", "live", "ace_one",
    "target", "discard_count", "discard_top", "draw_count", "start_card", "group_rank", "group_count", "players",
    "hand", "legal", "source",
}
ALLOWED_PLAYER_KEYS = {"hand_count", "known", "face_up", "face_down", "active", "finish", "place", "ready"}
OVER_ONLY_PLAYER_KEYS = {"hand", "face_down_cards"}


class PublicKnowledge:
    """Independent oracle: which hand cards has *everyone* seen enter a hand?

    Rebuilt only from public information (each view's face-up slots and the
    public event stream), never from engine internals.
    """

    def __init__(self, n: int) -> None:
        self.known = [set() for _ in range(n)]
        self.face_up = None

    def observe(self, game: dict, events: list[dict]) -> None:
        players = game["players"]
        live = set(game["live"])
        for e in events:
            kind, who = e.get("kind"), e.get("player")
            if kind == "play" and e.get("source") == "hand":
                self.known[who].discard(e["card"])
            elif kind == "pickup":
                self.known[who] |= set(e["cards"])
            elif kind in ("reveal", "face_down") and not e.get("ok"):
                self.known[who].add(e["card"])
            elif kind in ("deal_three", "take_three"):
                self.known[who].add(e["card"])
        if self.face_up is not None:
            for i, p in enumerate(players):
                before = {c for s in self.face_up[i] for c in s}
                now = {c for s in p["face_up"] for c in s}
                for c in before - now - live:  # left a face-up slot, not onto the pile: into the hand
                    self.known[i].add(c)
                self.known[i] -= now - before  # a hand card moved to a slot
        self.face_up = [[list(s) for s in p["face_up"]] for p in players]


def _hidden_from(engine: IBFlipEngine, viewer: int, known: list[set]) -> set[int]:
    st = engine.state
    hidden = set(st.draw_pile)
    for i, p in enumerate(st.players):
        hidden |= {c for c in p.face_down_slots if c is not None}
        if i != viewer:
            hidden |= set(p.hand) - known[i]
    return hidden


def _visible_cards(game: dict, events: list[dict]) -> set[int]:
    cards = set(game["live"]) | set(game["ace_one"]) | set(game.get("hand", []))
    if game["discard_top"] is not None:
        cards.add(game["discard_top"])
    for p in game["players"]:
        cards |= set(p["known"])
        cards |= {c for s in p["face_up"] for c in s}
    for e in events:
        if e.get("kind") == "start":
            continue  # the required start card is announced by the rules
        if isinstance(e.get("card"), int):
            cards.add(e["card"])
        cards |= set(e.get("cards", []))
    return cards


@pytest.mark.parametrize("players", [2, 3, 5])
def test_views_never_leak_hidden_cards(players, monkeypatch):
    checked = 0
    for seed in range(8):
        rng = random.Random(seed)
        room = make_room(players, seed=500 + seed, monkeypatch=monkeypatch)
        engine = room.engine
        oracle = PublicKnowledge(players)
        oracle.observe(room.view_for(0, [])["game"], [])
        # Fixing with random ops, checking after each op.
        for _ in range(30):
            seat = rng.randrange(players)
            p = engine.state.players[seat]
            if p.fixing_done:
                continue
            ops = [("swap", c, k) for c in p.hand for k in range(3)] + [("stack", c, k) for s in p.face_up_slots for c in s for k in range(3)]
            ops += [("stack", c, k) for c in p.hand for k in range(3)] + [("unstack", None, k) for k in range(3)]
            rng.shuffle(ops)
            for op, card, slot in ops:
                try:
                    room.fix(seat, op, card, slot)
                    break
                except IllegalActionError:
                    continue
            events = room.drain_events()
            oracle.observe(room.view_for(0, [])["game"], events)
        for seat in range(players):
            room._ready_with_full_slots(seat) if not engine.state.players[seat].fixing_done else None
        room._after_fixing_check()
        events = room.drain_events()
        group_slot = None
        for _ in range(1200):
            for viewer in range(players):
                game = room.view_for(viewer, events)["game"]
                assert set(game) <= ALLOWED_GAME_KEYS, set(game) - ALLOWED_GAME_KEYS
                for i, p in enumerate(game["players"]):
                    extra = set(p) - ALLOWED_PLAYER_KEYS
                    if room.status != "over":
                        assert not extra, (i, extra)
                    else:
                        assert extra <= OVER_ONLY_PLAYER_KEYS
                if room.status == "over":
                    continue
                hidden = _hidden_from(engine, viewer, oracle.known)
                leaked = _visible_cards(game, events) & hidden
                assert not leaked, f"seat {viewer} sees hidden cards {sorted(leaked)}"
                for i, p in enumerate(game["players"]):
                    assert set(p["known"]) == oracle.known[i], (i, sorted(p["known"]), sorted(oracle.known[i]))
                # Own face-down identities stay hidden as well.
                assert all(isinstance(x, bool) for x in game["players"][viewer]["face_down"])
                checked += 1
            if room.status != "playing":
                break
            st = engine.state
            if st.pending is not None and st.pending.kind.name == "NINE_DRAW":
                room.act(st.current_player, ACTION_RESOLVE_NINE_DRAW)
            else:
                seat = st.current_player
                game = room.view_for(seat, [])["game"]
                if game["group_rank"] is None:
                    group_slot = None
                offered = sorted(client_offered(game, seat, group_slot)["actions"]) or sorted(engine_choices(engine))
                action = rng.choice(offered)
                if action < 52 and game["source"] == "face_up" and group_slot is None:
                    group_slot = next(k for k, s in enumerate(st.players[seat].face_up_slots) if action in s)
                room.act(seat, action)
            events = room.drain_events()
            oracle.observe(room.view_for(0, [])["game"], events)
    assert checked > 1000


# -------------------------------------------------------------- robustness
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="LATENT BUG: room_socket resolves the seat index before handle_message waits for the room lock; "
    "a seat purge in between makes the queued message act for the wrong seat (today no long lock holder "
    "exists while seats can shift, so this is not reachable in normal play)",
)
def test_message_queued_behind_the_lock_acts_for_the_sender_after_seats_shift():
    """Seats: 0 host, 1 left mid-game, 2 Carol, 3 Dave. Game over.

    While the room lock is held (e.g. a bot thinking in asyncio.to_thread),
    the host's rematch and Carol's "leave" both queue. room_socket computed
    Carol's index (2) before waiting. Rematch purges seat 1, so seat 2 is now
    Dave, and Carol's leave removes Dave. Real-world window: messages that
    arrive while the lock is held. Today the only long holder is the bot
    runner (asyncio.to_thread) during fixing/playing, when seats never shift,
    so this is latent: it bites as soon as any locked await is added to a
    lobby/over code path.
    """
    import ibflip_web.main as main

    class FakeConn:
        def __init__(self) -> None:
            self.closed = False
            self.sent: list[dict] = []
            self.social = rooms.TokenBucket(10, 1)

        def send(self, message):
            self.sent.append(message)

        def close(self):
            self.closed = True

    async def scenario():
        room = Room(code="RACEQQ", host=None)
        for name in ("Host", "Leaver", "Carol", "Dave"):
            room.add_human(name)
        conns = [FakeConn() for _ in room.seats]
        for seat, conn in zip(room.seats, conns):
            seat.sockets.append(conn)
        room.start()
        room.status = "over"  # finished game
        room.leave(1)
        carol_token = room.seats[2].token
        carol_index = room.seat_by_token(carol_token)  # what room_socket computes
        await room.lock.acquire()  # someone holds the lock
        host_task = asyncio.create_task(main.handle_message(room, 0, {"type": "rematch"}, conns[0]))
        await asyncio.sleep(0)
        carol_task = asyncio.create_task(main.handle_message(room, carol_index, {"type": "leave"}, conns[2]))
        await asyncio.sleep(0)
        room.lock.release()
        await asyncio.gather(host_task, carol_task)
        if room.runner:
            room.runner.cancel()
        return room, carol_token

    room, carol_token = asyncio.run(scenario())
    names = [s.name for s in room.seats]
    carol = room.seat_by_token(carol_token)
    assert "Dave" in names and not room.seats[names.index("Dave")].left, names
    assert carol is None or room.seats[carol].left, "Carol's leave was applied to someone else"


def test_human_can_trigger_the_forced_nine_draw_early(monkeypatch):
    """Info (not a bug): during a nine draw the client gets no legal moves
    and waits for the server, but the server also accepts action 53 from the
    current player. The draw is random either way, so this only skips the
    pause. Documented so a future change is deliberate."""
    for seed in range(200):
        room = make_room(2, seed=seed, monkeypatch=monkeypatch)
        random_fixing(room, random.Random(seed), Counter())
        rng = random.Random(seed)
        for _ in range(600):
            if room.status != "playing":
                break
            st = room.engine.state
            if st.pending is not None and st.pending.kind.name == "NINE_DRAW":
                game = room.view_for(st.current_player, [])["game"]
                assert game["nine_draw"] and game["legal"] == {"cards": [], "pick_up": False, "reveal": False, "end_group": False, "face_down": []}
                room.act(st.current_player, ACTION_RESOLVE_NINE_DRAW)  # accepted
                return
            room.act(st.current_player, rng.choice(sorted(engine_choices(room.engine))))
    pytest.skip("no nine draw reached")


# ------------------------------------------- real app.js on the same views
def test_real_app_js_legality_matches_engine_on_random_game_views(monkeypatch):
    """Runs app.js isLegalNow / soleLegalAction / autoActFor (via Node) on
    thousands of serialized views and checks them against the engine; this
    also validates the Python mirror used above."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    samples = []
    for seed in range(10):
        players = 2 + seed % 4
        rng = random.Random(seed)
        room = make_room(players, seed=9000 + seed, monkeypatch=monkeypatch)
        random_fixing(room, rng, Counter())
        engine = room.engine
        for _ in range(400):
            if room.status != "playing":
                break
            st = engine.state
            for viewer in range(players):
                samples.append({"seat": viewer, "game": room.view_for(viewer, [])["game"], "engine": sorted(engine_choices(engine)) if viewer == st.current_player and not (st.pending and st.pending.kind.name == "NINE_DRAW") else []})
            if st.pending is not None and st.pending.kind.name == "NINE_DRAW":
                room.act(st.current_player, ACTION_RESOLVE_NINE_DRAW)
                continue
            room.act(st.current_player, rng.choice(sorted(engine_choices(engine))))
    script = Path(__file__).with_name("client_views_check.cjs")
    payload = json.dumps([{"seat": s["seat"], "game": s["game"]} for s in samples])
    result = subprocess.run([node, str(script)], input=payload, capture_output=True, text=True, check=True, timeout=120)
    outputs = json.loads(result.stdout)
    assert len(outputs) == len(samples) > 2000
    for sample, out in zip(samples, outputs):
        game, seat, engine_set = sample["game"], sample["seat"], set(sample["engine"])
        assert set(out["legalNow"]) == engine_set, (game, out)
        assert out["auto"] == auto_act_for(game, seat)
        assert out["sole"] == sole_legal_action(game)
        if out["auto"] is not None:
            assert engine_set == {out["auto"]}
