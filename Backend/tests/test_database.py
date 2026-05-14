import sys
from pathlib import Path

from sqlalchemy import inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

from src.config import get_settings
from src.database import ensure_momentum_schema_columns, get_db_context, get_engine, reset_db_components
from src.email_report import get_top_picks
from src.models import Base, MomentumStock


@pytest.fixture
def configured_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_anveshq.db"
    monkeypatch.setenv("MODE", "TEST")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("TEST_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DB_PASSWORD", "")
    get_settings.cache_clear()
    reset_db_components()
    Base.metadata.create_all(bind=get_engine())
    yield
    reset_db_components()
    get_settings.cache_clear()


def test_ensure_momentum_schema_columns_idempotent(configured_environment):
    ensure_momentum_schema_columns()
    ensure_momentum_schema_columns()


def test_all_model_columns_exist_in_db(configured_environment):
    ensure_momentum_schema_columns()
    db_columns = {column["name"] for column in inspect(get_engine()).get_columns("momentum_ranks")}
    model_columns = {column.name for column in MomentumStock.__table__.columns}

    assert model_columns <= db_columns


def test_email_report_get_top_picks_no_error(configured_environment):
    ensure_momentum_schema_columns()
    with get_db_context() as session:
        picks = get_top_picks(session)

    assert isinstance(picks, list)
