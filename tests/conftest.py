import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "web: multiplayer server / protocol tests (fast, in-process)")


@pytest.fixture(autouse=True)
def _generous_rate_limits(monkeypatch):
    """Every TestClient request comes from the same address; don't let the
    per-IP limits of one test leak into the next."""
    import ibflip_web.main as main

    for name in ("CREATE_LIMIT", "JOIN_LIMIT", "INFO_LIMIT"):
        if hasattr(main, name):
            monkeypatch.setattr(main, name, main.RateLimiter(capacity=1e9, per_minute=1e9))
