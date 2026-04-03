from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    pinecone_api_key: str
    pinecone_index_name: str = "the-gaffer"
    api_sports_key: str
    server_port: int = 8000
    environment: str = "development"

    model_config = {"env_file": ".env"}


settings = Settings()
