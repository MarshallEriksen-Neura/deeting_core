import argparse
import asyncio
import os
import sys
from pathlib import Path
from collections.abc import Iterable

from loguru import logger
from sqlalchemy import text, func, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal
from app.models.assistant import Assistant
from app.models.assistant_install import AssistantInstall
from app.models.skill_registry import SkillRegistry
from app.qdrant_client import close_qdrant_client_for_current_loop, get_qdrant_client, qdrant_is_configured
from app.services.assistant.constants import ASSISTANT_COLLECTION_NAME
from app.services.memory.qdrant_service import COLLECTION_PLUGIN_MARKETPLACE, system_qdrant
from app.services.system_assets import SystemAssetRegistryService
from app.storage.qdrant_kb_collections import get_marketplace_collection_name, get_skill_collection_name
from app.tasks.assistant import _run_sync_assistant
from app.tasks.skill_registry import _run_sync_skill


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = (item or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _projection_collection_names() -> list[str]:
    return _unique(
        [
            ASSISTANT_COLLECTION_NAME,
            get_skill_collection_name(),
            get_marketplace_collection_name(),
            "expert_network",
            "skill_registry",
            "plugin_marketplace",
        ]
    )


async def _collection_exists(name: str) -> bool:
    client = get_qdrant_client()
    resp = await client.get(f"/collections/{name}")
    return resp.status_code == 200


async def _delete_collection_if_exists(name: str) -> bool:
    client = get_qdrant_client()
    resp = await client.delete(f"/collections/{name}")
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    return True


async def _db_projection_stats() -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT COALESCE(metadata_json->>'registry_entity','<null>') AS registry_entity,
                       asset_kind,
                       COUNT(*) AS count
                FROM system_asset
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            )
        )
        system_asset_rows = [
            {
                "registry_entity": row.registry_entity,
                "asset_kind": row.asset_kind,
                "count": int(row.count),
            }
            for row in result
        ]

        assistant_install_count = await session.scalar(
            select(func.count()).select_from(AssistantInstall)
        )
        system_assistant_count = await session.scalar(
            select(func.count()).select_from(Assistant).where(Assistant.owner_user_id.is_(None))
        )
        active_skill_count = await session.scalar(
            select(func.count()).select_from(SkillRegistry).where(SkillRegistry.status == "active")
        )
        return {
            "system_asset": system_asset_rows,
            "assistant_install_count": int(assistant_install_count or 0),
            "system_assistant_count": int(system_assistant_count or 0),
            "active_skill_count": int(active_skill_count or 0),
        }


async def _wipe_projection_rows(*, drop_assistant_installs: bool) -> dict:
    async with AsyncSessionLocal() as session:
        delete_system_assets = await session.execute(
            text(
                """
                DELETE FROM system_asset
                WHERE COALESCE(metadata_json->>'registry_entity','') IN ('assistant', 'skill')
                """
            )
        )
        deleted_assistant_installs = 0
        if drop_assistant_installs:
            delete_result = await session.execute(text("DELETE FROM assistant_install"))
            deleted_assistant_installs = int(delete_result.rowcount or 0)
        await session.commit()
        return {
            "deleted_system_asset_rows": int(delete_system_assets.rowcount or 0),
            "deleted_assistant_install_rows": deleted_assistant_installs,
        }


async def _rebuild_system_asset_rows() -> None:
    async with AsyncSessionLocal() as session:
        service = SystemAssetRegistryService(session)
        await service.sync_projection_sources()


async def _rebuild_qdrant_projection_collections() -> dict:
    deleted: list[str] = []
    if not qdrant_is_configured():
        return {"deleted_collections": deleted, "reindexed_assistants": 0, "reindexed_skills": 0}

    for name in _projection_collection_names():
        if await _delete_collection_if_exists(name):
            logger.info("Deleted Qdrant projection collection: {}", name)
            deleted.append(name)

    await system_qdrant.initialize_collections()

    async with AsyncSessionLocal() as session:
        assistant_rows = await session.execute(
            select(Assistant.id).where(Assistant.owner_user_id.is_(None))
        )
        assistant_ids = [row for row in assistant_rows.scalars().all()]

        skill_rows = await session.execute(
            select(SkillRegistry.id).where(SkillRegistry.status == "active")
        )
        skill_ids = [str(row) for row in skill_rows.scalars().all()]

    for assistant_id in assistant_ids:
        await _run_sync_assistant(assistant_id)
    for skill_id in skill_ids:
        await _run_sync_skill(skill_id)

    return {
        "deleted_collections": deleted,
        "reindexed_assistants": len(assistant_ids),
        "reindexed_skills": len(skill_ids),
    }


async def _qdrant_projection_stats() -> dict:
    if not qdrant_is_configured():
        return {"enabled": False}

    client = get_qdrant_client()
    stats: dict[str, object] = {"enabled": True, "collections": {}}
    for name in _projection_collection_names():
        if not await _collection_exists(name):
            stats["collections"][name] = {"exists": False}
            continue
        resp = await client.post(f"/collections/{name}/points/count", json={"exact": True})
        resp.raise_for_status()
        count = resp.json().get("result", {}).get("count", 0)
        stats["collections"][name] = {"exists": True, "count": int(count or 0)}
    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild assistant/skill system-asset projections and Qdrant projection collections."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Apply destructive changes. Without this flag, only print current stats.",
    )
    parser.add_argument(
        "--drop-assistant-installs",
        action="store_true",
        help="Also delete all assistant_install rows as part of the new default-assistant model.",
    )
    args = parser.parse_args()

    before_db = await _db_projection_stats()
    before_qdrant = await _qdrant_projection_stats()
    logger.info("Current DB projection stats: {}", before_db)
    logger.info("Current Qdrant projection stats: {}", before_qdrant)

    if not args.force:
        logger.warning(
            "Dry-run only. Re-run with --force to wipe projection rows/collections and rebuild."
        )
        if before_db["assistant_install_count"] and not args.drop_assistant_installs:
            logger.warning(
                "assistant_install rows still exist ({}). Pass --drop-assistant-installs to delete them.",
                before_db["assistant_install_count"],
            )
        return

    wipe_stats = await _wipe_projection_rows(
        drop_assistant_installs=bool(args.drop_assistant_installs)
    )
    logger.info("Wiped DB projection rows: {}", wipe_stats)

    await _rebuild_system_asset_rows()
    logger.info("Rebuilt system_asset projection rows from assistant + skill registries.")

    qdrant_rebuild_stats = await _rebuild_qdrant_projection_collections()
    logger.info("Rebuilt Qdrant projection collections: {}", qdrant_rebuild_stats)

    after_db = await _db_projection_stats()
    after_qdrant = await _qdrant_projection_stats()
    logger.info("Post-rebuild DB projection stats: {}", after_db)
    logger.info("Post-rebuild Qdrant projection stats: {}", after_qdrant)

    await close_qdrant_client_for_current_loop()


if __name__ == "__main__":
    asyncio.run(main())
