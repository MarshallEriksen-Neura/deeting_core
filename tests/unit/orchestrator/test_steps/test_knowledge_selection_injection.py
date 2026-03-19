from uuid import uuid4

import pytest

from app.schemas.gateway import ChatCompletionRequest, ChatMessage
from app.schemas.user_document import KnowledgeSearchResult
from app.services.orchestrator.context import Channel, WorkflowContext
from app.services.workflow.steps.base import StepStatus
from app.services.workflow.steps.knowledge_selection_injection import (
    KnowledgeSelectionInjectionStep,
)


def test_extract_selected_doc_ids_prefers_metadata_knowledge_doc_ids():
    first_id = uuid4()
    second_id = uuid4()
    request = ChatCompletionRequest(
        model="gpt-5",
        messages=[ChatMessage(role="user", content="hello")],
        metadata={
            "knowledge": {
                "doc_ids": [str(first_id), str(second_id), "bad-id", str(first_id)],
            }
        },
    )

    doc_ids = KnowledgeSelectionInjectionStep._extract_selected_doc_ids(request, {})

    assert doc_ids == [first_id, second_id]


@pytest.mark.asyncio
async def test_execute_stores_selected_knowledge_snippets(monkeypatch):
    request = ChatCompletionRequest(
        model="gpt-5",
        messages=[ChatMessage(role="user", content="总结一下合同付款条款")],
        metadata={"knowledge": {"doc_ids": [str(uuid4())]}},
    )
    ctx = WorkflowContext(
        channel=Channel.INTERNAL,
        user_id=str(uuid4()),
        db_session=object(),
    )
    ctx.set("validation", "request", request)
    ctx.set("validation", "validated", request.model_dump(exclude_none=True))

    async def fake_search(self, *, user_id, query, limit, doc_ids):
        assert query == "总结一下合同付款条款"
        assert limit >= 4
        assert len(doc_ids) == 1
        return [
            KnowledgeSearchResult(
                score=0.93,
                text="付款周期为验收后 30 天。",
                filename="合同A.pdf",
                page=2,
                doc_id=str(doc_ids[0]),
            )
        ]

    monkeypatch.setattr(
        "app.services.knowledge.user_document_service.UserDocumentService.search",
        fake_search,
    )

    step = KnowledgeSelectionInjectionStep()
    result = await step.execute(ctx)

    assert result.status == StepStatus.SUCCESS
    snippets = ctx.get("knowledge_selection", "snippets")
    assert snippets == [
        {
            "content": "付款周期为验收后 30 天。",
            "score": 0.93,
            "filename": "合同A.pdf",
            "doc_id": snippets[0]["doc_id"],
            "page": 2,
        }
    ]
