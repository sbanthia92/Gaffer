from fastapi import FastAPI

from server.config import settings

app = FastAPI(title="The Gaffer", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
