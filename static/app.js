const API_BASE =
  window.IBFLIP_API_BASE ||
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8000"
    : "https://ibflip.onrender.com");

let sessionId = null;
let latestState = null;

const statusEl = document.getElementById("status");
const startButton = document.getElementById("startButton");
const handEl = document.getElementById("hand");
const faceUpEl = document.getElementById("faceUp");
const faceDownEl = document.getElementById("faceDown");
const specialActionsEl = document.getElementById("specialActions");
const opponentsEl = document.getElementById("opponents");
const liveTopEl = document.getElementById("liveTop");
const liveMetaEl = document.getElementById("liveMeta");
const discardTopEl = document.getElementById("discardTop");
const discardMetaEl = document.getElementById("discardMeta");
const gameLogEl = document.getElementById("gameLog");

startButton.addEventListener("click", startGame);

async function startGame() {
  startButton.disabled = true;
  try {
    const state = await request("/start", { method: "POST" });
    sessionId = state.session_id;
    renderState(state);
  } finally {
    startButton.disabled = false;
  }
}

async function playAction(actionId) {
  if (!sessionId || !latestState?.is_human_turn) return;
  disableActions(true);
  try {
    const state = await request(`/play/${sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: actionId }),
    });
    renderState(state);
  } catch (error) {
    addLog(`Error: ${error.message}`);
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

function renderState(state) {
  latestState = state;
  statusEl.textContent = state.game_over
    ? gameOverText(state)
    : state.is_human_turn
      ? "Your turn"
      : `Player ${state.current_player + 1} thinking`;

  renderOpponents(state.opponents);
  renderPiles(state);
  renderHuman(state);
  renderLog(state.log);
}

function renderOpponents(opponents) {
  opponentsEl.innerHTML = "";
  opponents.forEach((player) => {
    const card = document.createElement("article");
    card.className = "opponent";
    card.innerHTML = `
      <h2>Player ${player.player_index + 1}</h2>
      <p>Hand: ${player.hand_count}</p>
      <p>Face-down: ${player.face_down_count}</p>
      <div class="cards">${player.face_up_slots
        .map((slot, index) => `<span class="slot">Slot ${index + 1}: ${slot.map((c) => c.label).join(", ") || "Empty"}</span>`)
        .join("")}</div>
    `;
    opponentsEl.appendChild(card);
  });
}

function renderPiles(state) {
  liveTopEl.textContent = state.live_pile_top?.label || "Empty";
  liveTopEl.classList.toggle("muted", !state.live_pile_top);
  liveMetaEl.textContent = `${state.live_pile.length} live card${state.live_pile.length === 1 ? "" : "s"}`;

  discardTopEl.textContent = state.discard_top?.label || "Empty";
  discardTopEl.classList.toggle("muted", !state.discard_top);
  discardMetaEl.textContent = `${state.discard_count} discarded, ${state.draw_count} in draw pile`;
}

function renderHuman(state) {
  const legal = new Set(state.legal_actions);
  handEl.innerHTML = "";
  state.human.hand.forEach((card) => {
    handEl.appendChild(cardButton(card.label, card.id, legal.has(card.id)));
  });

  faceUpEl.innerHTML = "";
  state.human.face_up_slots.forEach((slot, index) => {
    const slotEl = document.createElement("div");
    slotEl.className = "slot";
    slotEl.innerHTML = `<span class="slot-title">Slot ${index + 1}</span>`;
    slot.forEach((card) => {
      slotEl.appendChild(cardButton(card.label, card.id, legal.has(card.id)));
    });
    if (!slot.length) slotEl.append("Empty");
    faceUpEl.appendChild(slotEl);
  });

  faceDownEl.innerHTML = "";
  (state.human_face_down_slots || []).forEach((slot) => {
    if (slot.available) {
      faceDownEl.appendChild(cardButton(`Face-down ${slot.slot + 1}`, slot.action_id, legal.has(slot.action_id)));
    }
  });

  specialActionsEl.innerHTML = "";
  state.legal_actions
    .filter((actionId) => actionId >= 52 && actionId < 67)
    .forEach((actionId) => {
      specialActionsEl.appendChild(cardButton(specialActionLabel(actionId), actionId, true));
    });
}

function cardButton(label, actionId, legal) {
  const button = document.createElement("button");
  button.className = `card${legal ? " legal" : ""}`;
  button.type = "button";
  button.textContent = label;
  button.disabled = !legal || !latestState?.is_human_turn;
  if (legal) button.addEventListener("click", () => playAction(actionId));
  return button;
}

function specialActionLabel(actionId) {
  const labels = {
    52: "Pick Up Live Pile",
    53: "Resolve 9 Draw",
    54: "Reveal Draw Pile",
    55: "End Group",
    56: "Fix Swap Slot 1",
    57: "Fix Swap Slot 2",
    58: "Fix Swap Slot 3",
    59: "Fix Stack Slot 1",
    60: "Fix Stack Slot 2",
    61: "Fix Stack Slot 3",
    62: "Fix Done",
    63: "Take Stack Slot 1",
    64: "Take Stack Slot 2",
    65: "Take Stack Slot 3",
    66: "Keep Undersized",
  };
  return labels[actionId] || `Action ${actionId}`;
}

function renderLog(entries) {
  if (!entries?.length) return;
  entries.forEach(addLog);
}

function addLog(message) {
  const item = document.createElement("li");
  item.textContent = message;
  gameLogEl.appendChild(item);
  gameLogEl.parentElement.scrollTop = gameLogEl.parentElement.scrollHeight;
}

function disableActions(disabled) {
  document.querySelectorAll(".card").forEach((button) => {
    button.disabled = disabled || !button.classList.contains("legal");
  });
}

function gameOverText(state) {
  if (state.winner === 0) return "Game over: you won";
  if (state.loser === 0) return "Game over: you lost";
  if (state.winner !== null && state.winner !== undefined) return `Game over: Player ${state.winner + 1} won`;
  if (state.loser !== null && state.loser !== undefined) return `Game over: Player ${state.loser + 1} lost`;
  return "Game over";
}

addLog(`API: ${API_BASE}`);
