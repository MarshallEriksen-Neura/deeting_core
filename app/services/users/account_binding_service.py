from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models import User
from app.schemas.user import (
    EmailBindingAlias,
    EmailBindingState,
    OAuthBindingState,
    UserBindingsRead,
)
from app.services.users.auth_service import AuthService
from app.services.users.user_provisioning_service import UserProvisioningService
from app.repositories import UserRepository

EMAIL_PROVIDER = "email_code"
OAUTH_PROVIDERS = ("google", "github")
EMAIL_BIND_PURPOSE = "bind_email"


def normalize_login_email(email: str) -> str:
    return str(email or "").strip().lower()


class AccountBindingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.auth_service = AuthService(db)
        self.provisioner = UserProvisioningService(db)

    async def list_user_bindings(self, user: User) -> UserBindingsRead:
        oauth_identities = await self.user_repo.list_identities(
            user.id, providers=list(OAUTH_PROVIDERS)
        )
        email_aliases = await self.user_repo.list_identities(user.id, providers=[EMAIL_PROVIDER])
        oauth = {
            provider: OAuthBindingState(is_bound=False, display_name=None, bound_at=None)
            for provider in OAUTH_PROVIDERS
        }
        for identity in oauth_identities:
            oauth[identity.provider] = OAuthBindingState(
                is_bound=True,
                display_name=identity.display_name,
                bound_at=identity.created_at.isoformat() if identity.created_at else None,
            )

        aliases = [
            EmailBindingAlias(
                email=identity.external_id,
                bound_at=identity.created_at.isoformat() if identity.created_at else None,
            )
            for identity in email_aliases
            if normalize_login_email(identity.external_id)
            != normalize_login_email(user.email)
        ]
        return UserBindingsRead(
            oauth=oauth,
            email=EmailBindingState(primary_email=user.email, aliases=aliases),
        )

    async def send_email_bind_code(
        self,
        *,
        user: User,
        email: str,
        client_ip: str | None = None,
    ) -> str:
        normalized = normalize_login_email(email)
        await self.ensure_email_bindable(user, normalized)
        code = await self.auth_service.send_verification_code(
            normalized, EMAIL_BIND_PURPOSE, client_ip=client_ip
        )
        logger.info(
            "email_binding_code_sent",
            extra={"user_id": str(user.id), "email": normalized},
        )
        return code

    async def confirm_email_bind(
        self,
        *,
        user: User,
        email: str,
        code: str,
        client_ip: str | None = None,
    ) -> bool:
        normalized = normalize_login_email(email)
        if normalize_login_email(user.email) == normalized:
            return False
        await self.ensure_email_bindable(user, normalized)
        ok = await self.auth_service.verify_code(
            normalized,
            code,
            EMAIL_BIND_PURPOSE,
            client_ip=client_ip,
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired code",
            )
        _, created = await self.provisioner.bind_identity_to_user(
            user=user,
            provider=EMAIL_PROVIDER,
            external_id=normalized,
            display_name=normalized,
        )
        return created

    async def resolve_user_by_login_email(self, email: str) -> User | None:
        normalized = normalize_login_email(email)
        identity_user = await self.user_repo.get_by_identity(EMAIL_PROVIDER, normalized)
        if identity_user:
            return identity_user
        return await self.user_repo.get_by_email(normalized)

    async def ensure_email_bindable(self, user: User, normalized_email: str) -> None:
        current_primary = normalize_login_email(user.email)
        if normalized_email == current_primary:
            return

        existing_primary = await self.user_repo.get_by_email(normalized_email)
        if existing_primary and existing_primary.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already belongs to another account",
            )

        existing_identity = await self.user_repo.get_identity(EMAIL_PROVIDER, normalized_email)
        if existing_identity and existing_identity.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already bound to another account",
            )
