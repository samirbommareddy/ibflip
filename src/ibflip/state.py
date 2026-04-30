from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from ibflip.cards import Rank


class Phase(Enum):
    DEALING = auto()
    FIXING_HANDS = auto()
    EARLY_GAME = auto()
    MIDDLE_GAME = auto()
    END_GAME = auto()
    GAME_OVER = auto()


class PendingKind(Enum):
    FOUR_LOOP = auto()
    NINE_DRAW = auto()


class FinishStatus(Enum):
    LEGAL_WIN = auto()
    ILLEGAL_LOSS = auto()


@dataclass
class PendingEffect:
    kind: PendingKind
    player_index: int


@dataclass
class TurnContext:
    open_group_rank: Rank | None = None
    played_card_ids: list[int] = field(default_factory=list)
    source: str | None = None


@dataclass
class Player:
    hand: list[int] = field(default_factory=list)
    face_up_slots: list[list[int]] = field(default_factory=list)
    face_down_slots: list[int | None] = field(default_factory=list)
    active: bool = True
    finish_status: FinishStatus | None = None
    fixing_done: bool = False

    def has_any_cards(self) -> bool:
        return bool(self.hand or any(self.face_up_slots) or any(card is not None for card in self.face_down_slots))


@dataclass
class GameState:
    players: list[Player]
    draw_pile: list[int] = field(default_factory=list)
    live_cards: list[int] = field(default_factory=list)
    discard_pile: list[int] = field(default_factory=list)
    phase: Phase = Phase.DEALING
    current_player: int = 0
    direction: int = 1
    pending: PendingEffect | None = None
    turn_context: TurnContext = field(default_factory=TurnContext)
    winner: int | None = None
    loser: int | None = None
    required_start_card_id: int | None = None
    fix_selected_card_id: int | None = None
    ace_as_one_card_ids: list[int] = field(default_factory=list)
