from __future__ import annotations

from functools import lru_cache
from typing import Any

import gymnasium as gym
import numpy as np
from pettingzoo import AECEnv

from ibflip import IBFlipEngine, IllegalActionError
from ibflip.actions import (
    ACTION_END_PLAY_GROUP,
    ACTION_PICK_UP_LIVE_PILE,
    ACTION_RESOLVE_NINE_DRAW,
    ACTION_SPACE_SIZE,
)
from ibflip.state import FinishStatus, PendingKind, Phase, TurnContext


class IBFlipAECEnv(AECEnv[str, dict[str, Any], int]):
    metadata = {"name": "ibflip_v0", "is_parallelizable": False, "render_modes": ["ansi"]}

    def __init__(
        self,
        num_players: int = 2,
        seed: int | None = None,
        max_steps: int = 2_000,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        if num_players < 2:
            raise ValueError("IBFlipAECEnv requires at least two players")
        self.num_players_config = num_players
        self.seed_value = seed
        self.max_steps = max_steps
        self.render_mode = render_mode

        self.possible_agents = [f"player_{index}" for index in range(num_players)]
        self.agent_name_mapping = {agent: index for index, agent in enumerate(self.possible_agents)}
        self._action_spaces = {agent: gym.spaces.Discrete(ACTION_SPACE_SIZE) for agent in self.possible_agents}
        self._observation_spaces = {agent: self._make_observation_space() for agent in self.possible_agents}
        self.action_spaces = self._action_spaces
        self.observation_spaces = self._observation_spaces

        self.engine = IBFlipEngine(num_players=num_players, seed=seed)
        self.agents: list[str] = []
        self.rewards: dict[str, float] = {}
        self._cumulative_rewards: dict[str, float] = {}
        self.terminations: dict[str, bool] = {}
        self.truncations: dict[str, bool] = {}
        self.infos: dict[str, dict[str, Any]] = {}
        self.agent_selection: str | None = None
        self.total_steps = 0

    @staticmethod
    def _make_observation_space() -> gym.spaces.Dict:
        return gym.spaces.Dict(
            {
                "my_hand": gym.spaces.Box(0, 1, shape=(52,), dtype=np.int8),
                "my_face_up": gym.spaces.Box(0, 4, shape=(52,), dtype=np.int8),
                "my_face_down_count": gym.spaces.Discrete(4),
                "live_pile_top": gym.spaces.Box(0, 1, shape=(52,), dtype=np.int8),
                "live_pile_second": gym.spaces.Box(0, 1, shape=(52,), dtype=np.int8),
                "discard_pile": gym.spaces.Box(0, 1, shape=(52,), dtype=np.int8),
                "opponent_face_up": gym.spaces.Box(0, 4, shape=(52,), dtype=np.int8),
                "opponent_hand_count": gym.spaces.Box(0, 52, shape=(1,), dtype=np.int8),
                "opponent_face_down_count": gym.spaces.Discrete(4),
                "state_flags": gym.spaces.Box(0, 1, shape=(5,), dtype=np.int8),
                "action_mask": gym.spaces.Box(0, 1, shape=(ACTION_SPACE_SIZE,), dtype=np.int8),
            }
        )

    @lru_cache(maxsize=None)
    def observation_space(self, agent: str) -> gym.spaces.Space:
        return self._observation_spaces[agent]

    @lru_cache(maxsize=None)
    def action_space(self, agent: str) -> gym.spaces.Space:
        return self._action_spaces[agent]

    def reset(self, seed: int | None = None, options: dict | None = None) -> None:
        del options
        if seed is not None:
            self.seed_value = seed
        self.engine = IBFlipEngine(num_players=self.num_players_config, seed=self.seed_value)
        self.engine.reset()
        self.engine.auto_fix_hands_randomly()

        self.agents = self.possible_agents[:]
        self.rewards = {agent: 0.0 for agent in self.agents}
        self._cumulative_rewards = {agent: 0.0 for agent in self.agents}
        self.terminations = {agent: False for agent in self.agents}
        self.truncations = {agent: False for agent in self.agents}
        self.infos = {agent: {} for agent in self.agents}
        self.total_steps = 0
        self.agent_selection = self._agent_from_player_index(self.engine.state.current_player)
        self._refresh_infos()

    def observe(self, agent: str) -> dict[str, Any]:
        player_index = self.agent_name_mapping[agent]
        player = self.engine.state.players[player_index]

        my_hand = self._card_count_vector(player.hand, binary=True)
        my_face_up = self._face_up_vector(player_index)
        opponent_face_up = np.zeros(52, dtype=np.int8)
        opponent_hand_count = 0
        opponent_face_down_count = 0
        for opponent_index, opponent in enumerate(self.engine.state.players):
            if opponent_index == player_index:
                continue
            opponent_face_up += self._face_up_vector(opponent_index)
            opponent_hand_count += len(opponent.hand)
            opponent_face_down_count += self._face_down_count(opponent_index)

        live_top = np.zeros(52, dtype=np.int8)
        live_second = np.zeros(52, dtype=np.int8)
        if self.engine.state.live_cards:
            live_top[self.engine.state.live_cards[-1]] = 1
        if len(self.engine.state.live_cards) >= 2:
            live_second[self.engine.state.live_cards[-2]] = 1

        return {
            "my_hand": my_hand,
            "my_face_up": my_face_up,
            "my_face_down_count": np.int8(self._face_down_count(player_index)),
            "live_pile_top": live_top,
            "live_pile_second": live_second,
            "discard_pile": self._card_count_vector(self.engine.state.discard_pile, binary=True),
            "opponent_face_up": np.clip(opponent_face_up, 0, 4).astype(np.int8),
            "opponent_hand_count": np.array([opponent_hand_count], dtype=np.int8),
            "opponent_face_down_count": np.int8(min(opponent_face_down_count, 3)),
            "state_flags": self._state_flags(),
            "action_mask": self._action_mask_for(agent),
        }

    def step(self, action: int | None) -> None:
        agent = self.agent_selection
        if agent is None:
            return
        if self.terminations.get(agent, False) or self.truncations.get(agent, False):
            self._was_dead_step(action)
            return

        self._clear_rewards()
        self._cumulative_rewards[agent] = 0.0

        acting_player = self.agent_name_mapping[agent]
        legal_mask = self.engine.get_legal_actions()
        action_is_legal = action is not None and 0 <= int(action) < ACTION_SPACE_SIZE and legal_mask[int(action)]

        before_live_count = len(self.engine.state.live_cards)
        before_hand_count = len(self.engine.state.players[acting_player].hand)

        if not action_is_legal:
            self.rewards[agent] -= 0.5
            self._pass_after_illegal_action()
        else:
            chosen_action = int(action)
            try:
                self.engine.step(chosen_action, validate=False)
            except IllegalActionError:
                self.rewards[agent] -= 0.5
                self._pass_after_illegal_action()
            else:
                if chosen_action < 52 or chosen_action == ACTION_END_PLAY_GROUP:
                    self.rewards[agent] += 0.01
                if self._picked_up_live_cards(acting_player, before_live_count, before_hand_count):
                    self.rewards[agent] -= 0.1

        self.total_steps += 1
        self._apply_terminal_rewards()
        if self.total_steps >= self.max_steps and self.engine.state.phase is not Phase.GAME_OVER:
            for live_agent in self.agents:
                self.truncations[live_agent] = True

        self._refresh_infos()
        self._accumulate_rewards()

        if any(self.terminations.values()) or any(self.truncations.values()):
            self._deads_step_first()
        else:
            self.agent_selection = self._agent_from_player_index(self.engine.state.current_player)

    def render(self) -> str | None:
        if self.render_mode != "ansi":
            return None
        return (
            f"phase={self.engine.state.phase.name} "
            f"current_player={self.engine.state.current_player} "
            f"live_cards={self.engine.state.live_cards} "
            f"discard_count={len(self.engine.state.discard_pile)}"
        )

    def close(self) -> None:
        pass

    def _agent_from_player_index(self, player_index: int) -> str:
        return self.possible_agents[player_index]

    def _card_count_vector(self, cards: list[int], *, binary: bool) -> np.ndarray:
        vector = np.zeros(52, dtype=np.int8)
        for card in cards:
            if card is None:
                continue
            if binary:
                vector[card] = 1
            else:
                vector[card] += 1
        return vector

    def _face_up_vector(self, player_index: int) -> np.ndarray:
        player = self.engine.state.players[player_index]
        vector = np.zeros(52, dtype=np.int8)
        for slot in player.face_up_slots:
            for card in slot:
                vector[card] += 1
        return np.clip(vector, 0, 4).astype(np.int8)

    def _face_down_count(self, player_index: int) -> int:
        return sum(card is not None for card in self.engine.state.players[player_index].face_down_slots)

    def _state_flags(self) -> np.ndarray:
        pending = self.engine.state.pending
        return np.array(
            [
                int(pending is not None and pending.kind is PendingKind.FOUR_LOOP),
                int(self.engine.state.direction == 1),
                int(pending is not None and pending.kind is PendingKind.NINE_DRAW),
                int(self.engine.state.turn_context.open_group_rank is not None),
                int(self.engine.state.phase is Phase.END_GAME),
            ],
            dtype=np.int8,
        )

    def _action_mask_for(self, agent: str) -> np.ndarray:
        mask = np.zeros(ACTION_SPACE_SIZE, dtype=np.int8)
        if (
            agent == self.agent_selection
            and agent in self.agents
            and not self.terminations.get(agent, False)
            and not self.truncations.get(agent, False)
        ):
            mask[:] = np.asarray(self.engine.get_legal_actions(), dtype=np.int8)
        return mask

    def _picked_up_live_cards(self, player_index: int, before_live_count: int, before_hand_count: int) -> bool:
        if before_live_count == 0:
            return False
        player = self.engine.state.players[player_index]
        return len(self.engine.state.live_cards) == 0 and len(player.hand) > before_hand_count

    def _pass_after_illegal_action(self) -> None:
        if self.engine.state.pending and self.engine.state.pending.kind is PendingKind.NINE_DRAW:
            self.engine.step(ACTION_RESOLVE_NINE_DRAW, validate=False)
            return
        if self.engine.state.turn_context.open_group_rank is not None and self.engine.state.turn_context.played_card_ids:
            self.engine.step(ACTION_END_PLAY_GROUP, validate=False)
            return
        self.engine.state.required_start_card_id = None
        self.engine.state.turn_context = TurnContext()
        self.engine.state.current_player = self.engine._next_player_index(self.engine.state.current_player)
        self.engine._update_phase()

    def _apply_terminal_rewards(self) -> None:
        if self.engine.state.phase is not Phase.GAME_OVER:
            return

        winner = self.engine.state.winner
        loser = self.engine.state.loser
        if winner is not None:
            winner_agent = self._agent_from_player_index(winner)
            self.rewards[winner_agent] += 1.0
            for agent in self.agents:
                if agent != winner_agent:
                    self.rewards[agent] -= 1.0
        elif loser is not None:
            loser_agent = self._agent_from_player_index(loser)
            self.rewards[loser_agent] -= 1.0
            for agent in self.agents:
                if agent != loser_agent:
                    self.rewards[agent] += 1.0
        else:
            for index, player in enumerate(self.engine.state.players):
                agent = self._agent_from_player_index(index)
                if player.finish_status is FinishStatus.LEGAL_WIN:
                    self.rewards[agent] += 1.0
                elif player.finish_status is FinishStatus.ILLEGAL_LOSS:
                    self.rewards[agent] -= 1.0

        for agent in self.agents:
            self.terminations[agent] = True

    def _refresh_infos(self) -> None:
        for agent in self.agents:
            self.infos[agent] = {"action_mask": self._action_mask_for(agent)}


def env(**kwargs: Any) -> IBFlipAECEnv:
    return IBFlipAECEnv(**kwargs)
