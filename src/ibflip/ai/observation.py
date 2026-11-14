"""Observation encoding and the compact action space used by the AI players.

Suits never matter for play in IB-Flip (only for deciding who starts, which is
automatic), so the agents act on *ranks*:

    0..12  play a card of rank r (``Rank`` index order 3,4,...,A,2)
    13     pick up the live pile
    14     reveal the top card of the draw pile
    15     end the current play group (stop adding same-rank cards)
    16     flip a face-down card (slots are indistinguishable to their owner)
    17..19 play from face-up slot k (rank actions are hand-only in v3)

The observation is strictly what the acting player is allowed to know: their
own cards, everything face up, card counts, the discard pile, and the cards
that were *publicly* seen going into opponents' hands (``Player.known_hand``).
"""

from __future__ import annotations

import numpy as np

from ibflip.actions import (
    ACTION_END_PLAY_GROUP,
    ACTION_PICK_UP_LIVE_PILE,
    ACTION_RESOLVE_NINE_DRAW,
    ACTION_REVEAL_DRAW_PILE_TOP,
    FACE_DOWN_ACTIONS,
)
from ibflip.cards import RANK_INDEX_BY_ID
from ibflip.engine import IBFlipEngine
from ibflip.state import PendingKind, Phase

NUM_RANKS = 13
MAX_PLAYERS = 5
MAX_OPPONENTS = MAX_PLAYERS - 1

A_PICK_UP = 13
A_REVEAL = 14
A_END_GROUP = 15
A_FACE_DOWN = 16
LEGACY_ACTIONS = 17
A_FACE_UP_SLOT_0 = 17
NUM_COMPACT_ACTIONS = 20
OBSERVATION_VERSION = 3
ACTION_VERSION = 3

_FACE_DOWN_ACTION_IDS = frozenset(FACE_DOWN_ACTIONS)


def compact_legal(engine: IBFlipEngine) -> tuple[np.ndarray, dict[int, list[int]]]:
    """Return (mask, mapping) where mapping[compact] lists engine actions."""
    mask = np.zeros(NUM_COMPACT_ACTIONS, dtype=bool)
    mapping: dict[int, list[int]] = {}
    for action in engine.get_legal_action_indices():
        if action < 52:
            if engine._active_source() == "face_up":
                slots = engine.state.players[engine.state.current_player].face_up_slots
                compact = A_FACE_UP_SLOT_0 + next(i for i, slot in enumerate(slots) if action in slot)
            else:
                compact = RANK_INDEX_BY_ID[action]
        elif action == ACTION_PICK_UP_LIVE_PILE:
            compact = A_PICK_UP
        elif action == ACTION_REVEAL_DRAW_PILE_TOP:
            compact = A_REVEAL
        elif action == ACTION_END_PLAY_GROUP:
            compact = A_END_GROUP
        elif action in _FACE_DOWN_ACTION_IDS:
            compact = A_FACE_DOWN
        else:  # forced actions (nine draw) are never decisions
            continue
        mask[compact] = True
        mapping.setdefault(compact, []).append(action)
    # A face-up stack is played from the top: list it first so callers that
    # take ``mapping[compact][0]`` (hint, safety checks) name a card the
    # player can actually pick up. Every card in a slot shares one rank.
    for compact in range(A_FACE_UP_SLOT_0, NUM_COMPACT_ACTIONS):
        if compact in mapping:
            slot = engine.state.players[engine.state.current_player].face_up_slots[compact - A_FACE_UP_SLOT_0]
            mapping[compact].sort(key=slot.index, reverse=True)
    return mask, mapping


def is_forced(engine: IBFlipEngine) -> bool:
    pending = engine.state.pending
    return pending is not None and pending.kind is PendingKind.NINE_DRAW


def resolve_forced(engine: IBFlipEngine) -> None:
    """Apply moves that involve no decision (the random 9 draw)."""
    while engine.state.phase is not Phase.GAME_OVER and is_forced(engine):
        engine.step(ACTION_RESOLVE_NINE_DRAW, validate=False)


def _rank_counts(cards, out: np.ndarray) -> None:
    for card in cards:
        if card is not None:
            out[RANK_INDEX_BY_ID[card]] += 1.0


def opponent_order(engine: IBFlipEngine, player_index: int) -> list[int]:
    """Opponents in the order they will act after ``player_index``."""
    n = engine.num_players
    step = engine.state.direction
    return [(player_index + step * k) % n for k in range(1, n)]


# Layout -----------------------------------------------------------------
_SELF = NUM_RANKS * 2 + 2 + 3  # hand, face-up, hand size, face-down, source
_LIVE = NUM_RANKS + (NUM_RANKS + 1) + 1 + 1 + NUM_RANKS + 1  # top, target(+any), ace1, run, counts, size
_PILES = NUM_RANKS + 1 + 1 + NUM_RANKS  # discard counts, discard size, draw size, unseen
_OPP = 1 + 1 + NUM_RANKS + 1 + NUM_RANKS + 1  # present, hand size, known, unknown, face-up, face-down
_FLAGS = 1 + 1 + NUM_RANKS + 1 + 1 + 3 + (MAX_PLAYERS - 1) + 1
OBS_SIZE_V1 = _SELF + _LIVE + _PILES + MAX_OPPONENTS * _OPP + _FLAGS
# v2 appends, per opponent (in turn order), the ranks publicly inferred to be
# missing from the unseen part of their hand. Appending keeps v1 models valid:
# they simply read the first OBS_SIZE_V1 entries.
_LACKS = MAX_OPPONENTS * NUM_RANKS
OBS_SIZE_V2 = OBS_SIZE_V1 + _LACKS
# Append public slot partitions and placement state; v1/v2 prefixes stay exact.
SLOT_FEATURES = NUM_RANKS + 1  # rank one-hot (all zero if empty), size / 4
SELF_SLOTS_OFFSET = OBS_SIZE_V2
SLOTS_SIZE = MAX_PLAYERS * 3 * SLOT_FEATURES
PLACEMENTS_OFFSET = SELF_SLOTS_OFFSET + SLOTS_SIZE
# self place; each opponent: finished, place, active-turn distance; active count,
# best/worst unclaimed place. Padding for missing opponents remains zero.
OBS_SIZE = PLACEMENTS_OFFSET + MAX_PLAYERS + MAX_OPPONENTS * (MAX_PLAYERS + 2) + 3


def encode(engine: IBFlipEngine, player_index: int) -> np.ndarray:
    state = engine.state
    me = state.players[player_index]
    obs = np.zeros(OBS_SIZE, dtype=np.float32)
    o = 0

    seen = np.zeros(NUM_RANKS, dtype=np.float32)  # cards whose location I know

    hand = obs[o : o + NUM_RANKS]
    _rank_counts(me.hand, hand)
    seen += hand
    hand /= 4.0
    o += NUM_RANKS
    face_up = obs[o : o + NUM_RANKS]
    for slot in me.face_up_slots:
        _rank_counts(slot, face_up)
    seen += face_up
    face_up /= 4.0
    o += NUM_RANKS
    obs[o] = min(len(me.hand), 26) / 13.0
    obs[o + 1] = sum(card is not None for card in me.face_down_slots) / 3.0
    o += 2
    if state.players[player_index] is state.players[state.current_player]:
        source = engine._active_source()
        if source == "hand":
            obs[o] = 1.0
        elif source == "face_up":
            obs[o + 1] = 1.0
        elif source == "face_down":
            obs[o + 2] = 1.0
    o += 3

    # Live pile ---------------------------------------------------------
    live = state.live_cards
    if live:
        obs[o + RANK_INDEX_BY_ID[live[-1]]] = 1.0
    o += NUM_RANKS
    target = engine._target_rank_index()
    if target is None:
        obs[o + NUM_RANKS] = 1.0
    else:
        obs[o + target] = 1.0
    o += NUM_RANKS + 1
    obs[o] = 1.0 if (live and live[-1] in state.ace_as_one_card_ids) else 0.0
    o += 1
    run = 0
    if live:
        top_rank = RANK_INDEX_BY_ID[live[-1]]
        for card in reversed(live):
            if RANK_INDEX_BY_ID[card] != top_rank:
                break
            run += 1
    obs[o] = min(run, 4) / 4.0
    o += 1
    live_counts = obs[o : o + NUM_RANKS]
    _rank_counts(live, live_counts)
    seen += live_counts
    live_counts /= 4.0
    o += NUM_RANKS
    obs[o] = len(live) / 52.0
    o += 1

    # Discard / draw / unseen ---------------------------------------------
    discard = obs[o : o + NUM_RANKS]
    _rank_counts(state.discard_pile, discard)
    seen += discard
    discard /= 4.0
    o += NUM_RANKS
    obs[o] = len(state.discard_pile) / 52.0
    obs[o + 1] = len(state.draw_pile) / 52.0
    o += 2
    unseen_offset = o
    o += NUM_RANKS

    # Opponents -----------------------------------------------------------
    for opp_index in opponent_order(engine, player_index):
        opp = state.players[opp_index]
        base = o
        obs[base] = 1.0 if opp.active else 0.0
        obs[base + 1] = min(len(opp.hand), 26) / 13.0
        known = obs[base + 2 : base + 2 + NUM_RANKS]
        _rank_counts(opp.known_hand, known)
        seen += known
        known /= 4.0
        obs[base + 2 + NUM_RANKS] = min(len(opp.hand) - len(opp.known_hand), 26) / 13.0
        fu = obs[base + 3 + NUM_RANKS : base + 3 + 2 * NUM_RANKS]
        for slot in opp.face_up_slots:
            _rank_counts(slot, fu)
        seen += fu
        fu /= 4.0
        obs[base + 3 + 2 * NUM_RANKS] = sum(card is not None for card in opp.face_down_slots) / 3.0
        o += _OPP
    o = unseen_offset + NUM_RANKS + MAX_OPPONENTS * _OPP
    obs[unseen_offset : unseen_offset + NUM_RANKS] = np.clip(4.0 - seen, 0.0, 4.0) / 4.0

    # Flags ---------------------------------------------------------------
    pending = state.pending
    obs[o] = 1.0 if pending is not None and pending.kind is PendingKind.FOUR_LOOP else 0.0
    group = state.turn_context.open_group_rank
    obs[o + 1] = 1.0 if group is not None else 0.0
    if group is not None:
        obs[o + 2 + int(group)] = 1.0
    o += 2 + NUM_RANKS
    obs[o] = len(state.turn_context.played_card_ids) / 4.0
    obs[o + 1] = 1.0 if state.required_start_card_id is not None and not state.turn_context.played_card_ids else 0.0
    o += 2
    phase = state.phase
    if phase is Phase.EARLY_GAME:
        obs[o] = 1.0
    elif phase is Phase.MIDDLE_GAME:
        obs[o + 1] = 1.0
    elif phase is Phase.END_GAME:
        obs[o + 2] = 1.0
    o += 3
    obs[o + min(engine.num_players, MAX_PLAYERS) - 2] = 1.0
    o += MAX_PLAYERS - 1
    obs[o] = 1.0 if state.direction == 1 else 0.0
    o += 1
    assert o == OBS_SIZE_V1, (o, OBS_SIZE_V1)
    for k, opp_index in enumerate(opponent_order(engine, player_index)):
        mask = state.players[opp_index].lacks_mask
        if mask:
            base = o + k * NUM_RANKS
            for r in range(NUM_RANKS):
                if (mask >> r) & 1:
                    obs[base + r] = 1.0
    # Slots are public. Do not encode face-down identities or unknown hands.
    order = [player_index, *opponent_order(engine, player_index)]
    for k, index in enumerate(order):
        for slot_index, slot in enumerate(state.players[index].face_up_slots):
            base = SELF_SLOTS_OFFSET + (k * 3 + slot_index) * SLOT_FEATURES
            if slot:
                obs[base + RANK_INDEX_BY_ID[slot[-1]]] = 1.0
                obs[base + NUM_RANKS] = len(slot) / 4.0
    o = PLACEMENTS_OFFSET
    if me.place is not None:
        obs[o + me.place - 1] = 1.0
    o += MAX_PLAYERS
    active_order = []
    index = player_index
    for _ in range(sum(p.active for p in state.players)):
        index = engine._next_player_index(index)
        active_order.append(index)
    for index in order[1:]:
        opponent = state.players[index]
        obs[o] = float(not opponent.active)
        if opponent.place is not None:
            obs[o + opponent.place] = 1.0
        if opponent.active and index in active_order:
            obs[o + MAX_PLAYERS + 1] = (active_order.index(index) + 1) / MAX_PLAYERS
        o += MAX_PLAYERS + 2
    o = PLACEMENTS_OFFSET + MAX_PLAYERS + MAX_OPPONENTS * (MAX_PLAYERS + 2)
    obs[o] = sum(p.active for p in state.players) / MAX_PLAYERS
    taken = {p.place for p in state.players if p.place is not None}
    free = [place for place in range(1, engine.num_players + 1) if place not in taken]
    if free:
        obs[o + 1], obs[o + 2] = free[0] / MAX_PLAYERS, free[-1] / MAX_PLAYERS
    return obs
