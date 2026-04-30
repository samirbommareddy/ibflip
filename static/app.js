const API_BASE =
  window.IBFLIP_API_BASE ||
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8000"
    : "https://ibflip.onrender.com");

let sessionId = null;
let latestState = null;
let isReplaying = false;

const statusEl = document.getElementById("status");
const startButton = document.getElementById("startButton");
const playerCountEl = document.getElementById("playerCount");
const handEl = document.getElementById("hand");
const faceUpEl = document.getElementById("faceUp");
const faceDownEl = document.getElementById("faceDown");
const specialActionsEl = document.getElementById("specialActions");
const handCountEl = document.getElementById("handCount");
const faceUpCountEl = document.getElementById("faceUpCount");
const faceDownCountEl = document.getElementById("faceDownCount");
const actionCountEl = document.getElementById("actionCount");
const opponentsEl = document.getElementById("opponents");
const liveTopEl = document.getElementById("liveTop");
const liveMetaEl = document.getElementById("liveMeta");
const liveCountBadgeEl = document.getElementById("liveCountBadge");
const discardTopEl = document.getElementById("discardTop");
const discardMetaEl = document.getElementById("discardMeta");
const discardCountBadgeEl = document.getElementById("discardCountBadge");
const gameLogEl = document.getElementById("gameLog");
const moveBannerEl = document.getElementById("moveBanner");
const turnBadgeEl = document.getElementById("turnBadge");

startButton.addEventListener("click", startGame);

async function startGame() {
  startButton.disabled = true;
  playerCountEl.disabled = true;
  clearLog();
  setMoveBanner("Shuffling and dealing...");
  try {
    const state = await request("/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ num_players: Number(playerCountEl.value) }),
    });
    sessionId = state.session_id;
    await renderState(state, { replay: true });
  } catch (error) {
    addLog(`Error: ${error.message}`, "bad");
    setMoveBanner("Could not start game");
  } finally {
    playerCountEl.disabled = false;
    startButton.disabled = false;
  }
}

async function playAction(actionId) {
  if (!sessionId || !latestState?.is_human_turn || isReplaying) return;
  disableActions(true);
  setMoveBanner("Resolving your move...");
  highlightActor(0);
  try {
    const state = await request(`/play/${sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: actionId }),
    });
    await renderState(state, { replay: true });
  } catch (error) {
    addLog(`Error: ${error.message}`, "bad");
    setMoveBanner("That move is not legal right now");
  } finally {
    disableActions(false);
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail?.message || payload.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

async function renderState(state, options = {}) {
  latestState = state;
  document.body.classList.toggle("has-game", Boolean(state.session_id));
  playerCountEl.value = String(state.num_players || playerCountEl.value);
  updateStatus(state);
  renderOpponents(state.opponents);
  renderPiles(state);
  renderHuman(state);

  if (options.replay && state.moves?.length) {
    await replayMoves(state.moves, state.bot_replay_delay_ms || 1300);
  } else {
    renderLog(state.log);
  }

  if (!state.moves?.length) {
    setMoveBanner(state.is_human_turn ? "Choose a highlighted card or action" : "Waiting for bots");
  }
  highlightActor(state.game_over ? null : state.current_player);
}

function updateStatus(state) {
  statusEl.textContent = state.game_over
    ? gameOverText(state)
    : state.is_human_turn
      ? "Your turn"
      : `Player ${state.current_player + 1} is acting`;
  setTurnBadge(
    state.game_over ? "Game Over" : state.is_human_turn ? "Your Move" : `Player ${state.current_player + 1}`,
    state.is_human_turn,
  );
}

function setTurnBadge(text, active = false) {
  turnBadgeEl.textContent = text;
  turnBadgeEl.className = active ? "turn-badge active" : "turn-badge";
}

function renderOpponents(opponents) {
  opponentsEl.innerHTML = "";
  opponentsEl.dataset.count = opponents.length;
  opponents.forEach((player) => {
    const panel = document.createElement("article");
    panel.className = `opponent seat-${player.player_index}`;
    panel.dataset.playerIndex = String(player.player_index);
    panel.innerHTML = `
      <div class="player-head">
        <h2>Player ${player.player_index + 1}</h2>
        <span class="seat-status">${player.active ? "In" : player.finish_status || "Out"}</span>
      </div>
      <div class="turn-marker">Acting</div>
      <div class="opponent-counts">
        <div>${backStack(player.hand_count, "Hand")}</div>
        <div>${backStack(player.face_down_count, "Down")}</div>
      </div>
      <div class="mini-slots">${player.face_up_slots
        .map((slot) => `<div class="mini-slot">${slot.map((card) => cardHTML(card, { mini: true })).join("") || emptySlot()}</div>`)
        .join("")}</div>
    `;
    opponentsEl.appendChild(panel);
  });
}

function renderPiles(state) {
  renderPileSnapshot({
    liveTop: state.live_pile_top,
    liveCards: state.live_pile,
    liveCount: state.live_pile.length,
    discardTop: state.discard_top,
    discardCount: state.discard_count,
    drawCount: state.draw_count,
  });
}

function renderPileSnapshot(snapshot) {
  const liveCards = snapshot.liveCards || (snapshot.liveTop ? [snapshot.liveTop] : []);
  liveTopEl.className = liveCards.length ? "pile-stack live-stack" : "pile-stack empty-stack";
  liveTopEl.innerHTML = liveCards.length ? liveStackHTML(liveCards) : emptyPile("Live");
  liveMetaEl.textContent = `${snapshot.liveCount} live`;
  liveCountBadgeEl.textContent = snapshot.liveCount;

  discardTopEl.innerHTML = snapshot.discardTop ? cardHTML(snapshot.discardTop, { large: true, muted: true }) : emptyPile("Discard");
  discardMetaEl.textContent = `${snapshot.discardCount} discard · ${snapshot.drawCount} draw`;
  discardCountBadgeEl.textContent = snapshot.discardCount;
}

function renderHuman(state) {
  const legal = new Set(state.legal_actions);
  const specialActionIds = state.legal_actions.filter((actionId) => actionId >= 52 && actionId < 67);
  const faceUpTotal = state.human.face_up_slots.reduce((total, slot) => total + slot.length, 0);
  const faceDownTotal = (state.human_face_down_slots || []).filter((slot) => slot.available).length;

  handCountEl.textContent = `${state.human.hand.length}`;
  faceUpCountEl.textContent = `${faceUpTotal}`;
  faceDownCountEl.textContent = `${faceDownTotal}`;
  actionCountEl.textContent = `${specialActionIds.length}`;

  updateHandLayout(state.human.hand.length);
  handEl.innerHTML = "";
  state.human.hand.forEach((card, index) => {
    handEl.appendChild(
      cardButton(card, card.id, legal.has(card.id), {
        showPlayable: true,
        handIndex: index,
        handCount: state.human.hand.length,
      }),
    );
  });

  faceUpEl.innerHTML = "";
  state.human.face_up_slots.forEach((slot, index) => {
    const slotEl = document.createElement("div");
    slotEl.className = "human-slot";
    slotEl.innerHTML = `<span class="slot-label">Up ${index + 1}</span>`;
    const row = document.createElement("div");
    row.className = "card-row compact";
    slot.forEach((card) => row.appendChild(cardButton(card, card.id, legal.has(card.id), { compact: true })));
    if (!slot.length) row.innerHTML = emptySlot();
    slotEl.appendChild(row);
    faceUpEl.appendChild(slotEl);
  });

  faceDownEl.innerHTML = "";
  (state.human_face_down_slots || []).forEach((slot) => {
    if (!slot.available) return;
    const button = document.createElement("button");
    button.className = `playing-card card-back ${legal.has(slot.action_id) ? "legal" : ""}`;
    button.type = "button";
    button.disabled = !legal.has(slot.action_id) || !state.is_human_turn || isReplaying;
    button.innerHTML = `<span>?</span><small>Slot ${slot.slot + 1}</small>`;
    button.addEventListener("click", () => playAction(slot.action_id));
    faceDownEl.appendChild(button);
  });

  specialActionsEl.innerHTML = "";
  specialActionIds.forEach((actionId) => {
    const button = document.createElement("button");
    button.className = `table-action legal ${actionClass(actionId)}`;
    button.type = "button";
    button.innerHTML = `<span class="action-icon">${specialActionIcon(actionId)}</span><span>${specialActionLabel(actionId)}</span>`;
    button.disabled = !state.is_human_turn || isReplaying;
    button.addEventListener("click", () => playAction(actionId));
    specialActionsEl.appendChild(button);
  });
  if (!specialActionsEl.children.length) {
    specialActionsEl.innerHTML = `<span class="hint">No table action available.</span>`;
  }
}

function cardButton(card, actionId, legal, options = {}) {
  const button = document.createElement("button");
  button.className = `playing-card ${card.color || ""}${legal ? " legal" : ""}${options.compact ? " compact-card" : ""}`;
  button.type = "button";
  button.disabled = !legal || !latestState?.is_human_turn || isReplaying;
  button.innerHTML = `${cardFace(card)}${legal && options.showPlayable ? '<span class="playable-tag">Play</span>' : ""}`;
  button.setAttribute("aria-label", card.label);
  if (Number.isInteger(options.handIndex) && Number.isInteger(options.handCount)) {
    const midpoint = (options.handCount - 1) / 2;
    const distance = options.handIndex - midpoint;
    button.style.setProperty("--hand-tilt", `${clamp(distance * 3, -9, 9)}deg`);
    button.style.setProperty("--hand-lift", `${Math.abs(distance) < 0.5 ? -8 : Math.abs(distance) < 1.5 ? -4 : 0}px`);
  }
  if (legal) button.addEventListener("click", () => playAction(actionId));
  return button;
}

function cardHTML(card, options = {}) {
  const classes = [
    "playing-card",
    card.color || "",
    options.large ? "large-card" : "",
    options.mini ? "mini-card" : "",
    options.muted ? "discarded" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return `<div class="${classes}" aria-label="${card.label}">${cardFace(card)}</div>`;
}

function cardFace(card) {
  return `
    <span class="corner top">${card.rank}<b>${card.symbol}</b></span>
    <span class="pip">${card.symbol}</span>
    <span class="corner bottom">${card.rank}<b>${card.symbol}</b></span>
  `;
}

function liveStackHTML(cards) {
  const visibleCards = cards.slice(-4);
  const hiddenCount = Math.max(0, cards.length - visibleCards.length);
  return `
    <div class="stacked-live-cards" style="--stack-size:${visibleCards.length}">
      ${visibleCards
        .map(
          (card, index) =>
            `<div class="stack-card" style="--stack-index:${index}; --stack-reverse:${visibleCards.length - index - 1}">${cardHTML(card, { large: true })}</div>`,
        )
        .join("")}
    </div>
    ${hiddenCount ? `<span class="under-count">+${hiddenCount} under</span>` : ""}
  `;
}

function updateHandLayout(count) {
  handEl.dataset.count = String(count);
  handEl.classList.toggle("many-cards", count > 6);
  const railWidth = Math.max(260, handEl.clientWidth || 420);
  const cardWidth = count <= 3 ? 92 : count <= 6 ? 84 : count <= 10 ? 76 : 68;
  const requiredOverlap = count <= 1 ? 0 : (count * cardWidth - railWidth + 42) / (count - 1);
  const overlap = count <= 3 ? 14 : clamp(requiredOverlap, 10, cardWidth - 28);
  handEl.style.setProperty("--hand-card-width", `${cardWidth}px`);
  handEl.style.setProperty("--hand-overlap", `${Math.max(0, overlap)}px`);
}

function backStack(count, label) {
  const cards = Array.from({ length: Math.min(count, 3) })
    .map((_, index) => `<span class="tiny-back" style="left:${index * 6}px"></span>`)
    .join("");
  return `<div class="stack"><div class="tiny-stack">${cards || '<span class="tiny-empty"></span>'}</div><span>${label}: ${count}</span></div>`;
}

function emptySlot() {
  return `<span class="empty-slot">Empty</span>`;
}

function emptyPile(label) {
  return `<div class="empty-pile">${label}<small>empty</small></div>`;
}

async function replayMoves(moves, delayMs) {
  isReplaying = true;
  document.body.classList.add("replaying");
  disableActions(true);
  for (const [index, move] of moves.entries()) {
    highlightActor(move.player_index);
    setTurnBadge(move.player_index === 0 ? "Your Move" : `Player ${move.player_index + 1}`, move.player_index === 0);
    statusEl.textContent = move.player_index === 0 ? "Your move is resolving" : `Player ${move.player_index + 1} is acting`;
    setMoveBanner(move.message, move, { step: index + 1, total: moves.length });
    renderReplayPileSnapshot(move);
    pulsePiles(move);
    addLog(move.message, move.player_index === 0 ? "you" : "bot");
    await sleep(delayMs);
  }
  isReplaying = false;
  document.body.classList.remove("replaying");
  disableActions(false);
  updateStatus(latestState);
  renderPiles(latestState);
  highlightActor(latestState?.game_over ? null : latestState?.current_player);
  setMoveBanner(latestState?.game_over ? gameOverText(latestState) : "Your turn: choose a highlighted move");
}

function setMoveBanner(message, move = null, replay = null) {
  if (!moveBannerEl) return;
  const playerName = move ? (move.player_index === 0 ? "You" : `Player ${move.player_index + 1}`) : "";
  const card = move?.card ? cardHTML(move.card, { large: true }) : "";
  const progress = replay ? `<div class="move-progress"><span>Move ${replay.step} of ${replay.total}</span><b style="width:${(replay.step / replay.total) * 100}%"></b></div>` : "";
  const detail = move ? `<small>${move.live_pile_count} live · ${move.discard_count} discard · ${move.draw_count} draw</small>` : "";
  moveBannerEl.innerHTML = `
    <div class="move-card">${card}</div>
    <div class="move-copy">
      <strong>${playerName || "Table"}</strong>
      <span>${message}</span>
      ${detail}
      ${progress}
    </div>
  `;
}

function renderReplayPileSnapshot(move) {
  renderPileSnapshot({
    liveTop: move.live_pile_top,
    liveCards: move.live_pile_top ? [move.live_pile_top] : [],
    liveCount: move.live_pile_count,
    discardTop: latestState?.discard_top,
    discardCount: move.discard_count,
    drawCount: move.draw_count,
  });
}

function pulsePiles(move) {
  pulseElement(liveTopEl);
  if (move.action_id === 52 || move.discard_count > 0) pulseElement(discardTopEl);
}

function pulseElement(element) {
  element.classList.remove("pile-pop");
  void element.offsetWidth;
  element.classList.add("pile-pop");
}

function highlightActor(playerIndex) {
  document.querySelectorAll("[data-player-index]").forEach((element) => {
    element.classList.toggle("is-acting", Number(element.dataset.playerIndex) === Number(playerIndex));
  });
}

function renderLog(entries) {
  if (!entries?.length) return;
  entries.forEach((entry) => addLog(entry));
}

function clearLog() {
  gameLogEl.innerHTML = "";
}

function addLog(message, kind = "") {
  const item = document.createElement("li");
  if (kind) item.className = kind;
  const icon = kind === "you" ? "YOU" : kind === "bot" ? "BOT" : kind === "bad" ? "!" : "SYS";
  item.innerHTML = `<span class="log-chip">${icon}</span><span>${message}</span>`;
  gameLogEl.prepend(item);
}

function disableActions(disabled) {
  document.querySelectorAll("button.playing-card, .table-action").forEach((button) => {
    button.disabled = disabled || !button.classList.contains("legal");
  });
}

function specialActionLabel(actionId) {
  const labels = {
    52: "Pick up live pile",
    53: "Resolve 9 draw",
    54: "Reveal draw card",
    55: "End play group",
    56: "Fix swap slot 1",
    57: "Fix swap slot 2",
    58: "Fix swap slot 3",
    59: "Fix stack slot 1",
    60: "Fix stack slot 2",
    61: "Fix stack slot 3",
    62: "Finish fixing",
    63: "Take stack slot 1",
    64: "Take stack slot 2",
    65: "Take stack slot 3",
    66: "Keep undersized hand",
  };
  return labels[actionId] || `Action ${actionId}`;
}

function specialActionIcon(actionId) {
  if (actionId === 52) return "⬆";
  if (actionId === 53) return "9";
  if (actionId === 54) return "↻";
  if (actionId === 55) return "✓";
  return "•";
}

function actionClass(actionId) {
  if (actionId === 52) return "danger-action";
  if (actionId === 55) return "commit-action";
  return "utility-action";
}

function gameOverText(state) {
  if (state.winner === 0) return "Game over: you won";
  if (state.loser === 0) return "Game over: you lost";
  if (state.winner !== null && state.winner !== undefined) return `Game over: Player ${state.winner + 1} won`;
  if (state.loser !== null && state.loser !== undefined) return `Game over: Player ${state.loser + 1} lost`;
  return "Game over";
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

setMoveBanner("Start a new game");
addLog(`API: ${API_BASE}`);
