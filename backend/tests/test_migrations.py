import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect

MIGRATIONS_DIRECTORY = Path(__file__).parents[1] / "migrations" / "versions"


def _load_revision(filename: str) -> ModuleType:
    path = MIGRATIONS_DIRECTORY / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_building_migration_preserves_users_and_unmanaged_tables() -> None:
    users_revision = _load_revision("2026_09_05_0000-1f9c3a8d7b42_create_users.py")
    buildings_revision = _load_revision(
        "2026_09_06_0001-62f75ed81cd4_create_buildings.py"
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

    inspector = inspect(engine)
    assert {"users", "buildings", "prefect_flow_run"} <= set(
        inspector.get_table_names()
    )
    foreign_keys = inspector.get_foreign_keys("buildings")
    assert foreign_keys[0]["referred_table"] == "users"
    assert foreign_keys[0]["options"] == {"ondelete": "CASCADE"}

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            buildings_revision.downgrade()

    assert set(inspect(engine).get_table_names()) == {"users", "prefect_flow_run"}
