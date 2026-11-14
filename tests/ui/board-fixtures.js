/* Dev-only board fixtures for layout checks. Never loaded by the game:
   scripts/ui-overflow-matrix.sh injects this file into a local page.
   window.__fixture(name) renders a synthetic table state without a server. */
(() => {
  const AV = ["🦁", "🐙", "🐧", "🐸", "🐳"];
  const NAMES = ["Yolo", "Milo", "Basil", "Nova", "Dex"];
  const LONG = "Bartholomew_the_Unshuffled";
  const range = (a, n) => Array.from({ length: n }, (_, i) => a + i);
  function build({ n = 2, status = "playing", seen = 8, oppHand = 8, myHand = 1, stacked = false, long = false, mine = "done", deck = 0, live = 4, discard = 30 }) {
    let next = 0;
    const take = (k) => { const out = range(next, k).map((c) => c % 52); next += k; return out; };
    const seats = range(0, n).map((i) => ({
      seat: i, kind: i ? "bot" : "human", name: long ? `${LONG}${i}` : NAMES[i], avatar: AV[i],
      level: i ? "hard" : null, connected: true, host: i === 0, wins: 0, left: false,
    }));
    const players = range(0, n).map((i) => ({
      hand_count: i ? oppHand : myHand,
      known: i ? range(0, seen).map((k) => (k * 7 + i) % 52) : [],
      face_up: stacked ? [take(4), take(3), take(2)] : [take(1), take(1), take(1)],
      face_down: [true, true, true], active: true, finish: null, place: null, ready: i % 2 === 1,
    }));
    const hand = take(myHand);
    const liveCards = take(live);
    const legal = { cards: [], pick_up: false, reveal: false, end_group: false, face_down: [] };
    if (mine === "done") legal.end_group = true;
    if (mine === "play") { legal.cards = hand.slice(0, 3); legal.pick_up = true; }
    if (mine === "pickup") legal.pick_up = true;
    const playing = status === "playing";
    return {
      type: "state", you: 0, events: [],
      room: { code: "FIXTUR", status, host: 0, seats, game_no: 1, hard_available: true },
      game: {
        status, phase: playing ? "MIDDLE_GAME" : "FIXING_HANDS", current: playing ? 0 : null, direction: 1,
        four_loop: false, nine_draw: false, winner: null, loser: null, live: playing ? liveCards : [], ace_one: [],
        target: playing ? (liveCards[liveCards.length - 1] >> 2) : null, discard_count: discard, discard_top: null,
        draw_count: deck, start_card: null, group_rank: mine === "done" ? (liveCards[liveCards.length - 1] >> 2) : null,
        group_count: mine === "done" ? 1 : 0, players, hand, legal: playing ? legal : { cards: [], pick_up: false, reveal: false, end_group: false, face_down: [] },
        source: playing ? "hand" : null,
      },
    };
  }
  const FIX = {
    "2p-mid": { n: 2 },
    "5p-mid": { n: 5, seen: 4, oppHand: 5, myHand: 4, mine: "play", deck: 9 },
    "2p-stress": { n: 2, seen: 16, oppHand: 18, myHand: 18, stacked: true, long: true, mine: "play" },
    "5p-stress": { n: 5, seen: 14, oppHand: 16, myHand: 18, stacked: true, long: true, mine: "play" },
    "4p-setup": { n: 4, status: "fixing", seen: 2, oppHand: 3, myHand: 3, deck: 14, live: 0, discard: 0 },
  };
  window.__FIXTURES = Object.keys(FIX);
  window.__fixture = async (name) => {
    if (S.ws) { S.ws.onclose = null; S.ws.onmessage = null; try { S.ws.close(); } catch (_) {} S.ws = null; }
    clearTimeout(S.autoActTimer);
    S.lastGameNo = 1; S.fast = true; S.queue = []; S.busy = false; S.liveShown = [];
    if (!S.game) S.game = build(FIX[name]).game; // skip the first-deal animation
    await apply(build(FIX[name]));
    S.fast = false;
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    return name;
  };
})();
