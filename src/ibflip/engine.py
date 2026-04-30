from __future__ import annotations

from copy import deepcopy
import random

from ibflip.actions import (
    ACTION_END_PLAY_GROUP,
    ACTION_FACE_DOWN_SLOT_0,
    ACTION_FIX_DONE,
    ACTION_FIX_KEEP_UNDERSIZED_HAND,
    ACTION_PICK_UP_LIVE_PILE,
    ACTION_RESOLVE_NINE_DRAW,
    ACTION_REVEAL_DRAW_PILE_TOP,
    ACTION_SPACE_SIZE,
    FACE_DOWN_ACTIONS,
    FIX_STACK_ACTIONS,
    FIX_SWAP_ACTIONS,
    FIX_TAKE_FROM_STACK_ACTIONS,
)
from ibflip.cards import (
    Card,
    RANK_BY_ID,
    RANK_INDEX_BY_ID,
    SUIT_BY_ID,
    Rank,
    STARTING_LOWEST_ORDER,
    card_from_id,
    full_deck,
)
from ibflip.rules import FOUR_LOOP_RANK_MASK, can_play_on_index
from ibflip.state import FinishStatus, GameState, PendingEffect, PendingKind, Phase, Player, TurnContext


class IllegalActionError(ValueError):
    pass


class IBFlipEngine:
    action_space_size = ACTION_SPACE_SIZE

    def __init__(self, num_players: int, seed: int | None = None) -> None:
        if num_players < 2:
            raise ValueError("IB-Flip requires at least two players")
        self.num_players = num_players
        self.rng = random.Random(seed)
        self.state = GameState(players=[Player() for _ in range(num_players)])

    def card(self, value: int) -> Card:
        return card_from_id(value)

    def rank(self, value: int) -> Rank:
        return RANK_BY_ID[value]

    def rank_index(self, value: int) -> int:
        return RANK_INDEX_BY_ID[value]

    def reset(self) -> GameState:
        deck = [card.card_id for card in full_deck()]
        self.rng.shuffle(deck)
        players = [Player() for _ in range(self.num_players)]

        for _ in range(3):
            for player in players:
                player.face_down_slots.append(deck.pop(0))
        for _ in range(3):
            for player in players:
                player.face_up_slots.append([deck.pop(0)])
        for _ in range(3):
            for player in players:
                player.hand.append(deck.pop(0))

        self.state = GameState(players=players, draw_pile=deck, phase=Phase.FIXING_HANDS, current_player=0)
        return self.state

    def clone(self) -> IBFlipEngine:
        clone = IBFlipEngine(self.num_players)
        clone.rng.setstate(self.rng.getstate())
        clone.state = deepcopy(self.state)
        return clone

    def set_state(self, state: GameState) -> None:
        self.num_players = len(state.players)
        self.state = deepcopy(state)
        self._update_phase()

    def get_legal_actions(self) -> list[bool]:
        mask = [False] * self.action_space_size
        for action in self.get_legal_action_indices():
            mask[action] = True
        return mask

    def get_legal_action_indices(self) -> list[int]:
        state = self.state
        if state.phase is Phase.GAME_OVER:
            return []

        if state.pending and state.pending.kind is PendingKind.NINE_DRAW:
            return [ACTION_RESOLVE_NINE_DRAW]

        if state.phase is Phase.FIXING_HANDS:
            return self._fixing_legal_action_indices()

        if state.turn_context.open_group_rank is not None:
            legal = [
                candidate
                for candidate in self._playable_source_card_ids()
                if RANK_INDEX_BY_ID[candidate] == int(state.turn_context.open_group_rank)
            ]
            if state.turn_context.played_card_ids:
                legal.append(ACTION_END_PLAY_GROUP)
            return legal

        source = self._active_source()
        if source == "face_down":
            player = self._current_player()
            return [
                action
                for action, slot_index in FACE_DOWN_ACTIONS.items()
                if slot_index < len(player.face_down_slots) and player.face_down_slots[slot_index] is not None
            ]

        playable = []
        target_rank = self._target_rank_index()
        required_start = state.required_start_card_id
        is_start_turn = required_start is not None and not state.turn_context.played_card_ids
        is_four_loop = state.pending is not None and state.pending.kind is PendingKind.FOUR_LOOP
        for candidate in self._playable_source_card_ids_for_source(source):
            if self._is_legal_card_play_with_context(candidate, target_rank, required_start, is_start_turn, is_four_loop):
                playable.append(candidate)

        if self._can_reveal_draw_pile(playable):
            playable.append(ACTION_REVEAL_DRAW_PILE_TOP)

        if self._can_pick_up(playable):
            playable.append(ACTION_PICK_UP_LIVE_PILE)

        return playable

    def step(self, action: int, *, validate: bool = True) -> GameState:
        if action < 0 or action >= self.action_space_size:
            raise IllegalActionError(f"action {action} outside action space")
        if validate and not self.get_legal_actions()[action]:
            raise IllegalActionError(f"illegal action {action}")

        if self.state.pending and self.state.pending.kind is PendingKind.NINE_DRAW:
            self._resolve_nine_draw()
        elif self.state.phase is Phase.FIXING_HANDS:
            self._step_fixing(action)
        elif self.state.turn_context.open_group_rank is not None:
            if action == ACTION_END_PLAY_GROUP:
                self._commit_open_group()
            else:
                self._play_card(action)
        elif action == ACTION_PICK_UP_LIVE_PILE:
            self._pick_up_live_pile(self.state.current_player)
            self._advance_to_next_player()
        elif action == ACTION_REVEAL_DRAW_PILE_TOP:
            self._reveal_draw_pile_top()
        elif action in FACE_DOWN_ACTIONS:
            self._attempt_face_down(FACE_DOWN_ACTIONS[action])
        else:
            self._play_card(action)

        self._update_phase()
        return self.state

    def auto_fix_hands_randomly(self) -> None:
        if self.state.phase is not Phase.FIXING_HANDS:
            return
        for player in self.state.players:
            player.fixing_done = True
        self.state.fix_selected_card_id = None
        self._start_game_after_fixing()

    def _current_player(self) -> Player:
        return self.state.players[self.state.current_player]

    def _fixing_legal_actions(self, mask: list[bool]) -> list[bool]:
        for action in self._fixing_legal_action_indices():
            mask[action] = True
        return mask

    def _fixing_legal_action_indices(self) -> list[int]:
        player = self._current_player()
        selected = self.state.fix_selected_card_id
        legal: list[int] = []
        if selected is None:
            legal.extend(player.hand)
            legal.append(ACTION_FIX_DONE)
            if len(player.hand) < 3 and not self.state.draw_pile:
                for action, slot_index in FIX_TAKE_FROM_STACK_ACTIONS.items():
                    if slot_index < len(player.face_up_slots) and len(player.face_up_slots[slot_index]) > 1:
                        legal.append(action)
                legal.append(ACTION_FIX_KEEP_UNDERSIZED_HAND)
            return legal

        for action, slot_index in FIX_SWAP_ACTIONS.items():
            if slot_index < len(player.face_up_slots) and player.face_up_slots[slot_index]:
                legal.append(action)
        selected_rank = self.rank(selected)
        for action, slot_index in FIX_STACK_ACTIONS.items():
            if slot_index < len(player.face_up_slots):
                slot = player.face_up_slots[slot_index]
                if slot and self.rank(slot[-1]) is selected_rank:
                    legal.append(action)
        return legal

    def _step_fixing(self, action: int) -> None:
        player = self._current_player()
        if 0 <= action < 52:
            self.state.fix_selected_card_id = action
            return
        if action in FIX_SWAP_ACTIONS:
            self._fix_swap(player, FIX_SWAP_ACTIONS[action])
            return
        if action in FIX_STACK_ACTIONS:
            self._fix_stack(player, FIX_STACK_ACTIONS[action])
            return
        if action in FIX_TAKE_FROM_STACK_ACTIONS:
            self._fix_take_from_stack(player, FIX_TAKE_FROM_STACK_ACTIONS[action])
            return
        if action == ACTION_FIX_KEEP_UNDERSIZED_HAND:
            return
        if action == ACTION_FIX_DONE:
            player.fixing_done = True
            self.state.fix_selected_card_id = None
            if all(next_player.fixing_done for next_player in self.state.players):
                self._start_game_after_fixing()
            else:
                self._advance_to_next_player()

    def _fix_swap(self, player: Player, slot_index: int) -> None:
        selected = self.state.fix_selected_card_id
        if selected is None:
            raise IllegalActionError("no selected card")
        player.hand.remove(selected)
        slot_card = player.face_up_slots[slot_index].pop()
        player.hand.append(slot_card)
        player.face_up_slots[slot_index].append(selected)
        self.state.fix_selected_card_id = None

    def _fix_stack(self, player: Player, slot_index: int) -> None:
        selected = self.state.fix_selected_card_id
        if selected is None:
            raise IllegalActionError("no selected card")
        player.hand.remove(selected)
        player.face_up_slots[slot_index].append(selected)
        self.state.fix_selected_card_id = None
        self._draw_to_three(player)

    def _fix_take_from_stack(self, player: Player, slot_index: int) -> None:
        player.hand.append(player.face_up_slots[slot_index].pop())

    def _start_game_after_fixing(self) -> None:
        player_index, start_card = self._find_starting_player_and_card()
        self.state.current_player = player_index
        self.state.required_start_card_id = start_card
        self.state.phase = Phase.EARLY_GAME if self.state.draw_pile else Phase.MIDDLE_GAME

    def _find_starting_player_and_card(self) -> tuple[int, int]:
        best: tuple[int, int, int, int] | None = None
        for player_index, player in enumerate(self.state.players):
            for value in player.hand:
                score = (STARTING_LOWEST_ORDER[self.rank(value)], int(SUIT_BY_ID[value]), player_index, value)
                if best is None or score < best:
                    best = score
        if best is None:
            return 0, -1
        return best[2], best[3]

    def _active_source(self) -> str | None:
        player = self._current_player()
        if player.hand:
            return "hand"
        if any(player.face_up_slots):
            return "face_up"
        if any(card is not None for card in player.face_down_slots):
            return "face_down"
        return None

    def _playable_source_card_ids(self) -> list[int]:
        return self._playable_source_card_ids_for_source(self._active_source())

    def _playable_source_card_ids_for_source(self, source: str | None) -> list[int]:
        player = self._current_player()
        if source == "hand":
            return player.hand
        if source == "face_up":
            return [card for slot in player.face_up_slots for card in slot]
        return []

    def _is_legal_card_play(self, value: int) -> bool:
        state = self.state
        return self._is_legal_card_play_with_context(
            value,
            self._target_rank_index(),
            state.required_start_card_id,
            state.required_start_card_id is not None and not state.turn_context.played_card_ids,
            state.pending is not None and state.pending.kind is PendingKind.FOUR_LOOP,
        )

    def _is_legal_card_play_with_context(
        self,
        value: int,
        target_rank: int | None,
        required_start: int | None,
        is_start_turn: bool,
        is_four_loop: bool,
    ) -> bool:
        if is_start_turn:
            return value == required_start
        if is_four_loop:
            return bool(FOUR_LOOP_RANK_MASK & (1 << RANK_INDEX_BY_ID[value]))
        return can_play_on_index(RANK_INDEX_BY_ID[value], target_rank)

    def _target_rank(self) -> Rank | None:
        target = self._target_rank_index()
        return None if target is None else Rank(target)

    def _target_rank_index(self) -> int | None:
        state = self.state
        if not state.live_cards:
            return None
        top = state.live_cards[-1]
        if top in state.ace_as_one_card_ids:
            return None
        if self.rank(top) is Rank.FIVE:
            if len(state.live_cards) == 1:
                return None
            beneath = state.live_cards[-2]
            if beneath in state.ace_as_one_card_ids:
                return None
            return RANK_INDEX_BY_ID[beneath]
        return RANK_INDEX_BY_ID[top]

    def _can_reveal_draw_pile(self, playable: list[int]) -> bool:
        return self.state.phase is Phase.EARLY_GAME and bool(self.state.draw_pile) and not playable and self._active_source() == "hand"

    def _can_pick_up(self, playable: list[int]) -> bool:
        if not self.state.live_cards:
            return False
        if self.state.pending and self.state.pending.kind is PendingKind.FOUR_LOOP:
            return True
        return not playable and self.state.phase in {Phase.MIDDLE_GAME, Phase.END_GAME}

    def _play_card(self, value: int) -> None:
        player = self._current_player()
        source = self._active_source()
        self._remove_card_from_source(player, value, source)
        self.state.live_cards.append(value)

        context = self.state.turn_context
        if context.open_group_rank is None:
            context.open_group_rank = self.rank(value)
            context.source = source
        context.played_card_ids.append(value)

        if self.rank(value) is Rank.ACE and self._rank_beneath_top() is Rank.SEVEN:
            if value not in self.state.ace_as_one_card_ids:
                self.state.ace_as_one_card_ids.append(value)

    def _remove_card_from_source(self, player: Player, value: int, source: str | None) -> None:
        if source == "hand":
            player.hand.remove(value)
            return
        if source == "face_up":
            for slot in player.face_up_slots:
                if value in slot:
                    slot.remove(value)
                    return
        raise IllegalActionError(f"card {value} is not playable from source {source}")

    def _rank_beneath_top(self) -> Rank | None:
        if len(self.state.live_cards) < 2:
            return None
        return self.rank(self.state.live_cards[-2])

    def _commit_open_group(self) -> None:
        context = self.state.turn_context
        flip_rank = self._four_consecutive_rank()
        if flip_rank is not None:
            self._resolve_committed_cards(context.open_group_rank, len(context.played_card_ids), list(context.played_card_ids))
            return
        if context.open_group_rank is Rank.NINE:
            self.state.pending = PendingEffect(PendingKind.NINE_DRAW, self.state.current_player)
            return
        played = list(context.played_card_ids)
        self._resolve_committed_cards(context.open_group_rank, len(played), played)

    def _resolve_nine_draw(self) -> None:
        if self.state.discard_pile:
            index = self.rng.randrange(len(self.state.discard_pile))
            drawn = self.state.discard_pile.pop(index)
            self.state.live_cards.append(drawn)
            self.state.turn_context.played_card_ids.append(drawn)
            self.state.pending = None
            self._resolve_or_defer_for_latest_card(drawn)
        else:
            self.state.pending = None
            self._resolve_committed_cards(Rank.NINE, 1, list(self.state.turn_context.played_card_ids))

    def _resolve_or_defer_for_latest_card(self, value: int) -> None:
        rank = self.rank(value)
        if self._four_consecutive_rank() is not None:
            self._resolve_committed_cards(rank, 1, list(self.state.turn_context.played_card_ids))
            return
        if rank is Rank.NINE:
            self.state.pending = PendingEffect(PendingKind.NINE_DRAW, self.state.current_player)
            return
        self._resolve_committed_cards(rank, 1, list(self.state.turn_context.played_card_ids))

    def _resolve_committed_cards(self, effect_rank: Rank | None, effect_count: int, played_cards: list[int]) -> None:
        player_index = self.state.current_player
        self.state.required_start_card_id = None

        if effect_rank is Rank.TEN:
            self._clear_turn_context()
            self._flip_live_cards(player_index, Rank.TEN, play_again=True)
            self._draw_to_three_if_early(self.state.players[player_index])
            self._finish_or_continue(player_index, player_index)
            return

        flip_rank = self._four_consecutive_rank()
        if flip_rank is not None:
            self._clear_turn_context()
            self._flip_live_cards(player_index, flip_rank, play_again=True)
            self._draw_to_three_if_early(self.state.players[player_index])
            if self.state.phase is not Phase.GAME_OVER and flip_rank not in {Rank.FOUR, Rank.NINE}:
                self._finish_or_continue(player_index, player_index)
            return

        next_player = self._next_player_index(player_index)
        if effect_rank is Rank.TWO:
            next_player = player_index
        elif effect_rank is Rank.THREE and effect_count % 2 == 1:
            self.state.direction *= -1
            next_player = self._next_player_index(player_index)
        elif effect_rank is Rank.FOUR:
            self.state.pending = PendingEffect(PendingKind.FOUR_LOOP, player_index)
        elif effect_rank is Rank.EIGHT:
            next_player = self._advance_index(player_index, effect_count + 1)

        self._clear_turn_context()
        self._draw_to_three_if_early(self.state.players[player_index])
        self._finish_or_continue(player_index, next_player)

    def _four_consecutive_rank(self) -> Rank | None:
        if len(self.state.live_cards) < 4:
            return None
        last_four = self.state.live_cards[-4:]
        ranks = [self.rank(value) for value in last_four]
        if all(rank is ranks[0] for rank in ranks):
            return ranks[0]
        return None

    def _flip_live_cards(self, player_index: int, flip_rank: Rank, play_again: bool) -> None:
        self.state.pending = None
        old_live = list(self.state.live_cards)
        pre_existing_discard = list(self.state.discard_pile)

        if flip_rank is Rank.THREE:
            threes = [card for card in old_live if self.rank(card) is Rank.THREE]
            non_threes = [card for card in old_live if self.rank(card) is not Rank.THREE]
            for other_index in self._other_active_players(player_index):
                if threes:
                    self.state.players[other_index].hand.append(threes.pop(0))
            self.state.discard_pile.extend(non_threes + threes)
            self.state.live_cards = []
            self.state.current_player = player_index
            return

        if flip_rank is Rank.NINE and pre_existing_discard:
            new_live = pre_existing_discard
            self.rng.shuffle(new_live)
            self.state.live_cards = new_live
            self.state.discard_pile = old_live
            self.state.current_player = player_index
            self._resolve_promoted_live_top_after_nine_flip(player_index)
            return

        self.state.discard_pile.extend(old_live)
        self.state.live_cards = []

        if flip_rank is Rank.FOUR:
            self._take_three_from_discard(player_index)
            self.state.pending = None
            self.state.current_player = self._next_player_index(player_index)
            return

        if flip_rank is Rank.EIGHT:
            self._mark_illegal_loss(player_index)
            return

        self.state.current_player = player_index if play_again else self._next_player_index(player_index)

    def _resolve_promoted_live_top_after_nine_flip(self, player_index: int) -> None:
        if not self.state.live_cards:
            return
        top_rank = self.rank(self.state.live_cards[-1])
        if top_rank is Rank.EIGHT:
            self.state.current_player = self._next_player_index(player_index)
        elif top_rank is Rank.TEN:
            self._flip_live_cards(player_index, Rank.TEN, play_again=True)

    def _take_three_from_discard(self, player_index: int) -> None:
        for value in list(self.state.discard_pile):
            if self.rank(value) is Rank.THREE:
                self.state.discard_pile.remove(value)
                self.state.players[player_index].hand.append(value)
                return

    def _other_active_players(self, player_index: int) -> list[int]:
        return [index for index, player in enumerate(self.state.players) if index != player_index and player.active]

    def _clear_turn_context(self) -> None:
        self.state.turn_context = TurnContext()
        if self.state.pending and self.state.pending.kind is PendingKind.FOUR_LOOP and not self.state.live_cards:
            self.state.pending = None

    def _draw_to_three_if_early(self, player: Player) -> None:
        if self.state.phase is Phase.EARLY_GAME:
            self._draw_to_three(player)

    def _draw_to_three(self, player: Player) -> None:
        missing = max(0, 3 - len(player.hand))
        for _ in range(min(missing, len(self.state.draw_pile))):
            player.hand.append(self.state.draw_pile.pop(0))

    def _finish_or_continue(self, player_index: int, next_player: int) -> None:
        player = self.state.players[player_index]
        if not player.has_any_cards():
            if next_player == player_index:
                self._mark_illegal_loss(player_index)
                return
            player.active = False
            player.finish_status = FinishStatus.LEGAL_WIN
            self.state.winner = player_index
            self.state.phase = Phase.GAME_OVER
            return
        self.state.current_player = next_player

    def _mark_illegal_loss(self, player_index: int) -> None:
        player = self.state.players[player_index]
        player.active = False
        player.finish_status = FinishStatus.ILLEGAL_LOSS
        self.state.loser = player_index
        self.state.phase = Phase.GAME_OVER

    def _pick_up_live_pile(self, player_index: int) -> None:
        self.state.players[player_index].hand.extend(self.state.live_cards)
        self.state.live_cards = []
        self.state.pending = None
        self._clear_turn_context()

    def _advance_to_next_player(self) -> None:
        self.state.current_player = self._next_player_index(self.state.current_player)

    def _next_player_index(self, start: int) -> int:
        return self._advance_index(start, 1)

    def _advance_index(self, start: int, steps: int) -> int:
        active_indices = [index for index, player in enumerate(self.state.players) if player.active]
        if not active_indices:
            return start
        if start not in active_indices:
            return active_indices[0]
        position = active_indices.index(start)
        offset = steps if self.state.direction == 1 else -steps
        return active_indices[(position + offset) % len(active_indices)]

    def _reveal_draw_pile_top(self) -> None:
        revealed = self.state.draw_pile.pop(0)
        if can_play_on_index(RANK_INDEX_BY_ID[revealed], self._target_rank_index()):
            self.state.live_cards.append(revealed)
            self.state.turn_context = TurnContext(open_group_rank=self.rank(revealed), played_card_ids=[revealed], source="draw")
            self._resolve_or_defer_for_latest_card(revealed)
        else:
            self.state.players[self.state.current_player].hand.append(revealed)
            self._pick_up_live_pile(self.state.current_player)
            self._advance_to_next_player()

    def _attempt_face_down(self, slot_index: int) -> None:
        player_index = self.state.current_player
        player = self.state.players[player_index]
        value = player.face_down_slots[slot_index]
        if value is None:
            raise IllegalActionError("empty face-down slot")
        player.face_down_slots[slot_index] = None
        if self._is_legal_card_play(value):
            self.state.live_cards.append(value)
            self.state.turn_context = TurnContext(open_group_rank=self.rank(value), played_card_ids=[value], source="face_down")
            self._resolve_or_defer_for_latest_card(value)
        else:
            player.hand.append(value)
            self._pick_up_live_pile(player_index)
            self._advance_to_next_player()

    def _update_phase(self) -> None:
        if self.state.phase in {Phase.DEALING, Phase.FIXING_HANDS, Phase.GAME_OVER}:
            return
        if self.state.winner is not None or self.state.loser is not None:
            self.state.phase = Phase.GAME_OVER
            return
        if self._active_source() == "face_down":
            self.state.phase = Phase.END_GAME
        elif self.state.draw_pile:
            self.state.phase = Phase.EARLY_GAME
        else:
            self.state.phase = Phase.MIDDLE_GAME
