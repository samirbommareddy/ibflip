"""Room / seat management for multiplayer IB-Flip (humans + bots)."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from fastapi import WebSocket

from ibflip import IBFlipEngine, IllegalActionError
from ibflip.ai.agents import (
    DEFAULT_MODEL_PATH,
    HeuristicAgent,
    MLPPolicy,
    NeuralAgent,
    RandomAgent,
    heuristic_fix,
    loses_immediately,
    model_available,
)
from ibflip.ai.observation import compact_legal, encode, is_forced, resolve_forced
from ibflip.state import Phase

from ibflip_web.serialize import serialize_event, serialize_view

log = logging.getLogger("ibflip_web")

MAX_SEATS = 5
BOT_LEVELS = ("easy", "medium", "hard")
BOT_NAMES = ["Ada", "Basil", "Cleo", "Dex", "Echo", "Fern", "Gus", "Hana", "Ivo", "Juno", "Kit", "Luna", "Milo", "Nova", "Otto", "Pip"]
AVATARS = ["🦊", "🐼", "🐯", "🐸", "🐙", "🦉", "🐳", "🦄", "🐝", "🦁", "🐨", "🐧"]

# Room codes: easy to read aloud and type — no I/L/O (they look like 1/0).
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 6
MAX_ROOMS = 500
# Rooms nobody is connected to expire after this long without activity...
ROOM_TTL_SECONDS = 3 * 3600
# ...or sooner when they are not mid-game (lobby / finished game).
IDLE_LOBBY_TTL_SECONDS = 30 * 60
GC_INTERVAL_SECONDS = 60

# A disconnected human is played for after this long (their turn / readying up).
AUTOPILOT_AFTER_SECONDS = 45
# A connected human who simply doesn't move gets autopiloted after this long.
IDLE_TURN_TIMEOUT_SECONDS = 90
# A human who explicitly left a running game is played for almost at once.
LEFT_AUTOPILOT_SECONDS = 1.0
# If the host has been disconnected this long, the next connected human hosts.
HOST_HANDOFF_SECONDS = 30
# Bot pacing (seconds). The host can change bot_delay via {"type": "speed"}.
DEFAULT_BOT_DELAY = 1.35
BOT_GROUP_FOLLOWUP_FACTOR = 0.7  # same bot adding cards to an open group
FORCED_MOVE_FACTOR = 0.8  # the random 9-draw

# Per-connection outbound queue.
SEND_TIMEOUT_SECONDS = 5.0
SEND_QUEUE_LIMIT = 64
# Ignore a repeated "remove seat i" from the same socket within this window if
# it would now hit a human (a double-click on ✕ must not kick the next player).
REMOVE_DEBOUNCE_SECONDS = 1.0


class RoomError(ValueError):
    """A lobby/room operation that is not allowed right now (shown to the user)."""


class RoomsFullError(RuntimeError):
    pass


def _code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


_WHITESPACE_RE = re.compile(r"\s+")


def clean_name(name: Any, default: str = "Player") -> str:
    """Strip control/format characters, collapse whitespace, cap at 18 chars."""
    text = str(name or "")
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C"))
    text = _WHITESPACE_RE.sub(" ", text).strip()[:18].strip()
    return text or default


class TokenBucket:
    def __init__(self, capacity: float, rate: float) -> None:
        self.capacity = capacity
        self.rate = rate
        self.tokens = capacity
        self.stamp = time.monotonic()

    def take(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.stamp) * self.rate)
        self.stamp = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


_CLOSE = object()


class Conn:
    """One websocket with its own ordered outbound queue.

    Room state is turned into messages under the room lock and *enqueued* here;
    a writer task does the slow network I/O. A client that stops reading can no
    longer stall the room: when its queue overflows or a send times out, the
    socket is closed (the client reconnects and gets a fresh state).
    """

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self.messages = TokenBucket(capacity=300, rate=100)  # everything (flood guard only)
        self.social = TokenBucket(capacity=10, rate=1)  # chat / emote / hint / ping
        self.task = asyncio.get_running_loop().create_task(self._writer())

    def send(self, message: dict[str, Any]) -> None:
        if self.closed:
            return
        if self.queue.qsize() >= SEND_QUEUE_LIMIT:
            log.warning("dropping slow socket (queue full)")
            self.close()
            return
        self.queue.put_nowait(message)

    def close(self) -> None:
        """Flush what is queued, then close the socket."""
        if not self.closed:
            self.closed = True
            self.queue.put_nowait(_CLOSE)

    async def _writer(self) -> None:
        try:
            while True:
                message = await self.queue.get()
                if message is _CLOSE:
                    break
                await asyncio.wait_for(self.ws.send_json(message), SEND_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - socket closed / too slow: drop it
            pass
        self.closed = True
        try:
            await asyncio.wait_for(self.ws.close(), 1.0)
        except Exception:  # noqa: BLE001
            pass


class _EasyAgent:
    """Heuristic most of the time, random the rest: beatable but not silly."""

    name = "easy"

    def __init__(self) -> None:
        self.h = HeuristicAgent()
        self.r = RandomAgent()

    def fix(self, engine: IBFlipEngine, idx: int) -> None:
        if random.random() < 0.5:
            heuristic_fix(engine, idx)

    def choose(self, engine: IBFlipEngine) -> int:
        return self.r.choose(engine) if random.random() < 0.45 else self.h.choose(engine)


_POLICY: MLPPolicy | None = None


def shared_policy() -> MLPPolicy:
    """The trained weights, loaded once and shared (read-only) by every Shark."""
    global _POLICY
    if _POLICY is None:
        _POLICY = MLPPolicy(DEFAULT_MODEL_PATH)
    return _POLICY


def make_agent(level: str):
    if level == "easy":
        return _EasyAgent()
    if level == "hard" and model_available():
        # Own agent per seat (own repetition guard / rng), shared weights.
        return NeuralAgent(shared_policy())
    return HeuristicAgent()


def hint_action(engine: IBFlipEngine) -> int | None:
    """Deterministic, stateless 'best move' for the current player."""
    mask, mapping = compact_legal(engine)
    legal = np.flatnonzero(mask)
    if len(legal) == 0:
        return None
    if len(legal) == 1:
        compact = int(legal[0])
    elif model_available():
        logits = shared_policy().logits(encode(engine, engine.state.current_player), mask)
        for a in np.argsort(-logits, kind="stable"):
            if not mask[a]:
                break
            if loses_immediately(engine, int(a), mapping):
                logits[a] = -1e8
            else:
                break
        compact = int(np.argmax(logits))
    else:
        compact = int(HeuristicAgent(seed=0).choose_compact(engine, mask))
    return mapping[compact][0]


@dataclass
class Seat:
    kind: str  # "human" | "bot"
    name: str
    avatar: str
    token: str | None = None
    level: str = "medium"
    sockets: list[Conn] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    wins: int = 0
    left: bool = False  # human chose to leave a running game
    left_at: float = 0.0

    @property
    def connected(self) -> bool:
        return self.kind == "bot" or bool(self.sockets)

    def public(self, index: int, host: int | None) -> dict[str, Any]:
        return {
            "seat": index,
            "kind": self.kind,
            "name": self.name,
            "avatar": self.avatar,
            "level": self.level if self.kind == "bot" else None,
            "connected": self.connected,
            "host": index == host,
            "wins": self.wins,
            "left": self.left,
        }


@dataclass
class Room:
    code: str
    seats: list[Seat] = field(default_factory=list)
    engine: IBFlipEngine | None = None
    status: str = "lobby"  # lobby | fixing | playing | over
    host: int | None = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)
    game_no: int = 0
    turn_started: float = field(default_factory=time.time)
    runner: asyncio.Task | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    bot_delay: float = DEFAULT_BOT_DELAY
    history: list[dict[str, Any]] = field(default_factory=list)
    agents: dict[int, Any] = field(default_factory=dict)
    chat: list[dict[str, Any]] = field(default_factory=list)
    last_remove: tuple[int, int, float] | None = None

    # ------------------------------------------------------------------ seats
    def seat_by_token(self, token: str | None) -> int | None:
        if not token or not isinstance(token, str):
            return None
        wanted = token.encode("utf-8", "surrogatepass")
        for index, seat in enumerate(self.seats):
            if seat.token and secrets.compare_digest(seat.token.encode(), wanted):
                return index
        return None

    def used_avatars(self) -> set[str]:
        return {s.avatar for s in self.seats}

    def free_avatar(self) -> str:
        free = [a for a in AVATARS if a not in self.used_avatars()]
        return random.choice(free or AVATARS)

    def add_human(self, name: str) -> tuple[int, str]:
        if len(self.seats) >= MAX_SEATS:
            raise RoomError("Room is full")
        if self.status != "lobby":
            raise RoomError("Game already in progress")
        token = secrets.token_urlsafe(16)
        self.seats.append(Seat("human", clean_name(name), self.free_avatar(), token=token))
        if self.host is None:
            self.host = len(self.seats) - 1
        return len(self.seats) - 1, token

    def add_bot(self, level: str = "medium") -> None:
        if self.status != "lobby":
            raise RoomError("Bots can only be added in the lobby")
        if len(self.seats) >= MAX_SEATS:
            raise RoomError("Room is full")
        used = {s.name for s in self.seats}
        name = random.choice([n for n in BOT_NAMES if n not in used] or BOT_NAMES)
        self.seats.append(Seat("bot", name, self.free_avatar(), level=level if level in BOT_LEVELS else "medium"))

    def set_bot(self, index: int, level: str) -> None:
        if self.status != "lobby" or not (0 <= index < len(self.seats)):
            raise RoomError("Cannot change that seat now")
        if self.seats[index].kind == "bot" and level in BOT_LEVELS:
            self.seats[index].level = level

    def remove_seat(self, index: int, *, by: int | None = None, expect_name: str | None = None) -> None:
        if self.status != "lobby" or not (0 <= index < len(self.seats)):
            raise RoomError("Cannot remove seat now")
        target = self.seats[index]
        if expect_name is not None and target.name != expect_name:
            raise RoomError("That seat changed — try again")
        now = time.time()
        if expect_name is None and by is not None and target.kind == "human" and self.last_remove is not None:
            last_by, last_index, last_t = self.last_remove
            if last_by == by and last_index == index and now - last_t < REMOVE_DEBOUNCE_SECONDS:
                return  # double-click on the ✕ of a seat that already went away
        self.last_remove = (by, index, now) if by is not None else None
        self._pop_seat(index)
        for conn in target.sockets:
            conn.send({"type": "kicked"})
            conn.close()

    def _pop_seat(self, index: int) -> Seat:
        seat = self.seats.pop(index)
        if self.host is not None:
            if index == self.host:
                self.host = None
                self._pick_host(prefer_after=index - 1)
            elif index < self.host:
                self.host -= 1
        return seat

    def _pick_host(self, prefer_after: int = -1) -> bool:
        """Hand the host role to the next human (connected ones first)."""
        n = len(self.seats)
        order = [(prefer_after + 1 + k) % n for k in range(n)] if n else []
        humans = [i for i in order if self.seats[i].kind == "human" and not self.seats[i].left and i != self.host]
        connected = [i for i in humans if self.seats[i].connected]
        pick = (connected or humans or [None])[0]
        if pick is None:
            return False
        self.host = pick
        return True

    def leave(self, index: int) -> None:
        """A human leaves on purpose (the "leave" message)."""
        seat = self.seats[index]
        if seat.kind != "human":
            return
        if self.status == "lobby":
            self._pop_seat(index)
        else:
            # Can't renumber seats mid-game; they're played for and dropped on
            # the next start / back-to-lobby.
            seat.left = True
            seat.left_at = time.time()
            if self.host == index:
                self.host = None
                if not self._pick_host(prefer_after=index):
                    self.host = index
        for conn in seat.sockets:
            conn.send({"type": "left"})
            conn.close()
        self.touch()

    def _purge_left_seats(self) -> None:
        for index in reversed(range(len(self.seats))):
            if self.seats[index].left:
                self._pop_seat(index)

    def maybe_handoff_host(self) -> bool:
        """If the host is gone (left, or away for a while), pass the role on."""
        if self.host is not None and 0 <= self.host < len(self.seats):
            seat = self.seats[self.host]
            if seat.connected and not seat.left:
                return False
            if not seat.left and time.time() - seat.last_seen < HOST_HANDOFF_SECONDS:
                return False
        others = [
            i for i, s in enumerate(self.seats) if i != self.host and s.kind == "human" and s.connected and not s.left
        ]
        if not others:
            return False
        return self._pick_host(prefer_after=self.host if self.host is not None else -1)

    def _handoff_due_at(self) -> float | None:
        if self.host is None or not (0 <= self.host < len(self.seats)):
            return None
        seat = self.seats[self.host]
        if seat.connected or seat.left:
            return None
        return seat.last_seen + HOST_HANDOFF_SECONDS

    def back_to_lobby(self) -> None:
        if self.status == "over":
            self.status = "lobby"
            self.engine = None
            self._purge_left_seats()

    # ------------------------------------------------------------------- game
    def start(self) -> None:
        self._purge_left_seats()
        if len(self.seats) < 2:
            raise RoomError("Need at least two players")
        self.engine = IBFlipEngine(len(self.seats))
        self.engine.reset()
        self.game_no += 1
        self.history = []
        self.agents = {i: make_agent(s.level) for i, s in enumerate(self.seats) if s.kind == "bot"}
        for index, agent in self.agents.items():
            agent.fix(self.engine, index)
            self.engine.fix_done(index)
        self.status = "fixing"
        self.turn_started = time.time()
        self._after_fixing_check()
        self.touch()

    def _after_fixing_check(self) -> None:
        assert self.engine is not None
        if self.engine.state.phase is not Phase.FIXING_HANDS:
            self.status = "playing"
            self.turn_started = time.time()

    def fix(self, seat: int, op: str, card: int | None, slot: int | None) -> None:
        engine = self._require_engine()
        if self.status != "fixing":
            raise IllegalActionError("Not fixing now")
        player = engine.state.players[seat]
        if player.fixing_done and op != "undo_done":
            raise IllegalActionError("Already ready")
        if op == "swap":
            engine.fix_swap_card(seat, int(card), int(slot))
        elif op == "stack":
            engine.fix_stack_card(seat, int(card), int(slot))
        elif op == "unstack":
            engine.fix_unstack_card(seat, int(slot))
        elif op == "done":
            engine.fix_done(seat)
            self._after_fixing_check()
        else:
            raise IllegalActionError("Unknown fix op")
        self.touch()

    def act(self, seat: int, action: int) -> None:
        engine = self._require_engine()
        if self.status != "playing" or engine.state.current_player != seat:
            raise IllegalActionError("Not your turn")
        if action not in engine.get_legal_action_indices():
            raise IllegalActionError("Illegal move")
        engine.step(action, validate=False)
        self.turn_started = time.time()
        self._check_over()
        self.touch()

    def hint(self, seat: int) -> int | None:
        """What would the strongest available bot play here? (deterministic)"""
        engine = self._require_engine()
        if self.status != "playing" or engine.state.current_player != seat or is_forced(engine):
            return None
        return hint_action(engine)

    def _check_over(self) -> None:
        engine = self._require_engine()
        if engine.state.phase is Phase.GAME_OVER and self.status != "over":
            self.status = "over"
            # The game runs until everyone is placed; 1st place gets the win.
            if engine.state.winner is not None:
                self.seats[engine.state.winner].wins += 1

    def _require_engine(self) -> IBFlipEngine:
        if self.engine is None:
            raise IllegalActionError("No game")
        return self.engine

    def touch(self) -> None:
        self.touched = time.time()
        self.wake.set()

    def humans_connected(self) -> bool:
        return any(s.kind == "human" and s.sockets for s in self.seats)

    def expired(self, now: float | None = None) -> bool:
        if self.humans_connected():
            return False
        now = time.time() if now is None else now
        ttl = ROOM_TTL_SECONDS if self.status in ("fixing", "playing") else IDLE_LOBBY_TTL_SECONDS
        last = max([self.touched] + [s.last_seen for s in self.seats if s.kind == "human"])
        return now - last > ttl

    # ----------------------------------------------------------- broadcasting
    def lobby_view(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "host": self.host,
            "seats": [s.public(i, self.host) for i, s in enumerate(self.seats)],
            "game_no": self.game_no,
            "hard_available": model_available(),
        }

    def view_for(self, seat: int | None, events: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {"type": "state", "room": self.lobby_view(), "you": seat, "events": events}
        if self.engine is not None and self.status != "lobby":
            payload["game"] = serialize_view(self.engine, seat, self.status)
        return payload

    async def broadcast(self, raw_events: list[dict[str, Any]] | None = None) -> None:
        """Queue a state message for every connected socket (non-blocking).

        Call with the room lock held so every client sees states in the same
        order; the actual network sends happen in each Conn's writer task.
        """
        events = [serialize_event(e) for e in (raw_events or [])]
        for index, seat in enumerate(self.seats):
            if not seat.sockets:
                continue
            message = self.view_for(index, events)
            for conn in list(seat.sockets):
                conn.send(message)

    def send_all(self, message: dict[str, Any]) -> None:
        for seat in self.seats:
            for conn in list(seat.sockets):
                conn.send(message)

    def drain_events(self) -> list[dict[str, Any]]:
        if self.engine is None:
            return []
        events = self.engine.events
        self.engine.events = []
        return events

    # -------------------------------------------------------------- bot loop
    async def run(self) -> None:
        """Advance bots / forced moves / autopilot with human-friendly pacing.

        Every iteration is exception-safe: a crashing bot must never freeze the
        room, so failures are logged and a random legal move is played instead.
        """
        while not self.expired():
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("room %s: runner iteration failed", self.code)
                await asyncio.sleep(0.5)

    async def _run_once(self) -> None:
        self.wake.clear()
        deadline = self._next_auto_deadline()
        if deadline is None:
            handoff = self._handoff_due_at()
            idle_wait = 10.0 if handoff is None else min(10.0, max(0.05, handoff - time.time()))
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=idle_wait)
            except asyncio.TimeoutError:
                pass
            async with self.lock:
                if self.maybe_handoff_host():
                    await self.broadcast()
            return
        remaining = deadline - time.time()
        if remaining > 0:
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=remaining)
                return  # something changed; re-evaluate
            except asyncio.TimeoutError:
                pass
        async with self.lock:
            # Re-check under the lock: a human may have moved (or reconnected)
            # right as the timer fired; never take a move that isn't due.
            deadline = self._next_auto_deadline()
            if deadline is None or deadline > time.time() + 0.01:
                return
            try:
                # Bot thinking (search) runs off the event loop so other rooms
                # stay responsive; the room lock keeps state stable.
                await asyncio.to_thread(self._auto_step)
            except Exception:  # noqa: BLE001
                log.exception("room %s: bot move failed; playing a random legal move", self.code)
                self._fallback_step()
            self.maybe_handoff_host()
            await self.broadcast(self.drain_events())

    def _human_deadline(self, seat: Seat, since: float) -> float:
        if seat.left:
            return max(since, seat.left_at) + LEFT_AUTOPILOT_SECONDS
        if not seat.connected:
            return max(since, seat.last_seen) + AUTOPILOT_AFTER_SECONDS
        return since + IDLE_TURN_TIMEOUT_SECONDS

    def _fix_deadlines(self) -> dict[int, float]:
        engine = self.engine
        if engine is None or self.status != "fixing":
            return {}
        return {
            i: self._human_deadline(seat, self.turn_started)
            for i, seat in enumerate(self.seats)
            if seat.kind == "human" and not engine.state.players[i].fixing_done
        }

    def _next_auto_deadline(self) -> float | None:
        """When the runner should next move on someone's behalf (or None)."""
        engine = self.engine
        if engine is not None and self.status == "fixing":
            deadlines = self._fix_deadlines()
            return min(deadlines.values()) if deadlines else None
        if engine is None or self.status != "playing":
            return None
        if engine.state.phase is Phase.GAME_OVER:
            return None
        if is_forced(engine):
            return self.turn_started + self.bot_delay * FORCED_MOVE_FACTOR
        current = engine.state.current_player
        seat = self.seats[current]
        if seat.kind == "bot":
            # Quicker follow-ups when the same bot is mid-group.
            factor = BOT_GROUP_FOLLOWUP_FACTOR if engine.state.turn_context.played_card_ids else 1.0
            return self.turn_started + self.bot_delay * factor
        return self._human_deadline(seat, self.turn_started)

    def _note_autopilot(self, index: int) -> None:
        seat = self.seats[index]
        reason = "left" if seat.left else ("away" if not seat.connected else "idle")
        assert self.engine is not None
        self.engine.events.append({"kind": "autopilot", "player": index, "reason": reason})

    def _auto_step(self) -> None:
        engine = self._require_engine()
        now = time.time()
        if self.status == "fixing":
            for i, deadline in self._fix_deadlines().items():
                if now >= deadline - 0.01:
                    self._note_autopilot(i)
                    heuristic_fix(engine, i)
                    engine.fix_done(i)
            self._after_fixing_check()
            self.touched = time.time()
            return
        if is_forced(engine):
            resolve_forced(engine)
        else:
            current = engine.state.current_player
            agent = self.agents.get(current)
            if agent is None:
                self._note_autopilot(current)
                agent = HeuristicAgent()
            action = agent.choose(engine)
            if action not in engine.get_legal_action_indices():
                raise IllegalActionError(f"bot chose illegal action {action}")
            engine.step(action, validate=False)
        self.turn_started = time.time()
        self._check_over()
        self.touched = time.time()

    def _fallback_step(self) -> None:
        """Last resort after a bot crash: any legal move keeps the game alive."""
        engine = self.engine
        try:
            if engine is None:
                return
            if self.status == "fixing":
                now = time.time()
                for i, deadline in self._fix_deadlines().items():
                    if now >= deadline - 0.01:
                        engine.fix_done(i)
                self._after_fixing_check()
            elif self.status == "playing" and engine.state.phase is not Phase.GAME_OVER:
                legal = engine.get_legal_action_indices()
                if legal:
                    engine.step(random.choice(legal), validate=False)
                self._check_over()
        finally:
            self.turn_started = time.time()
            self.touched = time.time()


async def _safe_send(ws: WebSocket | Conn, message: dict[str, Any]) -> None:
    """Back-compat helper: enqueue on a Conn, or send directly on a raw socket."""
    if isinstance(ws, Conn):
        ws.send(message)
        return
    try:
        await asyncio.wait_for(ws.send_json(message), SEND_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 - socket may already be closed
        pass


class RoomRegistry:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.gc_task: asyncio.Task | None = None

    def create(self) -> Room:
        self.gc()
        if len(self.rooms) >= MAX_ROOMS:
            raise RoomsFullError("The server is busy right now — too many open rooms. Please try again in a few minutes.")
        for _ in range(100):
            code = _code()
            if code not in self.rooms:
                break
        else:
            raise RoomsFullError("Couldn't allocate a room code — please try again.")
        room = Room(code=code, host=None)
        self.rooms[code] = room
        return room

    def discard(self, room: Room) -> None:
        if self.rooms.get(room.code) is room:
            del self.rooms[room.code]
        if room.runner is not None:
            room.runner.cancel()

    def get(self, code: str) -> Room | None:
        return self.rooms.get(code.strip().upper())

    def ensure_runner(self, room: Room) -> None:
        loop = asyncio.get_running_loop()
        if room.runner is not None and not room.runner.done() and room.runner.get_loop() is loop:
            return
        if room.runner is not None and room.runner.get_loop() is not loop:
            # A different event loop (e.g. test clients): rebuild primitives.
            room.runner.cancel()
            room.wake = asyncio.Event()
            room.lock = asyncio.Lock()
        room.runner = loop.create_task(room.run())

    def ensure_gc(self) -> None:
        """Start the periodic garbage collector on the running loop (idempotent)."""
        loop = asyncio.get_running_loop()
        if self.gc_task is not None and not self.gc_task.done() and self.gc_task.get_loop() is loop:
            return
        self.gc_task = loop.create_task(self._gc_loop())

    async def _gc_loop(self) -> None:
        while True:
            await asyncio.sleep(GC_INTERVAL_SECONDS)
            try:
                self.gc()
            except Exception:  # noqa: BLE001
                log.exception("room gc failed")

    def gc(self) -> None:
        now = time.time()
        for code in [c for c, r in self.rooms.items() if r.expired(now)]:
            room = self.rooms.pop(code)
            if room.runner:
                room.runner.cancel()
