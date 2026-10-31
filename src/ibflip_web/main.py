"""FastAPI backend: rooms for friends + bots over WebSockets.

REST
    POST /api/rooms              {name, bots?: [level...], autostart?}  -> {code, token, seat}
    POST /api/rooms/{code}/join  {name}                                  -> {code, token, seat}
    GET  /api/rooms/{code}                                               -> lobby info
WebSocket
    /ws/{code}?token=...   server pushes {"type": "state", ...} after every change.
    client messages:
        {"type": "action", "action": <engine action id>}
        {"type": "fix", "op": "swap"|"stack"|"unstack"|"done", "card": id, "slot": i}
        {"type": "add_bot", "level": "easy"|"medium"|"hard"}   (host)
        {"type": "set_bot", "seat": i, "level": ...}            (host)
        {"type": "remove", "seat": i}                           (host)
        {"type": "start"} / {"type": "rematch"}                 (host)
        {"type": "chat", "text": "..."} / {"type": "emote", "emoji": "..."}
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ibflip import IllegalActionError
from ibflip.ai.agents import model_available
from ibflip_web.rooms import BOT_LEVELS, MAX_SEATS, RoomRegistry, _safe_send

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
async def create_room(body: CreateRoom) -> dict[str, Any]:
    if len(body.bots) > MAX_SEATS - 1:
        raise HTTPException(400, "Too many bots")
    room = registry.create()
    seat, token = room.add_human(body.name.strip() or "Player")
    for level in body.bots:
        room.add_bot(level if level in BOT_LEVELS else "medium")
    if body.autostart:
        if len(room.seats) < 2:
            raise HTTPException(400, "Need at least one bot to autostart")
        room.start()
    registry.ensure_runner(room)
    return {"code": room.code, "token": token, "seat": seat}


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, body: JoinRoom) -> dict[str, Any]:
    room = registry.get(code)
    if room is None:
        raise HTTPException(404, "No room with that code")
    async with room.lock:
        try:
            seat, token = room.add_human(body.name.strip() or "Player")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await room.broadcast()
    registry.ensure_runner(room)
    return {"code": room.code, "token": token, "seat": seat}


@app.get("/api/rooms/{code}")
def room_info(code: str) -> dict[str, Any]:
    room = registry.get(code)
    if room is None:
        raise HTTPException(404, "No room with that code")
    return room.lobby_view()


@app.websocket("/ws/{code}")
async def room_socket(websocket: WebSocket, code: str, token: str = "") -> None:
    room = registry.get(code)
    await websocket.accept()
    if room is None:
        await websocket.send_json({"type": "error", "message": "Room not found", "fatal": True})
        await websocket.close()
        return
    seat_index = room.seat_by_token(token)
    if seat_index is None:
        await websocket.send_json({"type": "error", "message": "Not a member of this room", "fatal": True})
        await websocket.close()
        return
    registry.ensure_runner(room)
    room.seats[seat_index].sockets.append(websocket)
    room.seats[seat_index].last_seen = time.time()
    async with room.lock:
        await room.broadcast()
    try:
        while True:
            message = await websocket.receive_json()
            seat_index = room.seat_by_token(token)  # seat index can shift in lobby
            if seat_index is None:
                await websocket.send_json({"type": "kicked"})
                break
            room.seats[seat_index].last_seen = time.time()
            await handle_message(room, seat_index, message, websocket)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        index = room.seat_by_token(token)
        if index is not None and websocket in room.seats[index].sockets:
            room.seats[index].sockets.remove(websocket)
            room.seats[index].last_seen = time.time()
            async with room.lock:
                await room.broadcast()
            room.touch()


async def handle_message(room, seat: int, message: dict[str, Any], websocket: WebSocket) -> None:
    kind = message.get("type")
    is_host = seat == room.host
    async with room.lock:
        try:
            if kind == "action":
                room.act(seat, int(message["action"]))
            elif kind == "fix":
                room.fix(seat, str(message.get("op")), message.get("card"), message.get("slot"))
            elif kind == "add_bot" and is_host:
                room.add_bot(str(message.get("level", "medium")))
            elif kind == "set_bot" and is_host:
                target = int(message["seat"])
                level = str(message.get("level"))
                if room.seats[target].kind == "bot" and level in BOT_LEVELS:
                    room.seats[target].level = level
            elif kind == "remove" and is_host:
                room.remove_seat(int(message["seat"]))
            elif kind in ("start", "rematch") and is_host:
                if room.status in ("lobby", "over"):
                    room.start()
            elif kind == "lobby" and is_host:
                if room.status == "over":
                    room.status = "lobby"
                    room.engine = None
            elif kind == "speed" and is_host:
                room.bot_delay = min(2.0, max(0.2, float(message.get("delay", 0.9))))
            elif kind in ("chat", "emote"):
                text = str(message.get("text", ""))[:140] if kind == "chat" else str(message.get("emoji", ""))
                if kind == "emote" and text not in ALLOWED_EMOTES:
                    return
                if text.strip():
                    note = {"type": kind, "seat": seat, "text": text, "ts": time.time()}
                    for s in room.seats:
                        for ws in list(s.sockets):
                            await _safe_send(ws, note)
                return
            elif kind == "ping":
                await _safe_send(websocket, {"type": "pong"})
                return
            else:
                return
        except (IllegalActionError, ValueError, KeyError, TypeError, IndexError) as exc:
            await _safe_send(websocket, {"type": "error", "message": str(exc) or "Not allowed"})
            return
        await room.broadcast(room.drain_events())
    room.touch()


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
