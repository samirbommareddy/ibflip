from fastapi.testclient import TestClient

from ibflip_web.main import app


def test_start_state_and_play_endpoints_return_human_perspective():
    client = TestClient(app)

    start_response = client.post("/start")
    assert start_response.status_code == 200
    state = start_response.json()
    assert state["session_id"]
    assert "human" in state
    assert "legal_actions" in state
    assert len(state["action_mask"]) == 70

    state_response = client.get(f"/state/{state['session_id']}")
    assert state_response.status_code == 200

    if state["is_human_turn"] and state["legal_actions"]:
        play_response = client.post(
            f"/play/{state['session_id']}",
            json={"action_id": state["legal_actions"][0]},
        )
        assert play_response.status_code == 200
        assert "log" in play_response.json()
