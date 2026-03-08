from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/20260308_05_backfill_embedding_request_builder.py"
)


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_backfill_embedding_request_builder",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_patch_protocol_profiles_injects_openai_builder_when_missing() -> None:
    migration = _load_migration_module()

    protocol_profiles = {
        "embedding": {
            "request": {
                "request_template": {"model": None, "input": None},
                "request_builder": None,
            }
        }
    }

    updated, changed = migration._patch_protocol_profiles("nvidia", protocol_profiles)

    assert changed is True
    assert updated["embedding"]["request"]["request_builder"] == {
        "name": "embedding_request_from_input_items",
        "config": {"mode": "openai"},
    }


def test_patch_protocol_profiles_injects_gemini_builder_for_google_like_provider() -> None:
    migration = _load_migration_module()

    protocol_profiles = {
        "embedding": {
            "request": {
                "request_template": {"model": None, "input": None},
                "request_builder": None,
            }
        }
    }

    updated, changed = migration._patch_protocol_profiles("google", protocol_profiles)

    assert changed is True
    assert updated["embedding"]["request"]["request_builder"] == {
        "name": "embedding_request_from_input_items",
        "config": {"mode": "gemini"},
    }


def test_patch_protocol_profiles_leaves_existing_builder_untouched() -> None:
    migration = _load_migration_module()

    protocol_profiles = {
        "embedding": {
            "request": {
                "request_template": {"model": None, "input": None},
                "request_builder": {
                    "name": "embedding_request_from_input_items",
                    "config": {"mode": "openai"},
                },
            }
        }
    }

    updated, changed = migration._patch_protocol_profiles("openai", protocol_profiles)

    assert changed is False
    assert updated == protocol_profiles


def test_revert_protocol_profiles_only_removes_expected_builder() -> None:
    migration = _load_migration_module()

    protocol_profiles = {
        "embedding": {
            "request": {
                "request_template": {"model": None, "input": None},
                "request_builder": {
                    "name": "embedding_request_from_input_items",
                    "config": {"mode": "openai"},
                },
            }
        }
    }

    updated, changed = migration._revert_protocol_profiles("openai", protocol_profiles)

    assert changed is True
    assert updated["embedding"]["request"]["request_builder"] is None
