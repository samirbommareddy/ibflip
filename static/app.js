/* IB-Flip web client ------------------------------------------------------ */
"use strict";

// ---------------------------------------------------------------- constants
const RANKS = ["3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A", "2"];
const SUITS = ["♥", "♦", "♣", "♠"];
const POWER = { "2": "AGAIN", "3": "REVERSE", "4": "4-LOOP", "5": "UNDER", "7": "≤ 7", "8": "SKIP", "9": "DRAW", "10": "FLIP" };
const POWER_TEXT = {
  "2": "Play again.",
  "3": "Odd number of 3s reverses direction. Anything goes on a 3.",
  "4": "Next player picks up unless they play a 4, 5 or 6 — and so on.",
  "5": "Next player plays on the card <em>beneath</em> the 5.",
  "6": "Played on a 4 it keeps the 4-loop going.",
  "7": "Next player must play 7 or lower.",
  "8": "Skips one player per 8 played.",
  "9": "Draws a random card from the discard — it counts as played.",
  "10": "Flips the live pile away. Play again.",
  "A": "On a 7, an ace counts as 1: anything can follow.",
  "J": "No power.", "Q": "No power.", "K": "No power.",
};
// PLAYABLE_ON[played][target] (rank indexes), mirrors src/ibflip/rules.py
const ON = {
  A: "A23 6789JQK".split(""), "2": "A23 6789JQK".split(""), "3": "237".split(""),
  "4": "A234 6789JQK".split(""), "5": "A234 6789JQK".split(""), "6": "2346 7".split(""),
  "7": "A23 6789JQK".split(""), "8": "2368".split(""), "9": "23689".split(""),
  "10": "A23 689JQK".split(""), J: "23689J".split(""), Q: "23689JQ".split(""), K: "23689JQK".split(""),
};
const EMOTES = ["👏", "😂", "😱", "🔥", "😤", "🤝", "👀", "💀"];
const LEVEL_NAME = { easy: "Rookie", medium: "Regular", hard: "Shark" };
const A_PICKUP = 52, A_REVEAL = 54, A_END = 55, A_FACEDOWN = 67;

const rankOf = (id) => RANKS[id >> 2];
const rankIx = (id) => id >> 2;
const suitOf = (id) => SUITS[id & 3];
const isRed = (id) => (id & 3) < 2;
const short = (id) => `${rankOf(id)}${suitOf(id)}`;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ---------------------------------------------------------------- API base
const API = (() => {
  if (window.IBFLIP_API_BASE) return window.IBFLIP_API_BASE.replace(/\/$/, "");
  const { hostname, port, origin, protocol } = window.location;
  const local = hostname === "localhost" || hostname === "127.0.0.1";
  if (protocol === "file:") return "http://127.0.0.1:8000";
  if (local && port && port !== "8000") return `${protocol}//${hostname}:8000`;
  if (local || hostname.endsWith("onrender.com")) return origin;
  return document.querySelector('meta[name="ibflip-api"]').content.replace(/\/$/, "");
})();
const WS_BASE = API.replace(/^http/, "ws");

// -------------------------------------------------------------------- state
const S = {
  code: null, token: null, seat: null, ws: null, room: null, game: null,
  queue: [], busy: false, selected: null, sound: localStorage.getItem("ibflip:sound") !== "off",
  lastGameNo: 0, resultShownFor: null, lastFlipRank: null, reconnectTimer: null, pendingAction: false,
  liveShown: [], speed: 1,
};

// ===================================================================== sound
const Sound = (() => {
  let ctx = null;
  const ac = () => (ctx ||= new (window.AudioContext || window.webkitAudioContext)());
  function noise(dur, { freq = 2200, q = 1.2, gain = 0.25, sweep = 0 } = {}) {
    if (!S.sound) return;
    const a = ac(), len = Math.floor(a.sampleRate * dur);
    const buf = a.createBuffer(1, len, a.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3);
    const src = a.createBufferSource(); src.buffer = buf;
    const f = a.createBiquadFilter(); f.type = "bandpass"; f.frequency.value = freq; f.Q.value = q;
    if (sweep) f.frequency.exponentialRampToValueAtTime(freq * sweep, a.currentTime + dur);
    const g = a.createGain(); g.gain.value = gain;
    src.connect(f).connect(g).connect(a.destination); src.start();
  }
  function tone(freq, dur, when = 0, type = "sine", gain = 0.12) {
    if (!S.sound) return;
    const a = ac(), o = a.createOscillator(), g = a.createGain();
    o.type = type; o.frequency.value = freq;
    const t = a.currentTime + when;
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(gain, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(a.destination); o.start(t); o.stop(t + dur + 0.05);
  }
  return {
    snap: () => noise(0.07, { freq: 2600, q: 0.9, gain: 0.35 }),
    slide: () => noise(0.16, { freq: 1200, q: 0.6, gain: 0.18, sweep: 2.2 }),
    swoosh: () => noise(0.35, { freq: 500, q: 0.5, gain: 0.3, sweep: 4 }),
    flip: () => { noise(0.4, { freq: 300, q: 0.4, gain: 0.35, sweep: 6 }); tone(196, 0.25, 0, "triangle", 0.12); },
    turn: () => { tone(660, 0.18); tone(880, 0.25, 0.1); },
    bad: () => { tone(220, 0.3, 0, "sawtooth", 0.05); tone(165, 0.4, 0.12, "sawtooth", 0.05); },
    win: () => [523, 659, 784, 1046].forEach((f, i) => tone(f, 0.35, i * 0.11, "triangle", 0.12)),
    unlock: () => { try { ac().resume(); } catch (_) {} },
  };
})();

// =============================================================== card render
function cardHTML(id, { cls = "", tiny = false, extra = "" } = {}) {
  if (id === null || id === undefined) return `<div class="card back ${cls}" ${extra}></div>`;
  const r = rankOf(id), s = suitOf(id);
  const face = r === "J" || r === "Q" || r === "K";
  const center = face ? r : r === "A" ? s : s;
  const power = POWER[r] ? `<span class="power">${POWER[r]}</span>` : "";
  return `<div class="card ${isRed(id) ? "red" : ""} ${face ? "face" : ""} ${tiny ? "tiny" : ""} ${cls}" data-card="${id}" ${extra}>
    <span class="ix tl"><b>${r}</b><i>${s}</i></span>
    <span class="pip">${center}</span>
    <span class="ix br"><b>${r}</b><i>${s}</i></span>${power}</div>`;
}
function cardEl(id, opts) {
  const t = document.createElement("template");
  t.innerHTML = cardHTML(id, opts).trim();
  return t.content.firstChild;
}
const rot = (id) => ((((id ?? 7) * 37) % 13) - 6) * 1.1;

// ================================================================ screens
function show(screen) {
  $$(".screen").forEach((s) => s.classList.toggle("active", s.id === screen));
}
function toast(html, cls = "") {
  const el = document.createElement("div");
  el.className = `toast ${cls}`;
  el.innerHTML = html;
  const stack = $("#toasts");
  stack.prepend(el);
  while (stack.children.length > 5) stack.lastChild.remove();
  setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 400); }, 5200);
}
function callout(text, bad = false) {
  const el = $("#callout");
  el.textContent = text;
  el.classList.remove("show", "bad");
  void el.offsetWidth;
  el.classList.add("show");
  el.classList.toggle("bad", bad);
}
function nameOf(i) {
  if (i === S.seat) return "You";
  return esc(S.room?.seats[i]?.name ?? `Player ${i + 1}`);
}
function verb(i, youForm, otherForm) { return i === S.seat ? youForm : otherForm; }

// ================================================================== HOME
function initHome() {
  const name = localStorage.getItem("ibflip:name") || "";
  $("#nameInput").value = name;
  $$(".tab").forEach((t) => t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
    $$(".tab-body").forEach((b) => b.classList.toggle("hidden", b.dataset.body !== t.dataset.tab));
  }));
  $$(".seg").forEach((seg) => seg.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$("button", seg).forEach((x) => x.classList.toggle("on", x === b));
    localStorage.setItem(`ibflip:${seg.id}`, b.dataset.v);
  }));
  for (const id of ["botCount", "botLevel"]) {
    const v = localStorage.getItem(`ibflip:${id}`);
    if (v) $$(`#${id} button`).forEach((x) => x.classList.toggle("on", x.dataset.v === v));
  }
  // hero cards
  [47, 30, 51, 12, 41].forEach((id, i) => {
    const el = $(`.hero-card[data-hero="${i}"]`);
    el.outerHTML = cardHTML(id, { cls: "hero-card", extra: `data-hero="${i}"` });
  });
  $("#quickPlay").addEventListener("click", quickPlay);
  $("#createRoom").addEventListener("click", createRoom);
  $("#joinRoom").addEventListener("click", () => joinRoom($("#codeInput").value));
  $("#codeInput").addEventListener("keydown", (e) => e.key === "Enter" && joinRoom(e.target.value));
  $("#nameInput").addEventListener("change", (e) => localStorage.setItem("ibflip:name", e.target.value.trim()));
}
const segVal = (id) => $(`#${id} button.on`)?.dataset.v;
function playerName() {
  const n = $("#nameInput").value.trim() || localStorage.getItem("ibflip:name") || "";
  if (n) localStorage.setItem("ibflip:name", n);
  return n || "You";
}
const EXPIRED = "That room has expired — the server restarts after it's been idle for a while. Start a new one!";
const friendlyError = (m) => (/room not found/i.test(m || "") ? EXPIRED : m);
async function api(path, body) {
  const note = $("#serverNote");
  const slow = setTimeout(() => (note.textContent = "Waking up the game server… (free hosting naps — ~30s)"), 1800);
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (_) {
    throw new Error("Can't reach the game server right now — try again in a moment.");
  } finally {
    clearTimeout(slow);
    if (note.textContent.startsWith("Waking")) note.textContent = "";
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(friendlyError(typeof data.detail === "string" ? data.detail : res.statusText || "Request failed"));
  return data;
}
function busyHome(on) { $$("#home .btn").forEach((b) => (b.disabled = on)); }
async function quickPlay() {
  Sound.unlock();
  busyHome(true); $("#homeError").textContent = "";
  try {
    const n = Number(segVal("botCount") || 3), level = segVal("botLevel") || "medium";
    const r = await api("/api/rooms", { name: playerName(), bots: Array(n).fill(level), autostart: true });
    enterRoom(r);
  } catch (e) { $("#homeError").textContent = e.message; } finally { busyHome(false); }
}
async function createRoom() {
  Sound.unlock();
  busyHome(true); $("#homeError").textContent = "";
  try { enterRoom(await api("/api/rooms", { name: playerName() })); }
  catch (e) { $("#homeError").textContent = e.message; } finally { busyHome(false); }
}
async function joinRoom(code) {
  Sound.unlock();
  code = (code || "").trim().toUpperCase();
  if (code.length !== 4) { $("#homeError").textContent = "Room codes have 4 letters."; return; }
  busyHome(true); $("#homeError").textContent = "";
  try { enterRoom(await api(`/api/rooms/${code}/join`, { name: playerName() })); }
  catch (e) { $("#homeError").textContent = e.message; } finally { busyHome(false); }
}
function enterRoom({ code, token, seat }) {
  S.code = code; S.token = token; S.seat = seat;
  localStorage.setItem(`ibflip:room:${code}`, JSON.stringify({ token, seat }));
  history.replaceState(null, "", `?room=${code}`);
  connect();
}
function leaveRoom() {
  if (S.ws) { S.ws.onclose = null; S.ws.close(); }
  clearTimeout(S.reconnectTimer);
  Object.assign(S, { code: null, token: null, seat: null, ws: null, room: null, game: null, queue: [], busy: false, resultShownFor: null });
  history.replaceState(null, "", location.pathname);
  $("#resultOverlay").classList.add("hidden");
  show("home");
}

// ================================================================ socket
function connect() {
  clearTimeout(S.reconnectTimer);
  const ws = new WebSocket(`${WS_BASE}/ws/${S.code}?token=${encodeURIComponent(S.token)}`);
  S.ws = ws;
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") { S.queue.push(msg); pump(); }
    else if (msg.type === "error") {
      if (msg.fatal) { localStorage.removeItem(`ibflip:room:${S.code}`); leaveRoom(); $("#homeError").textContent = friendlyError(msg.message); }
      else { toast(`<b>Hmm.</b> ${esc(msg.message)}`, "bad"); S.pendingAction = false; renderGame(); }
    } else if (msg.type === "emote" || msg.type === "chat") bubble(msg.seat, msg.text, msg.type === "chat");
    else if (msg.type === "hint") showHint(msg.action);
    else if (msg.type === "kicked") { leaveRoom(); $("#homeError").textContent = "You were removed from the room."; }
  };
  ws.onclose = () => {
    if (S.ws !== ws || !S.code) return;
    $("#hudStatus").textContent = "Reconnecting…";
    S.reconnectTimer = setTimeout(connect, 1500);
  };
  ws.onopen = () => {
    clearInterval(S.pingTimer);
    S.pingTimer = setInterval(() => ws.readyState === 1 && ws.send(JSON.stringify({ type: "ping" })), 25000);
  };
}
function send(msg) {
  if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(msg));
}
function act(action) {
  if (S.pendingAction) return;
  S.pendingAction = true;
  Sound.unlock();
  send({ type: "action", action });
}

// ========================================================== state pump
async function pump() {
  if (S.busy) return;
  S.busy = true;
  try {
    while (S.queue.length) {
      const msg = S.queue.shift();
      S.speed = S.queue.length > 2 ? 0.45 : S.queue.length > 0 ? 0.75 : 1;
      const prev = S.game;
      const inGame = msg.game && prev && $("#game").classList.contains("active") && msg.room.game_no === S.lastGameNo;
      if (inGame && msg.events?.length) {
        S.room = msg.room;
        try { await animateEvents(msg.events, prev, msg.game); } catch (e) { console.error(e); }
      }
      apply(msg);
    }
  } finally { S.busy = false; }
}

function apply(msg) {
  const firstDeal = msg.game && msg.room.game_no !== S.lastGameNo;
  const prevCurrent = S.game?.current;
  S.room = msg.room; S.seat = msg.you; S.game = msg.game || null; S.pendingAction = false;
  if (msg.room.status === "lobby" || !msg.game) {
    S.lastGameNo = msg.room.game_no;
    $("#resultOverlay").classList.add("hidden");
    renderLobby(); show("lobby"); return;
  }
  show("game");
  if (firstDeal) {
    S.lastGameNo = msg.room.game_no; S.selected = null; S.resultShownFor = null;
    $("#resultOverlay").classList.add("hidden");
    S.liveShown = [];
    renderGame();
    dealAnimation();
  } else renderGame();
  if (S.game.current === S.seat && prevCurrent !== S.seat && S.game.status === "playing") {
    Sound.turn();
  }
  document.title = S.game.current === S.seat && S.game.status === "playing" ? "● Your turn — IB-Flip" : "IB-Flip";
  if (S.game.status === "over" && S.resultShownFor !== S.room.game_no) {
    S.resultShownFor = S.room.game_no;
    setTimeout(showResult, 900);
  }
  if (S.room.status !== "over") $("#resultOverlay").classList.add("hidden");
}

// ================================================================ LOBBY
function renderLobby() {
  const r = S.room, host = r.host === S.seat;
  $("#roomCode").textContent = r.code;
  const list = $("#seatList");
  list.innerHTML = "";
  r.seats.forEach((s, i) => {
    const li = document.createElement("li");
    li.className = "seat-item";
    const sub = s.kind === "bot" ? `Bot · ${LEVEL_NAME[s.level]}` : s.connected ? (i === S.seat ? "You" : "Online") : "Away";
    li.innerHTML = `<div class="avatar">${s.avatar}<span class="dot ${s.connected ? "" : "off"}"></span></div>
      <div class="who"><b>${esc(s.name)}${s.host ? " 👑" : ""}</b><small>${sub}</small></div>`;
    if (host && s.kind === "bot") {
      const sel = document.createElement("select");
      sel.innerHTML = Object.entries(LEVEL_NAME).map(([v, n]) => `<option value="${v}" ${v === s.level ? "selected" : ""}>${n}</option>`).join("");
      sel.addEventListener("change", () => send({ type: "set_bot", seat: i, level: sel.value }));
      li.append(sel);
    }
    if (host && i !== S.seat) {
      const x = document.createElement("button");
      x.className = "x"; x.title = "Remove"; x.textContent = "✕";
      x.addEventListener("click", () => send({ type: "remove", seat: i }));
      li.append(x);
    }
    list.append(li);
  });
  for (let i = r.seats.length; i < 5; i++) {
    const li = document.createElement("li");
    li.className = "seat-item seat-empty";
    li.textContent = "Open seat";
    list.append(li);
  }
  $("#hostControls").classList.toggle("hidden", !host);
  $("#waitHost").classList.toggle("hidden", host);
  $("#startGame").disabled = r.seats.length < 2;
  $("#startGame").textContent = r.seats.length < 2 ? "Need 2+ players" : `Start ${r.seats.length}-player game`;
  $$("[data-addbot]").forEach((b) => (b.disabled = r.seats.length >= 5));
  $$('[data-addbot="hard"]').forEach((b) => (b.title = r.hard_available ? "Self-play trained AI" : "AI model not deployed — plays like Regular"));
}
function inviteLink() { return `${location.origin}${location.pathname}?room=${S.code}`; }
async function copyInvite() {
  const link = inviteLink();
  try { await navigator.clipboard.writeText(link); toast("<b>Copied!</b> Send it to your friends."); }
  catch (_) { prompt("Copy this link:", link); }
}

// ================================================================= TABLE
const SEAT_POS = {
  1: [[50, 15]],
  2: [[27, 17], [73, 17]],
  3: [[9, 46], [50, 15], [91, 46]],
  4: [[9, 52], [31, 15], [69, 15], [91, 52]],
};
const SEAT_POS_NARROW = {
  1: [[50, 15]],
  2: [[27, 15], [73, 15]],
  3: [[19, 35], [50, 12], [81, 35]],
  4: [[19, 35], [30, 11], [70, 11], [81, 35]],
};
function relIndex(i) { const n = S.game.players.length; return (i - S.seat + n) % n; }

function renderGame() {
  const g = S.game, r = S.room;
  if (!g) return;
  const n = g.players.length;
  $("#hudCode").textContent = r.code;
  // direction ring
  $("#dirRing").classList.toggle("ccw", g.direction === -1);

  // ---- opponents
  const seats = $("#seats");
  seats.innerHTML = "";
  const table = innerWidth < 760 ? SEAT_POS_NARROW : SEAT_POS;
  const pos = table[n - 1] || table[4];
  for (let i = 0; i < n; i++) {
    if (i === S.seat) continue;
    const p = g.players[i], s = r.seats[i] || {};
    const [x, y] = pos[relIndex(i) - 1];
    const el = document.createElement("div");
    el.className = "seat";
    el.dataset.seat = i;
    el.style.left = `${x}%`; el.style.top = `${y}%`;
    if (g.current === i) el.classList.add("turn");
    if (!p.active) el.classList.add("out");
    if (g.status === "fixing") el.classList.add(p.ready ? "ready" : "ready-wait");
    const backs = Math.min(p.hand_count, 7);
    const sub = s.kind === "bot" ? LEVEL_NAME[s.level] : s.connected ? "" : "away";
    el.innerHTML = `
      <div class="seat-head"><div class="avatar">${s.avatar ?? "🙂"}${s.kind === "human" ? `<span class="dot ${s.connected ? "" : "off"}"></span>` : ""}</div>
        <div><div class="seat-name">${esc(s.name ?? "Player")}</div><div class="seat-sub">${sub}</div></div></div>
      <div class="opp-hand" data-hand="${i}">${Array.from({ length: backs }, () => cardHTML(null)).join("")}
        ${p.hand_count ? `<span class="hand-count">${p.hand_count}</span>` : ""}</div>
      ${p.known.length ? `<div class="known" title="Cards everyone saw go into this hand">${p.known.slice().sort((a, b) => a - b).map((c) => `<span class="chip ${isRed(c) ? "red" : ""}">${short(c)}</span>`).join("")}</div>` : ""}
      <div class="slots">${slotsHTML(p, i, false)}</div>`;
    seats.append(el);
  }

  // ---- center piles
  renderPiles();

  // ---- me
  renderMe();
  renderStatus();
}

function slotsHTML(p, seat, mine) {
  let html = "";
  for (let k = 0; k < 3; k++) {
    const down = p.face_down[k];
    const ups = p.face_up[k] || [];
    const empty = !down && !ups.length;
    html += `<div class="slot ${empty ? "empty" : ""}" data-slot="${k}" data-seat="${seat}">
      ${down ? cardHTML(null, { cls: "down", extra: `data-down="${k}"` }) : ""}
      ${ups.map((c) => cardHTML(c, { cls: "up", tiny: !mine })).join("")}</div>`;
  }
  return html;
}

function renderPiles(liveOverride) {
  const g = S.game;
  const draw = $("#drawPile");
  const dn = Math.min(g.draw_count, 5);
  draw.innerHTML = Array.from({ length: dn }, (_, i) => cardHTML(null, { extra: `style="transform:translate(${-i * 1.2}px, ${-i * 1.2}px)"` })).join("");
  $("#drawLabel").innerHTML = g.draw_count ? `Deck <b>${g.draw_count}</b>` : "Deck empty";
  const live = liveOverride || g.live;
  S.liveShown = [...live];
  drawLive(live);
  const disc = $("#discardPile");
  const k = Math.min(Math.ceil(g.discard_count / 6), 5);
  disc.innerHTML = Array.from({ length: k }, (_, i) => cardHTML(null, { extra: `style="transform:translate(${-i * 1.2}px, ${-i * 1.2}px) rotate(${(i % 2 ? 3 : -2)}deg)"` })).join("");
  $("#discardLabel").innerHTML = g.discard_count ? `Discard <b>${g.discard_count}</b>` : "Discard";
  const mine = g.current === S.seat && g.status === "playing";
  draw.classList.toggle("clickable", mine && !!g.legal?.reveal);
  $("#livePile").classList.toggle("clickable", mine && !!g.legal?.pick_up);
  $("#livePile").classList.toggle("fourloop", g.four_loop);
}
function drawLive(live) {
  const el = $("#livePile");
  const shown = live.slice(-5);
  const aceOne = new Set(S.game?.ace_one || []);
  el.innerHTML = shown.map((c, i) => {
    const off = (i - (shown.length - 1)) * 16;
    return cardHTML(c, { cls: aceOne.has(c) ? "ace-one" : "", extra: `style="transform: translateX(${off}%) rotate(${rot(c)}deg)"` });
  }).join("");
  const by = live.length && S.lastActor !== null && S.lastActor !== undefined ? ` · ${S.lastActor === S.seat ? "you" : esc(S.room?.seats[S.lastActor]?.name ?? "")}` : "";
  $("#liveLabel").innerHTML = live.length ? `Live <b>${live.length}</b>${by}` : "Live";
}

function targetText(g) {
  if (g.four_loop) return "4-loop: play a 4, 5 or 6";
  if (g.target === null || g.target === undefined) return "anything goes";
  const r = RANKS[g.target];
  if (r === "7") return "7 or lower";
  const top = g.live[g.live.length - 1];
  const under = top !== undefined && rankOf(top) === "5" ? " (under the 5)" : "";
  return `on ${r === "A" || r === "8" ? "an" : "a"} ${r}${under}`;
}

function renderStatus() {
  const g = S.game, r = S.room;
  let hud = "";
  if (g.status === "fixing") hud = "Set up your table";
  else if (g.status === "over") hud = "Game over";
  else {
    const phase = { EARLY_GAME: "Early game", MIDDLE_GAME: "Mid game", END_GAME: "End game" }[g.phase] || "";
    hud = `${phase} · ${targetText(g)}`;
  }
  $("#hudStatus").textContent = hud;
  const prompt = $("#prompt");
  let text = "", yours = false;
  const me = g.players[S.seat];
  if (g.status === "fixing") {
    if (me.ready) {
      const waiting = g.players.map((p, i) => (!p.ready ? r.seats[i]?.name : null)).filter(Boolean);
      text = `Waiting for ${waiting.join(", ")}…`;
    } else {
      yours = true;
      text = S.selected === null
        ? "Tap a hand card, then a face-up card to swap. Good face-up cards: 10, 2, 4, 5, 7."
        : `Now tap a face-up card to ${S.game.players[S.seat].face_up.some((sl) => sl.length && rankIx(sl[sl.length - 1]) === rankIx(S.selected)) ? "swap — or a matching one to stack" : "swap"}`;
    }
  } else if (g.status === "playing") {
    if (g.current === S.seat) {
      yours = true;
      const L = g.legal || {};
      if (g.nine_draw) text = "Drawing from the discard…";
      else if (g.group_rank !== null && g.group_rank !== undefined) text = L.cards?.length ? `Add another ${RANKS[g.group_rank]} — or tap Done` : "Tap Done to finish your turn";
      else if (L.face_down?.length) text = "Blind time — pick a face-down card";
      else if (g.start_card !== null && g.start_card !== undefined && L.cards?.length === 1 && L.cards[0] === g.start_card) text = `You start — play your ${short(g.start_card)}`;
      else if (!L.cards?.length && L.reveal) text = "Nothing playable — flip the top of the deck";
      else if (!L.cards?.length && L.pick_up) text = "Nothing playable — pick up the pile";
      else if (g.four_loop) text = "4-loop! Play a 4, 5 or 6 — or pick up";
      else text = `Your turn — ${targetText(g)}`;
    } else if (g.current !== null) {
      text = `${nameOf(g.current)} is thinking…`;
    }
  }
  prompt.innerHTML = text;
  prompt.classList.toggle("yours", yours);
  $("#me").classList.toggle("turn", g.current === S.seat && g.status === "playing");
  $("#hintBtn").disabled = !(g.current === S.seat && g.status === "playing" && !g.nine_draw);
}

function renderMe() {
  const g = S.game, me = g.players[S.seat], s = S.room.seats[S.seat] || {};
  $("#meBadge").innerHTML = `<div class="avatar">${s.avatar ?? "🙂"}</div><div><div class="seat-name">${esc(s.name ?? "You")}</div><div class="seat-sub">You</div></div>`;
  const mine = g.status === "playing" && g.current === S.seat;
  const L = mine ? g.legal || {} : {};
  const legalCards = new Set(L.cards || []);

  // table slots
  const slots = $("#mySlots");
  slots.innerHTML = slotsHTML(me, S.seat, true);
  $$(".slot", slots).forEach((slotEl) => {
    const k = Number(slotEl.dataset.slot);
    if (g.status === "fixing" && !me.ready) {
      const ups = $$(".card.up", slotEl);
      const top = ups[ups.length - 1];
      if (top) {
        if (S.selected !== null) top.classList.add("target");
        top.addEventListener("click", () => fixSlot(k));
      }
    }
    $$(".card.up", slotEl).forEach((c) => {
      const id = Number(c.dataset.card);
      if (legalCards.has(id) && g.source === "face_up") {
        c.classList.add("legal");
        c.addEventListener("click", () => act(id));
        c.addEventListener("dblclick", (e) => { e.preventDefault(); });
      }
    });
    const down = $(".card.down", slotEl);
    if (down && (L.face_down || []).includes(k)) {
      down.classList.add("legal");
      down.style.cursor = "pointer";
      down.addEventListener("click", () => act(A_FACEDOWN + k));
    }
  });

  // hand
  const hand = $("#hand");
  const cards = [...g.hand].sort((a, b) => a - b);
  const known = new Set(me.known || []);
  hand.innerHTML = cards.map((c) => cardHTML(c)).join("");
  const n = cards.length;
  const cw = $("#hand .card")?.getBoundingClientRect().width || 80;
  const avail = Math.max(200, hand.clientWidth - 30);
  const needed = n * cw;
  const margin = n > 1 ? Math.min(-cw * 0.08, (avail - needed) / (2 * n)) : 0;
  const spread = Math.min(22, n * 3.2);
  $$(".card", hand).forEach((el, i) => {
    const id = Number(el.dataset.card);
    el.style.margin = `0 ${margin}px`;
    const t = n > 1 ? (i / (n - 1)) * 2 - 1 : 0; // -1 .. 1
    el.style.setProperty("--rot", `${(t * spread) / 2}deg`);
    el.style.setProperty("--arc", `${t * t * Math.min(18, n * 2)}px`);
    el.style.zIndex = i + 1;
    if (known.has(id) && g.status !== "fixing") el.classList.add("known-mark");
    if (g.status === "fixing" && !me.ready) {
      el.classList.add("legal");
      if (S.selected === id) el.classList.add("selected");
      el.addEventListener("click", () => { S.selected = S.selected === id ? null : id; Sound.slide(); renderGame(); });
    } else if (mine) {
      if (legalCards.has(id) && g.source === "hand") {
        el.classList.add("legal");
        el.addEventListener("click", () => act(id));
        el.title = "Click to play · double-click to play all of this rank";
        el.addEventListener("dblclick", () => playAllOfRank(id));
      } else el.classList.add("dim");
    }
  });

  // action bar
  const bar = $("#actionBar");
  bar.innerHTML = "";
  const btn = (label, cls, fn) => { const b = document.createElement("button"); b.className = `btn ${cls}`; b.innerHTML = label; b.addEventListener("click", fn); bar.append(b); };
  if (g.status === "fixing" && !me.ready) btn("I'm ready ✓", "primary", () => { S.selected = null; send({ type: "fix", op: "done" }); });
  if (mine) {
    if (L.end_group) btn(`Done ✓`, "primary", () => act(A_END));
    if (L.pick_up) btn("Pick up pile", "danger", () => act(A_PICKUP));
    if (L.reveal) btn("Flip deck top", "primary", () => act(A_REVEAL));
  }
  // pile shortcuts
  $("#drawPile").onclick = () => mine && L.reveal && act(A_REVEAL);
  $("#livePile").onclick = () => mine && L.pick_up && act(A_PICKUP);
}

async function playAllOfRank(id) {
  // Play the clicked card, then the rest of that rank, then end the group.
  const r = rankIx(id);
  const order = [id, ...S.game.hand.filter((c) => c !== id && rankIx(c) === r)];
  S.autoGroup = { rank: r, queue: order.slice(1) };
  act(id);
}

function fixSlot(k) {
  const me = S.game.players[S.seat];
  const slot = me.face_up[k];
  if (S.selected === null) {
    if (slot.length > 1 && me.hand_count < 3 && S.game.draw_count === 0) send({ type: "fix", op: "unstack", slot: k });
    return;
  }
  const top = slot[slot.length - 1];
  const op = top !== undefined && rankIx(top) === rankIx(S.selected) ? "stack" : "swap";
  send({ type: "fix", op, card: S.selected, slot: k });
  S.selected = null;
  Sound.snap();
}

// ============================================================ animations
function rectOf(el) { return el ? el.getBoundingClientRect() : null; }
function seatAnchor(i, part = "hand") {
  if (i === S.seat) {
    if (part === "slots") return $("#mySlots");
    return $("#hand");
  }
  const seat = $(`.seat[data-seat="${i}"]`);
  if (!seat) return null;
  return part === "slots" ? $(".slots", seat) : $(".opp-hand", seat) || seat;
}
function findCardEl(i, id) {
  const root = i === S.seat ? $("#me") : $(`.seat[data-seat="${i}"]`);
  return root ? $(`.card[data-card="${id}"]`, root) : null;
}
async function fly(fromRect, toRect, id, { dur = 360, faceDown = false, rotateTo = 0, fromRot = 0, hideSource = null, keep = false } = {}) {
  if (!fromRect || !toRect) return;
  dur = dur * S.speed;
  const wrap = document.createElement("div");
  wrap.className = "fly";
  const el = cardEl(faceDown ? null : id);
  const w = toRect.width || 70;
  el.style.setProperty("--card-w", `${w}px`);
  wrap.append(el);
  $("#fx").append(wrap);
  if (hideSource) hideSource.style.visibility = "hidden";
  const sx = fromRect.left + fromRect.width / 2 - w / 2, sy = fromRect.top + fromRect.height / 2 - (w * 1.4) / 2;
  const tx = toRect.left + toRect.width / 2 - w / 2, ty = toRect.top + toRect.height / 2 - (w * 1.4) / 2;
  const s0 = Math.max(0.35, (fromRect.width || w) / w);
  const anim = wrap.animate([
    { transform: `translate(${sx}px, ${sy}px) scale(${s0}) rotate(${fromRot}deg)` },
    { transform: `translate(${(sx + tx) / 2}px, ${Math.min(sy, ty) - 30}px) scale(1.08) rotate(${(fromRot + rotateTo) / 2 + 6}deg)`, offset: 0.55 },
    { transform: `translate(${tx}px, ${ty}px) scale(1) rotate(${rotateTo}deg)` },
  ], { duration: dur, easing: "cubic-bezier(.3,.7,.25,1)", fill: "forwards" });
  await anim.finished.catch(() => {});
  if (!keep) wrap.remove();
  return wrap;
}
function livePileTargetRect() {
  const pile = $("#livePile");
  const r = pile.getBoundingClientRect();
  const w = parseFloat(getComputedStyle(pile.querySelector(".card") || pile).width) || r.width / 1.55;
  const left = r.left + r.width * 0.27 / 1.55 * 1.55 * 0.6;
  return new DOMRect(r.left + (r.width - w) / 2, r.top, w, w * 1.4);
}
function pushLive(id) { S.liveShown.push(id); drawLive(S.liveShown); }
function clearLive() { S.liveShown = []; drawLive([]); }

async function dealAnimation() {
  const g = S.game;
  const from = rectOf($("#drawPile")) || rectOf($("#center"));
  const tasks = [];
  g.players.forEach((_, i) => {
    const slots = seatAnchor(i, "slots"), hand = seatAnchor(i, "hand");
    for (let k = 0; k < 3; k++) {
      tasks.push(sleep((k * g.players.length + i) * 45).then(() => fly(from, rectOf(slots), null, { dur: 420, faceDown: true })));
      tasks.push(sleep(250 + (k * g.players.length + i) * 45).then(() => fly(from, rectOf(hand), null, { dur: 420, faceDown: true })));
    }
  });
  Sound.swoosh();
  await Promise.all(tasks);
}

async function animateEvents(events, prev, next) {
  for (const e of events) {
    const who = e.player;
    switch (e.kind) {
      case "start":
        toast(`${nameOf(who)} ${verb(who, "start", "starts")} with <b>${short(e.card)}</b>`);
        break;
      case "play": {
        const src = findCardEl(who, e.card);
        const from = rectOf(src) || rectOf(seatAnchor(who, e.source === "face_up" ? "slots" : "hand"));
        Sound.snap();
        S.lastActor = who;
        await fly(from, livePileTargetRect(), e.card, { dur: who === S.seat ? 300 : 420, rotateTo: rot(e.card), hideSource: src });
        pushLive(e.card);
        break;
      }
      case "draw": {
        const to = rectOf(seatAnchor(who, "hand"));
        const from = rectOf($("#drawPile"));
        for (let k = 0; k < Math.min(e.count, 3); k++) {
          Sound.slide();
          fly(from, to, null, { dur: 300, faceDown: true });
          await sleep(110 * S.speed);
        }
        await sleep(160 * S.speed);
        break;
      }
      case "pickup": {
        const to = rectOf(seatAnchor(who, "hand"));
        const from = rectOf($("#livePile"));
        Sound.swoosh();
        const cards = e.cards.slice(-6);
        clearLive();
        await Promise.all(cards.map((c, k) => sleep(k * 60 * S.speed).then(() => fly(from, to, c, { dur: 420, fromRot: rot(c) }))));
        toast(`${nameOf(who)} ${verb(who, "pick", "picks")} up <b>${e.cards.length}</b> card${e.cards.length === 1 ? "" : "s"}`, who === S.seat ? "bad" : "");
        break;
      }
      case "flip": {
        S.lastFlipRank = e.rank;
        const r = RANKS[e.rank];
        const label = r === "10" ? "FLIP!" : r === "8" ? "Four 8s — boom!" : r === "9" ? "Four 9s — resurrect!" : r === "3" ? "Four 3s — share!" : r === "4" ? "Four 4s!" : `Four ${r}s — FLIP!`;
        callout(label, r === "8");
        r === "8" ? Sound.bad() : Sound.flip();
        const from = rectOf($("#livePile"));
        const to = rectOf($("#discardPile"));
        const cards = S.liveShown.slice(-5);
        clearLive();
        await Promise.all(cards.map((c, k) => sleep(k * 50 * S.speed).then(() => fly(from, to, c, { dur: 480, fromRot: rot(c), rotateTo: 180 }))));
        toast(`${nameOf(who)} ${verb(who, "flip", "flips")} the pile${e.rank === 7 ? " with a 10" : ` — four ${r}s`}`);
        if (r === "9" && next.live.length) { S.liveShown = []; drawLive(next.live); }
        await sleep(200 * S.speed);
        break;
      }
      case "deal_three":
      case "take_three": {
        const from = rectOf(e.kind === "take_three" ? $("#discardPile") : $("#center"));
        await fly(from, rectOf(seatAnchor(who, "hand")), e.card, { dur: 380 });
        toast(`${nameOf(who)} ${verb(who, "get", "gets")} <b>${short(e.card)}</b>`);
        break;
      }
      case "reveal": {
        const from = rectOf($("#drawPile"));
        Sound.slide();
        if (e.ok) {
          S.lastActor = who;
          await fly(from, livePileTargetRect(), e.card, { dur: 460, rotateTo: rot(e.card) });
          pushLive(e.card);
          toast(`${nameOf(who)} ${verb(who, "flip", "flips")} <b>${short(e.card)}</b> off the deck — it plays!`);
        } else {
          const w = await fly(from, rectOf($("#center")), e.card, { dur: 380, keep: true });
          await sleep(450 * S.speed); w?.remove();
          toast(`${nameOf(who)} ${verb(who, "flip", "flips")} <b>${short(e.card)}</b> off the deck — no luck`, who === S.seat ? "bad" : "");
        }
        break;
      }
      case "face_down": {
        const slot = $(`.slot[data-seat="${who}"][data-slot="${e.slot}"]`);
        const from = rectOf(slot?.querySelector(".card.down") || slot);
        const hideSrc = slot?.querySelector(".card.down");
        if (e.ok) {
          Sound.snap();
          S.lastActor = who;
          await fly(from, livePileTargetRect(), e.card, { dur: 520, rotateTo: rot(e.card), hideSource: hideSrc });
          pushLive(e.card);
        } else {
          const w = await fly(from, rectOf($("#center")), e.card, { dur: 420, hideSource: hideSrc, keep: true });
          Sound.bad();
          await sleep(500 * S.speed); w?.remove();
          toast(`${nameOf(who)} ${verb(who, "turn", "turns")} over <b>${short(e.card)}</b> — doesn't fit`, who === S.seat ? "bad" : "");
        }
        break;
      }
      case "nine_draw": {
        callout(`9 draws ${short(e.card)}`);
        Sound.flip();
        await fly(rectOf($("#discardPile")), livePileTargetRect(), e.card, { dur: 520, rotateTo: rot(e.card) });
        pushLive(e.card);
        toast(`The 9 pulls <b>${short(e.card)}</b> from the discard`);
        break;
      }
      case "reverse":
        callout("Reverse!");
        $("#dirRing").classList.toggle("ccw", e.direction === -1);
        $("#dirRing").classList.add("spin"); setTimeout(() => $("#dirRing").classList.remove("spin"), 800);
        await sleep(300 * S.speed);
        break;
      case "skip":
        callout(e.count > 1 ? `Skip ×${e.count}` : "Skip!");
        await sleep(300 * S.speed);
        break;
      case "win":
      case "lose":
        break;
      default:
        break;
    }
  }
  // Continue a "play all of rank" chain.
  if (S.autoGroup && next.current === S.seat && next.group_rank === S.autoGroup.rank) {
    const nextCard = S.autoGroup.queue.find((c) => (next.legal?.cards || []).includes(c));
    if (nextCard !== undefined) {
      S.autoGroup.queue = S.autoGroup.queue.filter((c) => c !== nextCard);
      setTimeout(() => { S.pendingAction = false; act(nextCard); }, 30);
    } else if (next.legal?.end_group) {
      S.autoGroup = null;
      setTimeout(() => { S.pendingAction = false; act(A_END); }, 30);
    }
  } else if (S.autoGroup && next.group_rank !== S.autoGroup.rank) S.autoGroup = null;
}

// ================================================================== hints
function showHint(action) {
  if (action === null || action === undefined) return;
  let el = null, text = "";
  if (action < 52) {
    el = $(`#hand .card[data-card="${action}"]`) || $(`#mySlots .card[data-card="${action}"]`);
    text = `Shark would play <b>${short(action)}</b>`;
  } else if (action === A_PICKUP) { el = $$("#actionBar .btn").find((b) => b.textContent.includes("Pick up")); text = "Shark would <b>pick up</b>"; }
  else if (action === A_REVEAL) { el = $$("#actionBar .btn").find((b) => b.textContent.includes("Flip")); text = "Shark would <b>flip the deck top</b>"; }
  else if (action === A_END) { el = $$("#actionBar .btn").find((b) => b.textContent.includes("Done")); text = "Shark would <b>stop here</b>"; }
  else if (action >= A_FACEDOWN) { el = $(`#mySlots .card.down[data-down="${action - A_FACEDOWN}"]`); text = "Shark would flip <b>this face-down card</b>"; }
  toast(`💡 ${text}`);
  if (el) { el.classList.remove("hint-glow"); void el.offsetWidth; el.classList.add("hint-glow"); }
}

// =============================================================== results
function showResult() {
  const g = S.game, r = S.room;
  if (!g || g.status !== "over") return;
  const youWin = g.winner === S.seat || (g.loser !== null && g.loser !== S.seat && g.players.length === 2);
  let emoji, title, text;
  if (g.winner !== null && g.winner !== undefined) {
    if (g.winner === S.seat) { emoji = "🏆"; title = "You win!"; text = "Finished first — and legally."; }
    else { emoji = "🃏"; title = `${nameOf(g.winner)} wins`; text = "They went out first."; }
  } else {
    const how = S.lastFlipRank === 5 ? "flipped the 8s" : "finished illegally";
    if (g.loser === S.seat) { emoji = "💀"; title = "You lose"; text = `You ${how}.`; }
    else { emoji = g.players.length === 2 ? "🏆" : "😅"; title = `${nameOf(g.loser)} ${how}`; text = g.players.length === 2 ? "Which means you win!" : "And loses the game."; }
  }
  $("#resultEmoji").textContent = emoji;
  $("#resultTitle").innerHTML = title;
  $("#resultText").textContent = text;
  $("#revealHands").innerHTML = g.players.map((p, i) => {
    const cards = [...(p.hand || []), ...p.face_up.flat(), ...(p.face_down_cards || []).filter((c) => c !== null)];
    return `<div class="reveal-row"><span class="name">${r.seats[i]?.avatar ?? ""} ${nameOf(i)}</span><div class="cards">${
      cards.length ? cards.map((c) => cardHTML(c, { tiny: true })).join("") : '<span class="muted small">out!</span>'}</div></div>`;
  }).join("");
  $("#scoreboard").innerHTML = r.seats.map((s, i) => `<span class="score-pill">${s.avatar} ${i === S.seat ? "You" : esc(s.name)} <b>${s.wins}</b></span>`).join("");
  const host = r.host === S.seat;
  $("#rematchBtn").classList.toggle("hidden", !host);
  $("#toLobbyBtn").classList.toggle("hidden", !host);
  $("#rematchWait").textContent = host ? "" : "Waiting for the host to deal again…";
  $("#resultOverlay").classList.remove("hidden");
  if (youWin) { Sound.win(); confetti(); } else Sound.bad();
}

function confetti() {
  const canvas = $("#confetti"), ctx = canvas.getContext("2d");
  canvas.width = innerWidth; canvas.height = innerHeight;
  const colors = ["#f2c14e", "#e9a93a", "#c0392b", "#fffdf6", "#57d68d", "#7dd3fc"];
  const parts = Array.from({ length: 160 }, () => ({
    x: innerWidth / 2 + (Math.random() - 0.5) * 200, y: innerHeight / 3,
    vx: (Math.random() - 0.5) * 14, vy: -Math.random() * 14 - 4, s: 4 + Math.random() * 6,
    r: Math.random() * 6, vr: (Math.random() - 0.5) * 0.3, c: colors[(Math.random() * colors.length) | 0],
  }));
  let t = 0;
  (function frame() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of parts) {
      p.vy += 0.35; p.vx *= 0.99; p.x += p.vx; p.y += p.vy; p.r += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.c; ctx.fillRect(-p.s / 2, -p.s / 4, p.s, p.s / 2); ctx.restore();
    }
    if (++t < 200) requestAnimationFrame(frame); else ctx.clearRect(0, 0, canvas.width, canvas.height);
  })();
}

// ================================================================ emotes
function bubble(seat, text, isChat) {
  const anchor = seat === S.seat ? $("#meBadge") : $(`.seat[data-seat="${seat}"] .seat-head`);
  if (!anchor) return;
  const r = anchor.getBoundingClientRect();
  const el = document.createElement("div");
  el.className = `bubble ${isChat ? "text" : ""}`;
  el.textContent = text;
  el.style.left = `${r.left + r.width / 2}px`;
  el.style.top = `${r.top - 10}px`;
  document.body.append(el);
  setTimeout(() => el.remove(), 1900);
}

// ================================================================== rules
function buildRules() {
  $("#powers").innerHTML = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"].map((r) => {
    const id = RANKS.indexOf(r) * 4 + 3;
    return `<div class="power-item">${cardHTML(id, { tiny: true })}<div>${POWER_TEXT[r]}</div></div>`;
  }).join("");
  const order = ["3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A", "2"];
  let html = `<caption>Row = card you play · column = card on top of the live pile</caption><tr><th></th>${order.map((r) => `<th>${r}</th>`).join("")}</tr>`;
  for (const p of order) {
    const ok = new Set(ON[p].filter((x) => x !== " ").map((x) => (x === "1" ? "10" : x)));
    html += `<tr><th>${p}</th>${order.map((t) => {
      const y = t === "10" ? false : ok.has(t);
      return `<td class="${y ? "y" : "n"}">${y ? "✓" : "·"}</td>`;
    }).join("")}</tr>`;
  }
  $("#matrix").innerHTML = html;
}

// ================================================================== wiring
function wire() {
  $$("[data-open]").forEach((b) => b.addEventListener("click", () => $(`#${b.dataset.open}`).classList.remove("hidden")));
  $$(".overlay").forEach((o) => o.addEventListener("click", (e) => {
    if (e.target === o && o.id !== "resultOverlay") o.classList.add("hidden");
    if (e.target.closest("[data-close]")) o.classList.add("hidden");
  }));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $$(".overlay:not(#resultOverlay)").forEach((o) => o.classList.add("hidden"));
    if (!$("#game").classList.contains("active") || e.target.closest("input, select, textarea")) return;
    if ($$(".overlay:not(.hidden)").length) return;
    const playable = $$("#hand .card.legal, #mySlots .card.legal");
    if (/^[1-9]$/.test(e.key) && playable[Number(e.key) - 1]) { e.preventDefault(); playable[Number(e.key) - 1].click(); }
    else if (e.key === " " || e.key === "Enter") { const b = $("#actionBar .btn"); if (b) { e.preventDefault(); b.click(); } }
    else if (e.key === "h" || e.key === "H") { if (!$("#hintBtn").disabled) send({ type: "hint" }); }
  });
  $("#leaveLobby").addEventListener("click", leaveRoom);
  $("#copyLink").addEventListener("click", copyInvite);
  $("#copyLink2").addEventListener("click", copyInvite);
  $("#startGame").addEventListener("click", () => { Sound.unlock(); send({ type: "start" }); });
  $$("[data-addbot]").forEach((b) => b.addEventListener("click", () => send({ type: "add_bot", level: b.dataset.addbot })));
  $("#rematchBtn").addEventListener("click", () => { $("#resultOverlay").classList.add("hidden"); send({ type: "rematch" }); });
  $("#toLobbyBtn").addEventListener("click", () => { $("#resultOverlay").classList.add("hidden"); send({ type: "lobby" }); });
  $("#homeBtn").addEventListener("click", leaveRoom);
  $("#leaveGame").addEventListener("click", () => { $("#menuOverlay").classList.add("hidden"); leaveRoom(); });
  $("#menuBtn").addEventListener("click", () => {
    $("#speedRange").closest(".row").classList.toggle("hidden", S.room?.host !== S.seat);
    $("#menuOverlay").classList.remove("hidden");
  });
  $("#speedRange").addEventListener("change", (e) => send({ type: "speed", delay: Number(e.target.value) }));
  $("#hintBtn").addEventListener("click", () => send({ type: "hint" }));
  const soundBtn = $("#soundBtn");
  const syncSound = () => (soundBtn.textContent = S.sound ? "🔊" : "🔇");
  syncSound();
  soundBtn.addEventListener("click", () => { S.sound = !S.sound; localStorage.setItem("ibflip:sound", S.sound ? "on" : "off"); syncSound(); Sound.unlock(); });
  $("#emoteBar").innerHTML = EMOTES.map((e) => `<button data-emote="${e}">${e}</button>`).join("");
  $("#emoteBar").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) send({ type: "emote", emoji: b.dataset.emote }); });
  window.addEventListener("resize", () => S.game && $("#game").classList.contains("active") && renderGame());
}

async function wakeServer() {
  const note = $("#serverNote");
  const slow = setTimeout(() => (note.textContent = "Waking up the game server… (free hosting naps — ~30s)"), 1800);
  try {
    const res = await fetch(`${API}/health`);
    const h = await res.json();
    note.textContent = h.model ? "" : "";
  } catch (_) {
    note.textContent = "Can't reach the game server right now.";
  } finally { clearTimeout(slow); if (note.textContent.startsWith("Waking")) note.textContent = ""; }
}

function boot() {
  initHome();
  wire();
  buildRules();
  wakeServer();
  const code = new URLSearchParams(location.search).get("room");
  if (code) {
    const saved = JSON.parse(localStorage.getItem(`ibflip:room:${code.toUpperCase()}`) || "null");
    if (saved) { S.code = code.toUpperCase(); S.token = saved.token; S.seat = saved.seat; connect(); return; }
    $$(".tab").find((t) => t.dataset.tab === "friends").click();
    $("#codeInput").value = code.toUpperCase();
    if (!$("#nameInput").value) $("#nameInput").focus();
  }
}
boot();
