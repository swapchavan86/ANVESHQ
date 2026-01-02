import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../Backend')))
import logging
import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models import Base, MomentumStock, User, VerificationCode, Error
from src.config import get_settings, Settings
from src.database import get_engine
import src.config

# --- Logger for Tests ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TestLogger")
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


# --- Pytest Hooks ---
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # This hook is called for each test setup, call, and teardown.
    # We are using it to capture the result of each test phase.
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)

# --- Fixtures ---
@pytest.fixture(scope="session", autouse=True)
def load_env_for_tests():
    """Load environment variables from Test/.env for the test session."""
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path=dotenv_path, override=True)
    os.environ['MODE'] = 'TEST'

@pytest.fixture(scope="session")
def app_settings(load_env_for_tests):
    """Provides a single instance of application settings for the test session."""
    get_settings.cache_clear()
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    settings = Settings(_env_file=dotenv_path)
    return settings

@pytest.fixture(autouse=True)
def override_get_settings(monkeypatch, app_settings):
    """Monkeypatch the get_settings function to return test-specific settings."""
    def get_test_settings():
        return app_settings
    monkeypatch.setattr(src.config, "get_settings", get_test_settings)

@pytest.fixture(scope="session")
def test_db_engine(app_settings):
    """Creates a test database engine and tables once per session."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    db_path = app_settings.TEST_DATABASE_URL.replace("sqlite:///", "")
    if os.path.exists(db_path):
        os.remove(db_path)

@pytest.fixture(scope="function")
def db_session(test_db_engine):
    """Provides a new database session for each test function."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def log_test_case(request):
    """Logs the start and result of each test case."""
    logger.info(f"--- Starting test: {request.node.name} ---")
    yield
    if request.node.rep_setup.failed:
        logger.error(f"--- Test setup FAILED: {request.node.name} ---")
    elif request.node.rep_call.failed:
        logger.error(f"--- Test FAILED: {request.node.name} ---")
    else:
        logger.info(f"--- Test PASSED: {request.node.name} ---")
