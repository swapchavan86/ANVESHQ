import argparse
import datetime as dt
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import requests
import yfinance as yf
from bs4 import BeautifulSoup
from sqlalchemy import delete, func, select

from src.config import get_settings
from src.database import (
    analyze_database,
    get_database_size,
    get_db_context,
    run_wal_checkpoint,
    vacuum_database,
)
from src.models import AppMetadata, Error, MomentumStock

logger = logging.getLogger("Anveshq.Cleanup")

METADATA_LAST_MOMENTUM_CLEANUP = "last_momentum_cleanup_date"
METADATA_LAST_MONTHLY_VALIDATION = "last_monthly_validation_date"


@dataclass
class MomentumCleanupStats:
    deleted_count: int
    before_size_mb: float
    after_size_mb: float
    execution_time: float
    deleted_duplicates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MasterCleanupStats:
    deleted_files: list[str] = field(default_factory=list)
    kept_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompanyValidationStats:
    validated_count: int
    deleted_count: int
    invalid_symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ErrorCleanupStats:
    deleted_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatabaseOptimizationStats:
    size_before_mb: float
    size_after_mb: float
    space_saved_mb: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _today_in_app_timezone() -> dt.date:
    settings = get_settings()
    tz = dt.datetime.now(dt.timezone.utc).astimezone().tzinfo
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    except Exception:
        pass
    return dt.datetime.now(tz).date()


def _get_metadata_value(key: str) -> str | None:
    with get_db_context() as session:
        row = session.get(AppMetadata, key)
        return row.value if row else None


def _set_metadata_value(key: str, value: str) -> None:
    with get_db_context() as session:
        row = session.get(AppMetadata, key)
        if row is None:
            session.add(AppMetadata(key=key, value=value))
        else:
            row.value = value


def get_metadata_date(key: str) -> dt.date | None:
    value = _get_metadata_value(key)
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def set_metadata_date(key: str, value: dt.date) -> None:
    _set_metadata_value(key, value.isoformat())


def is_cleanup_due(key: str, frequency_days: int) -> bool:
    last_date = get_metadata_date(key)
    if last_date is None:
        return True
    return (_today_in_app_timezone() - last_date).days >= frequency_days


def cleanup_duplicate_symbols(dry_run: bool = False) -> int:
    """
    Keep latest row per symbol and delete older duplicates.
    """
    duplicate_symbols: list[str]
    with get_db_context() as session:
        duplicate_symbols = (
            session.execute(
                select(MomentumStock.symbol)
                .group_by(MomentumStock.symbol)
                .having(func.count(MomentumStock.id) > 1)
            )
            .scalars()
            .all()
        )

        deleted = 0
        for symbol in duplicate_symbols:
            rows = (
                session.execute(
                    select(MomentumStock)
                    .where(MomentumStock.symbol == symbol)
                    .order_by(MomentumStock.last_seen_date.desc(), MomentumStock.id.desc())
                )
                .scalars()
                .all()
            )
            for stale_row in rows[1:]:
                deleted += 1
                if not dry_run:
                    session.delete(stale_row)
        return deleted


def cleanup_old_momentum_records(dry_run: bool = False) -> MomentumCleanupStats:
    """
    Delete stale momentum rows older than configured retention.
    """
    settings = get_settings()
    start = time.perf_counter()
    today = _today_in_app_timezone()
    cutoff = today - dt.timedelta(weeks=settings.DATA_RETENTION_WEEKS)
    before_size = get_database_size()
    batch_size = max(1, int(settings.CLEANUP_BATCH_SIZE))
    deleted_total = 0

    with get_db_context() as session:
        if dry_run:
            deleted_total = int(
                session.execute(
                    select(func.count(MomentumStock.id)).where(MomentumStock.last_seen_date < cutoff)
                ).scalar_one()
                or 0
            )
        else:
            while True:
                stale_ids = (
                    session.execute(
                        select(MomentumStock.id)
                        .where(MomentumStock.last_seen_date < cutoff)
                        .limit(batch_size)
                    )
                    .scalars()
                    .all()
                )
                if not stale_ids:
                    break
                deleted_total += len(stale_ids)
                session.execute(delete(MomentumStock).where(MomentumStock.id.in_(stale_ids)))

    duplicate_deleted = cleanup_duplicate_symbols(dry_run=dry_run)
    deleted_total += duplicate_deleted

    if deleted_total and not dry_run:
        optimize_database()
    after_size = get_database_size()
    stats = MomentumCleanupStats(
        deleted_count=deleted_total,
        before_size_mb=before_size,
        after_size_mb=after_size,
        execution_time=round(time.perf_counter() - start, 3),
        deleted_duplicates=duplicate_deleted,
    )
    logger.info("Momentum cleanup stats: %s", stats.to_dict())
    return stats


def cleanup_old_master_files(dry_run: bool = False) -> MasterCleanupStats:
    """
    Keep `master-latest.json` and most recent N daily snapshots.
    """
    settings = get_settings()
    master_dir = Path(settings.master_data_directory)
    master_dir.mkdir(parents=True, exist_ok=True)
    keep_days = max(1, int(settings.MASTER_DATA_RETENTION_DAYS))

    snapshot_pattern = re.compile(r"^master-(\d{4}-\d{2}-\d{2})\.json$")
    snapshots: list[tuple[dt.date, Path]] = []
    kept_files: list[str] = []
    deleted_files: list[str] = []

    for file_path in master_dir.glob("master-*.json"):
        if file_path.name == "master-latest.json":
            kept_files.append(file_path.name)
            continue
        match = snapshot_pattern.match(file_path.name)
        if not match:
            kept_files.append(file_path.name)
            continue
        try:
            file_date = dt.date.fromisoformat(match.group(1))
        except ValueError:
            kept_files.append(file_path.name)
            continue
        snapshots.append((file_date, file_path))

    snapshots.sort(key=lambda item: item[0], reverse=True)
    cutoff_date = _today_in_app_timezone() - dt.timedelta(days=keep_days - 1)

    for snapshot_date, path in snapshots:
        if snapshot_date >= cutoff_date:
            kept_files.append(path.name)
            continue
        deleted_files.append(path.name)
        if not dry_run:
            path.unlink(missing_ok=True)

    stats = MasterCleanupStats(
        deleted_files=sorted(deleted_files),
        kept_files=sorted(set(kept_files)),
    )
    logger.info("Master file cleanup stats: %s", stats.to_dict())
    return stats


def _has_yahoo_data(symbol: str) -> bool:
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="1mo", interval="1d")
    if history is not None and not history.empty:
        return True
    fast_info = getattr(ticker, "fast_info", None)
    if isinstance(fast_info, dict):
        market_cap = fast_info.get("marketCap") or fast_info.get("market_cap")
        last_price = fast_info.get("lastPrice") or fast_info.get("last_price")
        return bool(market_cap or last_price)
    return False


def _has_google_evidence(symbol: str) -> bool:
    base_symbol = symbol.replace(".NS", "").replace(".BO", "")
    queries = [f"NSE:{base_symbol} stock", f"BSE:{base_symbol} stock"]
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    for query in queries:
        try:
            resp = requests.get(
                "https://www.google.com/search",
                params={"q": query},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(" ", strip=True).lower()
            if ("finance.yahoo.com" in text) or ("google finance" in text) or (base_symbol.lower() in text):
                return True
        except Exception:
            continue
    return False


def validate_company_existence(symbol: str) -> bool:
    """
    Try Yahoo Finance first and fallback to Google search evidence.
    """
    try:
        if _has_yahoo_data(symbol):
            return True
    except Exception:
        pass
    try:
        return _has_google_evidence(symbol)
    except Exception:
        return False


def _load_latest_master_symbols() -> set[str]:
    settings = get_settings()
    path = Path(settings.json_universe_file_path)
    if not path.exists():
        return set()
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        records = payload.get("records", [])
        symbols = {str(item.get("symbol", "")).strip() for item in records if item.get("symbol")}
        return {s for s in symbols if s}
    except Exception:
        return set()


def _symbol_without_suffix(symbol: str) -> str:
    return symbol.replace(".NS", "").replace(".BO", "")


def remove_invalid_companies(dry_run: bool = False) -> CompanyValidationStats:
    """
    Validate stale companies and delete invalid/delisted ones.
    """
    settings = get_settings()
    today = _today_in_app_timezone()
    stale_cutoff = today - dt.timedelta(days=settings.STALE_SYMBOL_DAYS)
    master_symbols = _load_latest_master_symbols()
    deleted_count = 0
    validated_count = 0
    invalid_symbols: list[str] = []

    with get_db_context() as session:
        candidates = (
            session.execute(
                select(MomentumStock).where(
                    (MomentumStock.last_seen_date < stale_cutoff) | (MomentumStock.manual_delete_flag.is_(True))
                )
            )
            .scalars()
            .all()
        )

        for stock in candidates:
            symbol = stock.symbol
            base_symbol = _symbol_without_suffix(symbol)
            validated_count += 1
            stock.last_validated_date = today

            if stock.manual_delete_flag:
                invalid_symbols.append(symbol)
                deleted_count += 1
                if not dry_run:
                    session.delete(stock)
                continue

            if master_symbols and base_symbol not in master_symbols:
                invalid_symbols.append(symbol)
                deleted_count += 1
                if not dry_run:
                    session.delete(stock)
                continue

            exists = validate_company_existence(symbol)
            if exists:
                stock.validation_failed_since = None
                stock.is_active = True
                continue

            invalid_symbols.append(symbol)
            if stock.validation_failed_since is None:
                stock.validation_failed_since = today
                stock.is_active = False
                continue

            failure_days = (today - stock.validation_failed_since).days
            if failure_days >= settings.STALE_SYMBOL_DAYS:
                deleted_count += 1
                if not dry_run:
                    session.delete(stock)
            else:
                stock.is_active = False

    stats = CompanyValidationStats(
        validated_count=validated_count,
        deleted_count=deleted_count,
        invalid_symbols=sorted(set(invalid_symbols)),
    )
    logger.info("Company validation stats: %s", stats.to_dict())
    return stats


def cleanup_error_logs(dry_run: bool = False) -> ErrorCleanupStats:
    """
    Delete error logs older than configured retention.
    """
    settings = get_settings()
    cutoff = dt.datetime.now() - dt.timedelta(days=settings.ERROR_LOG_RETENTION_DAYS)
    batch_size = max(1, int(settings.CLEANUP_BATCH_SIZE))
    deleted_count = 0

    with get_db_context() as session:
        if dry_run:
            deleted_count = int(
                session.execute(select(func.count(Error.id)).where(Error.timestamp < cutoff)).scalar_one() or 0
            )
        else:
            while True:
                stale_ids = (
                    session.execute(
                        select(Error.id)
                        .where(Error.timestamp < cutoff)
                        .limit(batch_size)
                    )
                    .scalars()
                    .all()
                )
                if not stale_ids:
                    break
                deleted_count += len(stale_ids)
                session.execute(delete(Error).where(Error.id.in_(stale_ids)))

    stats = ErrorCleanupStats(deleted_count=deleted_count)
    logger.info("Error cleanup stats: %s", stats.to_dict())
    return stats


def optimize_database() -> DatabaseOptimizationStats:
    """
    Run WAL checkpoint, ANALYZE and VACUUM.
    """
    size_before = get_database_size()
    run_wal_checkpoint(mode="TRUNCATE")
    analyze_database()
    vacuum_database()
    size_after = get_database_size()
    stats = DatabaseOptimizationStats(
        size_before_mb=size_before,
        size_after_mb=size_after,
        space_saved_mb=round(max(0.0, size_before - size_after), 3),
    )
    logger.info("DB optimization stats: %s", stats.to_dict())
    return stats


def run_full_cleanup(dry_run: bool = False) -> dict[str, Any]:
    """
    Run all cleanup operations except company validation.
    """
    momentum_stats = cleanup_old_momentum_records(dry_run=dry_run)
    master_stats = cleanup_old_master_files(dry_run=dry_run)
    error_stats = cleanup_error_logs(dry_run=dry_run)
    optimization_stats = optimize_database() if not dry_run else None
    return {
        "momentum": momentum_stats.to_dict(),
        "master_files": master_stats.to_dict(),
        "errors": error_stats.to_dict(),
        "database_optimization": optimization_stats.to_dict() if optimization_stats else None,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Anveshq cleanup and validation CLI.")
    parser.add_argument("--cleanup-momentum", action="store_true", help="Delete old momentum records.")
    parser.add_argument("--cleanup-master", action="store_true", help="Delete old master JSON snapshots.")
    parser.add_argument("--validate-companies", action="store_true", help="Validate stale companies.")
    parser.add_argument("--optimize-db", action="store_true", help="Run VACUUM/ANALYZE optimization.")
    parser.add_argument("--cleanup-errors", action="store_true", help="Delete old error logs.")
    parser.add_argument("--full-cleanup", action="store_true", help="Run full cleanup operation.")
    parser.add_argument("--dry-run", action="store_true", help="Show impact without deleting records/files.")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[ANVESHQ:CLEANUP] [%(levelname)s] %(message)s")
    parser = _build_parser()
    args = parser.parse_args()

    if not any(
        [
            args.cleanup_momentum,
            args.cleanup_master,
            args.validate_companies,
            args.optimize_db,
            args.cleanup_errors,
            args.full_cleanup,
        ]
    ):
        parser.print_help()
        return

    results: dict[str, Any] = {}

    if args.cleanup_momentum:
        results["cleanup_momentum"] = cleanup_old_momentum_records(dry_run=args.dry_run).to_dict()
    if args.cleanup_master:
        results["cleanup_master"] = cleanup_old_master_files(dry_run=args.dry_run).to_dict()
    if args.validate_companies:
        results["validate_companies"] = remove_invalid_companies(dry_run=args.dry_run).to_dict()
        if not args.dry_run:
            set_metadata_date(METADATA_LAST_MONTHLY_VALIDATION, _today_in_app_timezone())
    if args.cleanup_errors:
        results["cleanup_errors"] = cleanup_error_logs(dry_run=args.dry_run).to_dict()
    if args.optimize_db:
        results["optimize_db"] = optimize_database().to_dict()
    if args.full_cleanup:
        results["full_cleanup"] = run_full_cleanup(dry_run=args.dry_run)
        if not args.dry_run:
            set_metadata_date(METADATA_LAST_MOMENTUM_CLEANUP, _today_in_app_timezone())

    logger.info("Cleanup CLI results: %s", json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
