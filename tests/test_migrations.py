from io import StringIO

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import get_settings


def test_migration_chain_and_offline_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "offline-test-placeholder")
    get_settings.cache_clear()
    output = StringIO()
    config = Config("server/alembic.ini", output_buffer=output)
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0013_realtime_sync"]
    assert scripts.get_revision("0005_modbus_runtime").down_revision == "0004_history"
    assert scripts.get_revision("0004_history").down_revision == "0003_current_values"
    assert scripts.get_revision("0003_current_values").down_revision == "0002_configuration"
    assert scripts.get_revision("0002_configuration").down_revision == "0001_foundation"
    try:
        command.upgrade(config, "head", sql=True)
        sql = output.getvalue()
        for table in (
            "locations",
            "connections",
            "devices",
            "tags",
            "tag_current_values",
            "tag_history",
        ):
            assert f"CREATE TABLE {table}" in sql
        assert "ON DELETE RESTRICT" in sql
        assert "ck_tags_key_format" in sql
        assert "ck_tags_finite_numbers" in sql
        assert "BOOLEAN DEFAULT true" in sql
        assert "uq_devices_connection_slave" in sql
        output.truncate(0)
        output.seek(0)
        command.downgrade(config, "0013_realtime_sync:0001_foundation", sql=True)
        sql = output.getvalue()
        assert sql.index("DROP TABLE tags") < sql.index("DROP TABLE devices")
        assert sql.index("DROP TABLE tag_current_values") < sql.index("DROP TABLE tags")
    finally:
        get_settings.cache_clear()
