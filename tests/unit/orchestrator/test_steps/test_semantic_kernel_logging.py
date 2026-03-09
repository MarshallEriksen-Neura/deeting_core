from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.orchestrator.context import Channel, WorkflowContext
from app.services.workflow.steps.semantic_kernel import SemanticKernelStep


@pytest.mark.asyncio
async def test_semantic_kernel_logs_disabled_reason(monkeypatch, caplog):
    step = SemanticKernelStep()
    ctx = WorkflowContext(channel=Channel.INTERNAL, user_id="user-1")

    monkeypatch.setattr(
        "app.services.workflow.steps.semantic_kernel.qdrant_is_configured",
        lambda: False,
    )

    with caplog.at_level("INFO"):
        result = await step.execute(ctx)

    assert result.message == "qdrant_disabled"
    usage_logs = [
        record.message
        for record in caplog.records
        if "semantic_kernel_usage" in record.message
    ]
    assert usage_logs
    assert "reason=qdrant_disabled" in usage_logs[-1]
    assert "memory_used=False" in usage_logs[-1]
    assert "semantic_assistant_used=False" in usage_logs[-1]


@pytest.mark.asyncio
async def test_semantic_kernel_logs_memory_and_assistant(monkeypatch, caplog):
    step = SemanticKernelStep()
    ctx = WorkflowContext(channel=Channel.INTERNAL, user_id="user-1")
    ctx.set(
        "validation",
        "request",
        SimpleNamespace(
            messages=[SimpleNamespace(role="user", content="check contract risks")]
        ),
    )

    monkeypatch.setattr(
        "app.services.workflow.steps.semantic_kernel.qdrant_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        step,
        "_search_memories",
        AsyncMock(return_value=[{"id": "mem-1"}, {"id": "mem-2"}]),
    )
    monkeypatch.setattr(
        step,
        "_search_active_persona",
        AsyncMock(
            return_value={
                "assistant_id": "assistant-42",
                "name": "contract-review-assistant",
                "score": 0.93,
                "prompt": "system",
                "skill_tools": [],
            }
        ),
    )

    with caplog.at_level("INFO"):
        result = await step.execute(ctx)

    assert result.status.value == "success"
    usage_logs = [
        record.message
        for record in caplog.records
        if "semantic_kernel_usage" in record.message
    ]
    assert usage_logs
    assert "reason=perception_done" in usage_logs[-1]
    assert "memory_used=True" in usage_logs[-1]
    assert "memory_count=2" in usage_logs[-1]
    assert "semantic_assistant_used=True" in usage_logs[-1]
    assert "semantic_assistant_id=assistant-42" in usage_logs[-1]
    assert ctx.get("assistant", "id") == "assistant-42"
    assert ctx.get("assistant", "name") == "contract-review-assistant"
    assert ctx.get("assistant", "candidates")[0]["assistant_id"] == "assistant-42"


@pytest.mark.asyncio
async def test_semantic_kernel_does_not_override_locked_assistant(monkeypatch):
    step = SemanticKernelStep()
    ctx = WorkflowContext(channel=Channel.INTERNAL, user_id="user-1")
    ctx.set("assistant", "id", "locked-assistant")
    ctx.set("assistant", "name", "locked-name")
    ctx.set(
        "validation",
        "request",
        SimpleNamespace(
            messages=[SimpleNamespace(role="user", content="check contract risks")]
        ),
    )

    monkeypatch.setattr(
        "app.services.workflow.steps.semantic_kernel.qdrant_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(step, "_search_memories", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        step,
        "_search_active_persona",
        AsyncMock(
            return_value={
                "assistant_id": "assistant-42",
                "name": "contract-review-assistant",
                "summary": "semantic assistant",
                "score": 0.93,
                "prompt": "system",
                "skill_tools": [],
            }
        ),
    )

    result = await step.execute(ctx)

    assert result.status.value == "success"
    assert ctx.get("assistant", "id") == "locked-assistant"
    assert ctx.get("assistant", "name") == "locked-name"


@pytest.mark.asyncio
async def test_semantic_kernel_search_prioritizes_boot_and_core_memories(monkeypatch):
    step = SemanticKernelStep()

    class FakeVectorStore:
        async def list_points(self, limit: int, cursor: str | None):
            return (
                [
                    {
                        "id": "mem-boot",
                        "content": "Always answer in Chinese.",
                        "payload": {"is_boot": True, "memory_tier": "core"},
                    },
                    {
                        "id": "mem-core",
                        "content": "User prefers concise answers.",
                        "payload": {
                            "is_core": True,
                            "recall_when": "response style concise",
                        },
                    },
                    {
                        "id": "mem-ignore",
                        "content": "Favorite movie is Interstellar.",
                        "payload": {"is_core": True, "recall_when": "movies only"},
                    },
                ],
                None,
            )

        async def search(self, query: str, limit: int, score_threshold: float):
            return [
                {
                    "id": "mem-core",
                    "content": "User prefers concise answers.",
                    "payload": {"is_core": True},
                    "score": 0.95,
                },
                {
                    "id": "mem-semantic",
                    "content": "Project deadline is Friday.",
                    "payload": {},
                    "score": 0.91,
                },
            ]

    monkeypatch.setattr(
        "app.services.workflow.steps.semantic_kernel.get_qdrant_client",
        lambda: object(),
    )
    monkeypatch.setattr(
        "app.services.workflow.steps.semantic_kernel.QdrantUserVectorService",
        lambda **kwargs: FakeVectorStore(),
    )

    results = await step._search_memories("user-1", "Need a concise response style for this reply")

    assert results is not None
    assert [item["id"] for item in results] == ["mem-boot", "mem-core", "mem-semantic"]
