"""Anonymous, aggregated game-activity counters (see docs/usage-stats.md).

The game server keeps a few daily counters in memory and periodically POSTs
them to a Cloudflare Pages Function that adds them up in D1. Everything here
is best effort:

* Disabled (a no-op that allocates nothing) unless both STATS_INGEST_URL and
  STATS_INGEST_SECRET are set, so local development and tests need no
  credentials.
* Every public method swallows its own exceptions: tracking must never raise
  into game code. Recording is pure in-memory work under a threading.Lock
  because bot moves (and hence game-over) run in worker threads.
* Sending happens off the event loop with a short timeout; a failed batch is
  dropped, never retried (a retry after a timed-out success would double-count).

Privacy contract: only the counters below leave the process. No names, IP
addresses, user agents, room codes, tokens, chat, emotes or card data. Unique
players are approximated with a keyed hash whose key is random, held only in
memory and replaced every UTC day; hashes never leave the process — only the
number of first-seen hashes does.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("ibflip_web.stats")

SCHEMA_VERSION = 1
FLUSH_INTERVAL_SECONDS = 60.0
SEND_TIMEOUT_SECONDS = 5.0
USER_AGENT = "ibflip-backend-stats/1"
MAX_SEEN_PER_DAY = 200_000  # bound on the in-memory unique-player set
FAILURE_LOG_INTERVAL_SECONDS = 600.0

LEVELS = ("easy", "medium", "hard")
# Allow-list of everything that may be sent: metric -> allowed dimension values
# (None = shape "{seats}p-{humans}h"). The ingest function enforces the same list.
COUNTER_METRICS = {
    "rooms_created": {"solo", "friends"},
    "games_started": None,
    "games_finished": None,  # game over with a human still at the table
    "games_unattended": None,  # every human left; bots/autopilot finished it
    "games_abandoned": None,  # room expired or server stopped mid-game
    "game_seconds": None,  # summed duration of finished games
    "bot_seats": set(LEVELS),
    "bot_mix": None,  # "none" or "+"-joined sorted levels present
    "game_duration": {"lt5m", "5-10m", "10-20m", "20-40m", "40m+"},
    "new_players": {""},
}
PEAK_METRICS = ("peak_rooms", "peak_active_rooms", "peak_players")


def utc_day(ts: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, tz=timezone.utc).strftime("%Y-%m-%d")


def duration_bucket(seconds: float) -> str:
    minutes = seconds / 60
    if minutes < 5:
        return "lt5m"
    if minutes < 10:
        return "5-10m"
    if minutes < 20:
        return "10-20m"
    if minutes < 40:
        return "20-40m"
    return "40m+"


def bot_mix(levels: list[str]) -> str:
    present = [lvl for lvl in LEVELS if lvl in levels]
    return "+".join(present) if present else "none"


class GameShape:
    """What we remember about a running game (no names, no codes)."""

    __slots__ = ("seats", "humans", "levels", "started")

    def __init__(self, seats: int, humans: int, levels: list[str], started: float) -> None:
        self.seats = seats
        self.humans = humans
        self.levels = levels
        self.started = started

    @property
    def dim(self) -> str:
        return f"{self.seats}p-{self.humans}h"


def _post_json(url: str, secret: str, payload: dict[str, Any]) -> int:
    body = json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=SEND_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https URL from env
        return response.status


Sender = Callable[[dict[str, Any]], Any]


class Stats:
    def __init__(self, url: str = "", secret: str = "", sender: Sender | None = None) -> None:
        self.url = url.strip()
        self.secret = secret.strip()
        self.enabled = bool(self.url and self.secret) or sender is not None
        self._send = sender or (lambda payload: _post_json(self.url, self.secret, payload))
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, str, str], int] = {}
        self._peaks: dict[tuple[str, str], int] = {}
        self._seen_day = ""
        self._seen_key = b""
        self._seen: set[bytes] = set()
        self._task: asyncio.Task | None = None
        self._sampler: Callable[[], tuple[int, int, int]] | None = None
        self._last_failure_log = 0.0

    @classmethod
    def from_env(cls) -> Stats:
        return cls(os.environ.get("STATS_INGEST_URL", ""), os.environ.get("STATS_INGEST_SECRET", ""))

    # ------------------------------------------------------------- recording
    def _add(self, metric: str, dim: str, n: int = 1, ts: float | None = None) -> None:
        key = (utc_day(ts), metric, dim)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + n

    def room_created(self, with_bots: bool) -> None:
        if not self.enabled:
            return
        try:
            self._add("rooms_created", "solo" if with_bots else "friends")
        except Exception:  # noqa: BLE001
            log.debug("stats: room_created failed", exc_info=True)

    def game_started(self, shape: GameShape) -> None:
        if not self.enabled:
            return
        try:
            self._add("games_started", shape.dim, ts=shape.started)
            self._add("bot_mix", bot_mix(shape.levels), ts=shape.started)
            for level in LEVELS:
                count = shape.levels.count(level)
                if count:
                    self._add("bot_seats", level, count, ts=shape.started)
        except Exception:  # noqa: BLE001
            log.debug("stats: game_started failed", exc_info=True)

    def game_ended(self, shape: GameShape, outcome: str) -> None:
        """outcome: "finished" | "unattended" | "abandoned"."""
        if not self.enabled:
            return
        try:
            if outcome == "finished":
                seconds = max(0, int(time.time() - shape.started))
                self._add("games_finished", shape.dim)
                self._add("game_seconds", shape.dim, seconds)
                self._add("game_duration", duration_bucket(seconds))
            elif outcome == "unattended":
                self._add("games_unattended", shape.dim)
            else:
                self._add("games_abandoned", shape.dim)
        except Exception:  # noqa: BLE001
            log.debug("stats: game_ended failed", exc_info=True)

    def player_seen(self, address: str) -> None:
        """Count a first-seen player for today. The address is only hashed with
        a random in-memory key that is replaced daily; neither leaves here."""
        if not self.enabled:
            return
        try:
            day = utc_day()
            with self._lock:
                if day != self._seen_day:
                    self._seen_day = day
                    self._seen_key = secrets.token_bytes(32)
                    self._seen = set()
                if len(self._seen) >= MAX_SEEN_PER_DAY:
                    return
                digest = hmac.new(self._seen_key, str(address).encode(), hashlib.sha256).digest()[:16]
                if digest in self._seen:
                    return
                self._seen.add(digest)
            self._add("new_players", "")
        except Exception:  # noqa: BLE001
            log.debug("stats: player_seen failed", exc_info=True)

    def sample(self, rooms: int, active_rooms: int, players: int) -> None:
        if not self.enabled:
            return
        try:
            day = utc_day()
            with self._lock:
                for metric, value in zip(PEAK_METRICS, (rooms, active_rooms, players)):
                    key = (day, metric)
                    if value > self._peaks.get(key, -1):
                        self._peaks[key] = int(value)
        except Exception:  # noqa: BLE001
            log.debug("stats: sample failed", exc_info=True)

    # --------------------------------------------------------------- sending
    def take_batch(self) -> dict[str, Any] | None:
        """Swap out what has accumulated; None when there is nothing new."""
        with self._lock:
            if not self._counters and not self._peaks:
                return None
            counters, self._counters = self._counters, {}
            peaks, self._peaks = self._peaks, {}
        return {
            "v": SCHEMA_VERSION,
            "counters": [[d, m, k, n] for (d, m, k), n in sorted(counters.items())],
            "peaks": [[d, m, v] for (d, m), v in sorted(peaks.items())],
        }

    def flush_sync(self) -> bool:
        """Send the pending batch now. Never raises; drops the batch on failure."""
        if not self.enabled:
            return False
        try:
            if self._sampler is not None:
                self.sample(*self._sampler())
            batch = self.take_batch()
            if batch is None:
                return True
            status = self._send(batch)
            if isinstance(status, int) and status >= 300:
                self._note_failure(f"HTTP {status}")
                return False
            return True
        except Exception as exc:  # noqa: BLE001 - never let tracking break anything
            code = getattr(exc, "code", None)
            self._note_failure(f"HTTP {code}" if code else type(exc).__name__)
            return False

    def _note_failure(self, reason: str) -> None:
        now = time.monotonic()
        if now - self._last_failure_log >= FAILURE_LOG_INTERVAL_SECONDS or not self._last_failure_log:
            self._last_failure_log = now
            log.warning("stats: dropped a batch (%s)", reason)

    async def flush(self, timeout: float = SEND_TIMEOUT_SECONDS + 1) -> bool:
        if not self.enabled:
            return False
        try:
            return await asyncio.wait_for(asyncio.to_thread(self.flush_sync), timeout)
        except Exception:  # noqa: BLE001
            return False

    def ensure_running(self, sampler: Callable[[], tuple[int, int, int]]) -> None:
        """Start the periodic flusher on the running loop (idempotent; no-op when disabled)."""
        if not self.enabled:
            return
        try:
            self._sampler = sampler
            self.sample(*sampler())
            loop = asyncio.get_running_loop()
            if self._task is not None and not self._task.done() and self._task.get_loop() is loop:
                return
            self._task = loop.create_task(self._loop())
        except Exception:  # noqa: BLE001
            log.debug("stats: ensure_running failed", exc_info=True)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            await self.flush()

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        await self.flush()


STATS = Stats.from_env()
