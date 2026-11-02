// Shared mock state + semantic markup for the IB-Flip design studies.
// Every design renders the same moment of the same game; only its CSS (and a few
// options in window.DESIGN) differ, so the comparison is about look, not content.
(() => {
  const D = Object.assign({ suits: { s: "♠", h: "♥", d: "♦", c: "♣" }, tags: true, backLabel: "IB" }, window.DESIGN || {});
  const TAG = { 2: "again", 3: "reverse", 4: "4-loop", 5: "under", 7: "≤ 7", 8: "skip", 9: "draw", 10: "flip" };

  const S = {
    room: "KTRVNB",
    you: "Elliot",
    turn: "you",
    target: "2",
    caption: { who: "Otto", text: "2♠" },
    deck: 9,
    discard: 14,
    live: ["Qc", "Jd", "Kh", "2s"],
    opponents: [
      { name: "Otto", level: "Shark", hand: 3, down: 3, up: [["6s"], ["10d"], ["6d"]] },
      { name: "Pip", level: "Shark", hand: 0, down: 0, up: [], place: 1 },
      { name: "Fern", level: "Regular", hand: 5, down: 3, up: [["2d"], ["7d", "7s"], ["7c"]], seen: "Kd" },
    ],
    hand: [
      { c: "4d", ok: true },
      { c: "4c", ok: true },
      { c: "5h", ok: true },
      { c: "Jh", ok: true },
      { c: "3s", ok: false },
    ],
    up: [["9h"], ["Ac", "As"], ["Ks"]],
    down: 3,
    standings: [
      { place: "1st", name: "Pip", note: "" },
      { place: "2nd", name: "Elliot", note: "", you: true },
      { place: "3rd", name: "Fern", note: "" },
      { place: "4th", name: "Otto", note: "8s" },
    ],
  };

  const rankOf = (c) => c.slice(0, -1);
  const suitOf = (c) => c.slice(-1);
  const red = (c) => "hd".includes(suitOf(c));
  const esc = (s) => String(s).replace(/[&<>"]/g, (x) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[x]);

  function card(c, extra = "") {
    const r = rankOf(c), s = D.suits[suitOf(c)];
    const tag = D.tags && TAG[r] ? `<span class="tag">${TAG[r]}</span>` : "";
    return `<div class="card ${red(c) ? "red" : "black"} ${extra}" data-c="${c}" data-rank="${r}" data-suit="${suitOf(c)}" aria-label="${r} of ${{ s: "spades", h: "hearts", d: "diamonds", c: "clubs" }[suitOf(c)]}">` +
      `<span class="idx"><b>${r}</b><i>${s}</i></span><span class="pip">${s}</span><span class="idx2"><b>${r}</b><i>${s}</i></span>${tag}</div>`;
  }
  const back = (extra = "") => `<div class="card back ${extra}"><span>${D.backLabel}</span></div>`;
  const slot = (cards) => `<div class="slot${cards.length > 1 ? " stacked" : ""}">${cards.map((c) => card(c)).join("")}</div>`;

  function seat(o, i) {
    const done = o.place != null;
    const status = done ? `<span class="badge place">${o.place === 1 ? "1st" : o.place}</span>` : "";
    return `<section class="seat seat-${i + 1}${done ? " out" : ""}" aria-label="${esc(o.name)}">
      <header class="who"><span class="avatar" aria-hidden="true">${esc(o.name[0])}</span><span class="name">${esc(o.name)}</span><span class="level">${esc(o.level)}</span>${status}</header>
      <div class="holdings">
        <div class="hand-count" title="${o.hand} cards in hand"><span class="n">${o.hand}</span>${o.seen ? `<span class="seen-mini" title="Seen in their hand">${card(o.seen, "xs")}</span>` : ""}</div>
        <div class="table-cards">
          <div class="downs">${Array.from({ length: o.down }, () => back("sm")).join("")}</div>
          <div class="ups">${o.up.map(slot).join("")}</div>
        </div>
      </div>
    </section>`;
  }

  function table() {
    const liveTop = S.live.slice(-3);
    return `<main class="game" data-screen="table">
      <div class="topbar">
        <button class="icon menu" aria-label="Menu">≡</button>
        <span class="room">Room ${S.room}</span>
        <span class="phase">On a ${S.target}</span>
        ${D.themeToggle ? `<button class="icon theme" aria-label="Switch light or dark"><svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M10 2a8 8 0 0 1 0 16z" fill="currentColor"/></svg></button>` : ""}
        <button class="icon hint" aria-label="Hint">?</button>
      </div>
      <div class="opponents">${S.opponents.map(seat).join("")}</div>
      <div class="center">
        <div class="pile deck"><div class="stack">${back()}</div><span class="label" title="Deck">${S.deck}</span></div>
        <div class="pile live"><div class="stack fan">${liveTop.map((c, i) => card(c, i === liveTop.length - 1 ? "top" : "under")).join("")}</div><span class="label" title="Live pile">${S.live.length + 3}</span></div>
        <div class="pile discard"><div class="stack">${back("dim")}</div><span class="label" title="Discard">${S.discard}</span></div>
        <p class="caption"><b>${S.caption.who}</b> ${S.caption.text}</p>
      </div>
      <section class="me" aria-label="Your cards">
        <div class="my-table">
          <div class="downs">${Array.from({ length: S.down }, () => back("sm")).join("")}</div>
          <div class="ups">${S.up.map(slot).join("")}</div>
        </div>
        <div class="turn-banner">Your turn</div>
        <div class="hand">${S.hand.map((h) => card(h.c, h.ok ? "playable" : "blocked")).join("")}</div>
        <div class="actions"><button class="btn primary play" disabled>Play</button><button class="btn pickup">Pick up</button></div>
      </section>
    </main>`;
  }

  function home() {
    return `<main class="home" data-screen="home">${D.themeToggle ? `<button class="icon theme home-theme" aria-label="Switch light or dark"><svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M10 2a8 8 0 0 1 0 16z" fill="currentColor"/></svg></button>` : ""}
      <div class="brand"><h1>IB-Flip</h1></div>
      <form class="setup" onsubmit="return false">
        <label class="field"><span class="sr">Name</span><input value="${S.you}" placeholder="Name" autocomplete="nickname"></label>
        <fieldset class="choice"><legend>Opponents</legend>${[1, 2, 3, 4].map((n) => `<label><input type="radio" name="opp" ${n === 3 ? "checked" : ""}><span>${n}</span></label>`).join("")}</fieldset>
        <fieldset class="choice"><legend>Bots</legend>${["Rookie", "Regular", "Shark"].map((n) => `<label><input type="radio" name="lvl" ${n === "Shark" ? "checked" : ""}><span>${n}</span></label>`).join("")}</fieldset>
        <button class="btn primary deal">Play</button>
        <div class="alt"><button class="btn">New room</button><button class="btn">Join</button></div>
      </form>
      <a class="rules-link" href="#">Rules</a>
    </main>`;
  }

  function results() {
    return `<main class="results" data-screen="results">
      <div class="result-card">
        <h2>2nd</h2>
        <ol class="standings">${S.standings.map((r) => `<li class="${r.you ? "you" : ""}"><span class="pl">${r.place}</span><span class="nm">${esc(r.name)}</span><span class="nt">${r.note}</span></li>`).join("")}</ol>
        <div class="actions"><button class="btn primary">Again</button><button class="btn">Lobby</button></div>
      </div>
    </main>`;
  }

  // ---------- motion demo: play your selection, then Otto answers ----------
  const ORIG = JSON.parse(JSON.stringify({ live: S.live, hand: S.hand, caption: S.caption, target: S.target, opponents: S.opponents, deck: S.deck }));
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const EASE = "cubic-bezier(.2,.75,.25,1)";
  const rect = (el) => el && el.getBoundingClientRect();

  function flipFrom(el, from, { rotate = 0, scale = 1, duration = 460, delay = 0 } = {}) {
    if (!el || !from || reduced()) return Promise.resolve();
    const to = el.getBoundingClientRect();
    const dx = from.left + from.width / 2 - (to.left + to.width / 2);
    const dy = from.top + from.height / 2 - (to.top + to.height / 2);
    const s0 = (from.width / to.width) * scale;
    return el.animate(
      [{ transform: `translate(${dx}px, ${dy}px) scale(${s0}) rotate(${rotate}deg)` }, { transform: "none" }],
      { duration, delay, easing: EASE, fill: "backwards" }
    ).finished;
  }

  function rerenderTable() {
    const keepSwitch = document.body.dataset.screen;
    document.getElementById("app").innerHTML = table();
    document.body.dataset.screen = keepSwitch;
  }

  let busy = false;
  async function playSelected() {
    const sel = [...document.querySelectorAll(".hand .card.selected")];
    if (!sel.length || busy) return;
    busy = true;
    const from = new Map(sel.map((el) => [el.dataset.c, rect(el)]));
    const handBefore = new Map([...document.querySelectorAll(".hand .card")].map((el) => [el.dataset.c, rect(el)]));
    const codes = sel.map((el) => el.dataset.c);
    S.live = [...S.live, ...codes];
    S.hand = S.hand.filter((h) => !codes.includes(h.c));
    S.target = rankOf(codes[0]);
    S.caption = { who: "You", text: codes.map((c) => rankOf(c) + D.suits[suitOf(c)]).join(" ") };
    rerenderTable();
    document.querySelector(".me").classList.add("waiting");
    // cards you kept slide to close the gap; the played ones fly to the pile
    document.querySelectorAll(".hand .card").forEach((el) => flipFrom(el, handBefore.get(el.dataset.c), { duration: 320 }));
    await Promise.all(codes.map((c, i) => flipFrom(document.querySelector(`.live .card[data-c="${c}"]`), from.get(c), { rotate: -6 + i * 4, delay: i * 70 })));
    await new Promise((r) => setTimeout(r, 900));
    // Otto answers from his hand
    const seat = document.querySelector(".seat-1 .hand-count");
    const src = rect(seat);
    S.live = [...S.live, "5c"];
    S.opponents[0].hand -= 1;
    S.target = rankOf(codes[0]);
    S.caption = { who: "Otto", text: "5♣" };
    rerenderTable();
    document.querySelector(".me").classList.add("waiting");
    await flipFrom(document.querySelector('.live .card[data-c="5c"]'), src, { scale: .5, rotate: 8, duration: 520 });
    // and draws back up from the deck
    const deck = rect(document.querySelector(".deck .card"));
    S.opponents[0].hand += 1; S.deck -= 1;
    rerenderTable();
    const ghost = document.querySelector(".deck .card").cloneNode(true);
    const seatRect = rect(document.querySelector(".seat-1 .hand-count"));
    Object.assign(ghost.style, { position: "fixed", left: deck.left + "px", top: deck.top + "px", margin: 0, zIndex: 50, pointerEvents: "none" });
    document.body.append(ghost);
    if (!reduced()) await ghost.animate([{ transform: "none", opacity: 1 }, { transform: `translate(${seatRect.left - deck.left}px, ${seatRect.top - deck.top}px) scale(.4)`, opacity: 0 }], { duration: 480, easing: EASE }).finished;
    ghost.remove();
    S.caption = { who: "", text: "" };
    rerenderTable();
    busy = false;
  }

  function resetDemo() {
    Object.assign(S, JSON.parse(JSON.stringify(ORIG)));
    show("table");
  }

  const screens = { table, home, results };
  function show(name) {
    document.getElementById("app").innerHTML = screens[name]();
    document.querySelectorAll(".mock-switch button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.s === name));
    document.body.dataset.screen = name;
    try { history.replaceState(null, "", "#" + name); } catch (_) {}
  }

  document.addEventListener("click", (e) => {
    const sw = e.target.closest(".mock-switch button");
    if (sw) return sw.dataset.s === "reset" ? resetDemo() : show(sw.dataset.s);
    if (e.target.closest(".play")) return playSelected();
    if (e.target.closest(".theme")) {
      const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("ibflip:theme", document.documentElement.dataset.theme); } catch (_) {}
      return;
    }
    const c = e.target.closest(".hand .card.playable");
    if (c) {
      const same = [...document.querySelectorAll(".hand .card.selected")].every((x) => x.dataset.rank === c.dataset.rank);
      if (!same) document.querySelectorAll(".hand .card.selected").forEach((x) => x.classList.remove("selected"));
      c.classList.toggle("selected");
      const n = document.querySelectorAll(".hand .card.selected").length;
      const play = document.querySelector(".play");
      play.disabled = !n;
      play.textContent = n > 1 ? `Play ${n}` : "Play";
    }
    const opt = e.target.closest(".choice label");
    if (opt) opt.querySelector("input").checked = true;
  });

  try { const t = localStorage.getItem("ibflip:theme"); if (t) document.documentElement.dataset.theme = t; } catch (_) {}
  const Q = new URLSearchParams(location.search);
  ["density", "cards"].forEach((k) => Q.get(k) && (document.documentElement.dataset[k] = Q.get(k)));
  if (D.defaultCards && !document.documentElement.dataset.cards) document.documentElement.dataset.cards = D.defaultCards;
  if (Q.get("theme")) document.documentElement.dataset.theme = Q.get("theme");
  document.addEventListener("DOMContentLoaded", () => {
    const sw = document.createElement("nav");
    sw.className = "mock-switch";
    sw.setAttribute("aria-label", "Mockup screens");
    sw.innerHTML = `<a href="../">All designs</a>` + ["home", "table", "results"].map((s) => `<button data-s="${s}">${s[0].toUpperCase() + s.slice(1)}</button>`).join("") + `<button data-s="reset" title="Put the cards back">Replay</button>`;
    if (!Q.get("embed")) document.body.append(sw);
    const start = (location.hash || "#table").slice(1);
    show(screens[start] ? start : "table");
  });
})();
