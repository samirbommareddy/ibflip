// Motion lab: every animation in IB-Flip, each with a few alternatives to compare.
// Everything moves with transform/opacity only (Web Animations API), so it stays on the GPU.
(() => {
  const SUIT = { s: "♠", h: "♥", d: "♦", c: "♣" };
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const EASE = { out: "cubic-bezier(.2,.75,.25,1)", soft: "cubic-bezier(.4,0,.2,1)", snap: "cubic-bezier(.3,1.4,.5,1)", in: "cubic-bezier(.5,0,.75,0)" };

  const card = (c, extra = "") => {
    const r = c.slice(0, -1), s = c.slice(-1);
    return `<div class="card ${"hd".includes(s) ? "red" : "black"} ${extra}" data-c="${c}" data-rank="${r}"><span class="pip">${SUIT[s]}</span></div>`;
  };
  const back = (extra = "") => `<div class="card back ${extra}"></div>`;

  // ---------- a tiny table every demo runs on ----------
  function stageHTML() {
    return `<div class="stage">
      <div class="opp"><span class="dir" title="Direction">\u21bb</span><span class="who">Otto</span><span class="count"><b>3</b> in hand</span><div class="opp-cards">${back("sm") + back("sm") + back("sm")}</div></div>
      <div class="mid">
        <div class="slot deck">${back()}</div>
        <div class="slot pile">${card("Jd", "under") + card("2s")}</div>
        <div class="slot discard"><div class="ghost-slot"></div><span class="dc">0</span></div>
      </div>
      <p class="say">Otto played 2♠ and goes again</p>
      <div class="me"><div class="hand">${["4d", "4c", "5h", "Jh"].map((c) => card(c, "playable")).join("")}</div></div>
      <div class="fx" aria-hidden="true"></div>
    </div>`;
  }
  const $ = (root, sel) => root.querySelector(sel);
  const rectOf = (el) => el.getBoundingClientRect();

  // Fly a copy of `fromEl` (or a new element) from one rect to another, above everything.
  async function fly(html, from, to, { duration = 420, easing = EASE.out, arc = 0, rotate = 0, flipAt = null, faceHTML = null, scaleFrom = 1 } = {}) {
    const g = document.createElement("div");
    g.className = "flyer";
    g.innerHTML = html;
    const el = g.firstElementChild;
    Object.assign(g.style, { left: from.left + "px", top: from.top + "px", width: from.width + "px" });
    el.style.setProperty("--w", from.width + "px");
    document.body.append(g);
    const dx = to.left - from.left, dy = to.top - from.top, s = to.width / from.width;
    if (reduced) { g.remove(); return; }
    const frames = arc
      ? [
          { transform: `translate(0,0) scale(${scaleFrom}) rotate(0deg)` },
          { transform: `translate(${dx * 0.5}px, ${dy * 0.5 - arc}px) scale(${(scaleFrom + s) / 2}) rotate(${rotate / 2}deg)`, offset: 0.5 },
          { transform: `translate(${dx}px, ${dy}px) scale(${s}) rotate(${rotate}deg)` },
        ]
      : [{ transform: `translate(0,0) scale(${scaleFrom}) rotate(0deg)` }, { transform: `translate(${dx}px, ${dy}px) scale(${s}) rotate(${rotate}deg)` }];
    const move = g.animate(frames, { duration, easing });
    if (flipAt != null && faceHTML) {
      el.animate([{ transform: "scaleX(1)" }, { transform: "scaleX(0)" }], { duration: duration * 0.18, delay: duration * flipAt, easing: "linear", fill: "forwards" })
        .finished.then(() => {
          const f = document.createElement("div"); f.innerHTML = faceHTML;
          const face = f.firstElementChild; face.style.setProperty("--w", from.width + "px");
          el.replaceWith(face);
          face.animate([{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], { duration: duration * 0.18, easing: "linear" });
        });
    }
    await move.finished;
    g.remove();
  }
  async function flipInPlace(el, faceHTML, { duration = 320, mode = "flat" } = {}) {
    const half = duration / 2;
    const out = mode === "3d" ? [{ transform: "perspective(600px) rotateY(0)" }, { transform: "perspective(600px) rotateY(90deg)" }] : [{ transform: "scaleX(1)" }, { transform: "scaleX(0)" }];
    const inn = mode === "3d" ? [{ transform: "perspective(600px) rotateY(-90deg)" }, { transform: "perspective(600px) rotateY(0)" }] : [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }];
    if (!reduced) await el.animate(out, { duration: half, easing: EASE.in, fill: "forwards" }).finished;
    const t = document.createElement("div"); t.innerHTML = faceHTML;
    const face = t.firstElementChild; el.replaceWith(face);
    if (!reduced) await face.animate(inn, { duration: half, easing: EASE.out }).finished;
    return face;
  }
  // FLIP: animate elements from their previous positions after a layout change.
  function snapshot(els) { return new Map([...els].map((e) => [e.dataset.c || e, rectOf(e)])); }
  function flipFrom(els, before, { duration = 300, easing = EASE.out, overshoot = false } = {}) {
    if (reduced) return Promise.resolve();
    return Promise.all([...els].map((e) => {
      const b = before.get(e.dataset.c || e); if (!b) return null;
      const a = rectOf(e), dx = b.left - a.left, dy = b.top - a.top;
      if (!dx && !dy) return null;
      const frames = overshoot
        ? [{ transform: `translate(${dx}px,${dy}px)` }, { transform: `translate(${-dx * 0.08}px,${-dy * 0.08}px)`, offset: 0.7 }, { transform: "none" }]
        : [{ transform: `translate(${dx}px,${dy}px)` }, { transform: "none" }];
      return e.animate(frames, { duration, easing }).finished;
    }));
  }
  function addToPile(stage, c) {
    const pile = $(stage, ".pile");
    pile.querySelectorAll(".card").forEach((x) => x.classList.add("under"));
    pile.insertAdjacentHTML("beforeend", card(c));
    while (pile.children.length > 3) pile.firstElementChild.remove();
    return pile.lastElementChild;
  }
  function say(stage, text, variant = "fade") {
    const p = $(stage, ".say");
    if (reduced || variant === "none") { p.textContent = text; return; }
    if (variant === "slide") {
      p.animate([{ transform: "none", opacity: 1 }, { transform: "translateY(-8px)", opacity: 0 }], { duration: 140, easing: EASE.in }).finished.then(() => {
        p.textContent = text;
        p.animate([{ transform: "translateY(8px)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 220, easing: EASE.out });
      });
    } else if (variant === "mark") {
      p.textContent = text;
      p.animate([{ boxShadow: "inset 0 -3px 0 var(--accent)" }, { boxShadow: "inset 0 -3px 0 transparent" }], { duration: 900, easing: "ease-out" });
    } else {
      p.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 120 }).finished.then(() => { p.textContent = text; p.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200 }); });
    }
  }

  // ---------- the catalogue ----------
  const DEMOS = [
    { id: "attack", title: "Attack: a 4 lands", what: "Next player must answer with 4, 5 or 6.", options: {
      slam: ["Slam", "Card hits hard, table jolts, blue edge pulse", (st) => attack(st, "slam")],
      stamp: ["Giant 4", "A huge 4 stamps over the table", (st) => attack(st, "stamp")],
      word: ["Attack", "The word sweeps across in heavy type", (st) => attack(st, "word")],
      invert: ["Invert", "The table flips to negative twice", (st) => attack(st, "invert")],
    } },
    { id: "eights", title: "Easter egg: four 8s", what: "Someone flips the 8s and finishes last.", options: {
      infinity: ["Infinity", "Each 8 tips over into ∞ and spins away", (st) => eights(st, "infinity")],
      gravity: ["Gravity", "Every card on the table falls off the screen", (st) => eights(st, "gravity")],
      blackout: ["Blackout", "Lights out, 8 8 8 8 one at a time", (st) => eights(st, "blackout")],
    } },
    { id: "nine", title: "Nine: random card", what: "\u201cTackar från Tigdikar\u201d as the deck picks a card.", options: {
      banner: ["Banner", "Card spins out, a banner slides across", (st) => nine(st, "banner")],
      bubble: ["Speech bubble", "The deck says it", (st) => nine(st, "bubble")],
      marquee: ["Marquee", "Big type runs across the table once", (st) => nine(st, "marquee")],
    } },
    { id: "unlucky", title: "Unlucky ending: last card is a 2 or 10", what: "Going out on a card that makes it your turn again: illegal finish.", options: {
      crack: ["Crack", "The card lands, splits in two and falls", (st) => unlucky(st, "crack")],
      wrong: ["Buzzer", "Table flashes red, a heavy \u2715 lands on the card", (st) => unlucky(st, "wrong")],
      sink: ["Sink", "Your row sinks and greys out, Last stamps in", (st) => unlucky(st, "sink")],
    } },
    { id: "blind", title: "Blind play: face-down card", what: "Your last cards are face-down. You pick one blind.", options: {
      suspense: ["Suspense", "Lifts, holds a beat, slow 3D turn", (st) => blind(st, "suspense")],
      peek: ["Peek", "Corner lifts first, then it turns", (st) => blind(st, "peek")],
      quick: ["Plain", "Normal turn, no pause", (st) => blind(st, "quick")],
    } },
    { id: "win", title: "Going out first", what: "You play your last card legally.", options: {
      squares: ["Squares", "A short burst of small blue squares", (st) => win(st, "squares")],
      type: ["Big 1st", "1st fills the table in heavy type", (st) => win(st, "type")],
      calm: ["Calm", "Just the 1st badge, nothing else", (st) => win(st, "calm")],
    } },
    { id: "bigpickup", title: "Huge pickup", what: "Someone picks up a pile of 12.", options: {
      avalanche: ["Avalanche", "Cards pour in fast, 25 ms apart", (st) => bigPickup(st, "avalanche")],
      weight: ["Weight", "The pile slides over as one; their row dips under it", (st) => bigPickup(st, "weight")],
      counter: ["Counter", "Pile vanishes, their count rolls up to 15", (st) => bigPickup(st, "counter")],
    } },
    { id: "reverse", title: "Reverse: odd number of 3s", what: "Play direction flips.", options: {
      arrow: ["Arrow turns", "The direction arrow spins round", (st) => reverse(st, "arrow")],
      mirror: ["Mirror", "The table flips left-right for a moment", (st) => reverse(st, "mirror")],
      sweep: ["Sweep back", "A blue line sweeps the other way round", (st) => reverse(st, "sweep")],
    } },
    { id: "emote", title: "Targeted emotes", what: "Pick an emoji, pick a victim. Tap a player to send.", options: {
      throw: ["Throw", "Arcs from you and splats on them", (st) => emote(st, "throw")],
      stick: ["Stick", "Lands on their name and stays a few seconds, wobbling", (st) => emote(st, "stick")],
      rain: ["Rain on them", "A tiny cloud parks over their row; they cry", (st) => emote(st, "rain")],
      swarm: ["Swarm", "Five of them circle their head", (st) => emote(st, "swarm")],
    } },
    { id: "select", title: "Selecting a card", what: "What happens when you tap a card you could play.", options: {
      lift: ["Lift", "Rises 14px", async (st) => { const c = $(st, '.hand [data-c="4d"]'); c.classList.add("sel-lift"); await wait(700); c.classList.remove("sel-lift"); }],
      outline: ["Lift and outline", "Rises 10px with a blue frame", async (st) => { const c = $(st, '.hand [data-c="4d"]'); c.classList.add("sel-outline"); await wait(700); c.classList.remove("sel-outline"); }],
      bar: ["Bar underneath", "Stays put; a blue bar appears below", async (st) => { const c = $(st, '.hand [data-c="4d"]'); c.classList.add("sel-bar"); await wait(700); c.classList.remove("sel-bar"); }],
      grow: ["Grow", "Rises and scales to 106%", async (st) => { const c = $(st, '.hand [data-c="4d"]'); c.classList.add("sel-grow"); await wait(700); c.classList.remove("sel-grow"); }],
    } },
    { id: "play", title: "Playing your card", what: "Your selected card travels to the live pile.", options: {
      glide: ["Glide", "Straight line, 380 ms, eases out", (st) => playMine(st, { duration: 380 })],
      arc: ["Arc", "Gentle arc with a slight turn, 520 ms", (st) => playMine(st, { duration: 520, arc: 60, rotate: -8 })],
      snap: ["Snap", "Fast, 220 ms", (st) => playMine(st, { duration: 220 })],
      thump: ["Glide and settle", "Glide, then the pile gives a small press", (st) => playMine(st, { duration: 380, thump: true })],
    } },
    { id: "opp", title: "Opponent's card", what: "A bot plays a card from their hand to the pile.", options: {
      flipAtPile: ["Back, flips at the pile", "Travels face-down and turns over on arrival", (st) => oppPlays(st, { flipAt: 0.8, duration: 560 })],
      faceUp: ["Face-up glide", "Shown at their seat, then glides over", (st) => oppPlays(st, { duration: 500 })],
      fadeIn: ["Appear on the pile", "No travel, 200 ms fade", (st) => oppPlays(st, { appear: true })],
      arcFlip: ["Arc and turn mid-air", "Arcs over and flips halfway", (st) => oppPlays(st, { flipAt: 0.42, duration: 620, arc: 50 })],
    } },
    { id: "draw", title: "Drawing from the deck", what: "You draw back up to three after playing.", options: {
      flyFlip: ["Fly, then turn over", "Leaves the deck face-down, turns over in your hand", (st) => drawMine(st, { flip: true })],
      flyFace: ["Fly face-up", "Already face-up when it leaves the deck", (st) => drawMine(st, { flip: false })],
      appear: ["Appear in hand", "No travel; the new card fades in", (st) => drawMine(st, { appear: true })],
    } },
    { id: "reflow", title: "Hand closing the gap", what: "The rest of your hand moves after a card leaves it.", options: {
      slide: ["Slide", "300 ms, eases out", (st) => reflow(st, {})],
      spring: ["Slight spring", "Overshoots a little, then settles", (st) => reflow(st, { overshoot: true, duration: 420 })],
      instant: ["Instant", "Jumps into place", (st) => reflow(st, { instant: true })],
    } },
    { id: "pickup", title: "Picking up the pile", what: "You can't play, so the whole live pile comes to your hand.", options: {
      stream: ["One by one", "Cards stream in, 70 ms apart", (st) => pickup(st, { stagger: 70 })],
      block: ["As one block", "The pile slides over together, then fans out", (st) => pickup(st, { block: true })],
      quick: ["All at once, quick", "Every card moves together in 260 ms", (st) => pickup(st, { stagger: 0, duration: 260 })],
    } },
    { id: "flip", title: "Four of a kind flips", what: "Four in a row flip the pile out of play onto the discard.", options: {
      sequence: ["One after another", "Each card slides to the discard in turn", (st) => flipFour(st, { stagger: 110 })],
      turnThenGo: ["Turn over, then sweep", "The cards turn face-down, then move together", (st) => flipFour(st, { turnFirst: true })],
      sweep: ["Single sweep", "Everything moves at once, 300 ms", (st) => flipFour(st, { stagger: 0, duration: 300 })],
    } },
    { id: "reveal", title: "Revealing the deck's top card", what: "Nothing to play, so you turn over the top of the deck.", options: {
      flat: ["Flat turn", "Squeezes to a line and opens out, 320 ms", (st) => reveal(st, "flat")],
      depth: ["Turn with depth", "A 3D turn on the vertical axis", (st) => reveal(st, "3d")],
      lift: ["Lift and turn", "Rises off the deck first, then turns", (st) => reveal(st, "lift")],
    } },
    { id: "turn", title: "Whose turn it is", what: "How the table shows the turn moving to someone.", options: {
      bar: ["Sliding bar", "A blue bar moves to the player", (st) => turnTo(st, "bar")],
      tint: ["Row tint", "Their row takes a pale blue background", (st) => turnTo(st, "tint")],
      dot: ["Dot", "A blue dot appears by the name and pulses once", (st) => turnTo(st, "dot")],
    } },
    { id: "say", title: "What just happened", what: "The one-line caption under the piles.", options: {
      fade: ["Crossfade", "Old line fades out, new line in", (st) => say(st, "Otto played 5♣. Play on the card under it", "fade")],
      slide: ["Slide up", "New line pushes the old one up", (st) => say(st, "Otto played 5♣. Play on the card under it", "slide")],
      mark: ["Swap and underline", "Changes instantly, a blue underline fades", (st) => say(st, "Otto played 5♣. Play on the card under it", "mark")],
    } },
    { id: "illegal", title: "A move that isn't allowed", what: "You try to put a card where the rules don't let it go.", options: {
      shake: ["Shake", "The card shakes side to side, about 4px", (st) => illegal(st, "shake")],
      bounce: ["Bounce back", "It starts toward the pile and returns", (st) => illegal(st, "bounce")],
      flash: ["Outline flash", "A brief outline and a message, no movement", (st) => illegal(st, "flash")],
    } },
    { id: "finish", title: "Someone finishes", what: "A player goes out and takes a place.", options: {
      stamp: ["Stamp", "\"1st\" lands on their row with a small press", (st) => finish(st, "stamp")],
      fadeOut: ["Step back", "The row fades back as the place appears", (st) => finish(st, "fade")],
      slideTag: ["Slide in tag", "The place slides in from the right", (st) => finish(st, "slide")],
    } },
    { id: "pace", title: "Bot pace", what: "Time between bot moves. Plays three in a row.", options: {
      quick: ["Quick", "0.9 s per move", (st) => paced(st, 900)],
      steady: ["Steady", "1.35 s per move", (st) => paced(st, 1350)],
      relaxed: ["Relaxed", "1.8 s per move", (st) => paced(st, 1800)],
    } },
  ];

  // ---------- big moments ----------
  const fx = (st) => $(st, ".fx");
  async function attack(st, mode) {
    const c = $(st, '.hand [data-c="4d"]');
    const from = rectOf(c);
    c.remove();
    const t = addToPile(st, "4d"); t.style.visibility = "hidden";
    if (mode === "slam") {
      await fly(card("4d"), from, rectOf(t), { duration: 260, easing: EASE.in, scaleFrom: 1.25 });
      t.style.visibility = "";
      if (!reduced) {
        st.animate([0, -7, 6, -4, 3, 0].map((x) => ({ transform: `translate(${x}px, ${x / 2}px)` })), { duration: 380, easing: "ease-out" });
        await st.animate([{ boxShadow: "inset 0 0 0 0 var(--accent)" }, { boxShadow: "inset 0 0 0 10px var(--accent)", offset: 0.25 }, { boxShadow: "inset 0 0 0 0 var(--accent)" }], { duration: 700 }).finished;
      }
    } else {
      await fly(card("4d"), from, rectOf(t), { duration: 300 });
      t.style.visibility = "";
      const f = fx(st);
      if (mode === "stamp") {
        f.innerHTML = `<span class="big-four">4</span>`;
        if (!reduced) await f.firstChild.animate([{ transform: "scale(2.4)", opacity: 0 }, { transform: "scale(.95)", opacity: 1, offset: 0.35 }, { transform: "scale(1)", opacity: 1, offset: 0.7 }, { transform: "scale(1)", opacity: 0 }], { duration: 1100, easing: EASE.out }).finished;
      } else if (mode === "word") {
        f.innerHTML = `<span class="big-word">Attack</span>`;
        if (!reduced) await f.firstChild.animate([{ transform: "translateX(110%)" }, { transform: "translateX(0)", offset: 0.3 }, { transform: "translateX(-4%)", offset: 0.75 }, { transform: "translateX(-110%)" }], { duration: 1300, easing: "cubic-bezier(.6,0,.4,1)" }).finished;
      } else if (mode === "invert") {
        if (!reduced) await st.animate([{ filter: "none" }, { filter: "invert(1)" }, { filter: "none" }, { filter: "invert(1)" }, { filter: "none" }], { duration: 420, easing: "steps(4, jump-none)" }).finished;
      }
      f.innerHTML = "";
    }
    say(st, "Otto: 4, 5 or 6", "none");
  }
  async function eights(st, mode) {
    const pile = $(st, ".pile");
    pile.innerHTML = ["8s", "8h", "8d"].map((c) => card(c, "under")).join("") + card("8c");
    await wait(350);
    const f = fx(st);
    if (mode === "infinity") {
      const cs = [...pile.querySelectorAll(".card")];
      if (!reduced) await Promise.all(cs.map((c, i) => c.animate([{ transform: "none" }, { transform: "rotate(90deg)", offset: 0.4 }, { transform: `rotate(${450 + i * 40}deg) translate(${(i - 1.5) * 90}px, -260px) scale(.4)`, opacity: 0 }], { duration: 1300, delay: i * 90, easing: "cubic-bezier(.5,0,.3,1)", fill: "forwards" }).finished));
      f.innerHTML = `<span class="big-word inf">∞</span>`;
      if (!reduced) await f.firstChild.animate([{ opacity: 0, transform: "scale(.6)" }, { opacity: 1, transform: "scale(1)" }], { duration: 400, easing: EASE.out }).finished;
    } else if (mode === "gravity") {
      const all = [...st.querySelectorAll(".card")];
      if (!reduced) await Promise.all(all.map((c, i) => c.animate([{ transform: "none" }, { transform: `translateY(${-20 - (i % 3) * 8}px) rotate(${(i % 2 ? 1 : -1) * 6}deg)`, offset: 0.15 }, { transform: `translateY(520px) rotate(${(i % 2 ? 1 : -1) * (40 + i * 7)}deg)` }], { duration: 1100, delay: (i * 37) % 300, easing: "cubic-bezier(.55,0,.9,.5)", fill: "forwards" }).finished));
      f.innerHTML = `<span class="big-word">8888</span>`;
    } else {
      f.classList.add("dark");
      f.innerHTML = `<span class="big-word eights"><i>8</i><i>8</i><i>8</i><i>8</i></span>`;
      const is = [...f.querySelectorAll("i")];
      if (!reduced) { await f.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 250, fill: "forwards" }).finished; for (const i of is) { await wait(260); i.style.opacity = 1; } await wait(700); }
      else is.forEach((i) => (i.style.opacity = 1));
    }
    say(st, "Otto flipped the 8s. Last.", "none");
    await wait(900);
  }
  async function nine(st, mode) {
    const d = $(st, ".deck .card");
    const f = fx(st);
    const text = "Tackar från Tigdikar";
    if (mode === "banner") {
      if (!reduced) await d.animate([{ transform: "none" }, { transform: "rotate(360deg) translateY(-10px)" }, { transform: "none" }], { duration: 700, easing: EASE.soft }).finished;
      f.innerHTML = `<span class="banner">${text}</span>`;
      if (!reduced) await f.firstChild.animate([{ transform: "translateX(-105%)" }, { transform: "none", offset: 0.25 }, { transform: "none", offset: 0.8 }, { transform: "translateX(105%)" }], { duration: 2200, easing: "cubic-bezier(.6,0,.4,1)" }).finished;
    } else if (mode === "bubble") {
      const r = rectOf(d), sr = rectOf(st);
      f.innerHTML = `<span class="bubble" style="left:${r.left - sr.left - 10}px; top:${r.top - sr.top - 52}px">${text}</span>`;
      if (!reduced) { await f.firstChild.animate([{ transform: "scale(.4) translateY(20px)", opacity: 0 }, { transform: "scale(1.04)", opacity: 1, offset: 0.6 }, { transform: "none", opacity: 1 }], { duration: 360, easing: EASE.out }).finished; await wait(1500); }
    } else {
      f.innerHTML = `<span class="marquee">${text}</span>`;
      if (!reduced) await f.firstChild.animate([{ transform: "translateX(100%)" }, { transform: "translateX(-100%)" }], { duration: 2600, easing: "linear" }).finished;
    }
    f.innerHTML = "";
    const face = await flipInPlace(d, card("Ks"), { duration: 300 });
    face.classList.add("picked");
    say(st, "9: K♠", "none");
  }

  // ---------- more moments ----------
  async function unlucky(st, mode) {
    const c = $(st, '.hand [data-c="Jh"]'); const from = rectOf(c);
    st.querySelectorAll('.hand .card').forEach((x) => x.remove());
    $(st, ".hand").insertAdjacentHTML("beforeend", card("2h", "playable"));
    const last = $(st, ".hand .card"); const lf = rectOf(last); last.remove();
    const t = addToPile(st, "2h"); t.style.visibility = "hidden";
    await fly(card("2h"), lf, rectOf(t), { duration: 380 });
    t.style.visibility = "";
    await wait(250);
    const f = fx(st);
    if (mode === "crack") {
      const r = rectOf(t), sr = rectOf(st);
      f.innerHTML = `<div class="half l" style="left:${r.left - sr.left}px;top:${r.top - sr.top}px;width:${r.width}px">${card("2h")}</div><div class="half r" style="left:${r.left - sr.left}px;top:${r.top - sr.top}px;width:${r.width}px">${card("2h")}</div>`;
      f.querySelectorAll(".card").forEach((x) => x.style.setProperty("--w", r.width + "px"));
      t.style.visibility = "hidden";
      const [l, rr] = f.querySelectorAll(".half");
      if (!reduced) await Promise.all([
        l.animate([{ transform: "none" }, { transform: "translate(-4px, 4px) rotate(-6deg)", offset: 0.2 }, { transform: "translate(-40px, 300px) rotate(-50deg)" }], { duration: 1000, easing: "cubic-bezier(.55,0,.9,.5)", fill: "forwards" }).finished,
        rr.animate([{ transform: "none" }, { transform: "translate(4px, 4px) rotate(6deg)", offset: 0.2 }, { transform: "translate(40px, 300px) rotate(45deg)" }], { duration: 1000, easing: "cubic-bezier(.55,0,.9,.5)", fill: "forwards" }).finished,
      ]);
    } else if (mode === "wrong") {
      if (!reduced) st.animate([{ boxShadow: "inset 0 0 0 0 #e3120b" }, { boxShadow: "inset 0 0 0 200px rgba(227,18,11,.18)", offset: 0.2 }, { boxShadow: "inset 0 0 0 0 #e3120b" }], { duration: 700 });
      const r = rectOf(t), sr = rectOf(st);
      f.innerHTML = `<span class="x" style="left:${r.left - sr.left + r.width / 2}px;top:${r.top - sr.top + r.height / 2}px">\u2715</span>`;
      if (!reduced) await f.firstChild.animate([{ transform: "translate(-50%,-50%) scale(3)", opacity: 0 }, { transform: "translate(-50%,-50%) scale(.9)", opacity: 1, offset: 0.6 }, { transform: "translate(-50%,-50%) scale(1)", opacity: 1 }], { duration: 360, easing: EASE.out, fill: "forwards" }).finished;
      await wait(600);
    } else {
      const me = $(st, ".me");
      if (!reduced) await me.animate([{ transform: "none", filter: "none" }, { transform: "translateY(10px)", filter: "grayscale(1) opacity(.5)" }], { duration: 600, easing: EASE.soft, fill: "forwards" }).finished;
      f.innerHTML = `<span class="big-word last">Last</span>`;
      if (!reduced) await f.firstChild.animate([{ transform: "scale(1.8)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 300, easing: EASE.out }).finished;
      await wait(500);
    }
    say(st, "Out on a 2. Illegal: last.", "none");
  }
  async function blind(st, mode) {
    const hand = $(st, ".hand"); hand.innerHTML = back("fd") + back("fd") + back("fd");
    await wait(300);
    const pick = hand.children[1];
    if (mode === "suspense" && !reduced) { await pick.animate([{ transform: "none" }, { transform: "translateY(-22px) scale(1.08)" }], { duration: 300, easing: EASE.out, fill: "forwards" }).finished; await wait(650); }
    if (mode === "peek" && !reduced) { await pick.animate([{ transform: "none" }, { transform: "perspective(500px) rotateX(18deg) rotateY(-24deg)", offset: 0.5 }, { transform: "perspective(500px) rotateX(10deg) rotateY(-14deg)" }], { duration: 700, easing: EASE.soft, fill: "forwards" }).finished; await wait(300); }
    const face = await flipInPlace(pick, card("6s"), { duration: mode === "suspense" ? 760 : 340, mode: mode === "quick" ? "flat" : "3d" });
    if (mode === "suspense") { face.style.transform = "translateY(-22px) scale(1.08)"; if (!reduced) await face.animate([{ transform: "translateY(-22px) scale(1.08)" }, { transform: "none" }], { duration: 260, easing: EASE.out }).finished; face.style.transform = ""; }
    say(st, "6♠ on a 2", "none");
  }
  async function win(st, mode) {
    const hand = $(st, ".hand"); hand.innerHTML = card("Qs", "playable");
    const c = hand.firstElementChild, from = rectOf(c); c.remove();
    const t = addToPile(st, "Qs"); t.style.visibility = "hidden";
    await fly(card("Qs"), from, rectOf(t), { duration: 380 });
    t.style.visibility = "";
    const f = fx(st);
    if (mode === "squares") {
      const r = rectOf(t), sr = rectOf(st), cx = r.left - sr.left + r.width / 2, cy = r.top - sr.top + r.height / 2;
      f.innerHTML = Array.from({ length: 22 }, (_, i) => `<i class="sq" style="left:${cx}px;top:${cy}px;${i % 3 ? "" : "background:var(--line)"}"></i>`).join("");
      if (!reduced) await Promise.all([...f.children].map((q, i) => { const a = (i / 22) * Math.PI * 2, d = 90 + (i * 37) % 80; return q.animate([{ transform: "translate(-50%,-50%) scale(1)", opacity: 1 }, { transform: `translate(calc(-50% + ${Math.cos(a) * d}px), calc(-50% + ${Math.sin(a) * d}px)) rotate(${i * 30}deg) scale(.6)`, opacity: 0 }], { duration: 900 + (i % 5) * 60, easing: EASE.out, fill: "forwards" }).finished; }));
    } else if (mode === "type") {
      f.innerHTML = `<span class="big-four">1st</span>`;
      if (!reduced) await f.firstChild.animate([{ transform: "scale(.6)", opacity: 0 }, { transform: "scale(1)", opacity: 1, offset: 0.4 }, { transform: "scale(1)", opacity: 1, offset: 0.8 }, { opacity: 0 }], { duration: 1500, easing: EASE.out }).finished;
    }
    $(st, ".me").insertAdjacentHTML("afterbegin", `<span class="place">1st</span>`);
    if (!reduced) await $(st, ".me .place").animate([{ transform: "scale(1.6)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 300, easing: EASE.out }).finished;
    f.innerHTML = "";
    say(st, "You: 1st", "none");
  }
  async function bigPickup(st, mode) {
    const codes = ["3s", "5d", "6h", "7c", "8d", "9s", "Jc", "Qh", "Kd", "As", "Jd", "2s"];
    const pile = $(st, ".pile"); pile.innerHTML = codes.slice(-3).map((c, i) => card(c, i < 2 ? "under" : "")).join("");
    pile.insertAdjacentHTML("beforeend", `<span class="pcount">12</span>`);
    await wait(350);
    const to = rectOf($(st, ".opp-cards")), pr = rectOf(pile.querySelector(".card:last-of-type"));
    const n = $(st, ".opp .count b");
    if (mode === "avalanche") {
      pile.innerHTML = "";
      await Promise.all(codes.map((c, i) => wait(i * 25).then(() => fly(back(), pr, { left: to.left + (i % 3) * 10, top: to.top, width: 28 }, { duration: 380 })).then(() => (n.textContent = String(3 + i + 1)))));
    } else if (mode === "weight") {
      pile.innerHTML = "";
      await fly(`<div class="block">${codes.slice(-4).map((c) => card(c)).join("")}</div>`, pr, { left: to.left, top: to.top, width: pr.width * 0.6 }, { duration: 520, easing: EASE.soft });
      n.textContent = "15";
      if (!reduced) await $(st, ".opp").animate([{ transform: "none" }, { transform: "translateY(8px)", offset: 0.3 }, { transform: "none" }], { duration: 500, easing: EASE.out }).finished;
    } else {
      if (!reduced) await pile.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "scale(.8)" }], { duration: 220, fill: "forwards" }).finished;
      pile.innerHTML = ""; pile.style.opacity = ""; 
      for (let i = 4; i <= 15; i++) { n.textContent = String(i); await wait(40); }
    }
    say(st, "Otto picked up 12", "none");
  }
  async function reverse(st, mode) {
    const pile = $(st, ".pile"); pile.innerHTML = card("3h", "under") + card("3s", "under") + card("3c");
    const arrow = $(st, ".dir");
    if (mode === "arrow") { if (!reduced) await arrow.animate([{ transform: "none" }, { transform: "rotate(180deg)" }], { duration: 600, easing: EASE.snap, fill: "forwards" }).finished; arrow.textContent = "\u21ba"; arrow.getAnimations().forEach((a) => a.cancel()); }
    if (mode === "mirror" && !reduced) { await st.animate([{ transform: "none" }, { transform: "scaleX(-1)", offset: 0.45 }, { transform: "scaleX(-1)", offset: 0.6 }, { transform: "none" }], { duration: 1100, easing: EASE.soft }).finished; arrow.textContent = "\u21ba"; }
    if (mode === "sweep") {
      const f = fx(st); f.innerHTML = `<i class="sweep"></i>`;
      if (!reduced) await f.firstChild.animate([{ transform: "translateX(110%)" }, { transform: "translateX(-110%)" }], { duration: 700, easing: EASE.soft }).finished;
      f.innerHTML = ""; arrow.textContent = "\u21ba";
    }
    say(st, "Three 3s: reversed", "none");
  }
  async function emote(st, mode) {
    const em = mode === "rain" ? "\ud83d\ude2d" : mode === "stick" ? "\ud83e\udd21" : mode === "swarm" ? "\ud83d\udc1f" : "\ud83c\udf45";
    const f = fx(st), sr = rectOf(st);
    const from = rectOf($(st, ".hand")), to = rectOf($(st, ".opp .who"));
    const fx0 = from.left - sr.left + from.width / 2, fy0 = from.top - sr.top, tx = to.left - sr.left + to.width / 2, ty = to.top - sr.top + to.height / 2;
    $(st, ".opp").classList.add("targeted");
    if (mode === "throw") {
      f.innerHTML = `<span class="emo" style="left:${fx0}px;top:${fy0}px">${em}</span>`;
      const e = f.firstChild;
      if (!reduced) await e.animate([{ transform: "translate(-50%,-50%) scale(.8) rotate(0)" }, { transform: `translate(calc(-50% + ${(tx - fx0) / 2}px), calc(-50% + ${(ty - fy0) / 2 - 80}px)) scale(1.4) rotate(200deg)`, offset: 0.5 }, { transform: `translate(calc(-50% + ${tx - fx0}px), calc(-50% + ${ty - fy0}px)) scale(1) rotate(400deg)` }], { duration: 650, easing: "cubic-bezier(.3,.1,.6,1)", fill: "forwards" }).finished;
      e.remove();
      f.insertAdjacentHTML("beforeend", `<span class="splat" style="left:${tx}px;top:${ty}px"></span>`);
      if (!reduced) { $(st, ".opp").animate([0, -5, 5, -3, 0].map((x) => ({ transform: `translateX(${x}px)` })), { duration: 300 }); await f.lastChild.animate([{ transform: "translate(-50%,-50%) scale(.2)", opacity: 1 }, { transform: "translate(-50%,-50%) scale(1)", opacity: 1, offset: 0.3 }, { transform: "translate(-50%,-30%) scale(1)", opacity: 0 }], { duration: 1400, easing: EASE.out, fill: "forwards" }).finished; }
    } else if (mode === "stick") {
      f.innerHTML = `<span class="emo big" style="left:${tx}px;top:${ty - 6}px">${em}</span>`;
      const e = f.firstChild;
      if (!reduced) { await e.animate([{ transform: "translate(-50%,-50%) translateY(-120px) scale(2)", opacity: 0 }, { transform: "translate(-50%,-50%) scale(1)", opacity: 1 }], { duration: 380, easing: EASE.snap, fill: "forwards" }).finished; await e.animate([0, -12, 10, -8, 6, 0].map((r) => ({ transform: `translate(-50%,-50%) rotate(${r}deg)` })), { duration: 2200, easing: "ease-in-out" }).finished; }
    } else if (mode === "rain") {
      f.innerHTML = `<span class="cloud" style="left:${tx}px;top:${ty - 34}px">\u2601\ufe0f</span>` + Array.from({ length: 8 }, (_, i) => `<i class="drop" style="left:${tx - 18 + i * 5}px;top:${ty - 20}px"></i>`).join("") + `<span class="emo" style="left:${tx + 34}px;top:${ty}px">${em}</span>`;
      if (!reduced) {
        f.querySelector(".cloud").animate([{ transform: "translate(-50%,-50%) translateY(-30px)", opacity: 0 }, { transform: "translate(-50%,-50%)", opacity: 1 }], { duration: 400, easing: EASE.out, fill: "forwards" });
        await Promise.all([...f.querySelectorAll(".drop")].map((d, i) => d.animate([{ transform: "translateY(0)", opacity: 0 }, { opacity: 1, offset: 0.2 }, { transform: "translateY(40px)", opacity: 0 }], { duration: 600, delay: 300 + (i * 97) % 400, iterations: 3, easing: "ease-in" }).finished));
      }
    } else {
      f.innerHTML = Array.from({ length: 5 }, (_, i) => `<span class="emo sm" style="left:${tx}px;top:${ty}px">${em}</span>`).join("");
      if (!reduced) await Promise.all([...f.children].map((e, i) => e.animate(Array.from({ length: 9 }, (_, k) => { const a = (k / 8) * Math.PI * 2 + i * 1.256; return { transform: `translate(calc(-50% + ${Math.cos(a) * 34}px), calc(-50% + ${Math.sin(a) * 16 - 18}px))` }; }), { duration: 1400, iterations: 2, easing: "linear" }).finished));
    }
    await wait(300);
    f.innerHTML = ""; $(st, ".opp").classList.remove("targeted");
    say(st, `You \u2192 Otto ${em}`, "none");
  }

  // ---------- demo bodies ----------
  async function playMine(st, { duration, arc = 0, rotate = 0, thump = false }) {
    const c = $(st, '.hand [data-c="4d"]');
    const from = rectOf(c);
    const before = snapshot(st.querySelectorAll(".hand .card"));
    c.remove();
    const target = addToPile(st, "4d");
    target.style.visibility = "hidden";
    flipFrom(st.querySelectorAll(".hand .card"), before);
    await fly(card("4d"), from, rectOf(target), { duration, arc, rotate });
    target.style.visibility = "";
    if (thump && !reduced) await $(st, ".pile").animate([{ transform: "scale(1)" }, { transform: "scale(.96)" }, { transform: "scale(1)" }], { duration: 180, easing: "ease-out" }).finished;
    say(st, "You played 4♦");
  }
  async function oppPlays(st, { flipAt = null, duration = 500, arc = 0, appear = false }) {
    const from = rectOf($(st, ".opp-cards .card:last-child"));
    $(st, ".opp .count b").textContent = "2";
    const t = addToPile(st, "5c");
    if (appear) { if (!reduced) await t.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200 }).finished; }
    else {
      t.style.visibility = "hidden";
      const html = flipAt != null ? back() : card("5c");
      await fly(html, from, rectOf(t), { duration, arc, flipAt, faceHTML: card("5c") });
      t.style.visibility = "";
    }
    say(st, "Otto played 5♣");
  }
  async function drawMine(st, { flip, appear }) {
    const hand = $(st, ".hand");
    hand.insertAdjacentHTML("beforeend", card("Qh", "playable"));
    const n = hand.lastElementChild;
    if (appear) { if (!reduced) await n.animate([{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { duration: 240, easing: EASE.out }).finished; return say(st, "You drew a card"); }
    n.style.visibility = "hidden";
    const from = rectOf($(st, ".deck .card"));
    await fly(flip ? back() : card("Qh"), from, rectOf(n), { duration: 460, flipAt: flip ? 0.75 : null, faceHTML: card("Qh", "playable") });
    n.style.visibility = "";
    say(st, "You drew a card");
  }
  async function reflow(st, { overshoot, duration = 300, instant }) {
    const c = $(st, '.hand [data-c="4c"]');
    const before = snapshot(st.querySelectorAll(".hand .card"));
    if (!reduced) await c.animate([{ opacity: 1 }, { opacity: 0, transform: "translateY(-16px)" }], { duration: 200, fill: "forwards" }).finished;
    c.remove();
    if (!instant) await flipFrom(st.querySelectorAll(".hand .card"), before, { overshoot, duration });
  }
  async function pickup(st, { stagger = 70, block = false, duration = 380 }) {
    const pile = $(st, ".pile"); pile.insertAdjacentHTML("afterbegin", card("Kh", "under") + card("Qc", "under"));
    const cards = [...pile.querySelectorAll(".card")];
    const hand = $(st, ".hand");
    const froms = cards.map(rectOf);
    const codes = cards.map((c) => c.dataset.c);
    cards.forEach((c) => (c.style.visibility = "hidden"));
    const before = snapshot(hand.querySelectorAll(".card"));
    codes.forEach((c) => hand.insertAdjacentHTML("beforeend", card(c)));
    const added = [...hand.querySelectorAll(".card")].slice(-codes.length);
    added.forEach((a) => (a.style.visibility = "hidden"));
    flipFrom(hand.querySelectorAll(".card:not([style])"), before);
    if (block) {
      const pr = rectOf(pile);
      const first = rectOf(added[0]);
      await fly(`<div class="block">${codes.map((c) => card(c)).join("")}</div>`, { left: pr.left, top: pr.top, width: pr.width }, { left: first.left, top: first.top, width: pr.width }, { duration: 420 });
    } else {
      await Promise.all(added.map((a, i) => wait(i * stagger).then(() => fly(card(codes[i]), froms[i], rectOf(a), { duration }))));
    }
    added.forEach((a) => (a.style.visibility = ""));
    cards.forEach((c) => c.remove());
    say(st, "You picked up the pile");
  }
  async function flipFour(st, { stagger = 110, turnFirst = false, duration = 360 }) {
    const pile = $(st, ".pile"); pile.innerHTML = ["4s", "4h", "4d", "4c"].map((c, i) => card(c, i < 3 ? "under" : "")).join("");
    say(st, "Four 4s in a row: flip!", "none");
    await wait(450);
    let cards = [...pile.querySelectorAll(".card")];
    if (turnFirst) { cards = await Promise.all(cards.map((c) => flipInPlace(c, back(c.classList.contains("under") ? "under" : ""), { duration: 260 }))); await wait(120); }
    const to = rectOf($(st, ".discard .ghost-slot"));
    const froms = cards.map(rectOf);
    cards.forEach((c) => (c.style.visibility = "hidden"));
    const dc = $(st, ".discard .dc");
    await Promise.all(cards.map((c, i) => wait(i * stagger).then(() => fly(turnFirst ? back() : card(c.dataset.c), froms[i], to, { duration })).then(() => { dc.textContent = String(+dc.textContent + 1); $(st, ".discard").classList.add("has"); })));
    pile.innerHTML = "";
    say(st, "Pile flipped to the discard");
  }
  async function reveal(st, mode) {
    const d = $(st, ".deck .card");
    if (mode === "lift" && !reduced) await d.animate([{ transform: "none" }, { transform: "translateY(-12px)" }], { duration: 180, easing: EASE.out, fill: "forwards" }).finished;
    const face = await flipInPlace(d, card("7s"), { duration: 340, mode: mode === "3d" ? "3d" : "flat" });
    if (mode === "lift") { face.style.transform = "translateY(-12px)"; if (!reduced) await face.animate([{ transform: "translateY(-12px)" }, { transform: "none" }], { duration: 200, easing: EASE.out }).finished; face.style.transform = ""; }
    say(st, "You turned over a 7♠");
  }
  async function turnTo(st, mode) {
    const opp = $(st, ".opp");
    opp.classList.remove("turn-bar", "turn-tint", "turn-dot");
    void opp.offsetWidth;
    opp.classList.add("turn-" + mode);
    say(st, "Otto's turn", "none");
    await wait(1200);
  }
  async function illegal(st, mode) {
    const c = $(st, '.hand [data-c="Jh"]');
    if (mode === "shake" && !reduced) await c.animate([0, -4, 4, -4, 4, 0].map((x) => ({ transform: `translateX(${x}px)` })), { duration: 320 }).finished;
    if (mode === "bounce" && !reduced) {
      const p = rectOf($(st, ".pile")), r = rectOf(c);
      await c.animate([{ transform: "none" }, { transform: `translate(${(p.left - r.left) * 0.35}px, ${(p.top - r.top) * 0.35}px)`, offset: 0.4 }, { transform: "none" }], { duration: 480, easing: EASE.soft }).finished;
    }
    if (mode === "flash") { c.classList.add("bad"); setTimeout(() => c.classList.remove("bad"), 900); }
    say(st, "A J can't go on a 2", mode === "flash" ? "mark" : "fade");
  }
  async function finish(st, mode) {
    const opp = $(st, ".opp");
    opp.insertAdjacentHTML("beforeend", `<span class="place">1st</span>`);
    const tag = $(st, ".place");
    $(st, ".opp .count b").textContent = "0";
    $(st, ".opp-cards").innerHTML = "";
    if (reduced) return;
    if (mode === "stamp") await tag.animate([{ transform: "scale(1.6)", opacity: 0 }, { transform: "scale(.94)", opacity: 1, offset: 0.7 }, { transform: "scale(1)" }], { duration: 360, easing: EASE.out }).finished;
    if (mode === "fade") { opp.animate([{ opacity: 1 }, { opacity: 0.45 }], { duration: 500, fill: "forwards" }); await tag.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 400 }).finished; }
    if (mode === "slide") await tag.animate([{ transform: "translateX(40px)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 360, easing: EASE.out }).finished;
    say(st, "Otto finished 1st");
  }
  async function paced(st, ms) {
    const seq = ["5c", "5s", "8h"];
    for (const c of seq) {
      await wait(ms);
      const from = rectOf($(st, ".opp-cards .card:last-child") || $(st, ".opp"));
      const t = addToPile(st, c); t.style.visibility = "hidden";
      await fly(card(c), from, rectOf(t), { duration: 420 });
      t.style.visibility = "";
      say(st, `Otto played ${c.slice(0, -1)}${SUIT[c.slice(-1)]}`);
    }
  }

  // ---------- page ----------
  const KEY = "ibflip:lab-picks";
  let picks = {};
  try { picks = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (_) {}
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(picks)); } catch (_) {} summary(); };

  function render() {
    const list = document.getElementById("demos");
    list.innerHTML = DEMOS.map((d) => `<section class="demo" id="${d.id}">
      <header><h2>${d.title}</h2><p>${d.what}</p></header>
      <div class="stage-wrap">${stageHTML()}</div>
      <div class="opts" role="radiogroup" aria-label="${d.title}">${Object.entries(d.options).map(([k, [name, note]]) => `
        <label class="opt"><input type="radio" name="${d.id}" value="${k}" ${picks[d.id] === k ? "checked" : ""}><span class="nm">${name}</span><span class="nt">${note}</span><button class="btn run" data-demo="${d.id}" data-opt="${k}">Play</button></label>`).join("")}
      </div>
    </section>`).join("");
    summary();
  }
  const running = new WeakSet();
  async function run(id, opt) {
    const sec = document.getElementById(id);
    if (running.has(sec)) return;
    running.add(sec);
    sec.querySelector(".stage-wrap").innerHTML = stageHTML();
    await wait(60);
    try { await DEMOS.find((d) => d.id === id).options[opt][2](sec.querySelector(".stage")); } finally { running.delete(sec); }
  }
  function summary() {
    const out = DEMOS.map((d) => `${d.title}: ${picks[d.id] ? d.options[picks[d.id]][0] : "(no pick)"}`).join("\n");
    const sp = ["density", "cards"].map((k) => `${k === "density" ? "Spacing" : "Card size"}: ${picks[k] || "(no pick)"}`).join("\n");
    document.getElementById("summary").value = out + "\n" + sp;
  }

  document.addEventListener("click", (e) => {
    const b = e.target.closest(".run");
    if (b) { e.preventDefault(); const r = b.closest(".opt").querySelector("input"); r.checked = true; picks[b.dataset.demo] = b.dataset.opt; save(); run(b.dataset.demo, b.dataset.opt); return; }
    const c = e.target.closest("[data-copy]");
    if (c) { const t = document.getElementById("summary"); t.select(); try { navigator.clipboard.writeText(t.value); c.textContent = "Copied"; setTimeout(() => (c.textContent = "Copy my picks"), 1500); } catch (_) {} }
    const s = e.target.closest("[data-space]");
    if (s) {
      const [k, v] = s.dataset.space.split(":");
      picks[k] = v; save();
      document.querySelectorAll(`[data-space^="${k}:"]`).forEach((x) => x.setAttribute("aria-pressed", x === s));
      const f = document.getElementById("preview");
      const u = new URL(f.src, location.href); u.searchParams.set(k, v); f.src = u.pathname + u.search + "#table";
    }
  });
  document.addEventListener("change", (e) => { if (e.target.matches(".opt input")) { picks[e.target.name] = e.target.value; save(); } });
  document.addEventListener("DOMContentLoaded", () => {
    render();
    ["density", "cards"].forEach((k) => document.querySelectorAll(`[data-space^="${k}:"]`).forEach((x) => x.setAttribute("aria-pressed", x.dataset.space === `${k}:${picks[k] || (k === "density" ? "regular" : "medium")}`)));
    const f = document.getElementById("preview");
    f.src = `../blue/?density=${picks.density || "regular"}&cards=${picks.cards || "medium"}&embed=1#table`;
  });
})();
