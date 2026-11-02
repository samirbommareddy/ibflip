"""FastAPI backend: rooms for friends + bots over WebSockets.

REST
    POST /api/rooms              {name, bots?: [level...], autostart?}  -> {code, token, seat}
    POST /api/rooms/{code}/join  {name}                                  -> {code, token, seat}
    GET  /api/rooms/{code}                                               -> lobby info
WebSocket
    /ws/{code}?token=...   server pushes {"type": "state", ...} after every change.
    client messages (must be JSON objects with a string "type"):
        {"type": "action", "action": <engine action id>}
        {"type": "fix", "op": "swap"|"stack"|"unstack"|"done", "card": id, "slot": i}
        {"type": "add_bot", "level": "easy"|"medium"|"hard"}   (host, lobby)
        {"type": "set_bot", "seat": i, "level": ...}            (host, lobby)
        {"type": "remove", "seat": i, "name"?: "..."}           (host, lobby; "name" guards against stale indexes)
        {"type": "start"} / {"type": "rematch"} / {"type": "lobby"}   (host)
        {"type": "leave"}        give up your seat (lobby) / let a bot finish for you (in game)
        {"type": "chat", "text": "..."} / {"type": "emote", "emoji": "..."}
        {"type": "hint"} / {"type": "ping"} / {"type": "speed", "delay": s} (host)
    server messages: state | error {message, fatal?} | hint {action} | pong |
        chat/emote {seat, text, ts} | kicked | left
    state.events may contain {"kind": "autopilot", "player": i, "reason": "away"|"idle"|"left"}
    when the server moved for a human.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ibflip import IllegalActionError
from ibflip.actions import ACTION_SPACE_SIZE
from ibflip.ai.agents import model_available
from ibflip_web.rooms import (
    BOT_LEVELS,
    MAX_SEATS,
    Conn,
    RoomError,
    RoomRegistry,
    RoomsFullError,
    TokenBucket,
    _safe_send,  # noqa: F401 - re-exported for older callers
    clean_name,
)

log = logging.getLogger("ibflip_web")

app = FastAPI(title="IB-Flip")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

registry = RoomRegistry()
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
ALLOWED_EMOTES = {"👏", "😂", "😱", "🔥", "😤", "🤝", "👀", "💀"}
FIX_OPS = {"swap", "stack", "unstack", "done"}

# How many reverse proxies in front of us append to X-Forwarded-For. Render's
# edge is one; set to 2 if e.g. Cloudflare proxies api.* in front of Render,
# 0 to ignore the header entirely (direct exposure / local dev).
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))


class RateLimiter:
    """Per-client-IP token buckets (in memory; fine for a single instance)."""

    def __init__(self, capacity: float, per_minute: float) -> None:
        self.capacity = capacity
        self.rate = per_minute / 60.0
        self.buckets: dict[str, TokenBucket] = {}

    def allow(self, key: str) -> bool:
        if len(self.buckets) > 10_000:
            self.buckets.clear()
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = TokenBucket(self.capacity, self.rate)
        return bucket.take()


CREATE_LIMIT = RateLimiter(capacity=8, per_minute=6)
JOIN_LIMIT = RateLimiter(capacity=15, per_minute=15)
INFO_LIMIT = RateLimiter(capacity=30, per_minute=30)


def client_ip(request: Request | WebSocket) -> str:
    """The client address as seen by the outermost *trusted* proxy.

    Proxies append to X-Forwarded-For, so the left-most entries are whatever the
    client claimed; only the last TRUSTED_PROXY_HOPS entries are trustworthy.
    """
    peer = request.client.host if request.client else "unknown"
    if TRUSTED_PROXY_HOPS <= 0:
        return peer
    header = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in header.split(",") if h.strip()]
    if not hops:
        return peer
    return hops[-min(TRUSTED_PROXY_HOPS, len(hops))]


def _limit(limiter: RateLimiter, request: Request) -> None:
    if not limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many requests — please wait a moment and try again.")


class CreateRoom(BaseModel):
    name: str = Field("Player", max_length=24)
    bots: list[str] = Field(default_factory=list)
    autostart: bool = False


class JoinRoom(BaseModel):
    name: str = Field("Player", max_length=24)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "rooms": len(registry.rooms), "model": model_available()}


@app.post("/api/rooms")
async def create_room(body: CreateRoom, request: Request) -> dict[str, Any]:
    if len(body.bots) > MAX_SEATS - 1:
        raise HTTPException(400, "Too many bots")
    if body.autostart and not body.bots:
        raise HTTPException(400, "Need at least one bot to autostart")
    _limit(CREATE_LIMIT, request)
    registry.ensure_gc()
    try:
        room = registry.create()
    except RoomsFullError as exc:
        raise HTTPException(503, str(exc)) from exc
    seat, token = room.add_human(clean_name(body.name))
    for level in body.bots:
        room.add_bot(level if level in BOT_LEVELS else "medium")
    if body.autostart:
        room.start()
    registry.ensure_runner(room)
    return {"code": room.code, "token": token, "seat": seat}


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, body: JoinRoom, request: Request) -> dict[str, Any]:
    _limit(JOIN_LIMIT, request)
    registry.ensure_gc()
    room = registry.get(code)
    if room is None:
        raise HTTPException(404, "No room with that code")
    async with room.lock:
        try:
            seat, token = room.add_human(clean_name(body.name))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await room.broadcast()
    registry.ensure_runner(room)
    return {"code": room.code, "token": token, "seat": seat}


@app.get("/api/rooms/{code}")
def room_info(code: str, request: Request) -> dict[str, Any]:
    _limit(INFO_LIMIT, request)
    room = registry.get(code)
    if room is None:
        raise HTTPException(404, "No room with that code")
    return room.lobby_view()


class BadMessage(ValueError):
    pass


def _int_field(message: dict[str, Any], key: str, lo: int, hi: int) -> int:
    value = message.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise BadMessage(f"Bad '{key}'")
    return value


def _decode(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Turn an ASGI websocket.receive message into a JSON object (or None)."""
    text = raw.get("text")
    if text is None and raw.get("bytes") is not None:
        try:
            text = raw["bytes"].decode("utf-8")
        except UnicodeDecodeError:
            return None
    if text is None or len(text) > 4096:
        return None
    try:
        message = json.loads(text)
    except ValueError:
        return None
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        return None
    return message


@app.websocket("/ws/{code}")
async def room_socket(websocket: WebSocket, code: str, token: str = "") -> None:
    room = registry.get(code)
    await websocket.accept()
    if room is None:
        await websocket.send_json({"type": "error", "message": "Room not found", "fatal": True})
        await websocket.close()
        return
    if room.seat_by_token(token) is None:
        await websocket.send_json({"type": "error", "message": "Not a member of this room", "fatal": True})
        await websocket.close()
        return
    registry.ensure_runner(room)
    registry.ensure_gc()
    conn = Conn(websocket)
    async with room.lock:
        seat_index = room.seat_by_token(token)
        if seat_index is None:  # removed while we were connecting
            conn.send({"type": "kicked"})
            conn.close()
            return
        seat = room.seats[seat_index]
        seat.sockets.append(conn)
        seat.last_seen = time.time()
        if seat.left:  # came back to a game they had left: welcome back
            seat.left = False
        await room.broadcast()
    room.touch()
    try:
        while not conn.closed:
            raw = await websocket.receive()
            if raw.get("type") == "websocket.disconnect":
                break
            message = _decode(raw)
            if message is None:
                conn.send({"type": "error", "message": "Bad message"})
                continue
            if not conn.messages.take():
                conn.send({"type": "error", "message": "Slow down a little"})
                continue
            seat_index = room.seat_by_token(token)  # seat index can shift in lobby
            if seat_index is None:
                conn.send({"type": "kicked"})
                conn.close()
                break
            room.seats[seat_index].last_seen = time.time()
            try:
                await handle_message(room, seat_index, message, conn)
            except Exception:  # noqa: BLE001 - never drop the socket for a server bug
                log.exception("room %s: error handling %r", room.code, message.get("type"))
                conn.send({"type": "error", "message": "Something went wrong on the server"})
                async with room.lock:
                    await room.broadcast(room.drain_events())  # resync everyone
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:  # noqa: BLE001
        log.exception("room %s: socket loop failed", room.code)
    finally:
        conn.close()
        async with room.lock:
            index = room.seat_by_token(token)
            if index is not None and conn in room.seats[index].sockets:
                room.seats[index].sockets.remove(conn)
                room.seats[index].last_seen = time.time()
                await room.broadcast()
        room.touch()


async def handle_message(room, seat: int, message: dict[str, Any], conn: Conn) -> None:
    kind = message.get("type")
    if kind in ("chat", "emote", "hint", "ping") and not conn.social.take():
        return  # rate limited: silently drop chatter / hint / ping spam
    async with room.lock:
        is_host = seat == room.host
        try:
            if kind == "action":
                room.act(seat, _int_field(message, "action", 0, ACTION_SPACE_SIZE - 1))
            elif kind == "fix":
                op = message.get("op")
                if op not in FIX_OPS:
                    raise BadMessage("Bad 'op'")
                card = _int_field(message, "card", 0, 51) if op in ("swap", "stack") else None
                slot = _int_field(message, "slot", 0, 2) if op != "done" else None
                room.fix(seat, op, card, slot)
            elif kind == "add_bot" and is_host:
                room.add_bot(str(message.get("level", "medium")))
            elif kind == "set_bot" and is_host:
                room.set_bot(_int_field(message, "seat", 0, MAX_SEATS - 1), str(message.get("level")))
            elif kind == "remove" and is_host:
                name = message.get("name")
                room.remove_seat(
                    _int_field(message, "seat", 0, MAX_SEATS - 1),
                    by=id(conn),
                    expect_name=name if isinstance(name, str) else None,
                )
            elif kind in ("start", "rematch") and is_host:
                if room.status in ("lobby", "over"):
                    room.start()
            elif kind == "lobby" and is_host:
                room.back_to_lobby()
            elif kind == "leave":
                room.leave(seat)
            elif kind == "speed" and is_host:
                delay = message.get("delay", 0.9)
                if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay):
                    raise BadMessage("Bad 'delay'")
                room.bot_delay = min(2.0, max(0.2, float(delay)))
            elif kind in ("chat", "emote"):
                text = str(message.get("text", ""))[:140] if kind == "chat" else str(message.get("emoji", ""))
                if kind == "emote" and text not in ALLOWED_EMOTES:
                    return
                if text.strip():
                    room.send_all({"type": kind, "seat": seat, "text": text, "ts": time.time()})
                return
            elif kind == "hint":
                conn.send({"type": "hint", "action": room.hint(seat)})
                return
            elif kind == "ping":
                conn.send({"type": "pong"})
                return
            else:
                return
        except (IllegalActionError, RoomError, BadMessage) as exc:
            conn.send({"type": "error", "message": str(exc) or "Not allowed"})
            return
        await room.broadcast(room.drain_events())
    room.touch()
    registry.ensure_runner(room)  # self-heal a runner that died for any reason


# Serve the static front-end too (handy locally and as a single deploy).
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{asset}")
    def asset(asset: str) -> FileResponse:
        path = (STATIC_DIR / asset).resolve()
        if path.parent != STATIC_DIR.resolve() or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)
