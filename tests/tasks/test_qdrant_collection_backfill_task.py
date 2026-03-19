from app.tasks.qdrant_collections import backfill_legacy_collections_task


def test_backfill_legacy_collections_task_skips_without_qdrant(monkeypatch):
    monkeypatch.setattr(
        "app.tasks.qdrant_collections.qdrant_is_configured",
        lambda: False,
    )
    assert backfill_legacy_collections_task() == "skipped"


def test_backfill_legacy_collections_task_returns_stats(monkeypatch):
    async def fake_run(*_args, **_kwargs):
        return {"planned_collections": 2, "copied_collections": 1, "copied_points": 4}

    monkeypatch.setattr(
        "app.tasks.qdrant_collections.qdrant_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.tasks.qdrant_collections._run_backfill_legacy_collections",
        fake_run,
    )

    assert backfill_legacy_collections_task() == {
        "planned_collections": 2,
        "copied_collections": 1,
        "copied_points": 4,
    }