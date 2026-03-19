from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.cache import cache
from app.core.cache_keys import CacheKeys
from app.services.users import auth_service as auth_service_module
from app.services.users.auth_service import AuthService


class _FailingSender:
    async def send_code(self, **_kwargs) -> None:
        raise auth_service_module.VerificationEmailDeliveryError("delivery failed")


@pytest.mark.asyncio
async def test_send_verification_code_clears_cached_code_when_delivery_fails(
    monkeypatch,
):
    email = "delivery-fail@example.com"
    key = CacheKeys.verify_code(email, "login")

    await cache.delete(key)
    monkeypatch.setattr(auth_service_module, "VerificationEmailSender", _FailingSender)
    monkeypatch.setattr(AuthService, "_is_dev_env", lambda self: False)

    service = AuthService(None)

    with pytest.raises(HTTPException) as exc_info:
        await service.send_verification_code(email, "login")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Verification email delivery failed"
    assert await cache.get(key) is None
