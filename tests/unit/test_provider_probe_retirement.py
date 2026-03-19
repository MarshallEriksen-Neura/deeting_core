from pathlib import Path


def test_provider_probe_legacy_artifacts_removed():
    project_root = Path(__file__).resolve().parents[3]

    skill_registry_task = (
        project_root / "backend" / "app" / "tasks" / "skill_registry.py"
    ).read_text(encoding="utf-8")
    assert "core.tools.provider_probe" not in skill_registry_task

    official_skill_dir = project_root / "packages" / "official-skills" / "provider_probe"
    assert not official_skill_dir.exists()
