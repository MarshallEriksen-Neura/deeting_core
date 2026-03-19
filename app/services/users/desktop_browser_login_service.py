from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, timedelta
from urllib.parse import urlencode
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import DesktopBrowserLoginGrant, DesktopBrowserLoginSession, User
from app.services.users.auth_service import AuthService
from app.services.users.desktop_oauth_service import DesktopOAuthError
from app.utils.time_utils import Datetime

SESSION_STATUS_CREATED = "created"
SESSION_STATUS_COMPLETED = "completed"
SESSION_STATUS_EXCHANGED = "exchanged"
SESSION_STATUS_EXPIRED = "expired"
GRANT_STATUS_ACTIVE = "active"
GRANT_STATUS_CONSUMED = "consumed"
GRANT_STATUS_EXPIRED = "expired"


@dataclass
class DesktopBrowserLoginStartResult:
    session_id: UUID
    expires_in: int


@dataclass
class DesktopBrowserLoginCompleteResult:
    deep_link_url: str


class DesktopBrowserLoginService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.auth_service = AuthService(db)

    async def start_session(
        self,
        *,
        return_scheme: str | None = None,
        client_fingerprint: str | None = None,
    ) -> DesktopBrowserLoginStartResult:
        session = DesktopBrowserLoginSession(
            redirect_scheme=(return_scheme or settings.DESKTOP_OAUTH_CALLBACK_SCHEME).strip()
            or settings.DESKTOP_OAUTH_CALLBACK_SCHEME,
            status=SESSION_STATUS_CREATED,
            client_fingerprint=client_fingerprint,
            expires_at=Datetime.now()
            + timedelta(seconds=settings.DESKTOP_OAUTH_SESSION_TTL_SECONDS),
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return DesktopBrowserLoginStartResult(
            session_id=session.id,
            expires_in=settings.DESKTOP_OAUTH_SESSION_TTL_SECONDS,
        )

    async def complete_session(
        self,
        *,
        session_id: UUID,
        user: User,
    ) -> DesktopBrowserLoginCompleteResult:
        session = await self.db.get(DesktopBrowserLoginSession, session_id)
        if not session:
            raise DesktopOAuthError(
                "Desktop browser login session not found",
                status.HTTP_404_NOT_FOUND,
            )

        self._ensure_session_active(session, allow_completed=True)
        await self._expire_active_grants(session.id)

        raw_grant = secrets.token_urlsafe(32)
        grant = DesktopBrowserLoginGrant(
            session_id=session.id,
            grant_hash=self._hash_secret(raw_grant),
            status=GRANT_STATUS_ACTIVE,
            expires_at=Datetime.now()
            + timedelta(seconds=settings.DESKTOP_OAUTH_GRANT_TTL_SECONDS),
        )
        self.db.add(grant)
        session.user_id = user.id
        session.status = SESSION_STATUS_COMPLETED
        session.completed_at = Datetime.now()
        await self.db.commit()
        return DesktopBrowserLoginCompleteResult(
            deep_link_url=self.build_callback_redirect_url(
                scheme=session.redirect_scheme,
                session_id=session.id,
                grant=raw_grant,
            )
        )

    async def exchange_grant(
        self,
        *,
        session_id: UUID,
        grant: str,
    ):
        session = await self.db.get(DesktopBrowserLoginSession, session_id)
        if not session:
            raise DesktopOAuthError(
                "Desktop browser login session not found",
                status.HTTP_404_NOT_FOUND,
            )

        self._ensure_session_active(session, allow_completed=True)
        grant_row = await self.db.scalar(
            select(DesktopBrowserLoginGrant).where(
                DesktopBrowserLoginGrant.session_id == session.id
            )
        )
        if not grant_row:
            raise DesktopOAuthError(
                "Desktop browser login grant not found",
                status.HTTP_404_NOT_FOUND,
            )

        self._ensure_grant_active(grant_row)
        if grant_row.grant_hash != self._hash_secret(grant):
            raise DesktopOAuthError(
                "Desktop browser login grant invalid",
                status.HTTP_400_BAD_REQUEST,
            )
        if not session.user_id:
            raise DesktopOAuthError(
                "Desktop browser login user not found",
                status.HTTP_404_NOT_FOUND,
            )

        user = await self.db.get(User, session.user_id)
        if not user:
            raise DesktopOAuthError(
                "Desktop browser login user not found",
                status.HTTP_404_NOT_FOUND,
            )

        tokens = await self.auth_service.create_session_tokens(
            user,
            user_agent=f"Deeting Desktop ({session.client_fingerprint or 'desktop'})",
            device_type="desktop",
            device_name="Deeting Desktop",
        )
        grant_row.status = GRANT_STATUS_CONSUMED
        grant_row.consumed_at = Datetime.now()
        session.status = SESSION_STATUS_EXCHANGED
        await self.db.commit()
        return user, tokens

    async def _expire_active_grants(self, session_id: UUID) -> None:
        rows = await self.db.scalars(
            select(DesktopBrowserLoginGrant).where(
                DesktopBrowserLoginGrant.session_id == session_id,
                DesktopBrowserLoginGrant.status == GRANT_STATUS_ACTIVE,
            )
        )
        for row in rows:
            row.status = GRANT_STATUS_EXPIRED

    @staticmethod
    def build_callback_redirect_url(
        *,
        scheme: str,
        session_id: UUID,
        grant: str,
    ) -> str:
        query = urlencode(
            {
                "provider": "browser",
                "session_id": str(session_id),
                "grant": grant,
            }
        )
        return f"{scheme}://auth/callback?{query}"

    @staticmethod
    def _ensure_session_active(
        session: DesktopBrowserLoginSession,
        *,
        allow_completed: bool = False,
    ) -> None:
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < Datetime.now():
            session.status = SESSION_STATUS_EXPIRED
            raise DesktopOAuthError(
                "Desktop browser login session expired",
                status.HTTP_400_BAD_REQUEST,
            )
        allowed = {SESSION_STATUS_CREATED}
        if allow_completed:
            allowed.add(SESSION_STATUS_COMPLETED)
        if session.status not in allowed:
            raise DesktopOAuthError(
                "Desktop browser login session is not active",
                status.HTTP_400_BAD_REQUEST,
            )

    @staticmethod
    def _ensure_grant_active(grant: DesktopBrowserLoginGrant) -> None:
        expires_at = grant.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < Datetime.now():
            grant.status = GRANT_STATUS_EXPIRED
            raise DesktopOAuthError(
                "Desktop browser login grant expired",
                status.HTTP_400_BAD_REQUEST,
            )
        if grant.status != GRANT_STATUS_ACTIVE:
            raise DesktopOAuthError(
                "Desktop browser login grant already consumed",
                status.HTTP_400_BAD_REQUEST,
            )

    @staticmethod
    def _hash_secret(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
