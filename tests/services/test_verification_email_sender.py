from __future__ import annotations

import pytest

from app.services.users import verification_email_sender as sender_module
from app.services.users.verification_email_sender import VerificationEmailSender


class _FakeResponse:
    def __init__(self, *, status_code: int = 201, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("POST", "https://api.brevo.com/v3/smtp/email")
            response = httpx.Response(
                self.status_code,
                request=request,
                text=self.text,
            )
            raise httpx.HTTPStatusError(
                "brevo request failed",
                request=request,
                response=response,
            )

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, *, response: _FakeResponse, captured: dict[str, object]):
        self._response = response
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, *, json: dict, headers: dict):
        self._captured["url"] = url
        self._captured["json"] = json
        self._captured["headers"] = headers
        return self._response


@pytest.mark.asyncio
async def test_verification_email_sender_posts_transactional_email_to_brevo(
    monkeypatch,
    settings,
):
    captured: dict[str, object] = {}

    settings.ENVIRONMENT = "production"
    settings.AUTH_EMAIL_PROVIDER = "brevo"
    settings.BREVO_API_KEY = "brevo-key"
    settings.BREVO_API_BASE_URL = "https://api.brevo.com/v3/"
    settings.BREVO_SENDER_EMAIL = "noreply@example.com"
    settings.BREVO_SENDER_NAME = "Deeting"
    settings.BREVO_SANDBOX_MODE = True

    monkeypatch.setattr(
        sender_module,
        "create_async_http_client",
        lambda **_kwargs: _FakeClient(
            response=_FakeResponse(payload={"messageId": "<msg-id>"}),
            captured=captured,
        ),
    )

    await VerificationEmailSender().send_code(
        email="user@example.com",
        code="654321",
        purpose="login",
    )

    payload = captured["json"]
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["headers"] == {
        "accept": "application/json",
        "api-key": "brevo-key",
        "content-type": "application/json",
    }
    assert payload["sender"] == {
        "email": "noreply@example.com",
        "name": "Deeting",
    }
    assert payload["to"] == [{"email": "user@example.com"}]
    assert payload["subject"] == "Deeting 登录验证码"
    assert payload["headers"] == {"X-Sib-Sandbox": "drop"}
    assert "654321" in payload["htmlContent"]
    assert "654321" in payload["textContent"]


@pytest.mark.asyncio
async def test_verification_email_sender_skips_network_in_log_mode(
    monkeypatch,
    settings,
):
    settings.ENVIRONMENT = "production"
    settings.AUTH_EMAIL_PROVIDER = "log"

    monkeypatch.setattr(
        sender_module,
        "create_async_http_client",
        lambda **_kwargs: pytest.fail("network client should not be created"),
    )

    await VerificationEmailSender().send_code(
        email="user@example.com",
        code="123456",
        purpose="login",
    )
