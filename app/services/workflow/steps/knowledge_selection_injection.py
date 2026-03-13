"""
KnowledgeSelectionInjectionStep: inject retrieval from explicitly selected docs.

Responsibilities:
- Read `knowledge.doc_ids` from request metadata
- Run scoped retrieval against the user's selected knowledge docs
- Write snippets into workflow context for `template_render`
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from app.schemas.user_document import KnowledgeSearchResult
from app.services.knowledge.user_document_service import UserDocumentService
from app.services.orchestrator.registry import step_registry
from app.services.workflow.steps.base import BaseStep, StepResult, StepStatus

if TYPE_CHECKING:
    from app.services.orchestrator.context import WorkflowContext

logger = logging.getLogger(__name__)


@step_registry.register
class KnowledgeSelectionInjectionStep(BaseStep):
    """
    用户显式知识文件选择注入步骤。

    从上下文读取:
        - validation.request
        - validation.validated
        - conversation.merged_messages

    写入上下文:
        - knowledge_selection.snippets
    """

    name = "knowledge_selection_injection"
    depends_on: ClassVar[list[str]] = ["semantic_kernel"]

    async def execute(self, ctx: WorkflowContext) -> StepResult:
        if ctx.is_external:
            return StepResult(status=StepStatus.SUCCESS, message="skip_external")

        if not ctx.user_id or not ctx.db_session:
            return StepResult(status=StepStatus.SUCCESS, message="missing_user_or_db")

        request = ctx.get("validation", "request")
        validated = ctx.get("validation", "validated") or {}
        selected_doc_ids = self._extract_selected_doc_ids(request, validated)
        if not selected_doc_ids:
            return StepResult(status=StepStatus.SUCCESS, message="no_selected_docs")

        query = self._extract_latest_user_query(ctx, request)
        if not query:
            return StepResult(status=StepStatus.SUCCESS, message="no_query")

        try:
            user_id = UUID(str(ctx.user_id))
        except (TypeError, ValueError):
            logger.warning(
                "knowledge_selection_injection_invalid_user_id trace_id=%s user_id=%s",
                ctx.trace_id,
                ctx.user_id,
            )
            return StepResult(status=StepStatus.SUCCESS, message="invalid_user_id")

        ctx.emit_status(
            stage="remember",
            step=self.name,
            state="running",
            code="knowledge.context.loading",
            meta={"selected_files": len(selected_doc_ids)},
        )

        service = UserDocumentService(ctx.db_session)
        results = await service.search(
            user_id=user_id,
            query=query,
            limit=min(max(len(selected_doc_ids) * 2, 4), 8),
            doc_ids=selected_doc_ids,
        )
        if not results:
            ctx.emit_status(
                stage="remember",
                step=self.name,
                state="success",
                code="knowledge.context.loaded",
                meta={"selected_files": len(selected_doc_ids), "count": 0},
            )
            return StepResult(
                status=StepStatus.SUCCESS,
                message="no_selected_knowledge_hits",
                data={"selected_files": len(selected_doc_ids), "count": 0},
            )

        snippets = [self._serialize_result(item) for item in results if item.text]
        if not snippets:
            return StepResult(status=StepStatus.SUCCESS, message="no_renderable_hits")

        ctx.set("knowledge_selection", "snippets", snippets)
        ctx.emit_status(
            stage="remember",
            step=self.name,
            state="success",
            code="knowledge.context.loaded",
            meta={"selected_files": len(selected_doc_ids), "count": len(snippets)},
        )
        return StepResult(
            status=StepStatus.SUCCESS,
            data={"selected_files": len(selected_doc_ids), "count": len(snippets)},
        )

    @staticmethod
    def _extract_selected_doc_ids(
        request: Any,
        validated: dict[str, Any],
    ) -> list[UUID]:
        metadata = getattr(request, "metadata", None) or validated.get("metadata") or {}
        if not isinstance(metadata, dict):
            return []

        raw_doc_ids = []
        knowledge = metadata.get("knowledge")
        if isinstance(knowledge, dict) and isinstance(knowledge.get("doc_ids"), list):
            raw_doc_ids.extend(knowledge["doc_ids"])
        if isinstance(metadata.get("selected_doc_ids"), list):
            raw_doc_ids.extend(metadata["selected_doc_ids"])

        deduped: list[UUID] = []
        seen: set[UUID] = set()
        for value in raw_doc_ids:
            if not isinstance(value, str):
                continue
            try:
                doc_id = UUID(value.strip())
            except ValueError:
                continue
            if doc_id in seen:
                continue
            seen.add(doc_id)
            deduped.append(doc_id)
        return deduped

    def _extract_latest_user_query(
        self,
        ctx: WorkflowContext,
        request: Any,
    ) -> str | None:
        merged_messages = ctx.get("conversation", "merged_messages")
        if isinstance(merged_messages, list):
            for message in reversed(merged_messages):
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                content = self._extract_text_content(message.get("content"))
                if content:
                    return content

        messages = getattr(request, "messages", None) or []
        for message in reversed(messages):
            role = getattr(message, "role", None)
            if role != "user":
                continue
            content = self._extract_text_content(getattr(message, "content", None))
            if content:
                return content
        return None

    @staticmethod
    def _extract_text_content(content: Any) -> str | None:
        if isinstance(content, str):
            stripped = content.strip()
            if not stripped:
                return None
            if not (stripped.startswith("[") and stripped.endswith("]")):
                return stripped
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
            content = parsed

        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "text":
                    continue
                value = block.get("text") or block.get("content")
                if isinstance(value, str) and value.strip():
                    text_parts.append(value.strip())
            joined = "\n".join(text_parts).strip()
            return joined or None

        if content is None:
            return None

        rendered = str(content).strip()
        return rendered or None

    @staticmethod
    def _serialize_result(item: KnowledgeSearchResult) -> dict[str, Any]:
        return {
            "content": item.text,
            "score": item.score,
            "filename": item.filename,
            "doc_id": item.doc_id,
            "page": item.page,
        }
