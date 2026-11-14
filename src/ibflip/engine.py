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


_FINISH_NAMES = {
    FinishStatus.LEGAL_WIN: "legal",
    FinishStatus.ILLEGAL_LOSS: "illegal",
    FinishStatus.EIGHTS_LOSS: "eights",
}


_PLAY_PHASES = (Phase.EARLY_GAME, Phase.MIDDLE_GAME, Phase.END_GAME)


class IllegalActionError(ValueError):
    pass


EMPTY_SLOT_MESSAGE = "Fill every face-up slot before you are ready"


def face_up_slots_complete(player: Player) -> bool:
    """True when each of the player's face-up slots holds at least one card."""
    return all(player.face_up_slots)


class IBFlipEngine:
    action_space_size = ACTION_SPACE_SIZE

    def __init__(self, num_players: int, seed: int | None = None) -> None:
        if not 2 <= num_players <= 5:
            raise ValueError("IB-Flip requires two to five players")
        self.num_players = num_players
        self.rng = random.Random(seed)
        self.state = GameState(players=[Player() for _ in range(num_players)])
        # Public, append-only stream of what happened (for UIs / replays).
        # Consumers may clear it at any time.
        self.events: list[dict] = []
        self.record_events = True

    def _emit(self, kind: str, **data) -> None:
        if self.record_events:
            data["kind"] = kind
            self.events.append(data)

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
        self.events = []
        self._emit("deal")
        return self.state

    def clone(self) -> IBFlipEngine:
        clone = IBFlipEngine(self.num_players)
        clone.rng.setstate(self.rng.getstate())
        clone.state = deepcopy(self.state)
        clone.record_events = self.record_events
        return clone

    def set_state(self, state: GameState) -> None:
        self.num_players = len(state.players)
        self.state = deepcopy(state)
        self._update_phase()
        self._sync_four_loop_flag()

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
            candidates = self._playable_source_card_ids() if self._active_source() == state.turn_context.source else []
            slot_index = state.turn_context.face_up_slot
            if slot_index is not None and self._active_source() == "face_up":
                candidates = self._current_player().face_up_slots[slot_index]
            legal = [
                candidate
                for candidate in candidates
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
        start_cards = self._start_card_options()
        is_four_loop = self._four_rule_active()
        for candidate in self._playable_source_card_ids_for_source(source):
            if self._is_legal_card_play_with_context(candidate, target_rank, start_cards, is_four_loop):
                playable.append(candidate)

        can_reveal = self._can_reveal_draw_pile(playable)
        can_pick_up = self._can_pick_up(playable)
        if can_reveal:
            playable.append(ACTION_REVEAL_DRAW_PILE_TOP)
        if can_pick_up:
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
            # Pickup is only legal with nothing playable on this target.
            self._record_lacks(self.state.current_player)
            self._pick_up_live_pile(self.state.current_player)
            self._advance_to_next_player()
        elif action == ACTION_REVEAL_DRAW_PILE_TOP:
            self._reveal_draw_pile_top()
        elif action in FACE_DOWN_ACTIONS:
            self._attempt_face_down(FACE_DOWN_ACTIONS[action])
        else:
            self._play_card(action)

        self._update_phase()
        self._sync_four_loop_flag()
        return self.state

    def auto_fix_hands_randomly(self) -> None:
        if self.state.phase is not Phase.FIXING_HANDS:
            return
        for index, player in enumerate(self.state.players):
            if not player.fixing_done and not face_up_slots_complete(player):
                self.fix_fill_empty_slots(index)
            player.fixing_done = True
        self.state.fix_selected_card_id = None
        self._start_game_after_fixing()

    # ------------------------------------------------------------------
    # Simultaneous fixing API (used by multiplayer front-ends, where every
    # player fixes their own hand at the same time).
    # ------------------------------------------------------------------
    def fix_swap_card(self, player_index: int, card: int, slot_index: int) -> None:
        """Trade a hand card one-for-one with a face-up card.

        Onto a slot emptied by combining, the hand card is simply placed and
        the hand is refilled to three from the draw-pile, as after stacking.
        """
        player = self._fixing_player(player_index)
        if card not in player.hand or not (0 <= slot_index < len(player.face_up_slots)):
            raise IllegalActionError("illegal swap")
        slot = player.face_up_slots[slot_index]
        if not slot:
            player.hand.remove(card)
            if card in player.known_hand:
                player.known_hand.remove(card)
            slot.append(card)
            self._draw_to_three(player)
            return
        if len(slot) > 1 and self.rank(slot[-1]) is not self.rank(card):
            raise IllegalActionError("swap would mix ranks in a stack")
        player.hand.remove(card)
        taken = slot.pop()
        player.hand.append(taken)
        player.known_hand.append(taken)
        if card in player.known_hand:
            player.known_hand.remove(card)
        slot.append(card)

    def fix_stack_card(self, player_index: int, card: int, slot_index: int) -> None:
        player = self._fixing_player(player_index)
        if not (0 <= slot_index < len(player.face_up_slots)):
            raise IllegalActionError("illegal stack")
        slot = player.face_up_slots[slot_index]
        from_hand = card in player.hand
        source = player.hand if from_hand else next(
            (other for i, other in enumerate(player.face_up_slots) if i != slot_index and card in other), None
        )
        if source is None:
            raise IllegalActionError("card is not in hand or another face-up slot")
        if not slot:
            # Refill a slot emptied by combining with a card split off a
            # face-up stack; that must not empty yet another slot. Hand cards
            # go into an empty slot through ``fix_swap_card``.
            if from_hand or len(source) < 2:
                raise IllegalActionError("can only move a card from a stack into an empty slot")
        elif self.rank(slot[-1]) is not self.rank(card):
            raise IllegalActionError("can only stack matching ranks")
        source.remove(card)
        if card in player.known_hand:
            player.known_hand.remove(card)
        slot.append(card)
        if from_hand:
            self._draw_to_three(player)

    def fix_unstack_card(self, player_index: int, slot_index: int) -> None:
        player = self._fixing_player(player_index)
        if not (0 <= slot_index < len(player.face_up_slots)) or len(player.face_up_slots[slot_index]) < 2:
            raise IllegalActionError("nothing to take back")
        if len(player.hand) >= 3:
            raise IllegalActionError("hand already full")
        card = player.face_up_slots[slot_index].pop()
        player.hand.append(card)
        player.known_hand.append(card)

    def fix_done(self, player_index: int) -> bool:
        """Mark a player as ready. Returns True when the game has started.

        Every face-up slot must hold at least one card: combining matching
        face-up cards may empty a slot, but it must be refilled first.
        """
        player = self._fixing_player(player_index)
        if not face_up_slots_complete(player):
            raise IllegalActionError(EMPTY_SLOT_MESSAGE)
        player.fixing_done = True
        if all(p.fixing_done for p in self.state.players):
            self.state.fix_selected_card_id = None
            self._start_game_after_fixing()
            self._update_phase()
            return True
        return False

    def fix_fill_empty_slots(self, player_index: int) -> None:
        """Refill any empty face-up slot so the player can be marked ready.

        Used by automatic readiness (timeouts, disconnects, bots). A card is
        split back off the largest face-up stack, which undoes a combine
        without revealing or drawing anything. While fixing, a player holds at
        least six cards and at most three in hand, so a stack always exists;
        the hand is only a defensive fallback.
        """
        player = self._fixing_player(player_index)
        for slot_index, slot in enumerate(player.face_up_slots):
            if slot:
                continue
            donor = max(player.face_up_slots, key=len)
            if len(donor) >= 2:
                slot.append(donor.pop())
            elif player.hand:
                card = max(player.hand, key=lambda c: (STARTING_LOWEST_ORDER[self.rank(c)], int(SUIT_BY_ID[c])))
                self.fix_swap_card(player_index, card, slot_index)
        if not face_up_slots_complete(player):
            raise IllegalActionError(EMPTY_SLOT_MESSAGE)

    def _fixing_player(self, player_index: int) -> Player:
        if self.state.phase is not Phase.FIXING_HANDS:
            raise IllegalActionError("not in fixing phase")
        if not 0 <= player_index < len(self.state.players):
            raise IllegalActionError("invalid player")
        player = self.state.players[player_index]
        if player.fixing_done:
            raise IllegalActionError("already ready")
        return player

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
            # Offer only selections with a valid destination; selecting an
            # isolated face-up card or a hand card blocked by stacks must not
            # trap the fixing state with no next action.
            has_empty = not face_up_slots_complete(player)
            legal.extend(card for card in player.hand if has_empty or any(
                slot and (len(slot) == 1 or self.rank(slot[-1]) is self.rank(card))
                for slot in player.face_up_slots
            ))
            legal.extend(card for source in player.face_up_slots for card in source if any(
                (slot and card not in slot and self.rank(slot[-1]) is self.rank(card))
                or (not slot and len(source) >= 2)
                for slot in player.face_up_slots
            ))
            if not has_empty:
                legal.append(ACTION_FIX_DONE)
            if len(player.hand) < 3 and not self.state.draw_pile:
                for action, slot_index in FIX_TAKE_FROM_STACK_ACTIONS.items():
                    if slot_index < len(player.face_up_slots) and len(player.face_up_slots[slot_index]) > 1:
                        legal.append(action)
                legal.append(ACTION_FIX_KEEP_UNDERSIZED_HAND)
            return legal

        for action, slot_index in FIX_SWAP_ACTIONS.items():
            if selected in player.hand and slot_index < len(player.face_up_slots):
                slot = player.face_up_slots[slot_index]
                if not slot or len(slot) == 1 or self.rank(slot[-1]) is self.rank(selected):
                    legal.append(action)
        selected_rank = self.rank(selected)
        source = next((slot for slot in player.face_up_slots if selected in slot), None)
        for action, slot_index in FIX_STACK_ACTIONS.items():
            if slot_index < len(player.face_up_slots):
                slot = player.face_up_slots[slot_index]
                if slot and selected not in slot and self.rank(slot[-1]) is selected_rank:
                    legal.append(action)
                elif not slot and source is not None and len(source) >= 2:
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
            if not face_up_slots_complete(player):
                raise IllegalActionError(EMPTY_SLOT_MESSAGE)
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
        self.fix_swap_card(self.state.current_player, selected, slot_index)
        self.state.fix_selected_card_id = None

    def _fix_stack(self, player: Player, slot_index: int) -> None:
        selected = self.state.fix_selected_card_id
        if selected is None:
            raise IllegalActionError("no selected card")
        self.fix_stack_card(self.state.current_player, selected, slot_index)
        self.state.fix_selected_card_id = None

    def _fix_take_from_stack(self, player: Player, slot_index: int) -> None:
        card = player.face_up_slots[slot_index].pop()
        player.hand.append(card)
        player.known_hand.append(card)

    def _start_game_after_fixing(self) -> None:
        player_index, start_card = self._find_starting_player_and_card()
        self.state.current_player = player_index
        self.state.required_start_card_id = start_card
        self.state.phase = Phase.EARLY_GAME if self.state.draw_pile else Phase.MIDDLE_GAME
        self._emit("start", player=player_index, card=start_card)

    def _find_starting_player_and_card(self) -> tuple[int, int]:
        best: tuple[int, int, int, int] | None = None
        for player_index, player in enumerate(self.state.players):
            # Exhausted-deck fixing can leave a hand empty. Such a player
            # starts from their visible slots, just as on a normal turn.
            available = player.hand or [card for slot in player.face_up_slots for card in slot]
            for value in available:
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
        return self._is_legal_card_play_with_context(
            value,
            self._target_rank_index(),
            self._start_card_options(),
            self._four_rule_active(),
        )

    def _is_legal_card_play_with_context(
        self,
        value: int,
        target_rank: int | None,
        start_cards: frozenset[int] | None,
        is_four_loop: bool,
    ) -> bool:
        if start_cards is not None:
            return value in start_cards
        if is_four_loop:
            return bool(FOUR_LOOP_RANK_MASK & (1 << RANK_INDEX_BY_ID[value]))
        return can_play_on_index(RANK_INDEX_BY_ID[value], target_rank)

    def _start_card_options(self) -> frozenset[int] | None:
        """Cards that satisfy the opening requirement, or None after the start.

        The starter must play the lowest card. From the hand that is exactly
        that card. From a face-up stack (an empty hand after exhausted-deck
        fixing), every card in the stack has the required rank, and only the
        top one can be picked up, so any card of that slot counts.
        """
        state = self.state
        required = state.required_start_card_id
        if required is None or state.turn_context.played_card_ids:
            return None
        player = self._current_player()
        if not player.hand:
            for slot in player.face_up_slots:
                if required in slot:
                    return frozenset(slot)
        return frozenset((required,))

    def _target_rank(self) -> Rank | None:
        target = self._target_rank_index()
        return None if target is None else Rank(target)

    def _effective_live_index(self, end: int) -> int | None:
        """Index of the card a play on ``live_cards[:end]`` goes on.

        "When a 5 is played, the next player must play on the card beneath
        the 5. If the 5 is the only card in the live cards, the next player
        plays on zero." Several 5s in a row are all seen through. None means
        zero (empty pile, only 5s, or a 5 promoted by a 9s flip).
        """
        state = self.state
        index = end - 1
        while index >= 0 and RANK_INDEX_BY_ID[state.live_cards[index]] == int(Rank.FIVE):
            if state.live_cards[index] == state.five_on_zero_card_id:
                return None
            index -= 1
        return index if index >= 0 else None

    def _target_rank_index(self) -> int | None:
        state = self.state
        index = self._effective_live_index(len(state.live_cards))
        if index is None:
            return None
        card = state.live_cards[index]
        if card in state.ace_as_one_card_ids:
            return None
        return RANK_INDEX_BY_ID[card]

    def _four_rule_active(self) -> bool:
        """Whether the next player must play a 4, 5 or 6 (or pick up).

        Derived from the live pile, so a 4 brought up by a 9s flip acts like a
        played one (owner ruling, 14 November 2026). The effective top card
        (5s seen through) is a 4, or a 6 lying on a 4 or on another such 6:
        "If a 6 is played on a 4, the next player must play on a 4", and a 6
        on a 6 inside a 4 chain keeps the chain going (owner ruling).
        """
        live = self.state.live_cards
        index = self._effective_live_index(len(live))
        while index is not None:
            rank = RANK_INDEX_BY_ID[live[index]]
            if rank == int(Rank.FOUR):
                return True
            if rank != int(Rank.SIX):
                return False
            index = self._effective_live_index(index)
        return False

    def _sync_four_loop_flag(self) -> None:
        """Mirror the pile-derived 4 rule into ``state.pending`` for observers.

        Legality never reads the flag; serialization, observations and the
        training env do. It is only updated between turns, so a player's own
        open group of 4s does not show as a 4 loop to them.
        """
        state = self.state
        if state.phase not in _PLAY_PHASES or state.turn_context.open_group_rank is not None:
            return
        if state.pending is not None and state.pending.kind is PendingKind.NINE_DRAW:
            return
        active = self._four_rule_active()
        if active and state.pending is None:
            state.pending = PendingEffect(PendingKind.FOUR_LOOP, state.current_player)
        elif not active and state.pending is not None:
            state.pending = None

    def _can_reveal_draw_pile(self, playable: list[int]) -> bool:
        return self.state.phase is Phase.EARLY_GAME and bool(self.state.draw_pile) and not playable and self._active_source() == "hand"

    def _can_pick_up(self, playable: list[int]) -> bool:
        # Picking up is only for a player who cannot play: in a 4 loop that
        # means no 4, 5 or 6. In the early game a blocked player may choose
        # between picking up and revealing the draw-pile top.
        return bool(self.state.live_cards) and not playable

    def _play_card(self, value: int) -> None:
        player = self._current_player()
        source = self._active_source()
        context = self.state.turn_context
        if source == "face_up" and context.face_up_slot is None:
            context.face_up_slot = next(i for i, slot in enumerate(player.face_up_slots) if value in slot)
        self._remove_card_from_source(player, value, source)
        self._place_on_live(value)
        self._emit("play", player=self.state.current_player, card=value, source=source)

        if context.open_group_rank is None:
            context.open_group_rank = self.rank(value)
            context.source = source
        context.played_card_ids.append(value)

        # "Whenever one or more cards are played onto the live cards, the
        # player who played must draw [back to three]. If a player draws a card
        # that they just played, they may play that card as well": draw now,
        # so a drawn card of the group's rank can still join the group.
        self._draw_to_three_if_early(player)

    def _place_on_live(self, value: int) -> None:
        """Put a card on the live pile, updating per-card play status."""
        state = self.state
        target = self._target_rank_index()
        previous = state.live_cards[-1] if state.live_cards else None
        state.live_cards.append(value)
        # Status from an earlier visit to the live pile no longer applies.
        if value in state.ace_as_one_card_ids:
            state.ace_as_one_card_ids.remove(value)
        if value == state.five_on_zero_card_id:
            state.five_on_zero_card_id = None
        if self.rank(value) is Rank.ACE:
            # "When an ace is played on a 7, that ace becomes a one". Aces
            # played together with it (same group) are on the 7 as well.
            on_seven = target == int(Rank.SEVEN)
            with_one = (
                previous is not None
                and previous in state.ace_as_one_card_ids
                and previous in state.turn_context.played_card_ids
            )
            if on_seven or with_one:
                state.ace_as_one_card_ids.append(value)

    def _remove_card_from_source(self, player: Player, value: int, source: str | None) -> None:
        if source == "hand":
            player.hand.remove(value)
            if value in player.known_hand:
                player.known_hand.remove(value)
            return
        if source == "face_up":
            for slot in player.face_up_slots:
                if value in slot:
                    slot.remove(value)
                    return
        raise IllegalActionError(f"card {value} is not playable from source {source}")

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
            self._place_on_live(drawn)
            self._emit("nine_draw", player=self.state.current_player, card=drawn)
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
            if self.state.phase is not Phase.GAME_OVER and self.state.players[player_index].active:
                if flip_rank not in {Rank.FOUR, Rank.NINE}:
                    self._finish_or_continue(player_index, player_index)
                elif not self.state.players[player_index].has_any_cards():
                    # Finished by flipping 4s (and no 3 to take) or 9s: legal
                    # only if it is now somebody else's turn.
                    self._finish_or_continue(player_index, self.state.current_player)
            return

        next_player = self._next_player_index(player_index)
        if effect_rank is Rank.TWO:
            next_player = player_index
        elif effect_rank is Rank.THREE and effect_count % 2 == 1:
            self.state.direction *= -1
            next_player = self._next_player_index(player_index)
            self._emit("reverse", player=player_index, direction=self.state.direction)
        elif effect_rank is Rank.FOUR:
            # The 4 rule itself follows from the pile (``_four_rule_active``).
            self.state.pending = PendingEffect(PendingKind.FOUR_LOOP, player_index)
        elif effect_rank is Rank.EIGHT:
            next_player = self._advance_index(player_index, effect_count + 1)
            self._emit("skip", player=player_index, count=effect_count)

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
        self._emit("flip", player=player_index, rank=int(flip_rank), count=len(old_live))

        if flip_rank is Rank.THREE:
            threes = [card for card in old_live if self.rank(card) is Rank.THREE]
            non_threes = [card for card in old_live if self.rank(card) is not Rank.THREE]
            for other_index in self._other_active_players(player_index):
                if threes:
                    dealt = threes.pop(0)
                    self.state.players[other_index].hand.append(dealt)
                    self.state.players[other_index].known_hand.append(dealt)
                    self._emit("deal_three", player=other_index, card=dealt)
            self.state.discard_pile.extend(non_threes + threes)
            self.state.live_cards = []
            self.state.current_player = player_index
            return

        if flip_rank is Rank.NINE and pre_existing_discard:
            new_live = pre_existing_discard
            self.rng.shuffle(new_live)
            self.state.live_cards = new_live
            self.state.discard_pile = old_live
            # The promoted pile was never "played": no ace in it is a one, and
            # a 5 on top means playing on zero.
            self.state.ace_as_one_card_ids = []
            top = new_live[-1]
            self.state.five_on_zero_card_id = top if self.rank(top) is Rank.FIVE else None
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
            # "If a player flips the 8s they automatically finish in last place."
            self._finish_player(player_index, FinishStatus.EIGHTS_LOSS)
            if self.state.phase is not Phase.GAME_OVER:
                self.state.current_player = self._next_player_index(player_index)
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
                self.state.players[player_index].known_hand.append(value)
                self._emit("take_three", player=player_index, card=value)
                return

    def _other_active_players(self, player_index: int) -> list[int]:
        return [index for index, player in enumerate(self.state.players) if index != player_index and player.active]

    def _clear_turn_context(self) -> None:
        self.state.turn_context = TurnContext()
        if self.state.pending and self.state.pending.kind is PendingKind.FOUR_LOOP and not self.state.live_cards:
            self.state.pending = None

    def _draw_to_three_if_early(self, player: Player) -> None:
        if self.state.phase is Phase.EARLY_GAME and player.active:
            self._draw_to_three(player)

    def _draw_to_three(self, player: Player) -> None:
        missing = max(0, 3 - len(player.hand))
        count = min(missing, len(self.state.draw_pile))
        if count:
            player.lacks_mask = 0
        for _ in range(count):
            player.hand.append(self.state.draw_pile.pop(0))
        if count:
            self._emit("draw", player=self.state.players.index(player), count=count)

    def _finish_or_continue(self, player_index: int, next_player: int) -> None:
        player = self.state.players[player_index]
        if not player.has_any_cards():
            # "If a player finishes a game in a way that would make it their
            # own turn, they finish illegally."
            legal = next_player != player_index
            self._finish_player(player_index, FinishStatus.LEGAL_WIN if legal else FinishStatus.ILLEGAL_LOSS)
            if self.state.phase is not Phase.GAME_OVER:
                self.state.current_player = next_player if legal else self._next_player_index(player_index)
            return
        self.state.current_player = next_player

    def _finish_player(self, player_index: int, status: FinishStatus) -> None:
        """Take a player out of the game and give them their place.

        Legal finishers take places from the top (1st, 2nd, ...), illegal
        finishers from the bottom. An 8s flipper "automatically finish[es] in
        last place": they take the very last place and earlier bottom
        finishers each move up one. The game is over once at most one player
        is left; that player gets the remaining place.
        """
        state = self.state
        players = state.players
        n = len(players)
        player = players[player_index]
        player.active = False
        player.finish_status = status
        taken = {p.place for p in players if p.place is not None}
        free = [k for k in range(1, n + 1) if k not in taken]
        if status is FinishStatus.LEGAL_WIN:
            player.place = free[0]
        elif status is FinishStatus.ILLEGAL_LOSS:
            player.place = free[-1]
        else:
            for other in players:
                if other.place is not None and other.finish_status in (FinishStatus.ILLEGAL_LOSS, FinishStatus.EIGHTS_LOSS):
                    other.place -= 1
            player.place = n
        self._emit(
            "win" if status is FinishStatus.LEGAL_WIN else "lose",
            player=player_index,
            place=player.place,
            how=_FINISH_NAMES[status],
        )
        remaining = [index for index, p in enumerate(players) if p.place is None]
        if len(remaining) <= 1:
            taken = {p.place for p in players if p.place is not None}
            for index in remaining:
                players[index].place = next(k for k in range(1, n + 1) if k not in taken)
            state.phase = Phase.GAME_OVER
            self._emit("game_over", places=[p.place for p in players])
        state.winner = next((index for index, p in enumerate(players) if p.place == 1), None)
        state.loser = next((index for index, p in enumerate(players) if p.place == n), None)

    def _pick_up_live_pile(self, player_index: int) -> None:
        self._emit("pickup", player=player_index, cards=list(self.state.live_cards))
        self.state.players[player_index].hand.extend(self.state.live_cards)
        self.state.players[player_index].known_hand.extend(self.state.live_cards)
        self.state.live_cards = []
        self.state.pending = None
        self._clear_turn_context()

    def _advance_to_next_player(self) -> None:
        self.state.current_player = self._next_player_index(self.state.current_player)

    def _next_player_index(self, start: int) -> int:
        return self._advance_index(start, 1)

    def _advance_index(self, start: int, steps: int) -> int:
        """Seat reached after ``steps`` turns from ``start``, skipping players
        who have left the game (``start`` itself may have just left)."""
        players = self.state.players
        if not any(player.active for player in players):
            return start
        index = start
        while steps > 0:
            index = (index + self.state.direction) % len(players)
            if players[index].active:
                steps -= 1
        return index

    def _record_lacks(self, player_index: int) -> None:
        state = self.state
        if self._four_rule_active():
            mask = FOUR_LOOP_RANK_MASK
        else:
            target = self._target_rank_index()
            if target is None:
                return
            mask = sum(1 << r for r in range(13) if can_play_on_index(r, target))
        state.players[player_index].lacks_mask |= mask

    def _reveal_draw_pile_top(self) -> None:
        # Revealing is only allowed with nothing playable in hand.
        self._record_lacks(self.state.current_player)
        revealed = self.state.draw_pile.pop(0)
        # Same legality as a card from hand (incl. "4, 5 or 6" in a 4 loop).
        playable = self._is_legal_card_play(revealed)
        self._emit("reveal", player=self.state.current_player, card=revealed, ok=playable)
        if playable:
            self._place_on_live(revealed)
            self.state.turn_context = TurnContext(open_group_rank=self.rank(revealed), played_card_ids=[revealed], source="draw")
            self._resolve_or_defer_for_latest_card(revealed)
        else:
            self.state.players[self.state.current_player].hand.append(revealed)
            self.state.players[self.state.current_player].known_hand.append(revealed)
            self._pick_up_live_pile(self.state.current_player)
            self._advance_to_next_player()

    def _attempt_face_down(self, slot_index: int) -> None:
        player_index = self.state.current_player
        player = self.state.players[player_index]
        value = player.face_down_slots[slot_index]
        if value is None:
            raise IllegalActionError("empty face-down slot")
        player.face_down_slots[slot_index] = None
        ok = self._is_legal_card_play(value)
        self._emit("face_down", player=player_index, slot=slot_index, card=value, ok=ok)
        if ok:
            self._place_on_live(value)
            self.state.turn_context = TurnContext(open_group_rank=self.rank(value), played_card_ids=[value], source="face_down")
            self._resolve_or_defer_for_latest_card(value)
        else:
            player.hand.append(value)
            player.known_hand.append(value)
            self._pick_up_live_pile(player_index)
            self._advance_to_next_player()

    def _update_phase(self) -> None:
        if self.state.phase in {Phase.DEALING, Phase.FIXING_HANDS, Phase.GAME_OVER}:
            return
        if self._active_source() == "face_down":
            self.state.phase = Phase.END_GAME
        elif self.state.draw_pile:
            self.state.phase = Phase.EARLY_GAME
        else:
            self.state.phase = Phase.MIDDLE_GAME
