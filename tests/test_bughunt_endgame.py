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
from ibflip.state import FinishStatus, GameState, Phase, Player

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
# OWNER RULING (14 November 2026): several 8s as the last cards are illegal
# only if the skips land back on the finisher. The engine walks ``count + 1``
# seats from the finisher (still counted while skipping), so heads-up an odd
# number of 8s is illegal and two 8s (skip opponent, skip self, opponent
# plays) are a legal finish. These tests pin the ruling.
# ---------------------------------------------------------------------------
def test_two_eights_heads_up_from_a_face_up_stack_is_a_legal_finish():
    engine = make_engine(
        GameState(
            # Last cards: a face-up stack of two 8s (a common fixing choice).
            players=[Player(face_up_slots=[[EIGHTS[0], EIGHTS[1]], [], []], face_down_slots=[None, None, None]),
                     Player(hand=[KINGS[0]])],
            live_cards=[c(Rank.SIX)],
            phase=Phase.MIDDLE_GAME,
        )
    )
    engine.step(EIGHTS[1])
    engine.step(EIGHTS[0])
    engine.step(ACTION_END_PLAY_GROUP)
    me = engine.state.players[0]
    assert me.finish_status is FinishStatus.LEGAL_WIN
    assert me.place == 1
    assert engine.state.players[1].place == 2
    assert engine.state.phase is Phase.GAME_OVER


def test_two_eights_with_two_players_left_in_a_four_player_game_is_legal():
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
    assert engine.state.players[1].finish_status is FinishStatus.LEGAL_WIN
    assert [p.place for p in engine.state.players] == [1, 2, 4, 3]


# ---------------------------------------------------------------------------
# Cutoff scoring. arena.score: "At a cutoff retain earned places; only
# unplaced seats receive the timeout loss." The PettingZoo AEC env truncates
# with no terminal reward at all, so a seat that already finished 1st gets 0
# and unplaced seats also get 0.
# ---------------------------------------------------------------------------
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
def test_how_to_play_finish_copy_exempts_fours_and_nines_flips():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    line = next(li for li in re.findall(r"<li>.*?</li>", html, re.S) if "last play would give you another turn" in li)
    text = re.sub(r"<[^>]+>", "", line)
    assert "an 8 with two players left" in text
    assert re.search(r"4s|four 4s|fours", text, re.I), text
    assert re.search(r"9s|four 9s|nines", text, re.I), text


# ---------------------------------------------------------------------------
# Rematch after a player left (rooms.py Room.start). ``_purge_left_seats``
# renumbers the seats before the "Need at least two players" check, so a
# refused rematch leaves status "over" with the previous engine while seat
# indices have shifted: the survivor's view now pairs them with the leaver's
# engine seat (wrong place and cards on the results screen).
# ---------------------------------------------------------------------------
def test_refused_rematch_does_not_desync_seats_from_the_finished_game():
    from ibflip_web.rooms import Room, RoomError

    room = Room(code="ABCD", host=None)
    room.add_human("Ann")
    room.add_human("Bob")
    room.start()
    for index in range(2):
        if not room.engine.state.players[index].fixing_done:
            room._ready_with_full_slots(index)
    room._after_fixing_check()
    room.leave(0)  # Ann leaves; her seat is played on autopilot
    rng = random.Random(0)
    while room.engine.state.phase is not Phase.GAME_OVER:
        room.engine.step(rng.choice(room.engine.get_legal_action_indices()))
    room._check_over()
    bob_place = room.engine.state.players[1].place
    with pytest.raises(RoomError):
        room.start()  # Bob asks for a rematch alone
    bob = next(i for i, s in enumerate(room.seats) if s.name == "Bob")
    view = room.view_for(bob, [])
    if "game" in view:
        assert len(view["room"]["seats"]) == len(view["game"]["players"])
        assert view["game"]["players"][bob]["place"] == bob_place
