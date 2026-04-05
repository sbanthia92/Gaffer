from pathlib import Path

from pydantic_settings import BaseSettings

# Resolve .env relative to the project root (one level up from server/)
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    anthropic_api_key: str
    pinecone_api_key: str
    pinecone_index_name: str = "the-gaffer"
    api_sports_key: str
    fpl_team_id: int | None = None
    server_port: int = 8000
    environment: str = "development"

    model_config = {"env_file": str(_ENV_FILE)}


settings = Settings()
