import asyncio
import importlib.util
import os
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

MIGRATIONS_DIRECTORY = Path(__file__).parents[1] / "migrations" / "versions"


def _load_revision(filename: str) -> ModuleType:
    path = MIGRATIONS_DIRECTORY / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pending_upload_migration_generates_reversible_postgres_constraints() -> None:
    revision = _load_revision(
        "2026_10_18_2201-45148aa70325_support_pending_upload_reconstructions.py"
    )
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.upgrade()
        revision.downgrade()
    sql = output.getvalue()
    assert "ADD COLUMN upload_id UUID" in sql
    assert "CREATE INDEX ix_reconstructions_upload_id" in sql
    assert "ON DELETE SET NULL" in sql
    assert "waiting_for_upload" in sql
    assert "DROP CONSTRAINT fk_reconstructions_upload_id" in sql
    assert "DROP COLUMN upload_id" in sql


@pytest.mark.parametrize("has_upload", [True, False])
def test_pending_upload_downgrade_cancels_waiting_reconstructions(
    has_upload: bool,
) -> None:
    database_url = os.environ.get("HUD_TEST_MIGRATION_DB_URL")
    if database_url is None:
        pytest.skip("Set HUD_TEST_MIGRATION_DB_URL to a PostgreSQL asyncpg URL")

    revision = _load_revision(
        "2026_10_18_2201-45148aa70325_support_pending_upload_reconstructions.py"
    )

    def check_downgrade(connection: Connection) -> None:
        schema = f"migration_test_{uuid4().hex}"
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        context = MigrationContext.configure(connection)
        scripts = ScriptDirectory(str(MIGRATIONS_DIRECTORY.parent))
        with Operations.context(context):
            for parent in reversed(
                list(scripts.walk_revisions(base="base", head=revision.down_revision))
            ):
                parent.module.upgrade()
            revision.upgrade()

        metadata = MetaData()
        users = Table("users", metadata, autoload_with=connection)
        buildings = Table("buildings", metadata, autoload_with=connection)
        uploads = Table("user_uploads", metadata, autoload_with=connection)
        reconstructions = Table("reconstructions", metadata, autoload_with=connection)
        original_updated_at = datetime(2020, 1, 1, tzinfo=UTC)
        timestamps = {
            "created_at": original_updated_at,
            "updated_at": original_updated_at,
        }
        user_id, building_id, upload_id, waiting_id = (uuid4() for _ in range(4))
        connection.execute(
            users.insert().values(
                id=user_id, keycloak_sub="migration-test", **timestamps
            )
        )
        connection.execute(
            buildings.insert().values(
                id=building_id,
                user_id=user_id,
                name="Test building",
                latitude=0,
                longitude=0,
                **timestamps,
            )
        )
        connection.execute(
            uploads.insert().values(
                id=upload_id,
                user_id=user_id,
                name="Test upload",
                description="",
                filename="scan.mp4",
                size_bytes=100,
                file_path="scan.mp4",
                status="uploading",
                created_at=original_updated_at,
            )
        )
        statuses = [
            "preparing",
            "scheduled",
            "running",
            "completed",
            "failed",
            "cancelled",
            "crashed",
        ]
        connection.execute(
            reconstructions.insert(),
            [
                {
                    "id": waiting_id if status == "waiting_for_upload" else uuid4(),
                    "building_id": building_id,
                    "upload_id": upload_id if has_upload else None,
                    "status": status,
                    "progress": 0.25,
                    "error_message": None,
                    "settings": {},
                    **timestamps,
                }
                for status in ["waiting_for_upload", *statuses]
            ],
        )
        remaining_columns = [
            column for column in reconstructions.c if column.name != "upload_id"
        ]
        query = reconstructions.select().with_only_columns(*remaining_columns)
        before = {row.id: dict(row) for row in connection.execute(query).mappings()}

        with Operations.context(context):
            revision.downgrade()

        after = {row.id: dict(row) for row in connection.execute(query).mappings()}
        assert after[waiting_id] == {
            **before[waiting_id],
            "status": "cancelled",
            "error_message": (
                "Cancelled by database downgrade: pending uploads are no longer supported"
            ),
            "updated_at": after[waiting_id]["updated_at"],
        }
        assert after[waiting_id]["updated_at"] > original_updated_at
        assert {key: row for key, row in after.items() if key != waiting_id} == {
            key: row for key, row in before.items() if key != waiting_id
        }
        assert "upload_id" not in {
            column["name"]
            for column in inspect(connection).get_columns("reconstructions")
        }
        with pytest.raises(IntegrityError, match="ck_reconstructions_status"):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE reconstructions SET status = 'waiting_for_upload'"),
                )

    async def run() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.run_sync(check_downgrade)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_application_migrations_preserve_parent_and_unmanaged_tables() -> None:
    users_revision = _load_revision("2026_09_05_0000-1f9c3a8d7b42_create_users.py")
    buildings_revision = _load_revision(
        "2026_09_06_0001-62f75ed81cd4_create_buildings.py"
    )
    reconstructions_revision = _load_revision(
        "2026_09_07_0002-9d4d5e0f61a8_create_reconstructions.py"
    )
    optional_metadata_revision = _load_revision(
        "2026_09_07_0003-a42f9d8e7c31_make_building_metadata_optional.py"
    )
    latest_reconstruction_revision = _load_revision(
        "2026_09_08_0004-b51e8c2d7a90_index_latest_reconstruction.py"
    )
    assert (
        latest_reconstruction_revision.down_revision
        == optional_metadata_revision.revision
    )
    engine = create_engine("sqlite://")

    unmanaged_metadata = MetaData()
    Table(
        "prefect_flow_run",
        unmanaged_metadata,
        Column("id", Integer, primary_key=True),
    )
    unmanaged_metadata.create_all(engine)

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            users_revision.upgrade()
            buildings_revision.upgrade()
            reconstructions_revision.upgrade()
            optional_metadata_revision.upgrade()
            latest_reconstruction_revision.upgrade()

    inspector = inspect(engine)
    indexes = {
        index["name"]: index["column_names"]
        for index in inspector.get_indexes("reconstructions")
    }
    assert indexes["ix_reconstructions_building_created_id"] == [
        "building_id",
        "created_at",
        "id",
    ]
    assert {"users", "buildings", "reconstructions", "prefect_flow_run"} <= set(
        inspector.get_table_names()
    )
    foreign_keys = inspector.get_foreign_keys("buildings")
    assert foreign_keys[0]["referred_table"] == "users"
    assert foreign_keys[0]["options"] == {"ondelete": "CASCADE"}
    reconstruction_foreign_keys = inspector.get_foreign_keys("reconstructions")
    assert reconstruction_foreign_keys[0]["referred_table"] == "buildings"
    assert reconstruction_foreign_keys[0]["options"] == {"ondelete": "CASCADE"}
    constraint_names = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("reconstructions")
    }
    assert constraint_names == {
        "ck_reconstructions_progress_range",
        "ck_reconstructions_status",
    }
    building_columns = {
        column["name"]: column for column in inspector.get_columns("buildings")
    }
    assert building_columns["latitude"]["nullable"] is True
    assert building_columns["longitude"]["nullable"] is True
    building_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("buildings")
    }
    assert "ck_buildings_coordinates_complete" in building_constraints
    assert "ck_buildings_name_nonempty" not in building_constraints

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, keycloak_sub, created_at, updated_at) "
                "VALUES ('00000000000000000000000000000001', 'subject', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO buildings "
                "(id, user_id, name, latitude, longitude, created_at, updated_at) "
                "VALUES ('00000000000000000000000000000002', "
                "'00000000000000000000000000000001', '', NULL, NULL, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            latest_reconstruction_revision.downgrade()
            optional_metadata_revision.downgrade()

        converted = connection.execute(
            text("SELECT name, latitude, longitude FROM buildings")
        ).one()
        assert converted == ("Unnamed building", 0.0, 0.0)

    assert "ix_reconstructions_building_created_id" not in {
        index["name"] for index in inspect(engine).get_indexes("reconstructions")
    }

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            reconstructions_revision.downgrade()

    assert set(inspect(engine).get_table_names()) == {
        "users",
        "buildings",
        "prefect_flow_run",
    }

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            buildings_revision.downgrade()

    assert set(inspect(engine).get_table_names()) == {"users", "prefect_flow_run"}
