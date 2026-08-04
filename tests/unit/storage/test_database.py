"""Tests for SQLAlchemy setup and transaction behavior."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from retailflow.storage.database import Database
from retailflow.storage.models import RunRecordORM, RunStatus


def _orm_record(run_id: str) -> RunRecordORM:
    return RunRecordORM(
        run_id=run_id,
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        status=RunStatus.PENDING.value,
        reporting_period_start=date(2025, 1, 1),
        reporting_period_end=date(2025, 1, 31),
        source_filenames={},
        source_row_counts={},
        configuration_snapshot={},
        application_version="0.1.0",
    )


def test_database_file_and_table_are_created(tmp_path: Path) -> None:
    database_path = tmp_path / "history.sqlite3"
    database = Database(f"sqlite:///{database_path}")

    database.create_tables()

    assert database_path.exists()
    assert "report_runs" in inspect(database.engine).get_table_names()


def test_session_rolls_back_the_complete_transaction_after_error(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'rollback.sqlite3'}")
    database.create_tables()
    with database.session() as session:
        session.add(_orm_record("RUN-20250101-001"))

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(_orm_record("RUN-20250101-002"))
        session.add(_orm_record("RUN-20250101-001"))
        session.flush()

    with database.session() as session:
        assert session.get(RunRecordORM, "RUN-20250101-002") is None
