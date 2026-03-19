from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DesktopBrowserLoginSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """桌面端浏览器代理登录会话。"""

    __tablename__ = "desktop_browser_login_session"

    redirect_scheme: Mapped[str] = mapped_column(String(64), nullable=False, default="deeting")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="created")
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("user_account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    client_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DesktopBrowserLoginGrant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """桌面端浏览器代理登录一次性兑换凭据。"""

    __tablename__ = "desktop_browser_login_grant"

    session_id: Mapped[uuid.UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("desktop_browser_login_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grant_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["DesktopBrowserLoginSession", "DesktopBrowserLoginGrant"]
