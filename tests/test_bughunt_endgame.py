"""Endgame bug hunt: face-down play, legal/illegal finishes, placements,
cutoff scoring and result display.

Every test here documents a suspected defect and is marked
``xfail(strict=True)``: it fails today and will start "passing" (and so
error as XPASS) once the bug is fixed, at which point the marker should be
removed. See docs/bughunt-endgame.md for the write-up.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ibflip import IBFlipEngine
from ibflip.actions import ACTION_END_PLAY_GROUP
from ibflip.cards import Rank, Suit, card_id
from ibflip.env import IBFlipAECEnv
from ibflip.ai.arena import score
from ibflip.state import FinishStatus, GameState, PendingKind, Phase, Player

ROOT = Path(__file__).resolve().parents[1]


def c(rank: Rank, suit: Suit = Suit.HEARTS) -> int:
    return card_id(rank, suit)


def make_engine(state: GameState) -> IBFlipEngine:
    engine = IBFlipEngine(num_players=len(state.players), seed=3)
    engine.set_state(state)
    return engine


KINGS = [c(Rank.KING, s) for s in Suit]
EIGHTS = [c(Rank.EIGHT, s) for s in Suit]


# ---------------------------------------------------------------------------
# "Finishing Illegally: ... This occurs if they finish on a 2, an 8 with two
# players remaining, or a 10". The rule names any 8 heads-up, not only an odd
# number of them. The engine instead walks ``count + 1`` seats from the
# finisher (who is still counted as active), so an even number of 8s lands on
# the opponent and is scored as a legal win.
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="BUG: two 8s as the last cards with two players remaining is scored as a legal finish")
def test_two_eights_heads_up_from_a_face_up_stack_is_an_illegal_finish():
    engine = make_engine(
        GameState(
            # Last cards: a face-up stack of two 8s (a common fixing choice).
            players=[Player(face_up_slots=[[EIGHTS[0], EIGHTS[1]], [], []], face_down_slots=[None, None, None]),
                     Player(hand=[KINGS[0]])],
            live_cards=[c(Rank.SIX)],
            phase=Phase.MIDDLE_GAME,
        )
    )
    engine.step(EIGHTS[0])
    engine.step(EIGHTS[1])
    engine.step(ACTION_END_PLAY_GROUP)
    me = engine.state.players[0]
    assert me.finish_status is FinishStatus.ILLEGAL_LOSS
    assert me.place == 2
    assert engine.state.players[1].place == 1


@pytest.mark.xfail(strict=True, reason="BUG: two 8s heads-up after earlier finishers is scored as a legal finish")
def test_two_eights_with_two_players_left_in_a_four_player_game_is_illegal():
    out_legal = Player(place=1, active=False, finish_status=FinishStatus.LEGAL_WIN)
    out_illegal = Player(place=4, active=False, finish_status=FinishStatus.ILLEGAL_LOSS)
    engine = make_engine(
        GameState(
            players=[out_legal, Player(hand=[EIGHTS[0], EIGHTS[1]]), out_illegal, Player(hand=[KINGS[0]])],
            live_cards=[c(Rank.SIX)],
            phase=Phase.MIDDLE_GAME,
            current_player=1,
        )
    )
    engine.step(EIGHTS[0])
    engine.step(EIGHTS[1])
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.players[1].finish_status is FinishStatus.ILLEGAL_LOSS
    assert [p.place for p in engine.state.players] == [1, 3, 4, 2]


# ---------------------------------------------------------------------------
# Oracle fuzz over random full games (2 to 5 players).
# ---------------------------------------------------------------------------
def _all_cards(state: GameState) -> list[int]:
    cards = state.draw_pile + state.live_cards + state.discard_pile
    for p in state.players:
        cards += p.hand + [v for s in p.face_up_slots for v in s] + [v for v in p.face_down_slots if v is not None]
    return cards


def _holdings(p: Player):
    return (sorted(p.hand), [sorted(s) for s in p.face_up_slots], list(p.face_down_slots))


def _expected_finish(events: list[dict], active_before: int) -> FinishStatus | None:
    """What the PDF says about a finish made during this step, or None when the
    rules are ambiguous (9s flip, several 8s with three or more players)."""
    flips = [e for e in events if e["kind"] == "flip"]
    if flips:
        rank = Rank(flips[0]["rank"])
        if rank is Rank.EIGHT:
            return FinishStatus.EIGHTS_LOSS
        if rank is Rank.FOUR:
            return FinishStatus.LEGAL_WIN  # no 3 to take, else they would not have finished
        if rank is Rank.NINE:
            return None
        return FinishStatus.ILLEGAL_LOSS  # 10 or a non-4-or-9 set
    cards = [e["card"] for e in events if e["kind"] in ("play", "face_down", "nine_draw", "reveal")]
    if not cards:
        return None
    last = Rank(cards[-1] // 4)
    if last is Rank.TWO:
        return FinishStatus.ILLEGAL_LOSS
    if last is Rank.EIGHT:
        if active_before == 2:
            return FinishStatus.ILLEGAL_LOSS  # "an 8 with two players remaining"
        eights = sum(1 for e in events if e["kind"] == "play" and Rank(e["card"] // 4) is Rank.EIGHT)
        return FinishStatus.LEGAL_WIN if eights <= 1 else None
    return FinishStatus.LEGAL_WIN


def _run_oracle_game(n: int, seed: int) -> list[str]:
    problems: list[str] = []
    engine = IBFlipEngine(n, seed=seed)
    engine.reset()
    engine.auto_fix_hands_randomly()
    rng = random.Random(seed)
    finish_order: list[tuple[int, FinishStatus]] = []
    frozen: dict[int, tuple] = {}
    group_events: list[dict] = []
    for _ in range(20000):
        state = engine.state
        if state.phase is Phase.GAME_OVER:
            break
        actor = state.current_player
        if not state.players[actor].active:
            problems.append(f"inactive seat {actor} is to act")
        active_before = sum(p.active for p in state.players)
        placed_before = {i for i, p in enumerate(state.players) if p.place is not None}
        # A play group spans several steps (cards, then END, maybe a 9 draw).
        nine_draw = state.pending is not None and state.pending.kind is PendingKind.NINE_DRAW
        if not state.turn_context.played_card_ids and not nine_draw:
            group_events = []
        engine.events = []
        engine.step(rng.choice(engine.get_legal_action_indices()))
        group_events += engine.events
        state = engine.state
        if sorted(_all_cards(state)) != list(range(52)):
            problems.append("card conservation broken")
        for i, cards in frozen.items():
            if _holdings(state.players[i]) != cards:
                problems.append(f"finished seat {i} gained or lost cards")
        for i, p in enumerate(state.players):
            if i in placed_before or p.place is None:
                continue
            if p.finish_status is None:
                continue  # last player left, given the remaining place
            if i != actor:
                problems.append(f"seat {i} finished on seat {actor}'s move")
            finish_order.append((i, p.finish_status))
            frozen[i] = _holdings(p)
            expected = _expected_finish(group_events, active_before)
            if expected is not None and expected is not p.finish_status:
                kinds = [(e["kind"], e.get("card"), e.get("rank")) for e in group_events]
                problems.append(f"{n=} {seed=} seat {i}: expected {expected.name}, got {p.finish_status.name} after {kinds}")
    else:
        return problems  # truncated: random play may loop; not a rule error
    places = [p.place for p in engine.state.players]
    if sorted(places) != list(range(1, n + 1)):
        problems.append(f"places not a permutation: {places}")
    legal = [i for i, s in finish_order if s is FinishStatus.LEGAL_WIN]
    illegal = [i for i, s in finish_order if s is FinishStatus.ILLEGAL_LOSS]
    eights = [i for i, s in finish_order if s is FinishStatus.EIGHTS_LOSS]
    if [places[i] for i in legal] != list(range(1, len(legal) + 1)):
        problems.append(f"legal finishers not placed 1st.. in order: {places}")
    # First illegal finisher is lowest of the illegal block; 8s flippers below all.
    bottom = [places[i] for i in eights[::-1]] + [places[i] for i in illegal]
    if bottom != list(range(n, n - len(bottom), -1)):
        problems.append(f"illegal/eights placement wrong: {places} order={finish_order}")
    return problems


@pytest.mark.xfail(strict=True, reason="BUG: random games hit heads-up even-8s finishes scored as legal (e.g. n=2 seed=13)")
def test_random_full_games_follow_the_pdf_finishing_rules():
    problems: list[str] = []
    for n in (2, 3, 4, 5):
        for seed in range(150):
            problems += _run_oracle_game(n, seed)
    assert not problems, "\n".join(problems[:20])


# ---------------------------------------------------------------------------
# Cutoff scoring. arena.score: "At a cutoff retain earned places; only
# unplaced seats receive the timeout loss." The PettingZoo AEC env truncates
# with no terminal reward at all, so a seat that already finished 1st gets 0
# and unplaced seats also get 0.
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="BUG: AEC env truncation drops earned placement rewards (arena keeps them and gives only unplaced seats -1)")
def test_aec_truncation_keeps_earned_places_and_penalises_only_unplaced():
    env = IBFlipAECEnv(3, seed=2, max_steps=10**9)
    env.reset(seed=2)
    rng = random.Random(2)
    # Play until somebody is placed but the game is not over.
    while not any(p.place is not None for p in env.engine.state.players):
        agent = env.agent_selection
        mask = env.infos[agent]["action_mask"]
        env.step(rng.choice([a for a in range(len(mask)) if mask[a]]))
        assert env.engine.state.phase is not Phase.GAME_OVER
    env.max_steps = env.total_steps + 1
    agent = env.agent_selection
    mask = env.infos[agent]["action_mask"]
    action = next(a for a in range(len(mask)) if mask[a])
    snapshot = env.engine.clone()
    snapshot.step(action, validate=False)
    if snapshot.state.phase is Phase.GAME_OVER:
        pytest.skip("cut-off step ended the game")
    env.step(action)
    assert all(env.truncations.values())
    result = {"places": [p.place for p in env.engine.state.players], "winner": None, "loser": None}
    expected = {f"player_{i}": score(result, i, 3) for i in range(3)}
    got = {a: env._cumulative_rewards[a] for a in expected}
    # Placed seats keep their score, unplaced lose (shaping rewards aside).
    for a in expected:
        assert abs(got[a] - expected[a]) < 0.2, (got, expected)


# ---------------------------------------------------------------------------
# Results screen (static/app.js showResult). The last player left after
# everyone else finished illegally is placed 1st with no finish status ("A
# player wins the game if ... they are the last player remaining after all
# other players have finished illegally"). The client then claims "You
# finished first, legally." and, at 3 to 5 players, treats it as a loss
# (youWin false: no confetti, the "bad" sound) under a "You win" title.
# ---------------------------------------------------------------------------
def _run_show_result(game: dict, seat: int) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    source = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    helpers = source[source.index("const ordinal ="):source.index("// ================================================================== HOME")]
    helpers = helpers.split("function finishText")[0]
    show = source[source.index("function showResult()"):source.index("function confetti()")]
    script = (
        "const el = () => ({ innerHTML: '', textContent: '', classList: { toggle() {}, remove() {} }, focus() {} });\n"
        "const els = {}; const $ = (s) => (els[s] ??= el());\n"
        "let won = null; const Sound = { win() { won = true; }, bad() { won = false; } }; const confetti = () => {};\n"
        "const esc = (s) => String(s); const cardHTML = () => '';\n"
        f"const S = {{ seat: {seat}, game: GAME, room: {{ host: 0, seats: GAME.players.map((_, i) => ({{ name: 'P' + i, wins: 0 }})) }} }};\n"
        "function nameOf(i) { return i === S.seat ? 'You' : 'P' + i; }\n"
        + helpers + "\n" + show + "\n"
        "showResult(); console.log(JSON.stringify({ title: $('#resultTitle').innerHTML, text: $('#resultText').textContent, won }));\n"
    ).replace("GAME", json.dumps(game))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _over_game(places, finishes, winner, loser):
    return {
        "status": "over",
        "winner": winner,
        "loser": loser,
        "players": [
            {"place": p, "finish": f, "face_up": [[], [], []], "hand": [], "face_down_cards": []}
            for p, f in zip(places, finishes)
        ],
    }


@pytest.mark.xfail(strict=True, reason="BUG: results screen says 'finished first, legally' and plays the losing sound for the last player left after illegal finishers")
def test_results_for_last_player_left_after_illegal_finishers():
    # 3 players: seats 1 and 2 finished illegally; seat 0 is left and wins.
    game = _over_game([1, 3, 2], [None, "illegal", "illegal"], winner=0, loser=1)
    result = _run_show_result(game, seat=0)
    assert result["title"] == "You win"
    assert "legally" not in result["text"]
    assert result["won"] is True


# ---------------------------------------------------------------------------
# How-to-play copy (static/index.html). PDF: "or if they finish by flipping a
# non-4-or-9 set. If they finish by flipping the 4s they remain in the game
# ... If they finish by flipping the 9s ... the player finishes illegally
# unless that card is an 8". The copy says any flip on your last play loses.
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="BUG: How to play says any finishing flip loses; the PDF exempts the 4s and (with an 8 on top) the 9s")
def test_how_to_play_finish_copy_exempts_fours_and_nines_flips():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    line = next(li for li in re.findall(r"<li>.*?</li>", html, re.S) if "last play would give you another turn" in li)
    text = re.sub(r"<[^>]+>", "", line)
    assert "an 8 with two players left" in text
    assert re.search(r"4s|four 4s|fours", text, re.I), text
    assert re.search(r"9s|four 9s|nines", text, re.I), text
