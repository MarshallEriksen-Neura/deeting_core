from app.tasks.skill_registry import ingest_skill_repo


def test_ingest_skill_repo_task(monkeypatch):
    async def fake_run(*_args, **_kwargs):
        return "ok"

    monkeypatch.setattr(
        "app.tasks.skill_registry._run_repo_ingestion",
        fake_run,
    )
    assert ingest_skill_repo("https://example.com/repo.git") == "ok"


def test_ingest_skill_repo_does_not_trigger_dry_run(monkeypatch):
    async def fake_run(*_args, **_kwargs):
        return {"skill_id": "core.tools.docx", "status": "created"}

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("dry run should not be triggered automatically")

    monkeypatch.setattr(
        "app.tasks.skill_registry._run_repo_ingestion",
        fake_run,
    )
    monkeypatch.setattr(
        "app.tasks.skill_registry.dry_run_skill",
        fail_if_called,
    )

    result = ingest_skill_repo("https://example.com/repo.git")

    assert result == {"skill_id": "core.tools.docx", "status": "created"}
