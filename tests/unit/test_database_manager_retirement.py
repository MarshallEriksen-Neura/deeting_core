from pathlib import Path


def test_database_manager_legacy_artifacts_removed():
    project_root = Path(__file__).resolve().parents[3]

    skill_registry_task = (
        project_root / "backend" / "app" / "tasks" / "skill_registry.py"
    ).read_text(encoding="utf-8")
    assert "system/database_manager" not in skill_registry_task

    plugin_market_registry_test = (
        project_root / "backend" / "tests" / "api" / "test_plugin_market_registry.py"
    ).read_text(encoding="utf-8")
    assert "official.skills.database" not in plugin_market_registry_test

    official_skill_dir = project_root / "packages" / "official-skills" / "database"
    assert not official_skill_dir.exists()
