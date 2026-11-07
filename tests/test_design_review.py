"""The local review server must persist feedback without exposing the checkout."""

import json
import threading

import httpx
import pytest

from scripts.design_review import MAX_BODY, ReviewServer


@pytest.fixture
def review(tmp_path):
    designs = tmp_path / "designs"
    designs.mkdir()
    (designs / "index.html").write_text("Design review")
    (tmp_path / ".env").write_text("PRIVATE=do-not-serve")
    (designs / "escape").symlink_to(tmp_path / ".env")
    feedback = tmp_path / ".local/design-review.json"
    server = ReviewServer(("127.0.0.1", 0), designs, feedback)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False
        ) as client:
            yield client, feedback
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def decision():
    return {
        "version": 1,
        "updatedAt": "2026-11-07T12:00:00.000Z",
        "currentId": "play",
        "theme": "light",
        "generalNote": "Keep the table calm.",
        "decisions": {
            "play": {"option": "thump", "status": "changes", "note": "A little slower."}
        },
    }


def test_feedback_round_trip_and_private_storage(review, decision):
    client, path = review
    initial = client.get("/api/review")
    assert initial.json() is None
    client.headers["If-Match"] = initial.headers["ETag"]
    assert client.put("/api/review", json=decision).json() == decision
    assert client.get("/api/review").json() == decision
    assert json.loads(path.read_text()) == decision
    assert path.stat().st_mode & 0o777 == 0o600
    assert client.get("/.local/design-review.json").status_code == 404


def test_cross_origin_and_foreign_host_cannot_change_feedback(review, decision):
    client, path = review
    response = client.put(
        "/api/review", json=decision, headers={"Origin": "https://example.com"}
    )
    assert response.status_code == 403
    assert client.get("/api/review", headers={"Host": "example.com"}).status_code == 403
    assert not path.exists()


def test_private_files_and_symlinks_are_not_served(review):
    client, _ = review
    assert client.get("/").text == "Design review"
    for url in ["/.env", "/../.env", "/%2e%2e/.env", "/escape"]:
        response = client.get(url)
        assert response.status_code == 404
        assert "do-not-serve" not in response.text


def test_invalid_feedback_cannot_overwrite_saved_notes(review, decision):
    client, _ = review
    client.headers["If-Match"] = client.get("/api/review").headers["ETag"]
    assert client.put("/api/review", json=decision).status_code == 200
    invalid = dict(
        decision,
        decisions={"../.env": {"option": "x", "status": "approved", "note": ""}},
    )
    assert client.put("/api/review", json=invalid).status_code == 400
    assert (
        client.put(
            "/api/review",
            content="not json",
            headers={"Content-Type": "application/json"},
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/review", json=dict(decision, generalNote="x" * 10001)
        ).status_code
        == 400
    )
    assert client.get("/api/review").json() == decision


def test_writes_require_json_and_bounded_content(review, decision):
    client, path = review
    assert client.put("/api/review", content=json.dumps(decision)).status_code == 415
    response = client.put(
        "/api/review",
        content="x" * (MAX_BODY + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert not path.exists()


def test_stale_client_cannot_erase_newer_decisions(review, decision):
    client, _ = review
    tag = client.get("/api/review").headers["ETag"]
    assert client.put("/api/review", json=decision).status_code == 428
    response = client.put("/api/review", json=decision, headers={"If-Match": tag})
    assert response.status_code == 200
    assert response.headers["ETag"] != tag
    stale = dict(decision, generalNote="Another tab's stale notes")
    response = client.put("/api/review", json=stale, headers={"If-Match": tag})
    assert response.status_code == 409
    assert response.json()["review"] == decision
    assert client.get("/api/review").json() == decision


def test_alternate_forwarded_loopback_port_is_supported(review, decision):
    client, _ = review
    client.headers.update(
        {"Host": "localhost:18080", "Origin": "http://localhost:18080"}
    )
    response = client.get("/api/review")
    assert response.status_code == 200
    client.headers["If-Match"] = response.headers["ETag"]
    assert client.put("/api/review", json=decision).status_code == 200
    client.headers["Origin"] = "http://localhost:18081"
    assert client.put("/api/review", json=decision).status_code == 403
