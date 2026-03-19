import urllib.parse
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models import Base, DesktopOAuthSession, Identity
from app.services.users import desktop_oauth_service as oauth_desktop_svc
from main import app


def _enable_google(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_ENABLED", True)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "https://api.example.com/api/v1/auth/oauth/google/callback")
    monkeypatch.setattr(settings, "DESKTOP_OAUTH_CALLBACK_SCHEME", "deeting")


def _enable_github(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_OAUTH_ENABLED", True)
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "github-client")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "github-secret")
    monkeypatch.setattr(settings, "GITHUB_REDIRECT_URI", "https://api.example.com/api/v1/auth/oauth/github/callback")
    monkeypatch.setattr(settings, "DESKTOP_OAUTH_CALLBACK_SCHEME", "deeting")


@pytest.mark.asyncio
async def test_desktop_oauth_bind_callback_and_confirm(
    monkeypatch,
    client: AsyncClient,
    AsyncSessionLocal,
    auth_tokens,
):
    _enable_google(monkeypatch)
    from app.core.database import get_db

    prev_overrides = app.dependency_overrides.copy()

    async def _override_get_db():
        async with AsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncSessionLocal() as session:
            async with session.bind.begin() as conn:  # type: ignore[union-attr]
                await conn.run_sync(Base.metadata.create_all)

        async def fake_exchange(cfg, client, *, code, code_verifier):
            return oauth_desktop_svc.ProviderToken(access_token="google-access-token")

        async def fake_profile(cfg, client, access_token):
            return oauth_desktop_svc.ProviderUserProfile(
                external_id="google-bind-user-1",
                email="bind@example.com",
                username="bind-user",
                display_name="Bound Google User",
                avatar_url="https://example.com/avatar.png",
            )

        monkeypatch.setattr(oauth_desktop_svc, "_exchange_provider_code", fake_exchange)
        monkeypatch.setattr(oauth_desktop_svc, "_fetch_provider_profile", fake_profile)

        start = await client.post(
            "/api/v1/auth/oauth/desktop/bind/start",
            headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
            json={"provider": "google", "return_scheme": "deeting", "platform": "desktop"},
        )
        assert start.status_code == 200
        start_data = start.json()
        parsed = urllib.parse.urlparse(start_data["authorize_url"])
        qs = urllib.parse.parse_qs(parsed.query)
        state = qs["state"][0]

        callback = await client.get(
            f"/api/v1/auth/oauth/google/callback?code=test-code&state={state}",
            follow_redirects=False,
        )
        assert callback.status_code == 307
        redirect = callback.headers["location"]
        assert redirect.startswith("deeting://auth/callback?")
        redirect_qs = urllib.parse.parse_qs(urllib.parse.urlparse(redirect).query)
        assert redirect_qs["intent"][0] == "bind"
        grant = redirect_qs["grant"][0]

        confirm = await client.post(
            "/api/v1/auth/oauth/desktop/bind/confirm",
            headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
            json={
                "provider": "google",
                "session_id": start_data["session_id"],
                "state": state,
                "grant": grant,
            },
        )
        assert confirm.status_code == 200
        payload = confirm.json()
        assert payload["provider"] == "google"
        assert payload["is_bound"] is True
        assert payload["display_name"] == "Bound Google User"

        async with AsyncSessionLocal() as session:
            identity = await session.scalar(
                select(Identity).where(
                    Identity.provider == "google",
                    Identity.external_id == "google-bind-user-1",
                )
            )
            assert identity is not None
            oauth_session = await session.get(DesktopOAuthSession, UUID(start_data["session_id"]))
            assert oauth_session is not None
            assert oauth_session.status == oauth_desktop_svc.SESSION_STATUS_EXCHANGED
            assert oauth_session.user_id == identity.user_id
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prev_overrides)


@pytest.mark.asyncio
async def test_desktop_bind_start_rejects_unknown_provider(
    client: AsyncClient, auth_tokens: dict
):
    response = await client.post(
        "/api/v1/auth/oauth/desktop/bind/start",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
        json={"provider": "unknown", "return_scheme": "deeting", "platform": "desktop"},
    )
    assert response.status_code == 404
