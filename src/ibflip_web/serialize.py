"""Per-viewer (hidden information safe) JSON views of a game.

Cards are sent as integer ids: rank = id // 4 in the order
3,4,5,6,7,8,9,10,J,Q,K,A,2 and suit = id % 4 in the order ♥ ♦ ♣ ♠.
"""

from __future__ import annotations

from typing import Any

from ibflip import IBFlipEngine
from ibflip.actions import (
    ACTION_END_PLAY_GROUP,
    ACTION_PICK_UP_LIVE_PILE,
    ACTION_REVEAL_DRAW_PILE_TOP,
    FACE_DOWN_ACTIONS,
)
from ibflip.state import PendingKind, Phase


def serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    return dict(event)


def _target(engine: IBFlipEngine) -> int | None:
    return engine._target_rank_index()


def serialize_view(engine: IBFlipEngine, seat: int | None, status: str) -> dict[str, Any]:
    state = engine.state
    over = state.phase is Phase.GAME_OVER
    players = []
    for index, player in enumerate(state.players):
        entry = {
            "hand_count": len(player.hand),
            "known": list(player.known_hand),
            "face_up": [list(slot) for slot in player.face_up_slots],
            "face_down": [card is not None for card in player.face_down_slots],
            "active": player.active,
            "finish": player.finish_status.name if player.finish_status else None,
            "ready": player.fixing_done,
        }
        if over:
            # Reveal everything at the end of the game.
            entry["hand"] = list(player.hand)
            entry["face_down_cards"] = list(player.face_down_slots)
        players.append(entry)

    view: dict[str, Any] = {
        "status": status,
        "phase": state.phase.name,
        "current": None if over or status == "fixing" else state.current_player,
        "direction": state.direction,
        "four_loop": bool(state.pending and state.pending.kind is PendingKind.FOUR_LOOP),
        "nine_draw": bool(state.pending and state.pending.kind is PendingKind.NINE_DRAW),
        "winner": state.winner,
        "loser": state.loser,
        "live": list(state.live_cards),
        "ace_one": [c for c in state.ace_as_one_card_ids if c in state.live_cards],
        "target": _target(engine),
        "discard_count": len(state.discard_pile),
        "discard_top": state.discard_pile[-1] if state.discard_pile else None,
        "draw_count": len(state.draw_pile),
        "start_card": state.required_start_card_id,
        "group_rank": int(state.turn_context.open_group_rank) if state.turn_context.open_group_rank is not None else None,
        "group_count": len(state.turn_context.played_card_ids),
        "players": players,
    }

    if seat is not None and 0 <= seat < len(state.players):
        me = state.players[seat]
        view["hand"] = list(me.hand)
        legal: list[int] = []
        if not over and status == "playing" and state.current_player == seat and not view["nine_draw"]:
            legal = engine.get_legal_action_indices()
        view["legal"] = {
            "cards": [a for a in legal if a < 52],
            "pick_up": ACTION_PICK_UP_LIVE_PILE in legal,
            "reveal": ACTION_REVEAL_DRAW_PILE_TOP in legal,
            "end_group": ACTION_END_PLAY_GROUP in legal,
            "face_down": [FACE_DOWN_ACTIONS[a] for a in legal if a in FACE_DOWN_ACTIONS],
        }
        view["source"] = engine._active_source() if legal else None
    return view
