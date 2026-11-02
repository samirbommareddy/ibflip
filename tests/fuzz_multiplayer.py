"""Multiplayer protocol fuzzer for IB-Flip.

Runs the real FastAPI app under uvicorn in-process (so the registry can be
inspected and exceptions logged) and drives it with real websocket clients that
behave like static/app.js.

Not collected by pytest (slow). Run manually:

    uv run python tests/fuzz_multiplayer.py [ROOMS] [SEED] [scenario,scenario,...]

Scenarios: quick multi double stale reconnect leave simul garbage lobby.
"simul" / "garbage" / "double" send overlapping messages, so "fresh advertised
action rejected" reports there can be attribution noise (the protocol has no
request ids); every other PROBLEM line is a real finding.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time
import traceback
from collections import Counter, defaultdict

import httpx
import uvicorn
from websockets.asyncio.client import connect

import ibflip_web.main as main
import ibflip_web.rooms as rooms

A_PICKUP, A_REVEAL, A_END, A_FACEDOWN = 52, 54, 55, 67

PROBLEMS: list[str] = []
FIX_ERRORS = {"Not fixing now", "Already ready", "illegal swap", "illegal stack", "can only stack matching ranks", "nothing to take back", "hand already full"}
STATS = Counter()
PORT = int(__import__("os").environ.get("FUZZ_PORT", random.randint(18000, 19999)))


def problem(msg: str) -> None:
    if len(PROBLEMS) < 400:
        PROBLEMS.append(msg)
    print("PROBLEM:", msg, flush=True)


# ---------------------------------------------------------------- instrument
_orig_handle = main.handle_message


async def logged_handle(room, seat, message, websocket):
    try:
        return await _orig_handle(room, seat, message, websocket)
    except Exception as exc:  # noqa: BLE001
        problem(f"handle_message exception {type(exc).__name__}: {exc} msg={message} room={room.code}\n{traceback.format_exc()}")
        raise


main.handle_message = logged_handle

_orig_run = rooms.Room.run


async def logged_run(self):
    try:
        return await _orig_run(self)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        problem(f"runner crashed in room {self.code}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        raise


rooms.Room.run = logged_run

_orig_broadcast = rooms.Room.broadcast


async def checked_broadcast(self, raw_events=None):
    eng = self.engine
    if eng is not None and self.status != "lobby":
        st = eng.state
        cards = list(st.draw_pile) + list(st.live_cards) + list(st.discard_pile)
        for p in st.players:
            cards += p.hand + [c for s in p.face_up_slots for c in s] + [c for c in p.face_down_slots if c is not None]
        if sorted(cards) != list(range(52)):
            dup = [c for c, n in Counter(cards).items() if n > 1]
            problem(f"card conservation broken room {self.code}: n={len(cards)} dup={dup}")
    return await _orig_broadcast(self, raw_events)


rooms.Room.broadcast = checked_broadcast

_orig_auto = rooms.Room._auto_step


def traced_auto_step(self):
    eng = self.engine
    if eng is not None and self.status == "playing":
        from ibflip.ai.observation import is_forced

        cur = eng.state.current_player
        seat = self.seats[cur]
        if seat.kind == "human" and seat.connected and not is_forced(eng):
            waited = time.time() - max(self.turn_started, seat.last_seen)
            problem(f"autopilot moved for CONNECTED human seat {cur} in room {self.code} (waited {waited:.2f}s)")
    return _orig_auto(self)


rooms.Room._auto_step = traced_auto_step



def options_from(game: dict) -> list[int]:
    """Exactly what app.js lets the user click."""
    legal = game.get("legal") or {}
    opts = []
    src = game.get("source")
    me_hand = set(game.get("hand", []))
    for c in legal.get("cards", []):
        if src == "hand" and c in me_hand:
            opts.append(c)
        elif src == "face_up":
            opts.append(c)
        else:
            problem(f"legal card {c} not clickable in UI (source={src}, hand={sorted(me_hand)})")
    if legal.get("end_group"):
        opts.append(A_END)
    if legal.get("pick_up"):
        opts.append(A_PICKUP)
    if legal.get("reveal"):
        opts.append(A_REVEAL)
    opts += [A_FACEDOWN + k for k in legal.get("face_down", [])]
    return opts


def public_part(game: dict) -> str:
    g = {k: v for k, v in game.items() if k not in ("hand", "legal", "source")}
    return json.dumps(g, sort_keys=True)


class Client:
    def __init__(self, base: str, code: str, token: str, seat: int, name: str, rng: random.Random, mode: str = "normal"):
        self.base, self.code, self.token, self.seat, self.name = base, code, token, seat, name
        self.rng = rng
        self.mode = mode
        self.ws = None
        self.state = None
        self.pending = False
        self.history: list[tuple[int, str]] = []  # (game_no, public snapshot)
        self.errors: list[str] = []
        self.last_sent = None  # (action, state_public)
        self.stop = False
        self.kicked = False
        self.fatal = False
        self.connected_since_game: set[int] = set()
        self.recv_count = 0
        self.prev_states: list[dict] = []
        self.fix_ops = 0
        self.inflight = 0
        self.left = False
        self.last_err_t = 0.0
        self.n_states = 0
        self.queue = None
        self.reader = None
        self.drops = 0

    async def open(self):
        url = f"{self.base.replace('http', 'ws')}/ws/{self.code}?token={self.token}"
        ws = await connect(url, proxy=None, open_timeout=10)
        self.ws = ws
        self.pending = False
        self.queue = asyncio.Queue()
        queue = self.queue

        async def reader():
            try:
                async for raw in ws:
                    queue.put_nowait(raw)
                if not self.left:
                    print("CLOSED", self.name, ws.close_code, ws.close_reason, flush=True)
            except Exception as exc:  # noqa: BLE001
                if not self.left:
                    print("DROP", self.name, type(exc).__name__, exc, flush=True)
            queue.put_nowait(None)

        self.reader = asyncio.create_task(reader())

    async def close(self):
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.ws = None

    async def send(self, msg):
        if self.ws is None:
            return
        self.inflight += 1
        try:
            await self.ws.send(json.dumps(msg))
        except Exception:
            pass

    async def recv(self, timeout=0.05):
        if self.ws is None:
            await asyncio.sleep(timeout)
            return None
        try:
            if timeout <= 0:
                raw = self.queue.get_nowait()
            else:
                raw = await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return None
        if raw is None:
            self.ws = None
            self.drops += 1
            if not self.left:
                STATS["unexpected_socket_drops"] += 1
            return None
        self.recv_count += 1
        return json.loads(raw)

    def on_msg(self, msg) -> None:
        t = msg["type"]
        if t == "state":
            self.n_states += 1
            self.pending = False
            self.inflight = 0
            if self.state is not None:
                self.prev_states.append(self.state)
                self.prev_states = self.prev_states[-6:]
            self.state = msg
            if msg["you"] != self.seat:
                # seat can legitimately shift in lobby
                self.seat = msg["you"]
            g = msg.get("game")
            if g:
                self.history.append((msg["room"]["game_no"], public_part(g)))
                me = g["players"][self.seat]
                if g.get("hand") is not None and len(g["hand"]) != me["hand_count"]:
                    problem(f"{self.name}: hand len {len(g['hand'])} != hand_count {me['hand_count']}")
                if g["status"] == "playing" and g["current"] == self.seat and not g["nine_draw"] and not options_from(g):
                    problem(f"{self.name}: my turn but no legal options; phase={g['phase']} live={g['live']}")
        elif t == "error":
            if msg["message"] not in FIX_ERRORS or (self.state or {}).get("game", {}).get("status") == "fixing":
                self.pending = False
            self.errors.append(msg["message"])
            self.last_err_t = time.time()
            if msg.get("fatal"):
                self.fatal = True
        elif t == "kicked":
            self.kicked = True

    async def pump(self, timeout=0.05):
        if self.ws is None and not self.left and not self.kicked and not self.fatal:
            # app.js reconnects 1.5 s after an unexpected close
            await asyncio.sleep(0.2)
            await self.open()
        msg = await self.recv(timeout)
        while msg is not None:
            self.on_msg(msg)
            if msg["type"] == "error" and msg["message"] not in FIX_ERRORS and self.last_sent is not None:
                action, snap_id = self.last_sent
                self.last_sent = None
                same_as_prev = bool(self.prev_states) and "game" in self.prev_states[-1] and public_part(self.prev_states[-1]["game"]) == public_part(self.state["game"])
                if same_as_prev:
                    STATS["ui_resend_after_presence_broadcast"] += 1
                elif snap_id == id(self.state) and self.inflight == 1 and self.mode == "normal" and getattr(self, "scenario", "") != "simul":
                    problem(f"[{getattr(self, 'scenario', '?')}] {self.name}: fresh advertised action {action} rejected: {msg['message']} game={self.state.get('game', {}).get('legal')} srv_cur={main.registry.get(self.code).engine.state.current_player} srv_legal={main.registry.get(self.code).engine.get_legal_action_indices()} my_conn={main.registry.get(self.code).seats[self.seat].connected} view_cur={self.state['game']['current']} seat={self.seat} hist_tail={[e.get('kind') for e in self.state.get('events', [])]}")
            msg = await self.recv(0)

    def my_turn(self):
        s = self.state
        if not s or "game" not in s:
            return False
        g = s["game"]
        return g["status"] == "playing" and g["current"] == self.seat

    async def act(self, action):
        if self.pending and self.mode == "normal":
            return
        self.pending = True
        STATS["actions"] += 1
        await self.send({"type": "action", "action": action})
        self.last_sent = (action, id(self.state)) if self.inflight == 1 else None

    async def step(self):
        """Do whatever the UI user would do now."""
        s = self.state
        if not s or "game" not in s:
            return
        g = s["game"]
        if g["status"] == "fixing":
            me = g["players"][self.seat]
            if me["ready"] or self.pending:
                return
            if self.fix_ops < 3 and self.rng.random() < 0.6 and g["hand"]:
                card = self.rng.choice(g["hand"])
                k = self.rng.randrange(3)
                slot = me["face_up"][k]
                op = "stack" if slot and slot[-1] // 4 == card // 4 else "swap"
                self.fix_ops += 1
                self.pending = True
                await self.send({"type": "fix", "op": op, "card": card, "slot": k})
            else:
                self.fix_ops = 0
                self.pending = True
                await self.send({"type": "fix", "op": "done"})
            return
        if not self.my_turn() or self.pending:
            return
        opts = options_from(g)
        if not opts:
            return
        # Prefer card plays to keep games moving; sometimes end group.
        a = self.rng.choice(opts)
        if self.mode == "double":
            await self.act(a)
            await self.send({"type": "action", "action": a})
            STATS["dup_sends"] += 1
            return
        if self.mode == "stale" and self.prev_states and self.rng.random() < 0.3:
            old = self.rng.choice(self.prev_states).get("game")
            if old:
                o = options_from(old)
                if o:
                    await self.send({"type": "action", "action": self.rng.choice(o)})
                    STATS["stale_sends"] += 1
        await self.act(a)


async def wait_for(pred, clients, timeout):
    end = time.time() + timeout
    while time.time() < end:
        for c in clients:
            await c.pump(0.01)
        if pred():
            return True
    return False


async def play_room(base: str, http: httpx.AsyncClient, scenario: str, rng: random.Random, games: int = 2):
    """One room, several games, with a scenario of adversarial behaviour."""
    n_humans = rng.randint(1, 4)
    n_bots = rng.randint(0 if n_humans > 1 else 1, 5 - n_humans)
    clients: list[Client] = []
    if scenario == "quick":
        n_humans = 1
        n_bots = rng.randint(1, 4)
        r = (await http.post("/api/rooms", json={"name": "Q", "bots": [rng.choice(["easy", "medium", "hard"]) for _ in range(n_bots)], "autostart": True})).json()
        code = r["code"]
        clients.append(Client(base, code, r["token"], r["seat"], "H0", random.Random(rng.random())))
    else:
        r = (await http.post("/api/rooms", json={"name": "H0"})).json()
        code = r["code"]
        clients.append(Client(base, code, r["token"], r["seat"], "H0", random.Random(rng.random())))
        for i in range(1, n_humans):
            j = (await http.post(f"/api/rooms/{code}/join", json={"name": f"H{i}"})).json()
            clients.append(Client(base, code, j["token"], j["seat"], f"H{i}", random.Random(rng.random())))
    room = main.registry.get(code)
    room.bot_delay = 0.0
    modes = {"double": "double", "stale": "stale"}
    for c in clients:
        c.mode = modes.get(scenario, "normal") if c.rng.random() < 0.7 else "normal"
        c.scenario = scenario
        await c.open()
    host = clients[0]
    await wait_for(lambda: host.state is not None, clients, 5)
    if scenario != "quick":
        for _ in range(n_bots):
            await host.send({"type": "add_bot", "level": rng.choice(["easy", "medium", "hard"])})
        await wait_for(lambda: host.state and len(host.state["room"]["seats"]) == n_humans + n_bots, clients, 5)
        await host.send({"type": "start"})
    STATS[f"rooms_{scenario}"] += 1
    left: set[str] = set()
    games_done = 0
    last_change = time.time()
    last_snap = None
    seen_over_for = 0
    deadline = time.time() + 120
    while games_done < games and time.time() < deadline:
        for c in clients:
            if c.name in left:
                continue
            await c.pump(0.003)
        for c in clients:
            if c.name in left or c.ws is None:
                continue
            await c.step()
        present = [c for c in clients if c.name not in left]
        host = next((c for c in present if c.state and c.state["room"]["host"] == c.seat), present[0])
        # adversarial lifecycle events
        g = host.state.get("game") if host.state else None
        if g and g["status"] == "playing":
            if scenario == "reconnect" and rng.random() < 0.01:
                c = rng.choice(clients)
                if c.name not in left:
                    c.left = True
                    await c.close()
                    c.left = False
                    await asyncio.sleep(rng.random() * 0.2)
                    await c.open()
                    c.pending = False
                    ok = await wait_for(lambda: c.state is not None and c.ws is not None, [c], 2)
                    STATS["reconnects"] += 1
            if scenario == "leave" and len(clients) > 1 and not left and rng.random() < 0.01:
                c = rng.choice(clients)  # may be the host: hosting must pass on
                c.left = True
                if rng.random() < 0.5:
                    await c.send({"type": "leave"})
                    await asyncio.sleep(0.05)
                    STATS["leave_msgs"] += 1
                await c.close()
                left.add(c.name)
                STATS["leaves"] += 1
            if scenario == "simul" and rng.random() < 0.2:
                # every human fires their current best guess at the same instant
                sends = []
                for c in clients:
                    if c.name in left or not c.state or "game" not in c.state:
                        continue
                    o = options_from(c.state["game"]) or [rng.randrange(52)]
                    sends.append(c.send({"type": "action", "action": rng.choice(o)}))
                await asyncio.gather(*sends)
                STATS["simul_bursts"] += 1
            if scenario == "garbage" and rng.random() < 0.02:
                c = rng.choice(clients)
                junk = rng.choice([
                    {"type": "action", "action": rng.randrange(-5, 80)},
                    {"type": "action"},
                    {"type": "action", "action": "x"},
                    {"type": "fix", "op": "swap", "card": 3, "slot": 9},
                    {"type": "set_bot", "seat": -1, "level": "easy"},
                    {"type": "set_bot", "seat": 99, "level": "easy"},
                    {"type": "remove", "seat": 1},
                    {"type": "speed", "delay": "fast"},
                    {"type": "hint"},
                    {"type": "lobby"},
                    {"type": "start"},
                    {"type": "chat", "text": "hi"},
                    {"type": "emote", "emoji": "👏"},
                    [1, 2, 3],
                    "hello",
                ])
                await c.send(junk)
                STATS["garbage"] += 1
        # stall / progress
        snap = host.history[-1] if host.history else None
        if snap != last_snap:
            last_snap = snap
            last_change = time.time()
        if g and g["status"] in ("playing", "fixing") and time.time() - last_change > 6:
            cur = g["current"]
            seat = host.state["room"]["seats"][cur] if cur is not None else None
            eng = room.engine
            problem(
                f"[{scenario}] STALL room {code}: status={g['status']} current={cur} seat={seat} phase={g['phase']} "
                f"engine_phase={eng.state.phase if eng else None} pending={eng.state.pending if eng else None} "
                f"runner_done={room.runner.done() if room.runner else None} ready={[p['ready'] for p in g['players']]} "
                f"clients={[ (c.name, c.seat, c.pending, c.inflight, c.ws is not None, c.errors[-3:]) for c in clients]} "
                f"engine_legal={eng.get_legal_action_indices() if eng else None} "
                f"views={[(c.name, c.state['game'].get('legal'), c.state['game']['current']) for c in clients if c.state and 'game' in c.state]} "
                f"engine_current={eng.state.current_player if eng else None} lock_held={room.lock.locked()} "
                f"client_states={[c.n_states for c in clients]} "
                f"last_err_age={[round(time.time() - c.last_err_t, 2) for c in clients]}"
            )
            import io
            for t in asyncio.all_tasks():
                buf = io.StringIO()
                t.print_stack(file=buf)
                txt = buf.getvalue()
                if "broadcast" in txt or "_safe_send" in txt or "handle_message" in txt:
                    print("STUCK TASK:", txt[-1500:])
            break
        if g and g["status"] == "over" and host.state["room"]["game_no"] != seen_over_for:
            seen_over_for = host.state["room"]["game_no"]
            games_done += 1
            STATS["games"] += 1
            await asyncio.sleep(0.05)
            for c in clients:
                await c.pump(0.02)
            # compare final views across connected clients
            finals = {}
            for c in clients:
                if c.name in left or not c.state or "game" not in c.state:
                    continue
                cg = c.state["game"]
                if c.state["room"]["game_no"] == seen_over_for:
                    finals[c.name] = public_part(cg)
            if len(set(finals.values())) > 1:
                problem(f"[{scenario}] final views diverge in room {code}")
            if games_done < games:
                present = [c for c in clients if c.name not in left]

                def has_host():
                    return any(c.state and c.state["room"]["host"] == c.seat for c in present)

                if not await wait_for(has_host, present, 15):
                    problem(f"[{scenario}] nobody present is host after host left: {host.state['room']}")
                    break
                host = next(c for c in present if c.state and c.state["room"]["host"] == c.seat)
                if rng.random() < 0.5:
                    await host.send({"type": "rematch"})
                else:
                    await host.send({"type": "lobby"})
                    await wait_for(lambda: host.state["room"]["status"] == "lobby", clients, 3)
                    if host.state["room"]["status"] != "lobby":
                        problem(f"[{scenario}] lobby request ignored")
                    await host.send({"type": "start"})
                ok = await wait_for(
                    lambda: host.state["room"]["game_no"] == seen_over_for + 1 and host.state.get("game", {}).get("status") in ("fixing", "playing"),
                    clients,
                    5,
                )
                if not ok:
                    problem(f"[{scenario}] rematch did not start a new game: room={host.state['room']} ")
                    break
                for c in clients:
                    c.pending = False
                last_change = time.time()
    else:
        if games_done < games:
            problem(f"[{scenario}] room {code} timed out: games_done={games_done}")

    # sequence divergence among clients that stayed connected the whole time
    for _ in range(5):
        for c in clients:
            if c.name not in left:
                await c.pump(0.02)
    stayed = [c for c in clients if c.name not in left]
    if scenario not in ("reconnect",) and len(stayed) > 1:
        def dedup(h):
            out = []
            for item in h:
                if not out or out[-1] != item:
                    out.append(item)
            return out
        base_seq = dedup(stayed[0].history)
        for c in stayed[1:]:
            seq = dedup(c.history)
            # clients may have joined later; compare common suffix
            a, b = (seq, base_seq) if len(seq) <= len(base_seq) else (base_seq, seq)
            ok = not a
            for start in [i for i, x in enumerate(b) if a and x == a[0]]:
                if b[start:start + len(a)] == a[: len(b) - start]:
                    ok = True
                    break
            if not ok:
                problem(f"[{scenario}] public state sequence diverges between {stayed[0].name} and {c.name} in room {code}")
                break
    for c in clients:
        bad = [e for e in c.errors if e not in ("Not your turn", "Illegal move", "Already ready", "Not fixing now")]
        STATS["errors_total"] += len(c.errors)
        for e in set(bad):
            STATS[f"err:{e[:60]}"] += 1
        await c.close()
    return code


async def lobby_fuzz(base: str, http: httpx.AsyncClient, rng: random.Random, steps: int = 120):
    """Lobby lifecycle: nobody may be kicked unless the host removed exactly them."""
    r = (await http.post("/api/rooms", json={"name": "H0"})).json()
    code = r["code"]
    room = main.registry.get(code)
    clients = {"H0": Client(base, code, r["token"], r["seat"], "H0", random.Random(rng.random()))}
    await clients["H0"].open()
    victims: set[str] = set()  # removed by the host on purpose
    gone: set[str] = set()  # sent "leave"
    offline: set[str] = set()
    n = 1
    STATS["rooms_lobby"] += 1

    async def settle():
        live = [c for k, c in clients.items() if k not in offline and k not in gone]
        await wait_for(lambda: False, live, 0.08)

    for _ in range(steps):
        await settle()
        live = {k: c for k, c in clients.items() if k not in offline and k not in gone and k not in victims}
        host = next((c for c in live.values() if c.state and c.state["room"]["host"] == c.seat), None)
        op = rng.choice(["join", "join", "bot", "remove", "dblremove", "drop", "back", "leave", "idle", "setbot"])
        STATS[f"lobby_op_{op}"] += 1
        if op == "join" and len(room.seats) < 5:
            name = f"H{n}"
            n += 1
            j = await http.post(f"/api/rooms/{code}/join", json={"name": name})
            if j.status_code == 200:
                jj = j.json()
                clients[name] = Client(base, code, jj["token"], jj["seat"], name, random.Random(rng.random()))
                await clients[name].open()
        elif op == "bot" and host:
            await host.send({"type": "add_bot", "level": "easy"})
        elif op == "setbot" and host:
            await host.send({"type": "set_bot", "seat": rng.randrange(-2, 6), "level": "hard"})
        elif op in ("remove", "dblremove") and host and host.state:
            seats = host.state["room"]["seats"]
            idx = rng.randrange(len(seats))
            if idx == host.seat:
                continue
            target = seats[idx]
            if target["kind"] == "human":
                victims.add(target["name"])
            await host.send({"type": "remove", "seat": idx})
            if op == "dblremove":  # the UI's ✕ double-clicked: same index again
                await host.send({"type": "remove", "seat": idx})
        elif op == "drop" and live:
            k = rng.choice(list(live))
            live[k].left = True
            await live[k].close()
            offline.add(k)
        elif op == "back" and offline:
            k = rng.choice(sorted(offline))
            offline.discard(k)
            c = clients[k]
            c.left = False
            c.kicked = c.fatal = False
            await c.open()
        elif op == "leave" and live:
            k = rng.choice(list(live))
            live[k].left = True
            await live[k].send({"type": "leave"})
            await asyncio.sleep(0.05)
            await live[k].close()
            gone.add(k)
        elif op == "idle":
            # backgrounded tabs: nobody sends anything (no app pings) for a while
            await asyncio.sleep(rng.uniform(0.5, 2.5))
        await settle()
        # ------------------------------------------------------------ checks
        for k, c in clients.items():
            if k in offline or k in gone:
                continue
            if (c.kicked or c.fatal) and k not in victims:
                problem(f"[lobby] {k} was kicked/fatal without being removed (room {code}) errors={c.errors[-3:]}")
                victims.add(k)
            if k in victims:
                continue
            if c.state:
                you = c.state["you"]
                srv = room.seat_by_token(c.token)
                if srv != you:
                    problem(f"[lobby] {k}: view says seat {you}, server token seat {srv}")
                elif c.state["room"]["seats"][you]["name"] != k:
                    problem(f"[lobby] {k}: seat {you} in its view is {c.state['room']['seats'][you]['name']}")
        h = room.host
        humans = [i for i, s in enumerate(room.seats) if s.kind == "human"]
        if humans and (h is None or not (0 <= h < len(room.seats)) or room.seats[h].kind != "human"):
            problem(f"[lobby] host index invalid: host={h} seats={[(s.kind, s.name) for s in room.seats]}")
        connected_humans = [i for i in humans if room.seats[i].sockets]
        if connected_humans and h is not None and h < len(room.seats) and not room.seats[h].sockets:
            away = time.time() - room.seats[h].last_seen
            if away > rooms.HOST_HANDOFF_SECONDS + 12:
                problem(f"[lobby] host {h} away {away:.0f}s but host not handed to a connected human")
    for c in clients.values():
        await c.close()


async def amain(n_rooms: int, seed: int, scenarios: list[str]):
    rooms.AUTOPILOT_AFTER_SECONDS = 1.0
    rooms.HOST_HANDOFF_SECONDS = 1.0
    if hasattr(main, "CREATE_LIMIT"):
        main.CREATE_LIMIT.capacity = main.JOIN_LIMIT.capacity = 1e9
    config = uvicorn.Config(main.app, host="127.0.0.1", port=PORT, log_level="warning", ws="websockets")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    base = f"http://127.0.0.1:{PORT}"
    rng = random.Random(seed)
    t0 = time.time()
    async with httpx.AsyncClient(base_url=base, trust_env=False, timeout=10) as http:
        sem = asyncio.Semaphore(6)

        async def one(i):
            async with sem:
                sc = scenarios[i % len(scenarios)]
                try:
                    if sc == "lobby":
                        await lobby_fuzz(base, http, random.Random(rng.random()))
                    else:
                        await play_room(base, http, sc, random.Random(rng.random()), games=2)
                except Exception as exc:  # noqa: BLE001
                    problem(f"[{sc}] harness exception {type(exc).__name__}: {exc}\n{traceback.format_exc()}")

        await asyncio.gather(*(one(i) for i in range(n_rooms)))
    await asyncio.sleep(0.5)
    # leak check
    alive = [r for r in main.registry.rooms.values() if r.runner and not r.runner.done()]
    socks = sum(len(s.sockets) for r in main.registry.rooms.values() for s in r.seats)
    print(f"rooms in registry={len(main.registry.rooms)} runners alive={len(alive)} sockets still registered={socks} tasks={len(asyncio.all_tasks())}")
    print("elapsed", round(time.time() - t0, 1), "s")
    print(dict(STATS))
    print(f"{len(PROBLEMS)} problems")
    server.should_exit = True
    await task


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    sc = sys.argv[3].split(",") if len(sys.argv) > 3 else ["quick", "multi", "double", "stale", "reconnect", "leave", "simul", "garbage", "lobby"]
    asyncio.run(amain(n, seed, sc))
