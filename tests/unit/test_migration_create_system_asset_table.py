from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/20260310_01_create_system_asset_table.py"
)


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_create_system_asset_table",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_creates_system_asset_table_when_missing(monkeypatch) -> None:
    migration = _load_migration_module()
    created: dict[str, object] = {}
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "f", lambda name: name)
    monkeypatch.setattr(
        migration.sa,
        "inspect",
        lambda _bind: SimpleNamespace(has_table=lambda name: False),
    )

    def fake_create_table(name: str, *columns, **kwargs):
        created["name"] = name
        created["columns"] = columns
        created["kwargs"] = kwargs

    monkeypatch.setattr(migration.op, "create_table", fake_create_table)

    migration.upgrade()

    assert created["name"] == "system_asset"
    column_names = [column.name for column in created["columns"] if isinstance(column, sa.Column)]
    assert column_names == [
        "asset_id",
        "title",
        "description",
        "asset_kind",
        "owner_scope",
        "source_kind",
        "version",
        "status",
        "visibility_scope",
        "local_sync_policy",
        "execution_policy",
        "permission_grants",
        "allowed_role_names",
        "artifact_ref",
        "checksum",
        "metadata_json",
        "created_at",
        "updated_at",
    ]


def test_upgrade_skips_when_system_asset_table_already_exists(monkeypatch) -> None:
    migration = _load_migration_module()
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "f", lambda name: name)
    monkeypatch.setattr(
        migration.sa,
        "inspect",
        lambda _bind: SimpleNamespace(has_table=lambda name: name == "system_asset"),
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("create_table should not be called when the table exists")

    monkeypatch.setattr(migration.op, "create_table", fail_if_called)

    migration.upgrade()