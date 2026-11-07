import json

import pytest

from ibflip.training_budget import remaining_run_hours


def test_restart_retains_original_deadline_and_never_extends_the_budget(tmp_path):
    assert remaining_run_hours(tmp_path, 2, now=1000) == 2
    assert remaining_run_hours(tmp_path, 2, now=4600) == 1
    assert remaining_run_hours(tmp_path, 8, now=6400) == .5
    assert json.loads((tmp_path / 'run-budget.json').read_text())['deadline_unix'] == 8200


def test_expired_run_does_not_start_another_window(tmp_path):
    remaining_run_hours(tmp_path, 2, now=1000)
    assert remaining_run_hours(tmp_path, 2, now=8200) == 0
    assert remaining_run_hours(tmp_path, 2, now=10000) == 0


@pytest.mark.parametrize('hours', [0, -1, float('nan'), float('inf')])
def test_invalid_budget_is_rejected_before_writing(tmp_path, hours):
    with pytest.raises(ValueError):
        remaining_run_hours(tmp_path, hours, now=1000)
    assert not (tmp_path / 'run-budget.json').exists()
