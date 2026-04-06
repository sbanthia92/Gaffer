import json
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from pydantic_settings import BaseSettings

# Resolve .env relative to the project root (one level up from server/)
_ENV_FILE = Path(__file__).parent.parent / ".env"

_SECRET_NAME = "gaffer/production"


def _load_secrets_manager() -> dict:
    """Fetch all secrets from AWS Secrets Manager. Returns empty dict on failure."""
    try:
        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
        response = client.get_secret_value(SecretId=_SECRET_NAME)
        return json.loads(response["SecretString"])
    except (ClientError, Exception):
        return {}


def _inject_secrets() -> None:
    """
    In production, pull secrets from Secrets Manager and inject them into
    the environment so pydantic-settings can pick them up as normal.
    Only runs when ENVIRONMENT=production and the keys aren't already set.
    """
    if os.getenv("ENVIRONMENT", "development") != "production":
        return
    secrets = _load_secrets_manager()
    for key, value in secrets.items():
        if key not in os.environ:
            os.environ[key] = str(value)


_inject_secrets()


class Settings(BaseSettings):
    anthropic_api_key: str
    pinecone_api_key: str
    pinecone_index_name: str = "the-gaffer"
    api_sports_key: str
    fpl_team_id: int | None = None
    feedback_email: str = ""
    resend_api_key: str = ""
    server_port: int = 8000
    environment: str = "development"

    model_config = {"env_file": str(_ENV_FILE)}


settings = Settings()
