from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_registry import SkillRegistry
from app.repositories.skill_registry_repository import SkillRegistryRepository
from app.schemas.admin_ops import (
    PluginMarketReviewAdminItem,
    PluginMarketReviewAdminListResponse,
    PluginMarketReviewFinding,
)
from app.utils.time_utils import Datetime


class PluginMarketReviewAdminService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SkillRegistryRepository(db)

    async def list_reviews(
        self, *, skip: int, limit: int, status_filter: str | None = None
    ) -> PluginMarketReviewAdminListResponse:
        skills = await self.repo.list_market_submissions(status_filter=status_filter)
        items = [self._to_item(skill) for skill in skills[skip : skip + limit]]
        return PluginMarketReviewAdminListResponse(
            items=items, total=len(skills), skip=skip, limit=limit
        )

    async def approve_review(
        self, skill_id: str, *, reviewer_user_id: UUID, reason: str | None = None
    ) -> PluginMarketReviewAdminItem:
        skill = await self._get_pending_skill_or_404(skill_id)
        updated = await self.repo.update(
            skill,
            self._build_review_update(
                skill,
                target_status="active",
                reviewer_user_id=reviewer_user_id,
                decision="approved",
                reason=reason or "approved by admin dashboard",
            ),
        )
        return self._to_item(updated)

    async def reject_review(
        self, skill_id: str, *, reviewer_user_id: UUID, reason: str | None = None
    ) -> PluginMarketReviewAdminItem:
        skill = await self._get_pending_skill_or_404(skill_id)
        updated = await self.repo.update(
            skill,
            self._build_review_update(
                skill,
                target_status="rejected",
                reviewer_user_id=reviewer_user_id,
                decision="rejected",
                reason=reason or "rejected by admin dashboard",
            ),
        )
        return self._to_item(updated)

    async def _get_pending_skill_or_404(self, skill_id: str) -> SkillRegistry:
        skill = await self.repo.get_by_id(skill_id)
        if not skill or not self.repo.is_market_submission(skill):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="plugin market submission not found",
            )
        if skill.status != "needs_review":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="plugin market submission is not pending review",
            )
        return skill

    def _build_review_update(
        self,
        skill: SkillRegistry,
        *,
        target_status: str,
        reviewer_user_id: UUID,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        manifest = dict(skill.manifest_json or {})
        ingestion = self._as_dict(manifest.get("deeting_ingestion"))
        ingestion["admin_review"] = {
            "decision": decision,
            "reason": reason,
            "reviewer_user_id": str(reviewer_user_id),
            "reviewed_at": Datetime.to_iso_string(Datetime.utcnow()),
        }
        manifest["deeting_ingestion"] = ingestion
        return {"status": target_status, "manifest_json": manifest}

    def _to_item(self, skill: SkillRegistry) -> PluginMarketReviewAdminItem:
        manifest = skill.manifest_json or {}
        ingestion = self._as_dict(manifest.get("deeting_ingestion"))
        security_review = self._as_dict(ingestion.get("security_review"))
        admin_review = self._as_dict(ingestion.get("admin_review"))
        findings = []
        for finding in security_review.get("findings") or []:
            if isinstance(finding, dict):
                findings.append(
                    PluginMarketReviewFinding(
                        severity=self._as_str(finding.get("severity")),
                        category=self._as_str(finding.get("category")),
                        message=self._as_str(finding.get("message")),
                        file=self._as_str(finding.get("file")),
                    )
                )
        return PluginMarketReviewAdminItem(
            id=skill.id,
            name=skill.name,
            status=skill.status,
            runtime=skill.runtime,
            version=skill.version,
            description=skill.description,
            source_repo=skill.source_repo,
            source_revision=skill.source_revision,
            source_subdir=skill.source_subdir,
            risk_level=skill.risk_level,
            submission_channel=self._as_str(ingestion.get("submission_channel")),
            requires_admin_approval=bool(ingestion.get("requires_admin_approval")),
            submitter_user_id=self._as_str(ingestion.get("submitter_user_id")),
            reviewer_user_id=self._as_str(admin_review.get("reviewer_user_id")),
            reviewed_at=self._parse_datetime(admin_review.get("reviewed_at")),
            review_reason=self._as_str(admin_review.get("reason")),
            security_review_decision=self._as_str(security_review.get("decision")),
            security_review_summary=self._as_str(security_review.get("summary")),
            network_targets=self._string_list(security_review.get("network_targets")),
            destructive_actions=self._string_list(security_review.get("destructive_actions")),
            privacy_risks=self._string_list(security_review.get("privacy_risks")),
            findings=findings,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None]

    @staticmethod
    def _as_str(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value or not isinstance(value, str):
            return None
        try:
            return Datetime.from_iso_string(value)
        except ValueError:
            return None

