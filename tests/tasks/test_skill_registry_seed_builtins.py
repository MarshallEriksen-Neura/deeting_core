from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.skill_registry import SkillRegistry
from app.tasks.skill_registry import _run_seed_builtins

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(autouse=True)
async def ensure_tables():
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.run_sync(Base.metadata.create_all)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def dispose_engine():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_seed_builtins_disables_missing_builtin_skills(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    official_skill_dir = project_root / "packages" / "official-skills" / "crawler"
    official_skill_dir.mkdir(parents=True)
    (official_skill_dir / "deeting.json").write_text(
        json.dumps(
            {
                "id": "official.skills.crawler",
                "name": "Scout Crawler",
                "version": "1.0.0",
                "description": "Crawl websites",
            }
        ),
        encoding="utf-8",
    )

    plugins_yaml = project_root / "backend" / "app" / "core" / "plugins.yaml"
    plugins_yaml.parent.mkdir(parents=True)
    plugins_yaml.write_text("plugins: []\n", encoding="utf-8")

    fake_task_file = project_root / "backend" / "app" / "tasks" / "skill_registry.py"
    fake_task_file.parent.mkdir(parents=True, exist_ok=True)
    fake_task_file.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr("app.tasks.skill_registry.__file__", str(fake_task_file))
    monkeypatch.setattr("app.tasks.skill_registry.AsyncSessionLocal", AsyncSessionLocal)
    monkeypatch.setattr("app.tasks.skill_registry.qdrant_is_configured", lambda: False)

    async with AsyncSessionLocal() as session:
        session.add(
            SkillRegistry(
                id="official.skills.retired",
                name="Retired Skill",
                description="no longer exists on disk",
                version="1.0.0",
                runtime="builtin",
                status="active",
                type="SKILL",
                manifest_json={"id": "official.skills.retired"},
                env_requirements={},
            )
        )
        await session.commit()

    stats = await _run_seed_builtins()

    assert stats["created"] == 1
    assert stats["disabled"] == 1

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SkillRegistry).where(SkillRegistry.id == "official.skills.retired")
        )
        retired_skill = result.scalar_one()
        assert retired_skill.status == "disabled"

        result = await session.execute(
            select(SkillRegistry).where(SkillRegistry.id == "official.skills.crawler")
        )
        crawler_skill = result.scalar_one()
        assert crawler_skill.status == "active"
        assert crawler_skill.runtime == "builtin"
