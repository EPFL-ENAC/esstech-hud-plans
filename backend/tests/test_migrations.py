import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text

MIGRATIONS_DIRECTORY = Path(__file__).parents[1] / "migrations" / "versions"


def _load_revision(filename: str) -> ModuleType:
    path = MIGRATIONS_DIRECTORY / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
