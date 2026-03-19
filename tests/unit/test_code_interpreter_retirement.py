from pathlib import Path


def test_code_interpreter_legacy_artifacts_removed():
    project_root = Path(__file__).resolve().parents[3]

    skill_registry_task = (
        project_root / "backend" / "app" / "tasks" / "skill_registry.py"
    ).read_text(encoding="utf-8")
    assert "system.code_interpreter" not in skill_registry_task

    skill_resolver = (
        project_root / "backend" / "app" / "services" / "assistant" / "skill_resolver.py"
    ).read_text(encoding="utf-8")
    assert "official.skills.code_interpreter" not in skill_resolver

    official_skill_dir = project_root / "packages" / "official-skills" / "code_interpreter"
    assert not official_skill_dir.exists()
