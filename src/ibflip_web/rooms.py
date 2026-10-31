"""Room / seat management for multiplayer IB-Flip (humans + bots)."""

from __future__ import annotations

import asyncio
import random
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from ibflip import IBFlipEngine, IllegalActionError
from ibflip.ai.agents import HeuristicAgent, NeuralAgent, RandomAgent, heuristic_fix, model_available
from ibflip.ai.observation import is_forced, resolve_forced
from ibflip.state import Phase

from ibflip_web.serialize import serialize_event, serialize_view

MAX_SEATS = 5
BOT_LEVELS = ("easy", "medium", "hard")
BOT_NAMES = ["Ada", "Basil", "Cleo", "Dex", "Echo", "Fern", "Gus", "Hana", "Ivo", "Juno", "Kit", "Luna", "Milo", "Nova", "Otto", "Pip"]
AVATARS = ["🦊", "🐼", "🐯", "🐸", "🐙", "🦉", "🐳", "🦄", "🐝", "🦁", "🐨", "🐧"]
ROOM_TTL_SECONDS = 3 * 3600
AUTOPILOT_AFTER_SECONDS = 45


def _code() -> str:
    alphabet = "".join(c for c in string.ascii_uppercase if c not in "IO")
    return "".join(random.choice(alphabet) for _ in range(4))


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


_NEURAL: NeuralAgent | None = None


def make_agent(level: str):
    global _NEURAL
    if level == "easy":
        return _EasyAgent()
    if level == "hard" and model_available():
        if _NEURAL is None:
            _NEURAL = NeuralAgent()
        return _NEURAL
    return HeuristicAgent()


@dataclass
class Seat:
    kind: str  # "human" | "bot"
    name: str
    avatar: str
    token: str | None = None
    level: str = "medium"
    sockets: list[WebSocket] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    wins: int = 0

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
    bot_delay: float = 0.9
    history: list[dict[str, Any]] = field(default_factory=list)
    agents: dict[int, Any] = field(default_factory=dict)
    chat: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ seats
    def seat_by_token(self, token: str | None) -> int | None:
        if not token:
            return None
        for index, seat in enumerate(self.seats):
            if seat.token and secrets.compare_digest(seat.token, token):
                return index
        return None

    def used_avatars(self) -> set[str]:
        return {s.avatar for s in self.seats}

    def free_avatar(self) -> str:
        free = [a for a in AVATARS if a not in self.used_avatars()]
        return random.choice(free or AVATARS)

    def add_human(self, name: str) -> tuple[int, str]:
        if len(self.seats) >= MAX_SEATS:
            raise ValueError("Room is full")
        if self.status != "lobby":
            raise ValueError("Game already in progress")
        token = secrets.token_urlsafe(16)
        self.seats.append(Seat("human", name[:18] or "Player", self.free_avatar(), token=token))
        if self.host is None:
            self.host = len(self.seats) - 1
        return len(self.seats) - 1, token

    def add_bot(self, level: str = "medium") -> None:
        if len(self.seats) >= MAX_SEATS:
            raise ValueError("Room is full")
        used = {s.name for s in self.seats}
        name = random.choice([n for n in BOT_NAMES if n not in used] or BOT_NAMES)
        self.seats.append(Seat("bot", name, self.free_avatar(), level=level if level in BOT_LEVELS else "medium"))

    def remove_seat(self, index: int) -> None:
        if self.status != "lobby" or not (0 <= index < len(self.seats)):
            raise ValueError("Cannot remove seat now")
        seat = self.seats.pop(index)
        for ws in seat.sockets:
            asyncio.ensure_future(_safe_send(ws, {"type": "kicked"}))
        if self.host is not None:
            if index == self.host:
                humans = [i for i, s in enumerate(self.seats) if s.kind == "human"]
                self.host = humans[0] if humans else None
            elif index < self.host:
                self.host -= 1

    # ------------------------------------------------------------------- game
    def start(self) -> None:
        if len(self.seats) < 2:
            raise ValueError("Need at least two players")
        self.engine = IBFlipEngine(len(self.seats))
        self.engine.reset()
        self.game_no += 1
        self.history = []
        self.agents = {i: make_agent(s.level) for i, s in enumerate(self.seats) if s.kind == "bot"}
        for index, agent in self.agents.items():
            agent.fix(self.engine, index)
            self.engine.fix_done(index)
        self.status = "fixing"
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

    def _check_over(self) -> None:
        engine = self._require_engine()
        if engine.state.phase is Phase.GAME_OVER and self.status != "over":
            self.status = "over"
            if engine.state.winner is not None:
                self.seats[engine.state.winner].wins += 1
            elif engine.state.loser is not None and len(self.seats) == 2:
                self.seats[1 - engine.state.loser].wins += 1

    def _require_engine(self) -> IBFlipEngine:
        if self.engine is None:
            raise IllegalActionError("No game")
        return self.engine

    def touch(self) -> None:
        self.touched = time.time()
        self.wake.set()

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
        events = [serialize_event(e) for e in (raw_events or [])]
        for index, seat in enumerate(self.seats):
            if not seat.sockets:
                continue
            message = self.view_for(index, events)
            for ws in list(seat.sockets):
                await _safe_send(ws, message)

    def drain_events(self) -> list[dict[str, Any]]:
        if self.engine is None:
            return []
        events = self.engine.events
        self.engine.events = []
        return events

    # -------------------------------------------------------------- bot loop
    async def run(self) -> None:
        """Advance bots / forced moves with human-friendly pacing."""
        while True:
            self.wake.clear()
            delay = self._next_auto_delay()
            if delay is None:
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass
                if time.time() - self.touched > ROOM_TTL_SECONDS:
                    return
                continue
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=delay)
                continue  # something changed; re-evaluate
            except asyncio.TimeoutError:
                pass
            async with self.lock:
                if self._next_auto_delay() is None:
                    continue
                self._auto_step()
                await self.broadcast(self.drain_events())

    def _next_auto_delay(self) -> float | None:
        engine = self.engine
        if engine is None or self.status != "playing":
            return None
        if engine.state.phase is Phase.GAME_OVER:
            return None
        if is_forced(engine):
            return self.bot_delay * 0.8
        current = engine.state.current_player
        seat = self.seats[current]
        if seat.kind == "bot":
            # Quicker follow-ups when the same bot is mid-group.
            return self.bot_delay * (0.55 if engine.state.turn_context.played_card_ids else 1.0)
        if not seat.connected:
            waited = time.time() - max(self.turn_started, seat.last_seen)
            return max(0.5, AUTOPILOT_AFTER_SECONDS - waited)
        return None

    def _auto_step(self) -> None:
        engine = self._require_engine()
        if is_forced(engine):
            resolve_forced(engine)
        else:
            current = engine.state.current_player
            agent = self.agents.get(current) or HeuristicAgent()
            action = agent.choose(engine)
            engine.step(action, validate=False)
        self.turn_started = time.time()
        self._check_over()
        self.touched = time.time()


async def _safe_send(ws: WebSocket, message: dict[str, Any]) -> None:
    try:
        await ws.send_json(message)
    except Exception:  # noqa: BLE001 - socket may already be closed
        pass


class RoomRegistry:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def create(self) -> Room:
        self.gc()
        for _ in range(100):
            code = _code()
            if code not in self.rooms:
                break
        room = Room(code=code, host=None)
        self.rooms[code] = room
        return room

    def get(self, code: str) -> Room | None:
        return self.rooms.get(code.upper())

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

    def gc(self) -> None:
        now = time.time()
        for code in [c for c, r in self.rooms.items() if now - r.touched > ROOM_TTL_SECONDS]:
            room = self.rooms.pop(code)
            if room.runner:
                room.runner.cancel()
