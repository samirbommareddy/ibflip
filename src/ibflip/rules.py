from __future__ import annotations

from ibflip.cards import Rank


PLAYABLE_ON: dict[Rank, frozenset[Rank]] = {
    Rank.ACE: frozenset(
        {Rank.ACE, Rank.TWO, Rank.THREE, Rank.SIX, Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.JACK, Rank.QUEEN, Rank.KING}
    ),
    Rank.TWO: frozenset(
        {Rank.ACE, Rank.TWO, Rank.THREE, Rank.SIX, Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.JACK, Rank.QUEEN, Rank.KING}
    ),
    Rank.THREE: frozenset({Rank.TWO, Rank.THREE, Rank.SEVEN}),
    Rank.FOUR: frozenset(
        {Rank.ACE, Rank.TWO, Rank.THREE, Rank.FOUR, Rank.SIX, Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.JACK, Rank.QUEEN, Rank.KING}
    ),
    Rank.FIVE: frozenset(
        {Rank.ACE, Rank.TWO, Rank.THREE, Rank.FOUR, Rank.SIX, Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.JACK, Rank.QUEEN, Rank.KING}
    ),
    Rank.SIX: frozenset({Rank.TWO, Rank.THREE, Rank.FOUR, Rank.SIX, Rank.SEVEN}),
    Rank.SEVEN: frozenset(
        {Rank.ACE, Rank.TWO, Rank.THREE, Rank.SIX, Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.JACK, Rank.QUEEN, Rank.KING}
    ),
    Rank.EIGHT: frozenset({Rank.TWO, Rank.THREE, Rank.SIX, Rank.EIGHT}),
    Rank.NINE: frozenset({Rank.TWO, Rank.THREE, Rank.SIX, Rank.EIGHT, Rank.NINE}),
    Rank.TEN: frozenset({Rank.ACE, Rank.TWO, Rank.THREE, Rank.SIX, Rank.EIGHT, Rank.NINE, Rank.JACK, Rank.QUEEN, Rank.KING}),
    Rank.JACK: frozenset({Rank.TWO, Rank.THREE, Rank.SIX, Rank.EIGHT, Rank.NINE, Rank.JACK}),
    Rank.QUEEN: frozenset({Rank.TWO, Rank.THREE, Rank.SIX, Rank.EIGHT, Rank.NINE, Rank.JACK, Rank.QUEEN}),
    Rank.KING: frozenset({Rank.TWO, Rank.THREE, Rank.SIX, Rank.EIGHT, Rank.NINE, Rank.JACK, Rank.QUEEN, Rank.KING}),
}


FOUR_LOOP_RANKS = frozenset({Rank.FOUR, Rank.FIVE, Rank.SIX})
FOUR_LOOP_RANK_INDEXES = frozenset({int(Rank.FOUR), int(Rank.FIVE), int(Rank.SIX)})
FOUR_LOOP_RANK_MASK = sum(1 << rank for rank in FOUR_LOOP_RANK_INDEXES)
PLAYABLE_ON_MASKS = tuple(
    sum(1 << int(target_rank) for target_rank in PLAYABLE_ON[played_rank])
    for played_rank in Rank
)


def can_play_on(played_rank: Rank, target_rank: Rank | None) -> bool:
    if target_rank is None:
        return True
    return target_rank in PLAYABLE_ON[played_rank]


def can_play_on_index(played_rank: int, target_rank: int | None) -> bool:
    if target_rank is None:
        return True
    return bool(PLAYABLE_ON_MASKS[played_rank] & (1 << target_rank))
