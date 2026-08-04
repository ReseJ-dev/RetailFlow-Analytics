"""SQLAlchemy database setup and transaction-scoped sessions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from retailflow.storage.models import Base


class Database:
    """Own an SQLAlchemy engine and provide explicit transaction boundaries."""

    def __init__(self, database_url: str = "sqlite:///retailflow.sqlite3") -> None:
        """Create an engine for the configured URL without creating tables yet."""
        is_sqlite = database_url.startswith("sqlite")
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        pool_class = (
            StaticPool
            if is_sqlite and (database_url.endswith(":memory:") or database_url == "sqlite://")
            else NullPool if is_sqlite else None
        )
        self.engine: Engine = create_engine(
            database_url,
            future=True,
            connect_args=connect_args,
            poolclass=pool_class,
        )
        self._session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    def create_tables(self) -> None:
        """Create missing RetailFlow tables for local development."""
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self, *, immediate: bool = False) -> Iterator[Session]:
        """Yield a session and commit or roll back its explicit transaction."""
        with self._session_factory() as session:
            try:
                with session.begin():
                    if immediate and self.engine.dialect.name == "sqlite":
                        session.execute(text("BEGIN IMMEDIATE"))
                    yield session
            except Exception:
                session.rollback()
                raise

    def dispose(self) -> None:
        """Release pooled database connections."""
        self.engine.dispose()


__all__ = ["Database"]
