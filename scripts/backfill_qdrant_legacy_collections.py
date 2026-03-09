import argparse
import asyncio
import os
import sys

from loguru import logger

sys.path.append(os.getcwd())

from app.qdrant_client import close_qdrant_client_for_current_loop, qdrant_is_configured
from app.services.memory.qdrant_collection_migration_service import (
    QdrantCollectionMigrationService,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy Qdrant collections into new quadrant names.")
    parser.add_argument("--system-only", action="store_true", help="Skip user-scoped collections.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--force", action="store_true", help="Execute copy. Without this flag, only print the plan.")
    args = parser.parse_args()

    if not qdrant_is_configured():
        logger.error("Qdrant is not configured. Aborting.")
        return

    service = QdrantCollectionMigrationService()
    plan = await service.build_legacy_backfill_plan(include_user=not args.system_only)
    logger.info("Legacy backfill plan: {}", [f"{it.source}->{it.target}" for it in plan])
    if not args.force:
        logger.warning("Dry-run only. Re-run with --force to execute backfill.")
        return

    try:
        stats = await service.backfill_legacy_collections(
            include_user=not args.system_only,
            batch_size=max(1, min(int(args.batch_size or 100), 100)),
        )
        logger.info("Backfill finished: {}", stats)
    finally:
        await close_qdrant_client_for_current_loop()


if __name__ == "__main__":
    asyncio.run(main())