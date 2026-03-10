"""Tests for migration framework (not individual migrations)."""

import pytest

from app.migrations import Migration, MIGRATION_REGISTRY


class TestMigration:
    def test_create(self):
        async def dummy(app):
            pass

        m = Migration("test_migration", dummy)
        assert m.name == "test_migration"
        assert m.apply_fn is dummy

    @pytest.mark.asyncio
    async def test_apply(self):
        called = []

        async def fn(app):
            called.append(app)

        m = Migration("test", fn)
        await m.apply("fake_app")
        assert called == ["fake_app"]


class TestMigrationRegistry:
    def test_registry_not_empty(self):
        assert len(MIGRATION_REGISTRY) > 0

    def test_migration_names_unique(self):
        names = [m.name for m in MIGRATION_REGISTRY]
        assert len(names) == len(set(names))

    def test_expected_migrations_present(self):
        names = [m.name for m in MIGRATION_REGISTRY]
        assert "001_archive_2025_events" in names
        assert "002_seed_2026_spring_events" in names
        assert "003_add_guest_fields" in names
        assert "006_bump_moscow_spb_base_price" in names
