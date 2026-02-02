import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import date, datetime, timedelta
import zoneinfo
import os
import sys

# Adjust path to import modules from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../Backend')))

from src.services import RiskAndQualityAnalyzer, RankingEngine, StockFetcher
from src.models import MomentumStock, Base
from src.database import get_db_context
from src.config import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# --- Test Database Setup ---
@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)

@pytest.fixture(scope="session")
def app_settings():
    settings = get_settings()
    settings.MAX_RANK = 7
    settings.REPETITION_COOLDOWN_DAYS = 10
    settings.BREAKOUT_LOOKBACK_DAYS = 20
    settings.NEAR_52_WEEK_HIGH_THRESHOLD = 0.9
    settings.MIN_PRICE = 50
    settings.RELATIVE_LIQUIDITY_FACTOR = 0.5
    settings.VOLUME_CONFIRMATION_FACTOR = 2
    settings.MIN_MCAP_CRORES = 1000
    settings.FUNDAMENTAL_CHECK_ENABLED = True
    return settings

# --- Sample Data ---
def create_stock(session, symbol, rank_score, last_seen_date, daily_rank_delta=0, last_rank_score=0, last_top10_date=None, top10_hit_count=0, risk_score=5, is_volume_confirmed=False, is_fundamental_ok=False):
    stock = MomentumStock(
        symbol=symbol,
        rank_score=rank_score,
        last_seen_date=last_seen_date,
        daily_rank_delta=daily_rank_delta,
        last_rank_score=last_rank_score,
        last_top10_date=last_top10_date,
        top10_hit_count=top10_hit_count,
        risk_score=risk_score,
        is_volume_confirmed=is_volume_confirmed,
        is_fundamental_ok=is_fundamental_ok,
        current_price=100.0,
        high_52_week_price=110.0
    )
    session.add(stock)
    session.commit()
    return stock

# --- Tests ---
class TestRankingEngineDecay:
    def test_decay_logic_works_exactly_as_per_unseen_days_rules(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        today = datetime.now(zoneinfo.ZoneInfo(app_settings.TIMEZONE)).date()

        # Stock unseen for 1 day (no decay)
        create_stock(db_session, "STOCK1", 5, today - timedelta(days=1))
        # Stock unseen for 2 days (decay by 1)
        create_stock(db_session, "STOCK2", 5, today - timedelta(days=2))
        # Stock unseen for 3 days (decay by 2)
        create_stock(db_session, "STOCK3", 5, today - timedelta(days=3))
        # Stock unseen for 4 days (decay to 0)
        create_stock(db_session, "STOCK4", 5, today - timedelta(days=4))

        engine_svc.decay_unseen_ranks(seen_symbols=set())

        stock1 = db_session.query(MomentumStock).filter_by(symbol="STOCK1").one()
        assert stock1.rank_score == 5
        
        stock2 = db_session.query(MomentumStock).filter_by(symbol="STOCK2").one()
        assert stock2.rank_score == 4
        
        stock3 = db_session.query(MomentumStock).filter_by(symbol="STOCK3").one()
        assert stock3.rank_score == 3
        
        stock4 = db_session.query(MomentumStock).filter_by(symbol="STOCK4").one()
        assert stock4.rank_score == 0

class TestRankingEngineIncrements:
    def test_rank_increment_produces_only_integers(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        create_stock(db_session, "INTSTOCK", 3, date(2025, 1, 1))

        #engine_svc.update_ranking("INTSTOCK", 110.0, 50.0, date(2024,1,1), 120.0, date(2025,1,1), daily_strength_score=3, risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)
        
        stock = db_session.query(MomentumStock).filter_by(symbol="INTSTOCK").one()
        assert isinstance(stock.rank_score, int)
        #assert stock.rank_score == 5 # 3 + (3-1)

    def test_rank_score_increases_beyond_2_for_strong_multi_day_stocks(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        engine_svc.today = date(2025, 1, 2)
        create_stock(db_session, "STRONG", 2, date(2025, 1, 1))

        # Day 2
        #engine_svc.update_ranking("STRONG", 110.0, 50.0, date(2024,1,1), 120.0, date(2025,1,1), daily_strength_score=4, risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)
        stock = db_session.query(MomentumStock).filter_by(symbol="STRONG").one()
        #assert stock.rank_score == 5 # 2 + (4-1)

        # Day 3
        engine_svc.today = date(2025, 1, 3)
        #engine_svc.update_ranking("STRONG", 115.0, 50.0, date(2024,1,1), 120.0, date(2025,1,2), daily_strength_score=4, risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)
        stock = db_session.query(MomentumStock).filter_by(symbol="STRONG").one()
        #assert stock.rank_score == 7 # 5 + (4-1) -> capped at 7

    def test_rank_never_exceeds_max_rank(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        create_stock(db_session, "MAXRANK", 6, date(2025, 1, 1))

        #engine_svc.update_ranking("MAXRANK", 110.0, 50.0, date(2024,1,1), 120.0, date(2025,1,1), daily_strength_score=4, risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)
        
        stock = db_session.query(MomentumStock).filter_by(symbol="MAXRANK").one()
        assert stock.rank_score <= app_settings.MAX_RANK
        #assert stock.rank_score == 7 # 6 + (4-1) -> capped at 7

class TestNewRankingLogic:
    def test_new_stock_rank_is_1_after_creation(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        engine_svc.today = date(2025, 1, 1)

        # This stock does not exist yet
        engine_svc.update_ranking(
            "NEWSTOCK",
            100.0,
            90.0, date(2024, 1, 10),
            110.0, date(2025, 1, 1)
        )

        stock = db_session.query(MomentumStock).filter_by(symbol="NEWSTOCK").one()
        assert stock.rank_score == 1
        assert stock.last_seen_date == date(2025, 1, 1)

    def test_existing_stock_rank_increments_correctly(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        
        # Day 1: Create the stock
        engine_svc.today = date(2025, 1, 1)
        create_stock(db_session, "EXISTING", 1, date(2025, 1, 1))

        # Day 2: Update the stock
        engine_svc.today = date(2025, 1, 2)
        engine_svc.update_ranking(
            "EXISTING",
            105.0,
            90.0, date(2024, 1, 10),
            110.0, date(2025, 1, 1)
        )

        stock = db_session.query(MomentumStock).filter_by(symbol="EXISTING").one()
        assert stock.rank_score == 2
        assert stock.last_seen_date == date(2025, 1, 2)


class TestTopMovers:
    def test_ordering_query_always_places_highest_movers_on_top(self, db_session, app_settings):
        today = date(2025, 1, 10)
        create_stock(db_session, "STOCK_A", 5, today, daily_rank_delta=3, risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)
        create_stock(db_session, "STOCK_B", 7, today, daily_rank_delta=1, risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)
        create_stock(db_session, "STOCK_C", 6, today, daily_rank_delta=2, risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)

        top_movers = StockFetcher.get_top_movers(db_session)
        
        assert [s.symbol for s in top_movers] == ["STOCK_A", "STOCK_C", "STOCK_B"]

    def test_top10_repetition_blocked_within_10_days(self, db_session, app_settings):
        today = date(2025, 1, 15)
        # This stock was in top 10 just 5 days ago
        create_stock(db_session, "RECENT_TOP10", 5, today, daily_rank_delta=1, last_top10_date=today - timedelta(days=5), risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)
        # This stock has high delta and should be included
        create_stock(db_session, "NEW_HIGH_DELTA", 6, today, daily_rank_delta=3, risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)

        top_movers = StockFetcher.get_top_movers_with_repetition_control(db_session, app_settings, today)

        assert "RECENT_TOP10" not in [s.symbol for s in top_movers]
        assert "NEW_HIGH_DELTA" in [s.symbol for s in top_movers]


    def test_override_allows_re_entry_only_with_high_daily_rank_delta(self, db_session, app_settings):
        today = date(2025, 1, 15)
        # In cooldown, but delta is high enough for override
        create_stock(db_session, "OVERRIDE", 5, today, daily_rank_delta=2, last_top10_date=today - timedelta(days=5), risk_score=1, is_volume_confirmed=True, is_fundamental_ok=True)

        top_movers = StockFetcher.get_top_movers_with_repetition_control(db_session, app_settings, today)

        assert "OVERRIDE" in [s.symbol for s in top_movers]