import os

# Set dummy env vars before any server modules are imported,
# so pydantic-settings validation passes without real credentials.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("PINECONE_API_KEY", "test-key")
os.environ.setdefault("API_SPORTS_KEY", "test-key")
os.environ.setdefault("FPL_TEAM_ID", "123")
