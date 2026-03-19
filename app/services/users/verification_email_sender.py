from __future__ import annotations

from html import escape

import httpx

from app.core.config import settings
from app.core.http_client import create_async_http_client
from app.core.logging import logger


class VerificationEmailDeliveryError(RuntimeError):
    """Raised when a verification email cannot be delivered."""


class VerificationEmailSender:
    """Send auth verification emails through the configured provider."""

    async def send_code(self, *, email: str, code: str, purpose: str) -> None:
        environment = settings.ENVIRONMENT.lower()
        provider = (settings.AUTH_EMAIL_PROVIDER or "log").strip().lower()

        if environment == "test" or provider == "log":
            logger.info(
                "verification_email_delivery_skipped",
                extra={
                    "email": email,
                    "purpose": purpose,
                    "provider": provider,
                    "environment": environment,
                },
            )
            return

        if provider != "brevo":
            raise VerificationEmailDeliveryError(
                f"Unsupported verification email provider: {provider}"
            )

        await self._send_via_brevo(email=email, code=code, purpose=purpose)

    async def _send_via_brevo(self, *, email: str, code: str, purpose: str) -> None:
        if not settings.BREVO_API_KEY:
            raise VerificationEmailDeliveryError("BREVO_API_KEY is not configured")
        if not settings.BREVO_SENDER_EMAIL:
            raise VerificationEmailDeliveryError("BREVO_SENDER_EMAIL is not configured")

        message = self._build_message(code=code, purpose=purpose)
        payload: dict[str, object] = {
            "sender": {
                "email": settings.BREVO_SENDER_EMAIL,
                "name": settings.BREVO_SENDER_NAME,
            },
            "to": [{"email": email}],
            "subject": message["subject"],
            "htmlContent": message["html_content"],
            "textContent": message["text_content"],
        }
        if settings.BREVO_SANDBOX_MODE:
            payload["headers"] = {"X-Sib-Sandbox": "drop"}

        url = f"{settings.BREVO_API_BASE_URL.rstrip('/')}/smtp/email"
        headers = {
            "accept": "application/json",
            "api-key": settings.BREVO_API_KEY,
            "content-type": "application/json",
        }

        try:
            async with create_async_http_client(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise VerificationEmailDeliveryError(
                f"Brevo request failed status={exc.response.status_code} body={body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise VerificationEmailDeliveryError(
                f"Brevo request failed: {exc}"
            ) from exc

        message_id = None
        try:
            message_id = response.json().get("messageId")
        except Exception:
            message_id = None

        logger.info(
            "verification_email_delivered",
            extra={
                "email": email,
                "purpose": purpose,
                "provider": "brevo",
                "message_id": message_id,
            },
        )

    def _build_message(self, *, code: str, purpose: str) -> dict[str, str]:
        expires_in_minutes = max(1, (settings.VERIFICATION_CODE_TTL_SECONDS + 59) // 60)
        action = {
            "login": "登录",
            "activate": "激活账号",
        }.get(purpose, "验证身份")
        subject = {
            "login": "Deeting 登录验证码",
            "activate": "Deeting 激活验证码",
        }.get(purpose, "Deeting 验证码")
        safe_code = escape(code)

        text_content = (
            f"你的 Deeting {action}验证码是：{code}\n"
            f"该验证码将在 {expires_in_minutes} 分钟后失效。\n"
            "如果这不是你的操作，请忽略这封邮件。"
        )
        html_content = f"""
<html>
  <body style="font-family: Arial, sans-serif; color: #111827;">
    <p>你好，</p>
    <p>你的 Deeting {action}验证码如下：</p>
    <p style="font-size: 28px; font-weight: 700; letter-spacing: 6px;">{safe_code}</p>
    <p>该验证码将在 {expires_in_minutes} 分钟后失效。</p>
    <p>如果这不是你的操作，请忽略这封邮件。</p>
  </body>
</html>
""".strip()

        return {
            "subject": subject,
            "text_content": text_content,
            "html_content": html_content,
        }
