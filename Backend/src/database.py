from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.config import get_settings

_engine = None
_SessionLocal = None

def _initialize_db_components():
    global _engine, _SessionLocal
    if _engine is None or _SessionLocal is None:
        settings = get_settings()
        db_url = str(settings.TEST_DATABASE_URL) if settings.MODE == "TEST" else str(settings.DATABASE_URL)
        
        _engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20
        )
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

def get_engine():
    _initialize_db_components()
    return _engine

def get_session_local():
    _initialize_db_components()
    return _SessionLocal

@contextmanager
def get_db_context():
    """Context manager for DB sessions to ensure clean teardown."""
    SessionLocal = get_session_local()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()