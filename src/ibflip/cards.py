from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Suit(IntEnum):
    HEARTS = 0
    DIAMONDS = 1
    CLUBS = 2
    SPADES = 3


class Rank(IntEnum):
    THREE = 0
    FOUR = 1
    FIVE = 2
    SIX = 3
    SEVEN = 4
    EIGHT = 5
    NINE = 6
    TEN = 7
    JACK = 8
    QUEEN = 9
    KING = 10
    ACE = 11
    TWO = 12


RANKS: tuple[Rank, ...] = tuple(Rank)
SUITS: tuple[Suit, ...] = tuple(Suit)

STARTING_LOWEST_ORDER: dict[Rank, int] = {
    Rank.THREE: 0,
    Rank.SIX: 1,
    Rank.EIGHT: 2,
    Rank.NINE: 3,
    Rank.JACK: 4,
    Rank.QUEEN: 5,
    Rank.KING: 6,
    Rank.ACE: 7,
    Rank.SEVEN: 8,
    Rank.TWO: 9,
    Rank.TEN: 10,
    Rank.FOUR: 11,
    Rank.FIVE: 12,
}


@dataclass(frozen=True, order=True)
class Card:
    card_id: int
    rank: Rank
    suit: Suit


def card_id(rank: Rank, suit: Suit) -> int:
    return int(rank) * len(SUITS) + int(suit)


def card_from_id(value: int) -> Card:
    if not 0 <= value < 52:
        raise ValueError(f"card id must be in [0, 51], got {value}")
    return _CARD_CACHE[value]


def full_deck() -> list[Card]:
    return list(_CARD_CACHE)


_CARD_CACHE = tuple(Card(value, Rank(value // len(SUITS)), Suit(value % len(SUITS))) for value in range(52))
RANK_BY_ID = tuple(card.rank for card in _CARD_CACHE)
SUIT_BY_ID = tuple(card.suit for card in _CARD_CACHE)
RANK_INDEX_BY_ID = tuple(value // len(SUITS) for value in range(52))
SUIT_INDEX_BY_ID = tuple(value % len(SUITS) for value in range(52))
