import uuid

from app.models.knowledge import KnowledgeArtifact
from app.repositories.knowledge_repository import KnowledgeRepository
from app.tasks.knowledge_tasks import index_knowledge_artifact_task


class CrawlerKnowledgeService:
    """
    Service to manage knowledge artifact review workflow.
    """

    def __init__(self, repository: KnowledgeRepository):
        self.repo = repository

    async def approve_artifact(self, artifact_id: uuid.UUID) -> KnowledgeArtifact:
        """
        Admin approves the artifact. Trigger indexing.
        """
        artifact = await self.repo.get(artifact_id)
        if not artifact:
            raise Exception("Artifact not found")

        # Retrieve stored config if any
        embedding_config = artifact.meta_info.get("_embedding_config")

        # Update status
        updated = await self.repo.update(artifact, {"status": "processing"})

        # Trigger Task
        index_knowledge_artifact_task.delay(str(updated.id), embedding_config)

        return updated

    async def reject_artifact(self, artifact_id: uuid.UUID) -> None:
        """
        Admin rejects the artifact. Delete it.
        """
        artifact = await self.repo.get(artifact_id)
        if not artifact:
            return  # Already gone

        await self.repo.delete(artifact.id)
