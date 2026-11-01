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
  liveShown: [], speed: 1, groupSlot: null, dealing: false, autoGroup: null,
};

// ===================================================================== sound
// Soft, short sounds: everything goes through one quiet master bus with a
// gentle low-pass and a compressor, and every voice has an attack/release
// envelope (no hard starts or stops, so no clicks).
const Sound = (() => {
  let ctx = null, bus = null, noiseBuf = null;
  const ac = () => {
    if (ctx) return ctx;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -24; comp.ratio.value = 4;
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 5200;
    bus = ctx.createGain(); bus.gain.value = 0.55;
    bus.connect(lp).connect(comp).connect(ctx.destination);
    return ctx;
  };
  const ok = () => S.sound && !document.hidden;
  function env(g, t, peak, attack, dur) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  }
  function brush(dur, { freq = 1800, q = 0.7, gain = 0.06, sweep = 0, attack = 0.006, when = 0 } = {}) {
    if (!ok()) return;
    const a = ac(), t = a.currentTime + when;
    if (!noiseBuf) {
      noiseBuf = a.createBuffer(1, a.sampleRate, a.sampleRate);
      const d = noiseBuf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    }
    const src = a.createBufferSource(); src.buffer = noiseBuf;
    const f = a.createBiquadFilter(); f.type = "bandpass"; f.frequency.setValueAtTime(freq, t); f.Q.value = q;
    if (sweep) f.frequency.exponentialRampToValueAtTime(freq * sweep, t + dur);
    const g = a.createGain(); env(g, t, gain, attack, dur);
    src.connect(f).connect(g).connect(bus);
    src.start(t, Math.random() * 0.5); src.stop(t + dur + 0.05);
  }
  function tone(freq, dur, { when = 0, gain = 0.035, type = "sine", attack = 0.012 } = {}) {
    if (!ok()) return;
    const a = ac(), t = a.currentTime + when, o = a.createOscillator(), g = a.createGain();
    o.type = type; o.frequency.value = freq;
    env(g, t, gain, attack, dur);
    o.connect(g).connect(bus); o.start(t); o.stop(t + dur + 0.05);
  }
  return {
    snap: () => brush(0.09, { freq: 2400, q: 1.1, gain: 0.07, attack: 0.004 }),
    slide: () => brush(0.18, { freq: 900, q: 0.6, gain: 0.035, sweep: 1.8, attack: 0.03 }),
    swoosh: () => brush(0.32, { freq: 600, q: 0.5, gain: 0.05, sweep: 2.5, attack: 0.05 }),
    flip: () => { brush(0.4, { freq: 500, q: 0.5, gain: 0.05, sweep: 3, attack: 0.06 }); tone(392, 0.35, { when: 0.05, gain: 0.025, type: "triangle" }); },
    turn: () => { tone(659, 0.35, { gain: 0.03 }); tone(988, 0.45, { when: 0.09, gain: 0.022 }); },
    bad: () => { tone(330, 0.35, { gain: 0.03, type: "triangle" }); tone(247, 0.5, { when: 0.12, gain: 0.028, type: "triangle" }); },
    win: () => [523, 659, 784, 1046].forEach((f, i) => tone(f, 0.5, { when: i * 0.1, gain: 0.03, type: "triangle" })),
    unlock: () => { try { if (S.sound) ac().resume(); } catch (_) {} },
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
const ordinal = (n) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th"}`;
// Server sends finish as "legal" | "illegal" | "eights" (older builds:
// "LEGAL_WIN" | "ILLEGAL_LOSS"). Normalise to the new names.
function finishOf(p) {
  const f = String(p?.finish || "").toLowerCase();
  if (!f) return null;
  if (f.startsWith("legal")) return "legal";
  if (f.includes("eight")) return "eights";
  return "illegal";
}
const hasPlace = (p) => p && p.place !== null && p.place !== undefined;
function placeLabel(p, n) {
  if (!hasPlace(p)) return "";
  return p.place === n && finishOf(p) !== "legal" ? "last" : ordinal(p.place);
}
function finishText(i, p, n) {
  const who = nameOf(i), f = finishOf(p);
  const last = p.place === n;
  const where = last ? "last place" : `${ordinal(p.place)} place`;
  if (f === "eights") return `${who} flipped the 8s — ${where}`;
  if (f === "illegal") return `${who} finished illegally — ${where}`;
  return `${who} finished ${ordinal(p.place)} 🎉`;
}

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
// A room can vanish (server restart / idle cleanup). Instead of a red error,
// show a calm notice with a one-click way back into a game.
function roomLost() {
  const quick = S.quick;
  if (S.code) localStorage.removeItem(`ibflip:room:${S.code}`);
  leaveRoom();
  $("#homeError").textContent = "";
  const n = Number(segVal("botCount") || 3), level = LEVEL_NAME[segVal("botLevel") || "medium"];
  $("#lostText").textContent = quick
    ? `The game server restarted, so that table was cleared. Deal a fresh game with the same ${n} ${level} bot${n === 1 ? "" : "s"}?`
    : "The game server restarted, so that room was cleared. Create a new room and send your friends the new code.";
  $("#lostAgain").textContent = quick ? "Start a new game" : "Create a new room";
  $("#lostAgain").onclick = quick ? quickPlay : createRoom;
  if (!quick) $$(".tab").find((t) => t.dataset.tab === "friends")?.click();
  $("#lostNotice").classList.remove("hidden");
}
function hideLost() { $("#lostNotice").classList.add("hidden"); }
function busyHome(on) { $$("#home .btn").forEach((b) => (b.disabled = on)); }
async function quickPlay() {
  Sound.unlock();
  hideLost();
  busyHome(true); $("#homeError").textContent = "";
  try {
    const n = Number(segVal("botCount") || 3), level = segVal("botLevel") || "medium";
    const r = await api("/api/rooms", { name: playerName(), bots: Array(n).fill(level), autostart: true });
    enterRoom(r, true);
  } catch (e) { $("#homeError").textContent = e.message; } finally { busyHome(false); }
}
async function createRoom() {
  Sound.unlock();
  hideLost();
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
function enterRoom({ code, token, seat }, quick = false) {
  S.code = code; S.token = token; S.seat = seat; S.quick = quick;
  localStorage.setItem(`ibflip:room:${code}`, JSON.stringify({ token, seat, quick }));
  history.replaceState(null, "", `?room=${code}`);
  connect();
}
function leaveRoom() {
  if (S.ws) { S.ws.onclose = null; S.ws.close(); }
  clearTimeout(S.reconnectTimer);
  Object.assign(S, { code: null, token: null, seat: null, ws: null, room: null, game: null, queue: [], busy: false, resultShownFor: null, pendingAction: false, autoGroup: null });
  clearInterval(S.pingTimer);
  $("#fx").innerHTML = "";
  $("#seats").innerHTML = "";
  $("#hand").innerHTML = "";
  $$(".overlay").forEach((o) => o.classList.add("hidden"));
  document.title = "IB-Flip";
  history.replaceState(null, "", location.pathname);
  $("#resultOverlay").classList.add("hidden");
  show("home");
}

// ================================================================ socket
let reconnects = 0;
// Delay between bot moves on the server, in seconds (server clamps 0.2–2.0).
const PACE_DEFAULT = 1.35;
const pace = () => { const v = Number(localStorage.getItem("ibflip:pace")); return v >= 0.2 && v <= 2 ? v : PACE_DEFAULT; };
function connect() {
  clearTimeout(S.reconnectTimer);
  const ws = new WebSocket(`${WS_BASE}/ws/${S.code}?token=${encodeURIComponent(S.token)}`);
  S.ws = ws;
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") { S.queue.push(msg); pump(); }
    else if (msg.type === "error") {
      if (msg.fatal && /room not found/i.test(msg.message || "")) roomLost();
      else if (msg.fatal) { localStorage.removeItem(`ibflip:room:${S.code}`); leaveRoom(); $("#homeError").textContent = friendlyError(msg.message); }
      else { toast(`<b>Hmm.</b> ${esc(msg.message)}`, "bad"); S.pendingAction = false; renderGame(); }
    } else if (msg.type === "emote" || msg.type === "chat") bubble(msg.seat, msg.text, msg.type === "chat");
    else if (msg.type === "hint") showHint(msg.action);
    else if (msg.type === "kicked") { leaveRoom(); $("#homeError").textContent = "You were removed from the room."; }
  };
  ws.onclose = () => {
    if (S.ws !== ws || !S.code) return;
    S.pendingAction = false;
    $("#hudStatus").textContent = "Reconnecting…";
    S.reconnectTimer = setTimeout(connect, Math.min(8000, 1200 * 2 ** reconnects++));
  };
  ws.onopen = () => {
    clearInterval(S.pingTimer);
    reconnects = 0;
    // The host sets the bot pace for the room (other seats are ignored).
    ws.send(JSON.stringify({ type: "speed", delay: pace() }));
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
      // Catch up gently if messages pile up; never so fast that moves blur.
      S.speed = S.queue.length > 3 ? 0.6 : S.queue.length > 1 ? 0.85 : 1;
      const prev = S.game;
      const inGame = msg.game && prev && $("#game").classList.contains("active") && msg.room.game_no === S.lastGameNo;
      // Background tabs don't run animations (their promises would stall the
      // queue), so just apply state there.
      if (inGame && msg.events?.length && !document.hidden) {
        S.room = msg.room;
        try { await animateEvents(msg.events, prev, msg.game); } catch (e) { console.error(e); }
      }
      const finished = inGame ? newlyFinished(prev, msg.game) : [];
      try { await apply(msg); } catch (e) { console.error(e); }
      for (const i of finished) await announceFinish(i, msg.game);
    }
  } finally { S.busy = false; }
}

async function apply(msg) {
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
    S.lastGameNo = msg.room.game_no; S.selected = null; S.resultShownFor = null; S.lastActor = null;
    S.autoGroup = null; S.groupSlot = null;
    $("#resultOverlay").classList.add("hidden");
    $("#hand").innerHTML = "";
    narrate("");
    $("#narration").classList.remove("show");
    S.liveShown = [];
    renderGame();
    if (!document.hidden) await dealAnimation();
  } else renderGame();
  if (S.game.current === S.seat && prevCurrent !== S.seat && S.game.status === "playing") {
    Sound.turn();
  }
  document.title = S.game.current === S.seat && S.game.status === "playing" ? "● Your turn — IB-Flip" : "IB-Flip";
  if (S.game.status === "over" && S.resultShownFor !== S.room.game_no) {
    S.resultShownFor = S.room.game_no;
    setTimeout(showResult, 1100);
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
// Seat centres as % of the table box. The table keeps a fixed stadium
// aspect ratio (see .table in styles.css), so these stay on the felt.
const SEAT_POS = {
  1: [[50, 17]],
  2: [[28, 19], [72, 19]],
  3: [[11, 48], [50, 17], [89, 48]],
  4: [[11, 52], [32, 17], [68, 17], [89, 52]],
};
const SEAT_POS_NARROW = {
  1: [[50, 13]],
  2: [[28, 13], [72, 13]],
  3: [[22, 33], [50, 11], [78, 33]],
  4: [[22, 34], [28, 10], [72, 10], [78, 34]],
};
const narrow = () => innerWidth <= 760;
function relIndex(i) { const n = S.game.players.length; return (i - S.seat + n) % n; }

// Only touch the DOM when a piece of markup actually changed. Elements keep
// their identity between state messages, so CSS transitions run instead of
// nodes being thrown away and re-created on every update.
function setHTML(el, html) {
  if (el.__html !== html) { el.innerHTML = html; el.__html = html; }
}

function renderGame() {
  const g = S.game, r = S.room;
  if (!g) return;
  $("#hudCode").textContent = r.code;
  $("#dirRing").classList.toggle("ccw", g.direction === -1);
  renderSeats();
  renderPiles();
  renderMe();
  renderStatus();
}

function renderSeats() {
  const g = S.game, r = S.room, n = g.players.length;
  const seats = $("#seats");
  const pos = (narrow() ? SEAT_POS_NARROW : SEAT_POS)[n - 1] || SEAT_POS[4];
  const want = new Set();
  for (let i = 0; i < n; i++) if (i !== S.seat) want.add(String(i));
  $$(".seat", seats).forEach((el) => { if (!want.has(el.dataset.seat)) el.remove(); });
  for (let i = 0; i < n; i++) {
    if (i === S.seat) continue;
    const p = g.players[i], s = r.seats[i] || {};
    let el = $(`.seat[data-seat="${i}"]`, seats);
    if (!el) {
      el = document.createElement("div");
      el.className = "seat";
      el.dataset.seat = i;
      el.innerHTML = `<div class="seat-head"></div><div class="opp-row"><div class="opp-hand" data-hand="${i}"></div><div class="known" title="Cards everyone saw go into this hand"></div></div><div class="slots"></div>`;
      seats.append(el);
    }
    const [x, y] = pos[relIndex(i) - 1];
    el.style.left = `${x}%`; el.style.top = `${y}%`;
    el.classList.toggle("turn", g.current === i);
    el.classList.toggle("out", !p.active || hasPlace(p));
    el.classList.toggle("finished", hasPlace(p));
    el.classList.toggle("ready", g.status === "fixing" && p.ready);
    el.classList.toggle("ready-wait", g.status === "fixing" && !p.ready);
    const sub = s.kind === "bot" ? LEVEL_NAME[s.level] : s.connected ? "" : "away";
    setHTML($(".seat-head", el), `<div class="avatar">${s.avatar ?? "🙂"}${s.kind === "human" ? `<span class="dot ${s.connected ? "" : "off"}"></span>` : ""}</div>
        <div class="seat-text"><div class="seat-name">${esc(s.name ?? "Player")}</div><div class="seat-sub">${sub}</div></div>${hasPlace(p) ? `<span class="place-badge ${finishOf(p) === "legal" ? "" : "bad"}">${placeLabel(p, n)}</span>` : ""}`);
    const backs = Math.min(p.hand_count, 6);
    setHTML($(".opp-hand", el), `${Array.from({ length: backs }, () => cardHTML(null)).join("")}${p.hand_count ? `<span class="hand-count">${p.hand_count}</span>` : ""}`);
    const known = $(".known", el);
    known.classList.toggle("hidden", !p.known.length);
    setHTML(known, p.known.slice().sort((a, b) => a - b).map((c) => `<span class="chip ${isRed(c) ? "red" : ""}">${short(c)}</span>`).join(""));
    renderSlots($(".slots", el), p, i, false);
  }
}

function slotHTML(p, k, mine) {
  const down = p.face_down[k];
  const ups = p.face_up[k] || [];
  return `${down ? cardHTML(null, { cls: "down", extra: `data-down="${k}"` }) : ""}${ups.map((c) => cardHTML(c, { cls: "up", tiny: !mine })).join("")}`;
}
function renderSlots(container, p, seat, mine) {
  for (let k = 0; k < 3; k++) {
    let slot = container.children[k];
    if (!slot) {
      slot = document.createElement("div");
      slot.className = "slot";
      slot.dataset.slot = k;
      container.append(slot);
    }
    slot.dataset.seat = seat;
    setHTML(slot, slotHTML(p, k, mine));
    slot.classList.toggle("empty", !p.face_down[k] && !(p.face_up[k] || []).length);
  }
}

function renderPiles() {
  const g = S.game;
  const draw = $("#drawPile");
  const dn = Math.min(g.draw_count, 5);
  setHTML(draw, Array.from({ length: dn }, (_, i) => cardHTML(null, { extra: `style="translate:${-i * 1.2}px ${-i * 1.2}px"` })).join(""));
  setHTML($("#drawLabel"), g.draw_count ? `Deck <b>${g.draw_count}</b>` : "Deck empty");
  S.liveShown = [...g.live];
  drawLive(g.live);
  const k = Math.min(Math.ceil(g.discard_count / 6), 5);
  setHTML($("#discardPile"), Array.from({ length: k }, (_, i) => cardHTML(null, { extra: `style="translate:${-i * 1.2}px ${-i * 1.2}px; rotate:${i % 2 ? 3 : -2}deg"` })).join(""));
  setHTML($("#discardLabel"), g.discard_count ? `Discard <b>${g.discard_count}</b>` : "Discard");
  const mine = g.current === S.seat && g.status === "playing" && !S.pendingAction;
  draw.classList.toggle("clickable", mine && !!g.legal?.reveal);
  $("#livePile").classList.toggle("clickable", mine && !!g.legal?.pick_up);
  $("#livePile").classList.toggle("fourloop", !!g.four_loop);
}

const LIVE_FAN = 5;
const liveTransform = (c, i, len) => `translateX(${(i - (len - 1)) * 16}%) rotate(${rot(c)}deg)`;
// Keyed by card id: cards already on the pile keep their node and slide
// (CSS transition) when the fan shifts; only new cards are created.
function drawLive(live) {
  const el = $("#livePile");
  const shown = live.slice(-LIVE_FAN);
  const keep = new Set(shown);
  const aceOne = new Set(S.game?.ace_one || []);
  $$(".card", el).forEach((c) => { if (!keep.has(Number(c.dataset.card))) c.remove(); });
  shown.forEach((c, i) => {
    let node = $(`.card[data-card="${c}"]`, el);
    if (!node) node = cardEl(c);
    if (el.children[i] !== node) el.insertBefore(node, el.children[i] || null);
    node.style.transform = liveTransform(c, i, shown.length);
    node.classList.toggle("ace-one", aceOne.has(c));
  });
  const by = live.length && S.lastActor !== null && S.lastActor !== undefined ? ` · ${S.lastActor === S.seat ? "you" : esc(S.room?.seats[S.lastActor]?.name ?? "")}` : "";
  setHTML($("#liveLabel"), live.length ? `Live <b>${live.length}</b>${by}` : "Live");
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
      text = waiting.length ? `Waiting for ${waiting.map(esc).join(", ")}…` : "Dealing…";
    } else {
      yours = true;
      text = S.selected === null
        ? "Tap a hand card, then a face-up card to swap. Good face-up cards: 10, 2, 4, 5, 7."
        : `Now tap a face-up card to ${me.face_up.some((sl) => sl.length && rankIx(sl[sl.length - 1]) === rankIx(S.selected)) ? "swap — or a matching one to stack" : "swap"}`;
    }
  } else if (g.status === "playing") {
    if (g.current === S.seat) {
      yours = true;
      const L = g.legal || {};
      if (g.nine_draw) text = "Drawing from the discard…";
      else if (g.group_rank !== null && g.group_rank !== undefined) text = L.cards?.length ? `Add another ${RANKS[g.group_rank]} — or tap Done` : "Tap Done to finish your turn";
      else if (L.face_down?.length) text = "Blind time — pick a face-down card";
      else if (g.start_card !== null && g.start_card !== undefined && L.cards?.length === 1 && L.cards[0] === g.start_card) text = `You start — play your ${short(g.start_card)}`;
      else if (!L.cards?.length && L.reveal && L.pick_up) text = "Nothing playable — flip the deck top or pick up the pile";
      else if (!L.cards?.length && L.reveal) text = "Nothing playable — flip the top of the deck";
      else if (!L.cards?.length && L.pick_up) text = "Nothing playable — pick up the pile";
      else if (g.four_loop) text = "4-loop! Play a 4, 5 or 6 — or pick up";
      else text = `Your turn — ${targetText(g)}`;
    } else if (hasPlace(me)) {
      text = `You finished ${placeLabel(me, g.players.length) === "last" ? "last" : ordinal(me.place)} — watching the rest…`;
    } else if (g.current !== null) {
      text = `${nameOf(g.current)} is thinking…`;
    }
  }
  setHTML(prompt, text);
  prompt.classList.toggle("yours", yours);
  $("#me").classList.toggle("turn", g.current === S.seat && g.status === "playing");
  $("#me").classList.toggle("spectating", g.status === "playing" && hasPlace(me));
  $("#hintBtn").disabled = !(g.current === S.seat && g.status === "playing" && !g.nine_draw);
}

function renderMe() {
  const g = S.game, me = g.players[S.seat], s = S.room.seats[S.seat] || {};
  setHTML($("#meBadge"), `<div class="avatar">${s.avatar ?? "🙂"}</div><div><div class="seat-name">${esc(s.name ?? "You")}</div><div class="seat-sub">You</div></div>`);
  const mine = g.status === "playing" && g.current === S.seat && !S.pendingAction;
  const fixing = g.status === "fixing" && !me.ready;
  const L = mine ? g.legal || {} : {};
  const legalCards = new Set(L.cards || []);

  // ---- table slots (clicks are delegated, see wireTable)
  // Face-up plays: only the top card of a slot is offered, it must be in the
  // server's legal list, and once a group has started from a slot only that
  // same slot (a stack made during setup) may continue it.
  const slots = $("#mySlots");
  renderSlots(slots, me, S.seat, true);
  const groupOpen = g.group_rank !== null && g.group_rank !== undefined;
  if (!groupOpen) S.groupSlot = null;
  const lockSlot = mine && g.source === "face_up" && groupOpen ? S.groupSlot : null;
  $$(".slot", slots).forEach((slotEl) => {
    const k = Number(slotEl.dataset.slot);
    const ups = $$(".card.up", slotEl);
    ups.forEach((c, j) => {
      const id = Number(c.dataset.card), top = j === ups.length - 1;
      c.classList.toggle("target", fixing && S.selected !== null && top);
      c.classList.toggle("fixable", fixing && top);
      c.classList.toggle("legal", top && legalCards.has(id) && g.source === "face_up" && (lockSlot === null || lockSlot === undefined || lockSlot === k));
    });
    const down = $(".card.down", slotEl);
    if (down) down.classList.toggle("legal", (L.face_down || []).includes(k));
  });

  renderHand(g, me, { mine, fixing, legalCards });

  // ---- action bar: rebuilt only when the set of buttons changes
  const buttons = [];
  if (fixing) buttons.push(["I'm ready ✓", "primary", "ready"]);
  if (mine) {
    if (L.end_group) buttons.push(["Done ✓", "primary", A_END]);
    if (L.pick_up) buttons.push(["Pick up pile", "danger", A_PICKUP]);
    if (L.reveal) buttons.push(["Flip deck top", "primary", A_REVEAL]);
  }
  setHTML($("#actionBar"), buttons.map(([label, cls, a]) => `<button class="btn ${cls}" data-act="${a}">${label}</button>`).join(""));
}

function handLayout(hand, n) {
  const cw = hand.querySelector(".card")?.offsetWidth || 80;
  const avail = Math.max(160, hand.clientWidth - 24);
  const margin = n > 1 ? Math.min(-cw * 0.08, (avail - n * cw) / (2 * n)) : 0;
  const spread = Math.min(20, n * 3);
  return { margin, spread, arc: Math.min(10, n * 1.6) };
}

function renderHand(g, me, { mine, fixing, legalCards }) {
  const hand = $("#hand");
  const cards = [...g.hand].sort((a, b) => a - b);
  const want = new Set(cards);
  const known = new Set(me.known || []);
  const existing = new Map($$(".card", hand).map((el) => [Number(el.dataset.card), el]));
  // FLIP: remember where the surviving cards were laid out (offsetLeft
  // ignores the per-card rotate/lift transforms, so only the slide is animated).
  const before = new Map();
  for (const [id, el] of existing) if (want.has(id)) before.set(id, el.offsetLeft);
  for (const [id, el] of existing) if (!want.has(id)) el.remove();
  const added = [];
  cards.forEach((id, i) => {
    let el = existing.get(id);
    if (!el || !want.has(id)) { el = cardEl(id); added.push(el); }
    if (hand.children[i] !== el) hand.insertBefore(el, hand.children[i] || null);
  });
  const n = cards.length;
  const { margin, spread, arc } = handLayout(hand, n);
  $$(".card", hand).forEach((el, i) => {
    const id = Number(el.dataset.card);
    el.style.margin = `0 ${margin}px`;
    const t = n > 1 ? (i / (n - 1)) * 2 - 1 : 0; // -1 .. 1
    el.style.setProperty("--rot", `${(t * spread) / 2}deg`);
    el.style.setProperty("--arc", `${-(1 - t * t) * arc}px`);
    el.style.zIndex = i + 1;
    const legal = (fixing) || (mine && legalCards.has(id) && g.source === "hand");
    el.classList.toggle("known-mark", known.has(id) && g.status !== "fixing");
    el.classList.toggle("legal", legal);
    el.classList.toggle("selected", fixing && S.selected === id);
    el.classList.toggle("dim", mine && !legal);
    el.classList.remove("pending");
    el.title = mine && legal ? "Click to play · double-click to play all of this rank" : "";
  });
  if (REDUCED()) return;
  for (const [id, x0] of before) {
    const el = existing.get(id);
    const dx = x0 - el.offsetLeft;
    if (Math.abs(dx) > 1) el.animate([{ translate: `${dx}px 0` }, { translate: "0 0" }], { duration: 280, easing: "cubic-bezier(.2,.8,.2,1)" });
  }
  if (S.dealing) return;
  added.forEach((el, k) => el.animate([{ opacity: 0, translate: "0 24px" }, { opacity: 1, translate: "0 0" }], { duration: 260, delay: k * 40, easing: "cubic-bezier(.2,.8,.2,1)", fill: "backwards" }));
}

// Delegated input for the player's own area — listeners live on stable
// containers, so re-rendering never stacks duplicate handlers.
function wireTable() {
  $("#hand").addEventListener("click", (e) => {
    const c = e.target.closest(".card"); if (!c || !S.game) return;
    const id = Number(c.dataset.card);
    if (S.game.status === "fixing") {
      if (!S.game.players[S.seat].ready) { S.selected = S.selected === id ? null : id; Sound.slide(); renderGame(); }
      return;
    }
    if (c.classList.contains("legal")) playCard(c, id);
  });
  $("#hand").addEventListener("dblclick", (e) => {
    const c = e.target.closest(".card.legal"); if (!c || !S.game || S.game.status !== "playing") return;
    playAllOfRank(Number(c.dataset.card));
  });
  $("#mySlots").addEventListener("click", (e) => {
    const c = e.target.closest(".card"); if (!c || !S.game) return;
    const slot = c.closest(".slot"), k = Number(slot.dataset.slot);
    if (S.game.status === "fixing") { if (c.classList.contains("fixable")) fixSlot(k); return; }
    if (!c.classList.contains("legal")) return;
    if (c.classList.contains("down")) act(A_FACEDOWN + k);
    else { if (!S.pendingAction && S.groupSlot === null) S.groupSlot = k; playCard(c, Number(c.dataset.card)); }
  });
  $("#mySlots").addEventListener("dblclick", (e) => {
    // Double-click a face-up stack: play every card in that one slot.
    const c = e.target.closest(".card.up"); if (!c || !S.game || S.game.status !== "playing") return;
    const k = Number(c.closest(".slot").dataset.slot);
    if (S.groupSlot !== k) return;
    const id = Number(c.dataset.card);
    const rest = (S.game.players[S.seat].face_up[k] || []).filter((x) => x !== id && rankIx(x) === rankIx(id)).reverse();
    S.autoGroup = { rank: rankIx(id), queue: rest, slot: k };
  });
  $("#actionBar").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act]"); if (!b) return;
    if (b.dataset.act === "ready") { S.selected = null; send({ type: "fix", op: "done" }); b.disabled = true; return; }
    act(Number(b.dataset.act));
  });
  $("#drawPile").addEventListener("click", () => $("#drawPile").classList.contains("clickable") && act(A_REVEAL));
  $("#livePile").addEventListener("click", () => $("#livePile").classList.contains("clickable") && act(A_PICKUP));
}
function playCard(el, id) {
  if (S.pendingAction) return;
  el.classList.add("pending");
  act(id);
}

async function playAllOfRank(id) {
  // Play the clicked card, then the rest of that rank, then end the group.
  const r = rankIx(id);
  if (!S.game.hand.includes(id)) return;
  const order = [id, ...S.game.hand.filter((c) => c !== id && rankIx(c) === r)];
  S.autoGroup = { rank: r, queue: order.slice(1) };
  if (!S.pendingAction) act(id);
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
const REDUCED = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
function rectOf(el) { return el ? el.getBoundingClientRect() : null; }
function seatAnchor(i, part = "hand") {
  if (i === S.seat) return part === "slots" ? $("#mySlots") : $("#hand");
  const seat = $(`.seat[data-seat="${i}"]`);
  if (!seat) return null;
  return part === "slots" ? $(".slots", seat) : $(".opp-hand", seat) || seat;
}
// Width of one card inside a container (hand, slot row, pile…).
function cardWidthIn(el) {
  if (!el) return 70;
  const c = el.querySelector(".card");
  if (c && c.offsetWidth) return c.offsetWidth;
  if (el.classList.contains("slot") || el.classList.contains("pile")) return el.offsetWidth;
  const v = parseFloat(getComputedStyle(el).getPropertyValue("--card-w"));
  return v || 70;
}
// A card-sized rect centred on a container. Using the container's own rect
// as a card rect is what made flying cards balloon to the size of the hand.
function cardRect(el, w = cardWidthIn(el)) {
  const r = rectOf(el);
  if (!r) return null;
  const h = w * 1.4;
  return new DOMRect(r.left + r.width / 2 - w / 2, r.top + r.height / 2 - h / 2, w, h);
}
function findCardEl(i, id) {
  const root = i === S.seat ? $("#me") : $(`.seat[data-seat="${i}"]`);
  return root ? $(`.card[data-card="${id}"]`, root) : null;
}
async function fly(fromRect, toRect, id, { dur = 420, faceDown = false, rotateTo = 0, fromRot = 0, hideSource = null, keep = false, arc = 34 } = {}) {
  if (!fromRect || !toRect) return null;
  if (hideSource) hideSource.style.visibility = "hidden";
  if (REDUCED()) return null;
  dur *= S.speed;
  const wrap = document.createElement("div");
  wrap.className = "fly";
  const el = cardEl(faceDown ? null : id);
  const w = toRect.width || 70;
  el.style.setProperty("--card-w", `${w}px`);
  wrap.append(el);
  const sx = fromRect.left + fromRect.width / 2 - w / 2, sy = fromRect.top + fromRect.height / 2 - (w * 1.4) / 2;
  const tx = toRect.left + toRect.width / 2 - w / 2, ty = toRect.top + toRect.height / 2 - (w * 1.4) / 2;
  const s0 = Math.min(1.6, Math.max(0.35, (fromRect.width || w) / w));
  const lift = Math.min(arc, Math.abs(tx - sx) * 0.12 + 8);
  wrap.style.transform = `translate(${sx}px, ${sy}px) scale(${s0}) rotate(${fromRot}deg)`;
  $("#fx").append(wrap);
  const anim = wrap.animate([
    { transform: `translate(${sx}px, ${sy}px) scale(${s0}) rotate(${fromRot}deg)` },
    { transform: `translate(${(sx + tx) / 2}px, ${(sy + ty) / 2 - lift}px) scale(${(s0 + 1) / 2 * 1.04}) rotate(${(fromRot + rotateTo) / 2}deg)`, offset: 0.5 },
    { transform: `translate(${tx}px, ${ty}px) scale(1) rotate(${rotateTo}deg)` },
  ], { duration: dur, easing: "cubic-bezier(.45,.05,.25,1)", fill: "forwards" });
  await anim.finished.catch(() => {});
  if (!keep) wrap.remove();
  return wrap;
}
// Exactly where the next live-pile card will sit, so the landing is seamless.
function livePileTargetRect() {
  const pile = $("#livePile");
  const r = pile.getBoundingClientRect();
  const w = pileW() || r.width / 1.6;
  // Matches `.live-pile .card { right: calc(var(--pile-card-w) * .3) }`.
  return new DOMRect(r.right - w * 1.3, r.top + r.height / 2 - (w * 1.4) / 2, w, w * 1.4);
}
const pileW = () => $("#drawPile").offsetWidth || 70;
function pushLive(id) { S.liveShown.push(id); drawLive(S.liveShown); }
function clearLive() { S.liveShown = []; drawLive([]); }

// Narration: one clear caption under the piles saying what just happened.
let narrTimer = null;
function narrate(html, cls = "") {
  const el = $("#narration");
  if (!el) return;
  el.innerHTML = html;
  el.className = `narration show ${cls}`;
  el.getAnimations().forEach((a) => a.cancel());
  if (!REDUCED()) el.animate([{ opacity: 0, transform: "translate(-50%, 6px)" }, { opacity: 1, transform: "translate(-50%, 0)" }], { duration: 220, easing: "ease-out" });
  clearTimeout(narrTimer);
  narrTimer = setTimeout(() => el.classList.add("stale"), 4200);
}
const POWER_NOTE = { "2": "goes again", "4": "4-loop", "5": "play under it", "7": "7 or lower next", "8": "skip", "9": "draws from the discard", "10": "flip!" };
function playNote(card, count, events, idx) {
  const r = rankOf(card);
  if (r === "3") {
    const rev = events.slice(idx + 1).some((e) => e.kind === "reverse");
    return rev ? "reverse" : "";
  }
  if (r === "8") return "";
  return POWER_NOTE[r] || "";
}

async function dealAnimation() {
  const g = S.game;
  if (REDUCED()) return;
  const from = cardRect($("#drawPile"), pileW()) || cardRect($("#center"));
  const table = $("#game");
  S.dealing = true;
  table.classList.add("dealing");
  const tasks = [];
  const n = g.players.length;
  const step = n > 3 ? 40 : 55;
  g.players.forEach((_, i) => {
    const slotsEl = seatAnchor(i, "slots"), handEl = seatAnchor(i, "hand");
    if (!slotsEl || !handEl) return;
    const slotEls = [...slotsEl.children];
    for (let k = 0; k < 3; k++) {
      const slot = slotEls[k];
      tasks.push(sleep((k * n + i) * step).then(() => fly(from, cardRect(slot, cardWidthIn(slot)), null, { dur: 420, faceDown: true }))
        .then(() => slot?.classList.add("dealt")));
    }
    tasks.push(sleep((3 * n + i) * step).then(() => fly(from, cardRect(handEl, cardWidthIn(handEl)), null, { dur: 420, faceDown: true }))
      .then(() => handEl.classList.add("dealt")));
  });
  Sound.swoosh();
  await Promise.all(tasks);
  table.classList.remove("dealing");
  $$(".dealt").forEach((e) => e.classList.remove("dealt"));
  S.dealing = false;
}

function newlyFinished(prev, next) {
  if (!prev || !next) return [];
  return next.players.map((p, i) => (hasPlace(p) && !hasPlace(prev.players[i]) ? i : -1)).filter((i) => i >= 0)
    .sort((a, b) => next.players[a].place - next.players[b].place);
}
// A calm, readable banner when someone finishes; the queue waits for it.
async function announceFinish(i, g) {
  const p = g.players[i], n = g.players.length, f = finishOf(p);
  const el = $("#announce");
  el.innerHTML = `<span class="announce-place ${f === "legal" ? "" : "bad"}">${placeLabel(p, n) === "last" ? "Last" : ordinal(p.place)}</span><span>${finishText(i, p, n)}</span>`;
  el.classList.remove("show"); void el.offsetWidth; el.classList.add("show");
  narrate(finishText(i, p, n), f === "legal" ? "" : "bad");
  if (i === S.seat) (f === "legal" ? Sound.win : Sound.bad)();
  else Sound.turn();
  if (document.hidden) return;
  await sleep(g.status === "over" ? 900 : 1700);
}

// Per-move pacing (ms). Other players' moves get a readable hold after the
// card lands; your own moves stay snappy.
const HOLD_BOT = 420, HOLD_ME = 90;
async function animateEvents(events, prev, next) {
  for (let idx = 0; idx < events.length; idx++) {
    const e = events[idx];
    const who = e.player;
    const me = who === S.seat;
    const hold = (ms) => sleep((me ? HOLD_ME : ms) * S.speed);
    switch (e.kind) {
      case "start":
        narrate(`${nameOf(who)} ${verb(who, "start", "starts")} with <b>${short(e.card)}</b>`);
        break;
      case "play": {
        const src = findCardEl(who, e.card);
        const anchor = seatAnchor(who, e.source === "face_up" ? "slots" : "hand");
        const from = src ? rectOf(src) : cardRect(anchor);
        S.lastActor = who;
        const note = playNote(e.card, 1, events, idx);
        narrate(`${nameOf(who)} ${verb(who, "play", "plays")} <b class="${isRed(e.card) ? "red" : ""}">${short(e.card)}</b>${note ? ` <span class="note">— ${note}</span>` : ""}`);
        await fly(from, livePileTargetRect(), e.card, { dur: me ? 300 : 520, fromRot: src ? 0 : 0, rotateTo: rot(e.card), hideSource: src });
        Sound.snap();
        pushLive(e.card);
        await hold(HOLD_BOT);
        break;
      }
      case "draw": {
        const to = cardRect(seatAnchor(who, "hand"));
        const from = cardRect($("#drawPile"));
        Sound.slide();
        for (let k = 0; k < Math.min(e.count, 3); k++) {
          fly(from, to, null, { dur: 340, faceDown: true });
          await sleep(90 * S.speed);
        }
        await sleep(260 * S.speed);
        break;
      }
      case "pickup": {
        const to = cardRect(seatAnchor(who, "hand"));
        const from = livePileTargetRect();
        Sound.swoosh();
        narrate(`${nameOf(who)} ${verb(who, "pick", "picks")} up <b>${e.cards.length}</b> card${e.cards.length === 1 ? "" : "s"}`, me ? "bad" : "");
        const cards = e.cards.slice(-LIVE_FAN);
        clearLive();
        await Promise.all(cards.map((c, k) => sleep(k * 60 * S.speed).then(() => fly(from, to, c, { dur: 460, fromRot: rot(c) }))));
        await hold(HOLD_BOT);
        break;
      }
      case "flip": {
        S.lastFlipRank = e.rank;
        const r = RANKS[e.rank];
        const label = r === "10" ? "Flip!" : r === "8" ? "Four 8s — boom!" : r === "9" ? "Four 9s — resurrect!" : r === "3" ? "Four 3s — share!" : r === "4" ? "Four 4s!" : `Four ${r}s — flip!`;
        callout(label, r === "8");
        r === "8" ? Sound.bad() : Sound.flip();
        narrate(`${nameOf(who)} ${verb(who, "flip", "flips")} the pile${e.rank === 7 ? " with a 10" : ` — four ${r}s`}`, r === "8" ? "bad" : "");
        const from = livePileTargetRect();
        const to = cardRect($("#discardPile"), pileW());
        const cards = S.liveShown.slice(-LIVE_FAN);
        await sleep(260 * S.speed);
        clearLive();
        await Promise.all(cards.map((c, k) => sleep(k * 50 * S.speed).then(() => fly(from, to, c, { dur: 500, fromRot: rot(c), rotateTo: 180 + rot(c), faceDown: false }))));
        if (r === "9" && next.live.length) { S.liveShown = []; drawLive(next.live); }
        await sleep(380 * S.speed);
        break;
      }
      case "deal_three":
      case "take_three": {
        const from = e.kind === "take_three" ? cardRect($("#discardPile"), pileW()) : livePileTargetRect();
        await fly(from, cardRect(seatAnchor(who, "hand")), e.card, { dur: 420 });
        narrate(`${nameOf(who)} ${verb(who, "get", "gets")} <b>${short(e.card)}</b>`);
        await sleep(200 * S.speed);
        break;
      }
      case "reveal": {
        const from = cardRect($("#drawPile"));
        Sound.slide();
        if (e.ok) {
          S.lastActor = who;
          narrate(`${nameOf(who)} ${verb(who, "flip", "flips")} <b>${short(e.card)}</b> off the deck — it plays`);
          await fly(from, livePileTargetRect(), e.card, { dur: 500, rotateTo: rot(e.card) });
          pushLive(e.card);
          await hold(HOLD_BOT);
        } else {
          narrate(`${nameOf(who)} ${verb(who, "flip", "flips")} <b>${short(e.card)}</b> off the deck — no luck`, me ? "bad" : "");
          const w = await fly(from, livePileTargetRect(), e.card, { dur: 420, keep: true });
          await sleep(520 * S.speed);
          if (w) await w.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, fill: "forwards" }).finished.catch(() => {});
          w?.remove();
        }
        break;
      }
      case "face_down": {
        const slot = $(`.slot[data-seat="${who}"][data-slot="${e.slot}"]`);
        const hideSrc = slot?.querySelector(".card.down");
        const from = rectOf(hideSrc) || cardRect(slot);
        if (e.ok) {
          S.lastActor = who;
          narrate(`${nameOf(who)} ${verb(who, "turn", "turns")} over <b>${short(e.card)}</b> — it plays`);
          await fly(from, livePileTargetRect(), e.card, { dur: 540, rotateTo: rot(e.card), hideSource: hideSrc });
          Sound.snap();
          pushLive(e.card);
          await hold(HOLD_BOT);
        } else {
          narrate(`${nameOf(who)} ${verb(who, "turn", "turns")} over <b>${short(e.card)}</b> — doesn't fit`, me ? "bad" : "");
          const w = await fly(from, livePileTargetRect(), e.card, { dur: 460, hideSource: hideSrc, keep: true });
          Sound.bad();
          await sleep(560 * S.speed);
          if (w) await w.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, fill: "forwards" }).finished.catch(() => {});
          w?.remove();
        }
        break;
      }
      case "nine_draw": {
        callout(`9 draws ${short(e.card)}`);
        Sound.flip();
        narrate(`The 9 pulls <b>${short(e.card)}</b> from the discard`);
        await fly(cardRect($("#discardPile"), pileW()), livePileTargetRect(), e.card, { dur: 540, rotateTo: rot(e.card) });
        pushLive(e.card);
        await sleep(300 * S.speed);
        break;
      }
      case "reverse":
        callout("Reverse!");
        $("#dirRing").classList.toggle("ccw", e.direction === -1);
        $("#dirRing").classList.remove("spin"); void $("#dirRing").offsetWidth; $("#dirRing").classList.add("spin");
        await sleep(520 * S.speed);
        break;
      case "skip": {
        callout(e.count > 1 ? `Skip ×${e.count}` : "Skip!");
        const el = $("#narration");
        if (el && !/skip/i.test(el.textContent)) el.insertAdjacentHTML("beforeend", ` <span class="note">— skip${e.count > 1 ? ` ×${e.count}` : ""}</span>`);
        await sleep(520 * S.speed);
        break;
      }
      default:
        break;
    }
  }
  // Continue a "play all of rank" chain.
  if (S.autoGroup && next.current === S.seat && next.group_rank === S.autoGroup.rank) {
    // Only ever chain a card the server lists as legal (and, for a face-up
    // stack, only the current top of that same slot).
    const legalNow = new Set(next.legal?.cards || []);
    let nextCard;
    if (S.autoGroup.slot !== undefined) {
      const top = (next.players[S.seat].face_up[S.autoGroup.slot] || []).slice(-1)[0];
      if (next.source === "face_up" && legalNow.has(top) && rankIx(top) === S.autoGroup.rank) nextCard = top;
    } else if (next.source === "hand") {
      // Includes same-rank cards drawn mid-group (early game draws back to 3).
      nextCard = (next.hand || []).filter((c) => legalNow.has(c) && rankIx(c) === S.autoGroup.rank).sort((a, b) => a - b)[0];
    }
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
  toast(`💡 ${text}`, "hint");
  if (el) { el.classList.remove("hint-glow"); void el.offsetWidth; el.classList.add("hint-glow"); }
}

// =============================================================== results
function showResult() {
  const g = S.game, r = S.room;
  if (!g || g.status !== "over") return;
  const n = g.players.length;
  const placed = g.players.some(hasPlace);
  const me = g.players[S.seat];
  let youWin, emoji, title, text;
  if (placed && hasPlace(me)) {
    const f = finishOf(me);
    youWin = me.place === 1 && f === "legal" || (n === 2 && g.loser !== null && g.loser !== undefined && g.loser !== S.seat);
    if (me.place === 1) { emoji = "🏆"; title = "You win!"; text = "Finished first — and legally."; }
    else if (me.place === n) { emoji = "💀"; title = "Last place"; text = f === "eights" ? "You flipped the 8s." : f === "illegal" ? "You finished illegally." : "Everyone else got out first."; }
    else { emoji = me.place === 2 ? "🥈" : "🥉"; title = `You finished ${ordinal(me.place)}`; text = `${nameOf(g.players.findIndex((p) => p.place === 1))} took 1st.`; }
  } else {
    youWin = g.winner === S.seat || (g.loser !== null && g.loser !== S.seat && n === 2);
    if (g.winner !== null && g.winner !== undefined) {
      if (g.winner === S.seat) { emoji = "🏆"; title = "You win!"; text = "Finished first — and legally."; }
      else { emoji = "🃏"; title = `${nameOf(g.winner)} wins`; text = "They went out first."; }
    } else {
      const how = finishOf(g.players[g.loser]) === "eights" || S.lastFlipRank === 5 ? "flipped the 8s" : "finished illegally";
      if (g.loser === S.seat) { emoji = "💀"; title = "You lose"; text = `You ${how}.`; }
      else { emoji = n === 2 ? "🏆" : "😅"; title = `${nameOf(g.loser)} ${how}`; text = n === 2 ? "Which means you win!" : "And loses the game."; }
    }
  }
  $("#resultEmoji").textContent = emoji;
  $("#resultTitle").innerHTML = title;
  $("#resultText").textContent = text;
  // Standings, 1st → last (players without a place, if any, go last).
  const order = g.players.map((p, i) => i).sort((a, b) => (g.players[a].place ?? 99) - (g.players[b].place ?? 99));
  $("#revealHands").innerHTML = order.map((i) => {
    const p = g.players[i];
    const cards = [...(p.hand || []), ...p.face_up.flat(), ...(p.face_down_cards || []).filter((c) => c !== null)];
    const f = finishOf(p);
    const tag = hasPlace(p) ? `<span class="standing ${f === "legal" ? "" : "bad"}">${placeLabel(p, n) === "last" ? "Last" : ordinal(p.place)}</span>` : `<span class="standing none">–</span>`;
    const why = f === "eights" ? "8s" : f === "illegal" ? "illegal" : "";
    return `<div class="reveal-row ${i === S.seat ? "is-me" : ""}">${placed ? tag : ""}<span class="name">${r.seats[i]?.avatar ?? ""} ${nameOf(i)}${why ? ` <small class="why">${why}</small>` : ""}</span><div class="cards">${
      cards.length ? cards.map((c) => cardHTML(c, { tiny: true })).join("") : '<span class="muted small">out</span>'}</div></div>`;
  }).join("");
  $("#scoreboard").innerHTML = r.seats.map((s, i) => `<span class="score-pill">${s.avatar} ${i === S.seat ? "You" : esc(s.name)} <b>${s.wins}</b></span>`).join("");
  const host = r.host === S.seat;
  $("#rematchBtn").classList.toggle("hidden", !host);
  $("#toLobbyBtn").classList.toggle("hidden", !host);
  $("#rematchWait").textContent = host ? "" : "Waiting for the host to deal again…";
  $("#resultOverlay").classList.remove("hidden");
  (host ? $("#rematchBtn") : $("#homeBtn")).focus({ preventScroll: true });
  if (youWin) { Sound.win(); confetti(); } else Sound.bad();
}

function confetti() {
  if (REDUCED()) return;
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
    else if (e.key === " " || e.key === "Enter") { const b = $("#actionBar .btn.primary:not(:disabled)") || $("#actionBar .btn:not(:disabled)"); if (b) { e.preventDefault(); b.click(); } }
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
  // Slider runs slow → fast; the server wants a delay, so invert it.
  const speedRange = $("#speedRange");
  speedRange.value = (2.2 - pace()).toFixed(2);
  $("#menuBtn").addEventListener("click", () => {
    speedRange.closest(".row").classList.toggle("hidden", S.room?.host !== S.seat);
    $("#menuOverlay").classList.remove("hidden");
  });
  speedRange.addEventListener("change", (e) => {
    const delay = Math.round((2.2 - Number(e.target.value)) * 100) / 100;
    localStorage.setItem("ibflip:pace", delay);
    send({ type: "speed", delay });
  });
  $("#hintBtn").addEventListener("click", () => send({ type: "hint" }));
  const soundBtn = $("#soundBtn");
  const syncSound = () => (soundBtn.textContent = S.sound ? "🔊" : "🔇");
  syncSound();
  soundBtn.addEventListener("click", () => { S.sound = !S.sound; localStorage.setItem("ibflip:sound", S.sound ? "on" : "off"); syncSound(); Sound.unlock(); });
  const emoteBar = $("#emoteBar"), emoteBtn = $("#emoteBtn");
  emoteBar.innerHTML = EMOTES.map((e) => `<button data-emote="${e}" aria-label="Send ${e}">${e}</button>`).join("");
  const setEmotes = (open) => { emoteBar.classList.toggle("open", open); emoteBtn.setAttribute("aria-expanded", String(open)); };
  emoteBtn.addEventListener("click", (e) => { e.stopPropagation(); setEmotes(!emoteBar.classList.contains("open")); });
  emoteBar.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { send({ type: "emote", emoji: b.dataset.emote }); setEmotes(false); } });
  document.addEventListener("click", (e) => { if (!e.target.closest("#emoteBar")) setEmotes(false); });
  $("#lostDismiss").addEventListener("click", hideLost);
  wireTable();
  let resizeRaf = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(() => S.game && $("#game").classList.contains("active") && renderGame());
  });
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
    if (saved) { S.code = code.toUpperCase(); S.token = saved.token; S.seat = saved.seat; S.quick = !!saved.quick; connect(); return; }
    $$(".tab").find((t) => t.dataset.tab === "friends").click();
    $("#codeInput").value = code.toUpperCase();
    if (!$("#nameInput").value) $("#nameInput").focus();
  }
}
boot();
