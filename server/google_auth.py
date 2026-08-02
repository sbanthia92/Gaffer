"""Google OAuth client registration (authlib) for the sign-in flow in server/main.py."""

from authlib.integrations.starlette_client import OAuth

from server.config import settings

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
