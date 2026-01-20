"""SQLite database setup with WAL mode.

Provides a Database class that manages SQLite connections with:
- WAL mode for concurrent read access
- Automatic table creation
- Connection pooling
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine


def _set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
    """Enable WAL mode and other SQLite optimizations."""
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


class Database:
    """SQLite database manager with WAL mode.

    Usage:
        db = Database("workflow.db")
        db.init()  # Creates tables if needed

        with db.session() as session:
            workflow = Workflow(type="article-writer")
            session.add(workflow)
            session.commit()
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def engine(self) -> Engine:
        """Get or create the SQLAlchemy engine."""
        if self._engine is None:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Create engine with SQLite optimizations
            self._engine = create_engine(
                f"sqlite:///{self.db_path}",
                echo=False,
                pool_pre_ping=True,
            )

            # Register pragma handler
            event.listen(self._engine, "connect", _set_sqlite_pragma)

        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        """Get or create the session factory."""
        if self._session_factory is None:
            self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        return self._session_factory

    def init(self) -> None:
        """Initialize the database, creating tables if needed."""
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context manager for database sessions.

        Automatically commits on success, rolls back on exception.

        Yields:
            SQLAlchemy session
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def execute_sql(self, sql: str) -> None:
        """Execute raw SQL (for migrations, etc.)."""
        with self.engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None


# Default database instance (created lazily)
_default_db: Database | None = None


def get_database(db_path: str | Path | None = None) -> Database:
    """Get the default database instance.

    Args:
        db_path: Optional path to database file. If not provided,
                 uses 'workflow.db' in the current directory.

    Returns:
        Database instance
    """
    global _default_db

    if db_path is not None:
        # Explicit path - create new instance
        return Database(db_path)

    if _default_db is None:
        # Default path - create singleton
        _default_db = Database("workflow.db")
        _default_db.init()

    return _default_db
