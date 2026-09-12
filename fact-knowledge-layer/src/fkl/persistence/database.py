"""Database engine and session factory."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from fkl.persistence.orm import Base

_engine = None
_SessionLocal = None


def init_db(database_url: str) -> None:
    global _engine, _SessionLocal
    # Dispose old engine if re-initializing (e.g., in tests)
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    _engine = create_engine(database_url, connect_args=connect_args)

    # Task C: Enable WAL journal mode and busy timeout for SQLite concurrency.
    # WAL allows concurrent readers while a write is in progress, and busy_timeout
    # lets waiting writers retry for up to 5 000 ms before raising OperationalError.
    if database_url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    Base.metadata.create_all(bind=_engine)
    _run_migrations(_engine)


def _run_migrations(engine) -> None:
    """Safely apply missing columns to existing SQLite tables."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            try:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(documents)")).fetchall()]
                if cols and "canonical_entity" not in cols:
                    conn.execute(text("ALTER TABLE documents ADD COLUMN canonical_entity TEXT"))
                    conn.commit()
            except Exception:
                pass

            try:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(facts)")).fetchall()]
                if cols and "entity_canonical" not in cols:
                    conn.execute(text("ALTER TABLE facts ADD COLUMN entity_canonical TEXT"))
                    conn.commit()
            except Exception:
                pass

            try:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(ingestion_runs)")).fetchall()]
                if cols:
                    if "insufficient_context_count" not in cols:
                        conn.execute(text("ALTER TABLE ingestion_runs ADD COLUMN insufficient_context_count INTEGER DEFAULT 0"))
                        conn.commit()
                    if "blocks_skipped_due_to_cap" not in cols:
                        conn.execute(text("ALTER TABLE ingestion_runs ADD COLUMN blocks_skipped_due_to_cap INTEGER DEFAULT 0"))
                        conn.commit()
                    if "relationships_error" not in cols:
                        conn.execute(text("ALTER TABLE ingestion_runs ADD COLUMN relationships_error TEXT"))
                        conn.commit()
                    coverage_cols = [
                        "prose_blocks_total",
                        "prose_blocks_llm_called",
                        "table_cells_total",
                        "table_cells_rejected_missing_header",
                        "table_cells_rejected_not_numeric",
                        "relationship_pairs_total",
                        "relationship_pairs_jaccard_matched",
                        "relationship_pairs_llm_fallback_matched",
                        "relationship_pairs_insufficient_context",
                        "metric_llm_calls_skipped_due_to_cap",
                    ]
                    for col in coverage_cols:
                        if col not in cols:
                            conn.execute(text(f"ALTER TABLE ingestion_runs ADD COLUMN {col} INTEGER DEFAULT 0"))
                            conn.commit()
            except Exception:
                pass
    except Exception:
        pass


def get_session() -> Session:
    if _SessionLocal is None:
        from fkl.config import get_settings
        init_db(get_settings().database_url)
    return _SessionLocal()
