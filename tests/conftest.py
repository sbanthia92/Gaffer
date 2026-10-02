import os

# Set dummy env vars before any server modules are imported,
# so pydantic-settings validation passes without real credentials.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("FPL_TEAM_ID", "123")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The 10/minute limiter on /fpl/ask is shared by every test hitting that route."""
    from server.main import limiter

    limiter.reset()
