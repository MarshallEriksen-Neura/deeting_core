from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Identity, User
from app.utils.security import decode_token, get_password_hash


def _auth_headers(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.mark.asyncio
async def test_get_my_bindings_returns_primary_email_and_oauth_slots(
    client: AsyncClient,
    auth_tokens: dict,
    test_user: dict,
):
    response = await client.get(
        "/api/v1/users/me/bindings",
        headers=_auth_headers(auth_tokens),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["oauth"]["google"]["is_bound"] is False
    assert payload["oauth"]["github"]["is_bound"] is False
    assert payload["email"]["primary_email"] == test_user["email"]
    assert payload["email"]["aliases"] == []


@pytest.mark.asyncio
async def test_bind_email_alias_then_login_with_alias_returns_same_user(
    client: AsyncClient,
    auth_tokens: dict,
    test_user: dict,
):
    alias_email = "alias@example.com"

    send_code = await client.post(
        "/api/v1/users/me/bindings/email/send-code",
        headers=_auth_headers(auth_tokens),
        json={"email": alias_email},
    )
    assert send_code.status_code == 200

    confirm = await client.post(
        "/api/v1/users/me/bindings/email/confirm",
        headers=_auth_headers(auth_tokens),
        json={"email": alias_email, "code": "123456"},
    )
    assert confirm.status_code == 200

    bindings = await client.get(
        "/api/v1/users/me/bindings",
        headers=_auth_headers(auth_tokens),
    )
    assert bindings.status_code == 200
    aliases = bindings.json()["email"]["aliases"]
    assert [item["email"] for item in aliases] == [alias_email]

    await client.post(
        "/api/v1/auth/login/code",
        json={"email": alias_email, "captcha_token": "test-token"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": alias_email, "code": "123456"},
    )
    assert login.status_code == 200

    token_payload = decode_token(login.json()["access_token"])
    assert UUID(token_payload["sub"]) == UUID(test_user["id"])


@pytest.mark.asyncio
async def test_bind_email_alias_rejects_email_owned_by_another_account(
    client: AsyncClient,
    auth_tokens: dict,
):
    response = await client.post(
        "/api/v1/users/me/bindings/email/send-code",
        headers=_auth_headers(auth_tokens),
        json={"email": "inactive@example.com"},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_bind_email_alias_rejects_existing_email_identity_on_other_account(
    client: AsyncClient,
    auth_tokens: dict,
    AsyncSessionLocal,
):
    conflict_email = "bound-alias@example.com"

    async with AsyncSessionLocal() as session:
        other_user = User(
            email="other-account@example.com",
            hashed_password=get_password_hash("testPassword123"),
            username="Other Account",
            is_active=True,
        )
        session.add(other_user)
        await session.flush()
        session.add(
            Identity(
                user_id=other_user.id,
                provider="email_code",
                external_id=conflict_email,
                display_name=conflict_email,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/users/me/bindings/email/send-code",
        headers=_auth_headers(auth_tokens),
        json={"email": conflict_email},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_get_my_bindings_reflects_linked_oauth_identity(
    client: AsyncClient,
    auth_tokens: dict,
    test_user: dict,
    AsyncSessionLocal,
):
    async with AsyncSessionLocal() as session:
        session.add(
            Identity(
                user_id=UUID(test_user["id"]),
                provider="google",
                external_id="google-user-1",
                display_name="Bound Google User",
            )
        )
        await session.commit()

    response = await client.get(
        "/api/v1/users/me/bindings",
        headers=_auth_headers(auth_tokens),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["oauth"]["google"]["is_bound"] is True
    assert payload["oauth"]["google"]["display_name"] == "Bound Google User"
    assert payload["oauth"]["github"]["is_bound"] is False
