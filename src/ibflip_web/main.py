from __future__ import annotations

import random
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ibflip import IBFlipEngine, IllegalActionError
from ibflip.actions import ACTION_SPACE_SIZE
from ibflip.cards import Rank, Suit, card_from_id
from ibflip.state import Phase


ACTIVE_GAMES: dict[str, IBFlipEngine] = {}
BOT_RNG = random.Random()
HUMAN_PLAYER = 0
BOT_STEP_LIMIT = 500

app = FastAPI(title="IB-Flip API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PlayRequest(BaseModel):
    action_id: int


def card_label(card_id: int) -> str:
    card = card_from_id(card_id)
    rank_names = {
        Rank.THREE: "3",
        Rank.FOUR: "4",
        Rank.FIVE: "5",
        Rank.SIX: "6",
        Rank.SEVEN: "7",
        Rank.EIGHT: "8",
        Rank.NINE: "9",
        Rank.TEN: "10",
        Rank.JACK: "J",
        Rank.QUEEN: "Q",
        Rank.KING: "K",
        Rank.ACE: "A",
        Rank.TWO: "2",
    }
    suit_names = {
        Suit.HEARTS: "Hearts",
        Suit.DIAMONDS: "Diamonds",
        Suit.CLUBS: "Clubs",
        Suit.SPADES: "Spades",
    }
    return f"{rank_names[card.rank]} of {suit_names[card.suit]}"


def action_label(action_id: int) -> str:
    if 0 <= action_id < 52:
        return f"played {card_label(action_id)}"
    labels = {
        52: "picked up the live pile",
        53: "resolved a 9 draw",
        54: "revealed the draw pile top card",
        55: "ended their play group",
        67: "played face-down slot 1",
        68: "played face-down slot 2",
        69: "played face-down slot 3",
    }
    return labels.get(action_id, f"used action {action_id}")


def legal_actions(engine: IBFlipEngine) -> list[int]:
    return [index for index, is_legal in enumerate(engine.get_legal_actions()) if is_legal]


def serialize_slot(slot: list[int]) -> list[dict[str, Any]]:
    return [{"id": card_id, "label": card_label(card_id)} for card_id in slot]


def serialize_player(engine: IBFlipEngine, player_index: int, *, reveal_hand: bool) -> dict[str, Any]:
    player = engine.state.players[player_index]
    hand = [{"id": card_id, "label": card_label(card_id)} for card_id in player.hand] if reveal_hand else []
    return {
        "player_index": player_index,
        "hand": hand,
        "hand_count": len(player.hand),
        "face_up_slots": [serialize_slot(slot) for slot in player.face_up_slots],
        "face_down_count": sum(card is not None for card in player.face_down_slots),
        "active": player.active,
        "finish_status": player.finish_status.name if player.finish_status else None,
    }


def serialize_state(session_id: str, engine: IBFlipEngine, log: list[str] | None = None) -> dict[str, Any]:
    legal = legal_actions(engine) if engine.state.phase is not Phase.GAME_OVER else []
    action_mask = [index in set(legal) for index in range(ACTION_SPACE_SIZE)]
    live_cards = [{"id": card_id, "label": card_label(card_id)} for card_id in engine.state.live_cards]
    return {
        "session_id": session_id,
        "phase": engine.state.phase.name,
        "game_over": engine.state.phase is Phase.GAME_OVER,
        "current_player": engine.state.current_player,
        "is_human_turn": engine.state.phase is not Phase.GAME_OVER and engine.state.current_player == HUMAN_PLAYER,
        "direction": engine.state.direction,
        "pending": engine.state.pending.kind.name if engine.state.pending else None,
        "winner": engine.state.winner,
        "loser": engine.state.loser,
        "human": serialize_player(engine, HUMAN_PLAYER, reveal_hand=True),
        "human_face_down_slots": [
            {"slot": index, "action_id": 67 + index, "available": card is not None}
            for index, card in enumerate(engine.state.players[HUMAN_PLAYER].face_down_slots)
        ],
        "opponents": [
            serialize_player(engine, player_index, reveal_hand=False)
            for player_index in range(1, len(engine.state.players))
        ],
        "live_pile": live_cards,
        "live_pile_top": live_cards[-1] if live_cards else None,
        "discard_count": len(engine.state.discard_pile),
        "discard_top": (
            {"id": engine.state.discard_pile[-1], "label": card_label(engine.state.discard_pile[-1])}
            if engine.state.discard_pile
            else None
        ),
        "draw_count": len(engine.state.draw_pile),
        "legal_actions": legal,
        "action_mask": action_mask,
        "log": log or [],
    }


def run_bots_until_human_turn(engine: IBFlipEngine) -> list[str]:
    log: list[str] = []
    bot_steps = 0
    while engine.state.phase is not Phase.GAME_OVER and engine.state.current_player != HUMAN_PLAYER:
        bot_steps += 1
        if bot_steps > BOT_STEP_LIMIT:
            log.append("Bot loop stopped after safety limit.")
            break

        player_index = engine.state.current_player
        actions = legal_actions(engine)
        if not actions:
            log.append(f"Player {player_index + 1} had no legal actions; bot loop stopped.")
            break
        action_id = BOT_RNG.choice(actions)
        try:
            engine.step(action_id, validate=False)
        except IllegalActionError as exc:
            log.append(f"Player {player_index + 1} attempted illegal action {action_id}: {exc}")
            break
        log.append(f"Player {player_index + 1} {action_label(action_id)}.")
    return log


def get_engine(session_id: str) -> IBFlipEngine:
    engine = ACTIVE_GAMES.get(session_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="Unknown session_id")
    return engine


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/start")
def start_game() -> dict[str, Any]:
    session_id = str(uuid4())
    engine = IBFlipEngine(num_players=4)
    engine.reset()
    engine.auto_fix_hands_randomly()
    ACTIVE_GAMES[session_id] = engine
    log = ["Started a new 4-player game."]
    log.extend(run_bots_until_human_turn(engine))
    return serialize_state(session_id, engine, log)


@app.get("/state/{session_id}")
def get_state(session_id: str) -> dict[str, Any]:
    return serialize_state(session_id, get_engine(session_id))


@app.post("/play/{session_id}")
def play(session_id: str, request: PlayRequest) -> dict[str, Any]:
    engine = get_engine(session_id)
    log: list[str] = []

    if engine.state.phase is Phase.GAME_OVER:
        return serialize_state(session_id, engine, ["Game is already over."])
    if engine.state.current_player != HUMAN_PLAYER:
        log.append("It was not the human turn; bots advanced first.")
        log.extend(run_bots_until_human_turn(engine))
        return serialize_state(session_id, engine, log)

    action_id = request.action_id
    actions = legal_actions(engine)
    if action_id not in actions:
        raise HTTPException(status_code=400, detail={"message": "Illegal action", "legal_actions": actions})

    try:
        engine.step(action_id, validate=False)
    except IllegalActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    log.append(f"You {action_label(action_id)}.")
    log.extend(run_bots_until_human_turn(engine))
    return serialize_state(session_id, engine, log)
