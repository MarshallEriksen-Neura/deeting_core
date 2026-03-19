from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps.auth import get_current_active_user
from app.models import User
from app.qdrant_client import get_qdrant_client, qdrant_is_configured
from app.repositories.memory_snapshot_repository import MemorySnapshotRepository
from app.schemas.memory import (
    MemoryItem,
    MemoryListResponse,
    MemoryRollbackRequest,
    MemoryRollbackResponse,
    MemorySnapshotListResponse,
    MemoryUpdateRequest,
)
from app.services.memory.management_service import MemoryManagementService
from app.services.vector.qdrant_user_service import QdrantUserVectorService

router = APIRouter(prefix="/memory", tags=["User Memory"])


async def get_vector_memory_service(
    current_user: User = Depends(get_current_active_user),
) -> QdrantUserVectorService:
    """
    Dependency to get the QdrantUserVectorService for the current user.
    """
    if not qdrant_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory service (Qdrant) is not configured.",
        )

    client = get_qdrant_client()
    return QdrantUserVectorService(
        client=client,
        user_id=current_user.id,
        plugin_id=None,  # Access all user memories regardless of plugin
        embedding_model=None,
        enforce_embedding_model_scope=False,
        fail_open=False,  # We want errors in the management API
    )


async def get_memory_service(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    vector_service: QdrantUserVectorService = Depends(get_vector_memory_service),
) -> MemoryManagementService:
    return MemoryManagementService(
        user_id=current_user.id,
        vector_service=vector_service,
        snapshot_repository=MemorySnapshotRepository(db),
        session=db,
    )


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, description="Pagination cursor"),
    service: MemoryManagementService = Depends(get_memory_service),
) -> MemoryListResponse:
    """
    List user's memory entries (paginated).
    """
    return await service.list_memories(limit=limit, cursor=cursor)


@router.get("/search", response_model=list[MemoryItem])
async def search_memories(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(5, ge=1, le=50),
    service: MemoryManagementService = Depends(get_memory_service),
) -> list[MemoryItem]:
    """
    Semantic memory search with vitality-aware reranking.
    Over-fetches 3x, applies vitality decay rerank, returns top-K.
    """
    return await service.search_memories(query=q, limit=limit)


@router.patch("/{memory_id}", response_model=MemoryItem)
async def update_memory(
    memory_id: str,
    request: MemoryUpdateRequest,
    service: MemoryManagementService = Depends(get_memory_service),
):
    """
    Update a specific memory entry's content.
    This will re-embed the content and update the vector store.
    Records a snapshot for audit trail before updating.
    """
    return await service.update_memory(memory_id=memory_id, request=request)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    service: MemoryManagementService = Depends(get_memory_service),
):
    """
    Delete a specific memory entry.
    Records a snapshot for audit trail before deleting.
    """
    await service.delete_memory(memory_id=memory_id)
    return None


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_memories(
    service: MemoryManagementService = Depends(get_memory_service),
):
    """
    Clear ALL user memories.
    """
    await service.clear_memories()
    return None


# --- Snapshot & Rollback Endpoints ---


@router.get("/{memory_id}/snapshots", response_model=MemorySnapshotListResponse)
async def list_memory_snapshots(
    memory_id: str,
    limit: int = Query(20, ge=1, le=100),
    service: MemoryManagementService = Depends(get_memory_service),
) -> MemorySnapshotListResponse:
    """
    List audit trail snapshots for a specific memory entry.
    """
    return await service.list_snapshots(memory_id=memory_id, limit=limit)


@router.post("/{memory_id}/rollback", response_model=MemoryRollbackResponse)
async def rollback_memory(
    memory_id: str,
    request: MemoryRollbackRequest,
    service: MemoryManagementService = Depends(get_memory_service),
) -> MemoryRollbackResponse:
    """
    Rollback a memory to a previous snapshot state.
    Restores old_content from the snapshot and re-embeds.
    """
    return await service.rollback_memory(memory_id=memory_id, request=request)
