from uuid import uuid4

from app.storage.qdrant_kb_collections import (
    get_assistant_collection_name,
    get_infra_candidates_collection_name,
    get_marketplace_collection_name,
    get_semantic_cache_collection_name,
    get_skill_collection_name,
    get_system_capability_tool_collection_name,
    get_system_memory_collection_name,
    get_user_capability_tool_collection_name,
    get_user_memory_collection_name,
)


def test_qdrant_collection_defaults_use_business_quadrant_names(monkeypatch):
    user_id = uuid4()

    monkeypatch.setattr(
        "app.storage.qdrant_kb_collections.settings.QDRANT_KB_SYSTEM_COLLECTION",
        "system_memory",
    )
    monkeypatch.setattr(
        "app.storage.qdrant_kb_collections.settings.QDRANT_KB_CANDIDATES_COLLECTION",
        "infra_candidates",
    )
    monkeypatch.setattr(
        "app.storage.qdrant_kb_collections.settings.QDRANT_KB_USER_COLLECTION",
        "user_memory",
    )
    monkeypatch.setattr(
        "app.storage.qdrant_kb_collections.settings.QDRANT_TOOL_SYSTEM_COLLECTION",
        "system_capability_tools",
    )
    monkeypatch.setattr(
        "app.storage.qdrant_kb_collections.settings.QDRANT_TOOL_USER_COLLECTION_PREFIX",
        "user_capability",
    )
    monkeypatch.setattr(
        "app.storage.qdrant_kb_collections.settings.QDRANT_SKILL_COLLECTION",
        "system_capability_skills",
    )
    monkeypatch.setattr(
        "app.storage.qdrant_kb_collections.settings.QDRANT_ASSISTANT_COLLECTION",
        "system_capability_assistants",
    )
    monkeypatch.setattr(
        "app.storage.qdrant_kb_collections.settings.QDRANT_MARKETPLACE_COLLECTION",
        "system_capability_marketplace",
    )
    monkeypatch.setattr(
        "app.storage.qdrant_kb_collections.settings.QDRANT_SEMANTIC_CACHE_COLLECTION",
        "infra_semantic_cache",
    )

    assert get_system_memory_collection_name() == "system_memory"
    assert get_infra_candidates_collection_name() == "infra_candidates"
    assert get_user_memory_collection_name(user_id).startswith("user_memory_")
    assert get_system_capability_tool_collection_name() == "system_capability_tools"
    assert get_user_capability_tool_collection_name(user_id).startswith(
        "user_capability_"
    )
    assert get_skill_collection_name() == "system_capability_skills"
    assert get_assistant_collection_name() == "system_capability_assistants"
    assert get_marketplace_collection_name() == "system_capability_marketplace"
    assert get_semantic_cache_collection_name() == "infra_semantic_cache"