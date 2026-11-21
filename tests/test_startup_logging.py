"""The app's own log lines: what startup writes, and the level setting."""

import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_a_custom_admin_password_never_reaches_the_startup_log(db_engine, monkeypatch, caplog):
    from app import main as app_main

    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(app_main, "async_session", session_factory)
    monkeypatch.setattr(app_main.settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(app_main.settings, "ADMIN_PASSWORD", "s3cret-admin-pw-7f2c")

    with caplog.at_level(logging.DEBUG, logger="github_emulator"):
        await app_main._ensure_admin_user()

    assert "Created admin user: admin" in caplog.text
    assert "s3cret-admin-pw-7f2c" not in caplog.text


def test_an_unknown_log_level_falls_back_to_info(caplog):
    from app import main as app_main

    with caplog.at_level(logging.WARNING, logger="github_emulator"):
        assert app_main._log_level("verbose") == logging.INFO
    assert "Unknown GITHUB_EMULATOR_LOG_LEVEL 'verbose'" in caplog.text
    assert app_main._log_level(" warning ") == logging.WARNING
    assert app_main._log_level("debug") == logging.DEBUG


def test_the_startup_migration_leaves_the_app_logging_alone(tmp_path, caplog):
    # Startup imports app.main, then runs the migrations. Alembic's env.py
    # applied alembic.ini's logging config, which disabled every logger that
    # already existed, the app's own included: nothing it logged after
    # startup reached the server log.
    from app import main as app_main
    from app.migrations import upgrade_database_sync

    root_handlers = list(logging.getLogger().handlers)
    upgrade_database_sync(f"sqlite+aiosqlite:///{tmp_path / 'startup.db'}")

    assert not app_main.logger.disabled
    assert logging.getLogger().handlers == root_handlers
    with caplog.at_level(logging.INFO, logger="github_emulator"):
        app_main.logger.info("still heard after the migration")
    assert "still heard after the migration" in caplog.text


def test_the_alembic_command_line_keeps_existing_loggers(tmp_path):
    # `alembic upgrade` still configures logging from alembic.ini, but does
    # not disable the loggers that exist already.
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    from app import main as app_main

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}")
    root_logger = logging.getLogger()
    saved = (root_logger.level, list(root_logger.handlers))
    try:
        command.upgrade(config, "head")
        assert not app_main.logger.disabled
    finally:
        root_logger.setLevel(saved[0])
        root_logger.handlers[:] = saved[1]


@pytest.mark.asyncio
async def test_startup_logs_how_long_each_phase_took(tmp_path, monkeypatch, caplog):
    # A slow start shows which phase took the time (#107).
    from app import main as app_main
    from app.git import ssh_server

    async def nothing():
        return None

    monkeypatch.setattr(app_main.settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_main.settings, "SEED_DATA", True)
    monkeypatch.setattr(app_main.settings, "MEMORY_WATCH", False)
    monkeypatch.setattr(app_main, "init_db", nothing)
    monkeypatch.setattr(app_main, "_ensure_admin_user", nothing)
    monkeypatch.setattr(ssh_server, "start_ssh_server", nothing)

    with caplog.at_level(logging.INFO, logger="github_emulator"):
        async with app_main.lifespan(None):
            pass

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Startup: ")]
    phases = ["database init (migrations)", "admin user seed", "SSH server"]
    expected = ["Startup: app import done in"]
    for phase in phases:
        expected += [f"Startup: {phase}...", f"Startup: {phase} done in"]
    assert len(lines) == len(expected), lines
    for line, start in zip(lines, expected, strict=True):
        assert line.startswith(start), lines
