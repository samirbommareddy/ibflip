"""The web client's "What can go on what" table must match the rules engine."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ibflip.cards import Rank
from ibflip.rules import PLAYABLE_ON

APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"
LABELS = ["3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A", "2"]


def client_table() -> dict[str, list[str]]:
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"const PLAYABLE_ON = (\{.*?\n\});", source, re.S)
    assert match, "PLAYABLE_ON table not found in static/app.js"
    return json.loads(match.group(1))


def test_client_table_matches_rules_engine() -> None:
    expected = {
        LABELS[int(played)]: sorted((LABELS[int(t)] for t in targets), key=LABELS.index)
        for played, targets in PLAYABLE_ON.items()
    }
    actual = {played: sorted(targets, key=LABELS.index) for played, targets in client_table().items()}
    assert actual == expected
    assert set(actual) == {LABELS[int(rank)] for rank in Rank}
