from __future__ import annotations

import logging

from app.core.celery_app import celery_app
from app.qdrant_client import qdrant_is_configured
from app.services.memory.qdrant_collection_migration_service import (
    QdrantCollectionMigrationService,
)
from app.tasks.async_runner import run_async

logger = logging.getLogger(__name__)


async def _run_backfill_legacy_collections(include_user: bool = True) -> dict[str, int]:
    service = QdrantCollectionMigrationService()
    return await service.backfill_legacy_collections(include_user=include_user)


@celery_app.task(name="qdrant.backfill_legacy_collections")
def backfill_legacy_collections_task(include_user: bool = True) -> dict[str, int] | str:
    if not qdrant_is_configured():
        return "skipped"
    try:
        return run_async(_run_backfill_legacy_collections(include_user=include_user))
    except Exception as exc:
        logger.exception("qdrant_backfill_legacy_collections_failed: %s", exc)
        return "failed"