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
    caption: { who: "Otto", text: "played 2♠ and goes again… then drew" },
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
      { place: "1st", name: "Pip", note: "out legally" },
      { place: "2nd", name: "Elliot", note: "out legally", you: true },
      { place: "3rd", name: "Fern", note: "out legally" },
      { place: "Last", name: "Otto", note: "flipped the 8s" },
    ],
  };

  const rankOf = (c) => c.slice(0, -1);
  const suitOf = (c) => c.slice(-1);
  const red = (c) => "hd".includes(suitOf(c));
  const esc = (s) => String(s).replace(/[&<>"]/g, (x) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[x]);

  function card(c, extra = "") {
    const r = rankOf(c), s = D.suits[suitOf(c)];
    const tag = D.tags && TAG[r] ? `<span class="tag">${TAG[r]}</span>` : "";
    return `<div class="card ${red(c) ? "red" : "black"} ${extra}" data-rank="${r}" data-suit="${suitOf(c)}" aria-label="${r} of ${{ s: "spades", h: "hearts", d: "diamonds", c: "clubs" }[suitOf(c)]}">` +
      `<span class="idx"><b>${r}</b><i>${s}</i></span><span class="pip">${s}</span><span class="idx2"><b>${r}</b><i>${s}</i></span>${tag}</div>`;
  }
  const back = (extra = "") => `<div class="card back ${extra}"><span>${D.backLabel}</span></div>`;
  const slot = (cards) => `<div class="slot${cards.length > 1 ? " stacked" : ""}">${cards.map((c) => card(c)).join("")}</div>`;

  function seat(o, i) {
    const done = o.place != null;
    const status = done ? `<span class="badge place">Finished ${o.place === 1 ? "1st" : o.place}</span>` : "";
    return `<section class="seat seat-${i + 1}${done ? " out" : ""}" aria-label="${esc(o.name)}">
      <header class="who"><span class="avatar" aria-hidden="true">${esc(o.name[0])}</span><span class="name">${esc(o.name)}</span><span class="level">${esc(o.level)}</span>${status}</header>
      <div class="holdings">
        <div class="hand-count" title="Cards in hand"><span class="n">${o.hand}</span><span class="l">in hand</span></div>
        <div class="table-cards">
          <div class="downs">${Array.from({ length: o.down }, () => back("sm")).join("")}</div>
          <div class="ups">${o.up.map(slot).join("")}</div>
        </div>
        ${o.seen ? `<div class="seen">Seen in hand: ${card(o.seen, "xs")}</div>` : ""}
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
        <button class="icon hint" aria-label="Hint">?</button>
      </div>
      <div class="opponents">${S.opponents.map(seat).join("")}</div>
      <div class="center">
        <div class="pile deck"><div class="stack">${back()}</div><span class="label">Deck ${S.deck}</span></div>
        <div class="pile live"><div class="stack fan">${liveTop.map((c, i) => card(c, i === liveTop.length - 1 ? "top" : "under")).join("")}</div><span class="label">Live pile ${S.live.length + 3}</span></div>
        <div class="pile discard"><div class="stack">${back("dim")}</div><span class="label">Discard ${S.discard}</span></div>
        <p class="caption"><b>${S.caption.who}</b> ${S.caption.text}</p>
      </div>
      <section class="me" aria-label="Your cards">
        <div class="my-table">
          <div class="downs">${Array.from({ length: S.down }, () => back("sm")).join("")}</div>
          <div class="ups">${S.up.map(slot).join("")}</div>
        </div>
        <div class="turn-banner">Your turn. Play on the ${S.target}.</div>
        <div class="hand">${S.hand.map((h) => card(h.c, h.ok ? "playable" : "blocked")).join("")}</div>
        <div class="actions"><button class="btn primary play" disabled>Play</button><button class="btn pickup">Pick up pile</button></div>
      </section>
    </main>`;
  }

  function home() {
    return `<main class="home" data-screen="home">
      <div class="brand"><h1>IB-Flip</h1><p class="tagline">Flips, skips and sudden reversals. Lose your cards legally to win.</p></div>
      <form class="setup" onsubmit="return false">
        <label class="field"><span>Your name</span><input value="${S.you}" autocomplete="nickname"></label>
        <fieldset class="choice"><legend>Opponents</legend>${[1, 2, 3, 4].map((n) => `<label><input type="radio" name="opp" ${n === 3 ? "checked" : ""}><span>${n}</span></label>`).join("")}</fieldset>
        <fieldset class="choice"><legend>Bots</legend>${["Rookie", "Regular", "Shark"].map((n) => `<label><input type="radio" name="lvl" ${n === "Shark" ? "checked" : ""}><span>${n}</span></label>`).join("")}</fieldset>
        <button class="btn primary deal">Deal me in</button>
        <div class="alt"><button class="btn">Create a room</button><button class="btn">Join with a code</button></div>
      </form>
      <a class="rules-link" href="#">How to play</a>
    </main>`;
  }

  function results() {
    return `<main class="results" data-screen="results">
      <div class="result-card">
        <h2>You finished 2nd</h2>
        <p class="sub">Pip went out first. Otto flipped the 8s.</p>
        <ol class="standings">${S.standings.map((r) => `<li class="${r.you ? "you" : ""}"><span class="pl">${r.place}</span><span class="nm">${esc(r.name)}</span><span class="nt">${r.note}</span></li>`).join("")}</ol>
        <div class="actions"><button class="btn primary">Play again</button><button class="btn">Back to lobby</button></div>
      </div>
    </main>`;
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
    if (sw) return show(sw.dataset.s);
    const c = e.target.closest(".hand .card.playable");
    if (c) {
      const same = [...document.querySelectorAll(".hand .card.selected")].every((x) => x.dataset.rank === c.dataset.rank);
      if (!same) document.querySelectorAll(".hand .card.selected").forEach((x) => x.classList.remove("selected"));
      c.classList.toggle("selected");
      const n = document.querySelectorAll(".hand .card.selected").length;
      const play = document.querySelector(".play");
      play.disabled = !n;
      play.textContent = n ? `Play ${n > 1 ? n + " cards" : "card"}` : "Play";
    }
    const opt = e.target.closest(".choice label");
    if (opt) opt.querySelector("input").checked = true;
  });

  document.addEventListener("DOMContentLoaded", () => {
    const sw = document.createElement("nav");
    sw.className = "mock-switch";
    sw.setAttribute("aria-label", "Mockup screens");
    sw.innerHTML = `<a href="../">All designs</a>` + ["home", "table", "results"].map((s) => `<button data-s="${s}">${s[0].toUpperCase() + s.slice(1)}</button>`).join("");
    document.body.append(sw);
    const start = (location.hash || "#table").slice(1);
    show(screens[start] ? start : "table");
  });
})();
