"""Turn-play bug hunt (14 November 2026).

Tests that document a rules bug are marked ``xfail(strict=True)`` so the suite
stays green; each reason starts with ``BUG:``. The remaining tests pin down
behaviour that was checked against the PDF and found correct, including a
seeded fuzz whose invariants are written independently of the engine.
See ``docs/bughunt-play.md`` for the findings and questions for the owner.
"""
from __future__ import annotations

import random

import pytest

from ibflip import IBFlipEngine
from ibflip.actions import (
    ACTION_END_PLAY_GROUP,
    ACTION_PICK_UP_LIVE_PILE,
    ACTION_RESOLVE_NINE_DRAW,
    ACTION_REVEAL_DRAW_PILE_TOP,
    FACE_DOWN_ACTIONS,
)
from ibflip.ai.observation import compact_legal
from ibflip.cards import RANK_BY_ID, Rank, Suit, card_id
from ibflip.rules import can_play_on
from ibflip.state import GameState, PendingEffect, PendingKind, Phase, Player


def c(rank: Rank, suit: Suit = Suit.HEARTS) -> int:
    return card_id(rank, suit)


def engine_for(players, **kwargs) -> IBFlipEngine:
    """A MIDDLE_GAME state unless a draw-pile is given (set_state then makes it
    EARLY_GAME, so every play draws back to three)."""
    engine = IBFlipEngine(len(players), seed=1)
    engine.set_state(GameState(players=players, phase=Phase.MIDDLE_GAME, **kwargs))
    return engine


def nine_flip_engine(promoted: int, flipper_hand: list[int], others: list[list[int]]) -> IBFlipEngine:
    """Player 0 completes four 9s. The pre-existing discard is a single card, so
    the promoted pile is exactly ``[promoted]`` regardless of the shuffle."""
    nines = [c(Rank.NINE, s) for s in Suit]
    engine = engine_for(
        [Player(hand=[nines[3], *flipper_hand])] + [Player(hand=list(h)) for h in others],
        live_cards=nines[:3],
        discard_pile=[promoted],
    )
    engine.step(nines[3])
    engine.step(ACTION_END_PLAY_GROUP)
    return engine


# ---------------------------------------------------------------- bugs


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="BUG: a 6 played on a 4 promoted by a 9s flip does not start the 4 rule; "
    "the next player may play any card that goes on a regular 6",
)
def test_six_on_a_four_promoted_by_a_nine_flip_makes_the_next_player_play_on_a_four():
    # PDF, 6: "If a 6 is played on a 4, the next player must play on a 4, as
    # outlined above." 4: "the next player must pick up the live cards ...
    # unless they can play a 4, 5 or 6."
    six = c(Rank.SIX, Suit.SPADES)
    engine = nine_flip_engine(
        c(Rank.FOUR, Suit.CLUBS),
        flipper_hand=[six, c(Rank.KING, Suit.SPADES)],
        others=[[c(Rank.SEVEN, Suit.SPADES), c(Rank.JACK, Suit.SPADES)]],
    )
    assert engine.state.live_cards == [c(Rank.FOUR, Suit.CLUBS)] and engine.state.current_player == 0
    engine.step(six)
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.current_player == 1
    # A 7 and a J are not a 4, 5 or 6: player 1 must pick up. The engine
    # currently offers both (7 and J go on a regular 6).
    assert engine.get_legal_action_indices() == [ACTION_PICK_UP_LIVE_PILE]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="BUG: a 6 on a 5 on a 4 promoted by a 9s flip does not start the 4 rule either",
)
def test_six_on_five_on_a_promoted_four_keeps_the_four_rule():
    five, six = c(Rank.FIVE, Suit.SPADES), c(Rank.SIX, Suit.DIAMONDS)
    engine = nine_flip_engine(
        c(Rank.FOUR, Suit.CLUBS),
        flipper_hand=[five, c(Rank.KING, Suit.SPADES)],
        others=[[six, c(Rank.JACK, Suit.SPADES)], [c(Rank.SEVEN, Suit.SPADES), c(Rank.QUEEN, Suit.SPADES)]],
    )
    assert engine.state.live_cards == [c(Rank.FOUR, Suit.CLUBS)] and engine.state.current_player == 0
    engine.step(five)
    engine.step(ACTION_END_PLAY_GROUP)
    # Player 1 plays on the card beneath the 5, the 4: only the 6 fits.
    assert engine.get_legal_action_indices() == [six]
    engine.step(six)
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.current_player == 2
    assert engine.get_legal_action_indices() == [ACTION_PICK_UP_LIVE_PILE]


# ------------------------------------------- checked and found correct


@pytest.mark.parametrize("rank", [r for r in Rank if r is not Rank.NINE])
def test_nine_flip_promoted_single_card(rank):
    """Special Flip Rules, 9: the flipper plays on the promoted top card; a 5
    means zero, an 8 skips the flipper, a 10 flips again and the flipper plays."""
    promoted = c(rank, Suit.CLUBS)
    probe = [c(r, Suit.SPADES) for r in Rank if r is not Rank.NINE]
    engine = nine_flip_engine(promoted, flipper_hand=probe, others=[[c(Rank.JACK, Suit.DIAMONDS)]])
    state = engine.state
    assert state.direction == 1
    assert state.pending is None
    if rank is Rank.EIGHT:
        assert state.current_player == 1
        return
    assert state.current_player == 0
    legal = set(engine.get_legal_action_indices())
    if rank is Rank.TEN:
        assert state.live_cards == [] and promoted in state.discard_pile
        assert legal == set(probe)
        return
    target = None if rank is Rank.FIVE else rank
    assert {v for v in legal if v < 52} == {v for v in probe if can_play_on(RANK_BY_ID[v], target)}


@pytest.mark.parametrize("last_card", [False, True], ids=["more-cards", "last-card"])
@pytest.mark.parametrize("rank", list(Rank))
def test_nine_draw_plays_as_the_drawn_card(rank, last_card):
    """9: "Play continues as if the player that played the 9 had played this
    card instead." 3 players, the 9 is played on a 6."""
    nine = c(Rank.NINE, Suit.HEARTS)
    drawn = c(rank, Suit.CLUBS)
    hand = [nine] if last_card else [nine, c(Rank.KING, Suit.SPADES)]
    engine = engine_for(
        [Player(hand=hand), Player(hand=[c(Rank.JACK, Suit.SPADES)]), Player(hand=[c(Rank.QUEEN, Suit.SPADES)])],
        live_cards=[c(Rank.SIX, Suit.DIAMONDS)],
        discard_pile=[drawn],
    )
    engine.step(nine)
    engine.step(ACTION_END_PLAY_GROUP)
    engine.step(ACTION_RESOLVE_NINE_DRAW)
    state = engine.state
    expected_next = {Rank.TWO: 0, Rank.TEN: 0, Rank.NINE: 0, Rank.THREE: 2, Rank.EIGHT: 2}.get(rank, 1)
    expected_dir = -1 if rank is Rank.THREE else 1
    assert state.direction == expected_dir
    if rank is Rank.NINE:
        assert state.pending.kind is PendingKind.NINE_DRAW
        return
    assert (state.pending is not None and state.pending.kind is PendingKind.FOUR_LOOP) == (rank is Rank.FOUR)
    if rank is Rank.TEN:
        assert state.live_cards == []
    else:
        assert state.live_cards[-1] == drawn
    player0 = state.players[0]
    if last_card:
        # Finishing on a 9 whose drawn card would make it your own turn is illegal.
        illegal = expected_next == 0
        assert player0.place == (3 if illegal else 1)
        assert state.current_player == (1 if illegal else expected_next)
    else:
        assert player0.active and state.current_player == expected_next


def test_starter_is_lowest_rank_then_lowest_suit_and_must_play_it():
    # Lowest order: 3, 6, 8, 9, J, Q, K, A, 7, 2, 10, 4, 5; suits H < D < C < S.
    def seat(hand, up):
        return Player(hand=hand, face_up_slots=[[v] for v in up], face_down_slots=[None, None, None])

    six_h, six_c = c(Rank.SIX, Suit.HEARTS), c(Rank.SIX, Suit.CLUBS)
    players = [
        seat([c(Rank.SIX, Suit.DIAMONDS), c(Rank.FIVE), c(Rank.FOUR)], [c(Rank.THREE), c(Rank.ACE), c(Rank.KING)]),
        seat([six_c, c(Rank.KING, Suit.CLUBS), six_h], [c(Rank.THREE, Suit.DIAMONDS), c(Rank.ACE, Suit.CLUBS), c(Rank.QUEEN)]),
        seat([c(Rank.EIGHT), c(Rank.TEN), c(Rank.TWO)], [c(Rank.THREE, Suit.CLUBS), c(Rank.JACK), c(Rank.SEVEN)]),
    ]
    engine = IBFlipEngine(3, seed=0)
    engine.set_state(GameState(players=players, phase=Phase.FIXING_HANDS))
    for i in range(3):
        engine.fix_done(i)
    # Face-up 3s do not count: the lowest hand card is a 6, hearts beats clubs/diamonds.
    assert engine.state.current_player == 1
    assert engine.get_legal_action_indices() == [six_h]
    engine.step(six_h)
    # The starter may add the other 6 to the opening play.
    assert set(engine.get_legal_action_indices()) == {six_c, ACTION_END_PLAY_GROUP}


def test_start_with_three_threes_reverses_direction():
    threes = [c(Rank.THREE, s) for s in (Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS)]
    engine = engine_for(
        [Player(hand=threes + [c(Rank.KING)]), Player(hand=[c(Rank.JACK)]), Player(hand=[c(Rank.QUEEN)])],
        required_start_card_id=threes[0],
    )
    for v in threes:
        engine.step(v)
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.direction == -1 and engine.state.current_player == 2


def test_two_threes_keep_direction():
    threes = [c(Rank.THREE, s) for s in (Suit.HEARTS, Suit.DIAMONDS)]
    engine = engine_for(
        [Player(hand=threes + [c(Rank.KING)]), Player(hand=[c(Rank.JACK)]), Player(hand=[c(Rank.QUEEN)])],
        live_cards=[c(Rank.SEVEN)],
    )
    for v in threes:
        engine.step(v)
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.direction == 1 and engine.state.current_player == 1


def test_reverse_with_two_players_passes_to_the_opponent():
    three = c(Rank.THREE)
    engine = engine_for([Player(hand=[three, c(Rank.KING)]), Player(hand=[c(Rank.JACK)])], live_cards=[c(Rank.TWO)])
    engine.step(three)
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.current_player == 1


@pytest.mark.parametrize("count,expected", [(1, 0), (2, 1), (3, 0)])
def test_skips_with_two_players(count, expected):
    eights = [c(Rank.EIGHT, s) for s in list(Suit)[:count]]
    engine = engine_for([Player(hand=eights + [c(Rank.KING)]), Player(hand=[c(Rank.JACK)])], live_cards=[c(Rank.SIX)])
    for v in eights:
        engine.step(v)
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.current_player == expected


def test_four_in_a_row_across_three_players_flips_on_the_fourth():
    queens = [c(Rank.QUEEN, s) for s in Suit]
    engine = engine_for(
        [Player(hand=[queens[0], c(Rank.KING)]), Player(hand=[queens[1], c(Rank.KING, Suit.DIAMONDS)]),
         Player(hand=[queens[2], queens[3], c(Rank.KING, Suit.CLUBS)])],
        live_cards=[c(Rank.JACK)],
    )
    for v in (queens[0], queens[1]):
        engine.step(v)
        engine.step(ACTION_END_PLAY_GROUP)
    engine.step(queens[2])
    engine.step(queens[3])
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.live_cards == [] and engine.state.current_player == 2


def test_failed_reveal_keeps_card_picks_up_and_passes_turn():
    jack = c(Rank.JACK, Suit.CLUBS)
    engine = engine_for(
        [Player(hand=[c(Rank.KING), c(Rank.QUEEN), c(Rank.JACK)]), Player(hand=[c(Rank.TWO), c(Rank.TWO, Suit.CLUBS), c(Rank.TWO, Suit.SPADES)])],
        live_cards=[c(Rank.SEVEN)],
        draw_pile=[jack, c(Rank.ACE, Suit.CLUBS)],
    )
    assert engine.state.phase is Phase.EARLY_GAME
    assert set(engine.get_legal_action_indices()) == {ACTION_PICK_UP_LIVE_PILE, ACTION_REVEAL_DRAW_PILE_TOP}
    engine.step(ACTION_REVEAL_DRAW_PILE_TOP)
    hand = engine.state.players[0].hand
    assert jack in hand and c(Rank.SEVEN) in hand and len(hand) == 5
    assert engine.state.live_cards == [] and engine.state.current_player == 1


def test_face_down_two_plays_again_from_face_down():
    two = c(Rank.TWO)
    engine = engine_for(
        [Player(face_down_slots=[two, c(Rank.KING), None]), Player(hand=[c(Rank.JACK)])],
        live_cards=[c(Rank.SIX)],
    )
    engine.step(next(a for a, s in FACE_DOWN_ACTIONS.items() if s == 0))
    assert engine.state.current_player == 0
    assert set(engine.get_legal_action_indices()) == {next(a for a, s in FACE_DOWN_ACTIONS.items() if s == 1)}


def _three_ways_engine(rank, how, last):
    """Player 0 of 3 plays ``rank`` on a 2 (everything goes on a 2): from the
    hand, by a successful reveal (early game), or face-down."""
    card = c(rank, Suit.CLUBS)
    others = [Player(hand=[c(Rank.JACK, Suit.SPADES)]), Player(hand=[c(Rank.QUEEN, Suit.SPADES)])]
    kw = dict(live_cards=[c(Rank.TWO, Suit.HEARTS)], discard_pile=[c(Rank.KING, Suit.DIAMONDS)])
    spare = [] if last else [c(Rank.KING, Suit.HEARTS)]
    if how == "hand":
        me = Player(hand=[card], face_down_slots=[None, None, None] if last else [spare[0], None, None])
    elif how == "face_down":
        me = Player(face_down_slots=[card, *(spare or [None]), None])
    else:
        # A hand of three 3s is blocked on any target but 2, 3 or 7; reveal
        # on a target the card goes on. The draw-pile top is the card.
        threes = [c(Rank.THREE, s) for s in (Suit.HEARTS, Suit.DIAMONDS, Suit.SPADES)]
        me = Player(hand=threes)
        target = next(t for t in (Rank.KING, Rank.QUEEN, Rank.JACK, Rank.NINE, Rank.EIGHT, Rank.SIX)
                      if can_play_on(rank, t))
        kw["live_cards"] = [c(Rank.TWO, Suit.HEARTS), c(target, Suit.SPADES)]
        kw["draw_pile"] = [card, c(Rank.ACE, Suit.DIAMONDS), c(Rank.ACE, Suit.SPADES)]
    engine = engine_for([me, *others], **kw)
    if how == "hand":
        engine.step(card)
        engine.step(ACTION_END_PLAY_GROUP)
    elif how == "face_down":
        engine.step(next(a for a, i in FACE_DOWN_ACTIONS.items() if i == 0))
    else:
        engine.step(ACTION_REVEAL_DRAW_PILE_TOP)
    if engine.state.pending is not None and engine.state.pending.kind is PendingKind.NINE_DRAW:
        engine.step(ACTION_RESOLVE_NINE_DRAW)
    return engine


@pytest.mark.parametrize("rank", list(Rank))
def test_special_cards_act_the_same_from_hand_reveal_and_face_down(rank):
    """A card's effect does not depend on how it reached the live cards.
    The reveal is made with a blocked hand of 3s, so a revealed 3 is not
    compared: wherever a 3 fits, the hand of 3s would not be blocked. With 9 the drawn card is the
    discard's only card, a K."""
    results = {}
    for how in ("hand", "face_down") + (() if rank is Rank.THREE else ("reveal",)):
        s = _three_ways_engine(rank, how, last=False).state
        results[how] = (s.current_player, s.direction, None if s.pending is None else s.pending.kind, len(s.live_cards) == 0)
    assert results["hand"] == results["face_down"]
    if rank is not Rank.THREE:
        assert results["reveal"] == results["hand"]


@pytest.mark.parametrize("rank", list(Rank))
def test_last_face_down_card_finish_legality_matches_hand(rank):
    hand = _three_ways_engine(rank, "hand", last=True).state.players[0]
    down = _three_ways_engine(rank, "face_down", last=True).state.players[0]
    assert (hand.finish_status, hand.place) == (down.finish_status, down.place)
    expected_illegal = rank in (Rank.TWO, Rank.TEN)
    assert hand.place == (3 if expected_illegal else 1)


# ---------------------------------------------------------------- fuzz


def _zones(player: Player):
    return (
        list(player.hand),
        [v for slot in player.face_up_slots for v in slot],
        [v for v in player.face_down_slots if v is not None],
    )


def _signature(engine: IBFlipEngine):
    s = engine.state
    return (
        tuple(s.draw_pile), tuple(s.live_cards), tuple(sorted(s.discard_pile)), s.current_player, s.direction,
        None if s.pending is None else s.pending.kind, s.turn_context.open_group_rank,
        tuple(s.turn_context.played_card_ids),
        tuple((tuple(sorted(p.hand)), tuple(tuple(x) for x in p.face_up_slots), tuple(p.face_down_slots), p.active)
              for p in s.players),
    )


def _eff_index(state, pile):
    i = len(pile) - 1
    while i >= 0 and RANK_BY_ID[pile[i]] is Rank.FIVE:
        if pile[i] == state.five_on_zero_card_id:
            return None
        i -= 1
    return i if i >= 0 else None


def _four_rule(state, pile) -> bool:
    """4 rule derived from the pile itself (not the engine's pending flag)."""
    i = _eff_index(state, pile)
    if i is None:
        return False
    top = RANK_BY_ID[pile[i]]
    if top is Rank.FOUR:
        return True
    if top is Rank.SIX:
        j = _eff_index(state, pile[:i])
        return j is not None and (RANK_BY_ID[pile[j]] is Rank.FOUR or _four_rule(state, pile[:i]))
    return False


def _oracle_legal(state, cards):
    """Legal set for a non-group decision from the PDF matrix. Encodes the
    engine's reading of owner question 1 (a 6 on a 6 keeps a 4 chain) and
    reads the ace-as-one, five-on-zero and start-card fields from the state."""
    if state.required_start_card_id is not None:
        return {state.required_start_card_id}
    i = _eff_index(state, state.live_cards)
    target = None if i is None or state.live_cards[i] in state.ace_as_one_card_ids else RANK_BY_ID[state.live_cards[i]]
    if _four_rule(state, state.live_cards):
        return {v for v in cards if RANK_BY_ID[v] in (Rank.FOUR, Rank.FIVE, Rank.SIX)}
    return {v for v in cards if can_play_on(RANK_BY_ID[v], target)}


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_fuzz_turn_play_invariants(n):
    """Checks written without engine helpers:

    * all 52 cards exist exactly once;
    * while the draw-pile lasts, every active player holds at least 3 hand
      cards whenever no play group or 9 draw is open;
    * a face-up card leaves only when the hand was empty before the step, a
      face-down card only when hand and face-up were empty;
    * no player but the one acting loses cards;
    * an open group offers exactly the same-rank cards of the zone (and
      face-up slot) it started from, plus END;
    * a non-group decision offers exactly the cards the PDF matrix allows
      (``_oracle_legal``), from the zone the PDF allows;
    * the policy's compact mapping covers exactly the legal decisions;
    * forced-only play never repeats a position (a true deadlock).
    """
    truncated = 0
    for seed in range(25):
        engine = IBFlipEngine(n, seed=seed)
        engine.record_events = False
        engine.reset()
        engine.auto_fix_hands_randomly()
        rng = random.Random(1000 * n + seed)
        forced_seen: set = set()
        for _ in range(20000):
            s = engine.state
            if s.phase is Phase.GAME_OVER:
                break
            cards = s.draw_pile + s.live_cards + s.discard_pile
            for p in s.players:
                h, fu, fd = _zones(p)
                cards += h + fu + fd
            assert sorted(cards) == list(range(52))
            boundary = s.turn_context.open_group_rank is None and s.pending is None or (
                s.pending is not None and s.pending.kind is PendingKind.FOUR_LOOP
                and s.turn_context.open_group_rank is None)
            if s.draw_pile and boundary:
                for p in s.players:
                    if p.active:
                        assert len(p.hand) >= 3, (n, seed)
            me = s.players[s.current_player]
            hand, fu, fd = _zones(me)
            legal = engine.get_legal_action_indices()
            assert legal
            cards_in_legal = {a for a in legal if a < 52}
            ctx = s.turn_context
            if s.pending is not None and s.pending.kind is PendingKind.NINE_DRAW:
                assert legal == [ACTION_RESOLVE_NINE_DRAW]
            elif ctx.open_group_rank is not None:
                assert ACTION_END_PLAY_GROUP in legal
                if ctx.source == "hand":
                    pool = hand
                elif ctx.source == "face_up" and not hand:
                    pool = list(me.face_up_slots[ctx.face_up_slot])
                else:
                    pool = []
                assert cards_in_legal == {v for v in pool if RANK_BY_ID[v] is ctx.open_group_rank}
                assert set(legal) - cards_in_legal == {ACTION_END_PLAY_GROUP}
            else:
                zone = hand or fu
                assert cards_in_legal <= set(zone)
                if zone:
                    # A promoted 4 never carries the 4 rule in the engine: the
                    # known bug, see the xfail tests above.
                    promoted_four_bug = _four_rule(s, s.live_cards) and s.pending is None
                    if not promoted_four_bug:
                        assert cards_in_legal == _oracle_legal(s, zone), (n, seed)
                if not hand and not fu:
                    assert all(a in FACE_DOWN_ACTIONS for a in legal)
                    assert {FACE_DOWN_ACTIONS[a] for a in legal} == {
                        i for i, v in enumerate(me.face_down_slots) if v is not None}
                if ACTION_REVEAL_DRAW_PILE_TOP in legal:
                    assert s.draw_pile and hand and not cards_in_legal
                if ACTION_PICK_UP_LIVE_PILE in legal:
                    assert s.live_cards and not cards_in_legal
            _, mapping = compact_legal(engine)
            assert sorted(a for acts in mapping.values() for a in acts) == sorted(
                a for a in legal if a != ACTION_RESOLVE_NINE_DRAW)
            if len(legal) == 1:
                sig = _signature(engine)
                assert sig not in forced_seen, f"forced-only cycle {n=} {seed=}"
                forced_seen.add(sig)
            else:
                forced_seen.clear()
            before = [_zones(p) for p in s.players]
            actor = s.current_player
            engine.step(rng.choice(legal))
            after = [_zones(p) for p in engine.state.players]
            for i, (b, a) in enumerate(zip(before, after)):
                if i != actor:
                    assert set(b[0]) <= set(a[0]) and set(b[1]) == set(a[1]) and set(b[2]) == set(a[2])
                    continue
                if set(b[1]) - set(a[1]):
                    assert not b[0], "face-up card played while hand held cards"
                if set(b[2]) - set(a[2]):
                    assert not b[0] and not b[1], "face-down card played too early"
        else:
            truncated += 1
    # A step cap is a truncation, not a rules failure (see rules audit); none
    # of these seeds reach it, so record that.
    assert truncated == 0
