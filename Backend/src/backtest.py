import argparse
import datetime as dt
import json
import logging
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

# Support both `cd Backend && python -m src.backtest` and direct module execution.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import get_settings
from src.services import RiskAndQualityAnalyzer, StockFetcher
from src.yahoo_finance import download_history


logger = logging.getLogger("Anveshq.Backtest")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "backtest_results.csv"
HORIZONS = (5, 10, 20)


@dataclass
class SimulatedMomentumStock:
    symbol: str
    rank_score: int
    last_seen_date: dt.date
    daily_rank_delta: int = 0
    last_top10_date: dt.date | None = None
    top10_hit_count: int = 0
    risk_score: int | None = None
    is_volume_confirmed: bool = False
    is_fundamental_ok: bool = True
    current_price: float | None = None
    low_52_week: float | None = None
    high_52_week_price: float | None = None


@dataclass
class BacktestMetrics:
    trade_count: int
    win_rate_10d_pct: float | None
    average_return_5d_pct: float | None
    average_return_10d_pct: float | None
    average_return_20d_pct: float | None
    maximum_drawdown_pct: float | None
    sharpe_ratio_approx: float | None


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc


def load_universe(settings_obj) -> list[str]:
    if not settings_obj.USE_JSON_UNIVERSE:
        raise RuntimeError(
            "Backtest uses the configured JSON universe for reproducibility. "
            "Set USE_JSON_UNIVERSE=true or provide a JSON universe path in config."
        )

    universe_path = Path(settings_obj.json_universe_file_path)
    with universe_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    tickers: list[str] = []
    for record in payload.get("records", []):
        symbol = record.get("symbol")
        suffix = record.get("exchange_suffix")
        if symbol and suffix:
            tickers.append(f"{symbol}.{suffix}")
    return list(dict.fromkeys(tickers))


def normalize_history(df: pd.DataFrame, settings_obj) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    normalized = df.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = normalized.columns.get_level_values(0)
    normalized = normalized.loc[:, ~normalized.columns.duplicated()]

    required_columns = ["Open", "High", "Low", "Close", "Volume"]
    missing_columns = [column for column in required_columns if column not in normalized.columns]
    if missing_columns:
        logger.info("History skipped due to missing columns: %s", missing_columns)
        return pd.DataFrame()

    normalized = normalized[required_columns]
    normalized = StockFetcher._normalize_market_dataframe(normalized, settings_obj)
    normalized = normalized.dropna(subset=["High", "Low", "Close", "Volume"])
    return normalized.sort_index()


def download_symbol_history(
    symbol: str,
    start_date: dt.date,
    end_date: dt.date,
    settings_obj,
    timeout: int,
) -> tuple[str, pd.DataFrame]:
    df = download_history(
        symbol,
        start=start_date.isoformat(),
        end=(end_date + dt.timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
        timeout=timeout,
    )
    return symbol, normalize_history(df, settings_obj)


def download_histories(
    tickers: list[str],
    fetch_start: dt.date,
    fetch_end: dt.date,
    settings_obj,
    max_workers: int,
    timeout: int,
) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {
            executor.submit(download_symbol_history, symbol, fetch_start, fetch_end, settings_obj, timeout): symbol
            for symbol in tickers
        }
        for idx, future in enumerate(as_completed(futures), start=1):
            symbol = futures[future]
            try:
                fetched_symbol, df = future.result()
                if not df.empty:
                    histories[fetched_symbol] = df
            except Exception as exc:
                logger.warning("Download failed for %s: %s", symbol, exc)

            if idx % 100 == 0 or idx == len(futures):
                logger.info("Downloaded %s/%s symbols; usable histories=%s", idx, len(futures), len(histories))
    return histories


def iter_trading_days(
    histories: dict[str, pd.DataFrame],
    start_date: dt.date,
    end_date: dt.date,
) -> list[dt.date]:
    trading_days: set[dt.date] = set()
    for df in histories.values():
        dates = pd.to_datetime(df.index).date
        trading_days.update(day for day in dates if start_date <= day <= end_date)
    return sorted(trading_days)


def history_until(
    df: pd.DataFrame,
    signal_date: dt.date,
    lookback_days: int,
) -> pd.DataFrame:
    start_window = signal_date - dt.timedelta(days=lookback_days)
    mask = (df.index.date <= signal_date) & (df.index.date >= start_window)
    return df.loc[mask]


def passes_momentum_filters(
    symbol: str,
    df: pd.DataFrame,
    settings_obj,
    use_current_fundamentals: bool,
) -> tuple[bool, dict[str, float | int | bool | None]]:
    min_history_days = max(30, int(getattr(settings_obj, "MIN_HISTORY_DAYS", 150)))
    if len(df) < min_history_days:
        return False, {}

    current_close = float(df["Close"].iloc[-1])
    high_52 = float(df["High"].max())
    if current_close < settings_obj.MIN_PRICE:
        return False, {}
    if current_close < (high_52 * settings_obj.NEAR_52_WEEK_HIGH_THRESHOLD):
        return False, {}

    is_liquid, _ = RiskAndQualityAnalyzer.relative_liquidity_check(df, settings_obj)
    if not is_liquid:
        return False, {}

    is_confirmed, _ = RiskAndQualityAnalyzer.volume_confirmation(df, settings_obj)
    if not is_confirmed:
        return False, {}

    if use_current_fundamentals and getattr(settings_obj, "FUNDAMENTAL_CHECK_ENABLED", True):
        is_fundamental_ok = RiskAndQualityAnalyzer.deep_fundamental_check(symbol, settings_obj)
    else:
        # Historical fundamentals are not available through the existing yfinance wrapper.
        # Treating this as pass avoids introducing lookahead from current fundamentals.
        is_fundamental_ok = True

    if not is_fundamental_ok:
        return False, {}

    risk_score, _ = RiskAndQualityAnalyzer.calculate_risk_score(df, current_close, high_52)
    return True, {
        "current_price": current_close,
        "low_52_week": float(df["Low"].min()),
        "high_52_week_price": high_52,
        "risk_score": risk_score,
        "is_volume_confirmed": is_confirmed,
        "is_fundamental_ok": is_fundamental_ok,
    }


def update_ranking_state(
    states: dict[str, SimulatedMomentumStock],
    symbol: str,
    signal_date: dt.date,
    details: dict[str, float | int | bool | None],
    settings_obj,
) -> None:
    state = states.get(symbol)
    if state is None:
        state = SimulatedMomentumStock(symbol=symbol, rank_score=1, last_seen_date=signal_date)
        states[symbol] = state
    elif state.last_seen_date < signal_date:
        old_rank = state.rank_score or 0
        state.rank_score = min(old_rank + 1, min(settings_obj.MAX_RANK, 100))
        state.daily_rank_delta = state.rank_score - old_rank
    else:
        state.daily_rank_delta = 0

    state.last_seen_date = signal_date
    state.current_price = float(details["current_price"]) if details.get("current_price") is not None else None
    state.low_52_week = float(details["low_52_week"]) if details.get("low_52_week") is not None else None
    state.high_52_week_price = (
        float(details["high_52_week_price"]) if details.get("high_52_week_price") is not None else None
    )
    state.risk_score = int(details["risk_score"]) if details.get("risk_score") is not None else None
    state.is_volume_confirmed = bool(details.get("is_volume_confirmed"))
    state.is_fundamental_ok = bool(details.get("is_fundamental_ok"))


def decay_unseen_ranks(
    states: dict[str, SimulatedMomentumStock],
    seen_symbols: set[str],
    signal_date: dt.date,
) -> None:
    for symbol, state in states.items():
        if symbol in seen_symbols:
            continue
        unseen_days = (signal_date - state.last_seen_date).days
        if unseen_days == 2:
            state.rank_score = max(0, state.rank_score - 1)
        elif unseen_days == 3:
            state.rank_score = max(0, state.rank_score - 2)
        elif unseen_days > 3:
            state.rank_score = 0


def select_top_picks(
    states: dict[str, SimulatedMomentumStock],
    settings_obj,
    signal_date: dt.date,
) -> list[SimulatedMomentumStock]:
    candidates = sorted(
        states.values(),
        key=lambda stock: (
            -(stock.daily_rank_delta or 0),
            -(stock.rank_score or 0),
            stock.top10_hit_count or 0,
            stock.symbol,
        ),
    )

    top_picks: list[SimulatedMomentumStock] = []
    for stock in candidates:
        if len(top_picks) >= 10:
            break

        if stock.last_top10_date and (
            signal_date - stock.last_top10_date
        ).days <= settings_obj.REPETITION_COOLDOWN_DAYS:
            if stock.daily_rank_delta < 2:
                continue

        if not (
            stock.rank_score >= 3
            and stock.daily_rank_delta >= 1
            and stock.risk_score is not None
            and stock.risk_score <= 3
            and stock.is_volume_confirmed
            and stock.is_fundamental_ok
        ):
            continue

        top_picks.append(stock)

    for stock in top_picks:
        stock.last_top10_date = signal_date
        stock.top10_hit_count = (stock.top10_hit_count or 0) + 1
    return top_picks


def future_close(df: pd.DataFrame, signal_date: dt.date, horizon: int) -> tuple[dt.date | None, float | None]:
    signal_positions = [idx for idx, value in enumerate(df.index.date) if value == signal_date]
    if not signal_positions:
        return None, None

    future_position = signal_positions[-1] + horizon
    if future_position >= len(df):
        return None, None

    future_index = df.index[future_position]
    future_date = future_index.date() if isinstance(future_index, pd.Timestamp) else future_index
    return future_date, float(df["Close"].iloc[future_position])


def compute_net_return(
    gross_return_pct: float | None,
    entry_price: float,
    exit_price: float,
    shares: int,
    holding_days: int,
    settings_obj=None,
) -> float | None:
    if gross_return_pct is None or entry_price <= 0 or exit_price <= 0 or shares <= 0:
        return None

    settings_obj = settings_obj or get_settings()
    buy_value = entry_price * shares
    sell_value = exit_price * shares
    gross_pnl = sell_value - buy_value

    brokerage_buy = buy_value * (settings_obj.BROKERAGE_PER_TRADE_PCT / 100)
    brokerage_sell = sell_value * (settings_obj.BROKERAGE_PER_TRADE_PCT / 100)
    brokerage_total = brokerage_buy + brokerage_sell
    exchange_charges = (buy_value + sell_value) * (settings_obj.EXCHANGE_CHARGES_PCT / 100)
    sebi_charges = (buy_value + sell_value) * (settings_obj.SEBI_CHARGES_PCT / 100)
    gst = brokerage_total * (settings_obj.GST_ON_BROKERAGE_PCT / 100)
    stamp_duty = buy_value * (settings_obj.STAMP_DUTY_BUY_PCT / 100)
    stt = sell_value * (settings_obj.STT_SELL_SIDE_PCT / 100)
    charges = brokerage_total + exchange_charges + sebi_charges + gst + stamp_duty + stt

    taxable_profit = max(0.0, gross_pnl - charges)
    tax = taxable_profit * (settings_obj.STCG_TAX_PCT / 100) if holding_days < 365 else 0.0
    net_pnl = gross_pnl - charges - tax
    return (net_pnl / buy_value) * 100


def build_trade_row(
    stock: SimulatedMomentumStock,
    signal_date: dt.date,
    histories: dict[str, pd.DataFrame],
) -> dict[str, object]:
    df = histories[stock.symbol]
    entry_close = stock.current_price
    row: dict[str, object] = {
        "row_type": "TRADE",
        "signal_date": signal_date.isoformat(),
        "symbol": stock.symbol,
        "entry_close": entry_close,
        "rank_score": stock.rank_score,
        "daily_rank_delta": stock.daily_rank_delta,
        "risk_score": stock.risk_score,
        "is_volume_confirmed": stock.is_volume_confirmed,
        "is_fundamental_ok": stock.is_fundamental_ok,
    }

    for horizon in HORIZONS:
        close_date, close_price = future_close(df, signal_date, horizon)
        row[f"close_date_{horizon}d"] = close_date.isoformat() if close_date else None
        row[f"close_{horizon}d"] = close_price
        row[f"return_{horizon}d_pct"] = (
            ((close_price / entry_close) - 1.0) * 100.0
            if close_price is not None and entry_close not in (None, 0)
            else None
        )
        row[f"net_return_{horizon}d_pct"] = compute_net_return(
            row[f"return_{horizon}d_pct"],
            float(entry_close or 0),
            float(close_price or 0),
            shares=1,
            holding_days=horizon,
        )
    return row


def calculate_metrics(rows: list[dict[str, object]]) -> BacktestMetrics:
    trade_rows = [row for row in rows if row.get("row_type") == "TRADE"]
    returns_10d = pd.Series(
        [row.get("return_10d_pct") for row in trade_rows],
        dtype="float64",
    ).dropna() / 100.0

    win_rate = None
    if not returns_10d.empty:
        win_rate = float((returns_10d > 0).mean() * 100.0)

    average_returns: dict[int, float | None] = {}
    for horizon in HORIZONS:
        horizon_returns = pd.Series(
            [row.get(f"return_{horizon}d_pct") for row in trade_rows],
            dtype="float64",
        ).dropna()
        average_returns[horizon] = float(horizon_returns.mean()) if not horizon_returns.empty else None

    maximum_drawdown = None
    sharpe_ratio = None
    if not returns_10d.empty:
        equity_curve = (1.0 + returns_10d).cumprod()
        running_max = equity_curve.cummax()
        drawdowns = (equity_curve / running_max) - 1.0
        maximum_drawdown = float(drawdowns.min() * 100.0)

        std = returns_10d.std(ddof=1)
        if std and not math.isnan(std):
            sharpe_ratio = float((returns_10d.mean() / std) * math.sqrt(252 / 10))

    return BacktestMetrics(
        trade_count=len(trade_rows),
        win_rate_10d_pct=win_rate,
        average_return_5d_pct=average_returns[5],
        average_return_10d_pct=average_returns[10],
        average_return_20d_pct=average_returns[20],
        maximum_drawdown_pct=maximum_drawdown,
        sharpe_ratio_approx=sharpe_ratio,
    )


def simulate_with_stop_loss(
    trades_df: pd.DataFrame | str | Path,
    stop_pct: float = -8.0,
    target_pct: float = 15.0,
) -> pd.DataFrame:
    """
    Apply stop-loss/take-profit bounds to an existing backtest CSV/DataFrame.

    The trade CSV contains point-in-time forward returns, not each intervening
    candle. This utility therefore approximates exit handling by clipping each
    horizon return to the configured risk/reward bounds.
    """
    df = pd.read_csv(trades_df) if isinstance(trades_df, (str, Path)) else trades_df.copy()
    if "row_type" in df.columns:
        trade_mask = df["row_type"].fillna("TRADE") == "TRADE"
    else:
        trade_mask = pd.Series(True, index=df.index)

    stop_floor = -abs(float(stop_pct))
    target_ceiling = abs(float(target_pct))
    adjusted = df.copy()
    for horizon in HORIZONS:
        source_column = f"return_{horizon}d_pct"
        adjusted_column = f"adjusted_return_{horizon}d_pct"
        exit_column = f"adjusted_exit_{horizon}d"
        if source_column not in adjusted.columns:
            continue
        returns = pd.to_numeric(adjusted[source_column], errors="coerce")
        clipped = returns.clip(lower=stop_floor, upper=target_ceiling)
        adjusted.loc[trade_mask, adjusted_column] = clipped.loc[trade_mask]
        adjusted.loc[trade_mask & (returns <= stop_floor), exit_column] = "STOP_LOSS"
        adjusted.loc[trade_mask & (returns >= target_ceiling), exit_column] = "TAKE_PROFIT"
        adjusted.loc[trade_mask & returns.notna() & (returns > stop_floor) & (returns < target_ceiling), exit_column] = "HORIZON"
    return adjusted


def append_summary_row(rows: list[dict[str, object]], metrics: BacktestMetrics) -> None:
    rows.append(
        {
            "row_type": "SUMMARY",
            "trade_count": metrics.trade_count,
            "win_rate_10d_pct": metrics.win_rate_10d_pct,
            "average_return_5d_pct": metrics.average_return_5d_pct,
            "average_return_10d_pct": metrics.average_return_10d_pct,
            "average_return_20d_pct": metrics.average_return_20d_pct,
            "maximum_drawdown_pct": metrics.maximum_drawdown_pct,
            "sharpe_ratio_approx": metrics.sharpe_ratio_approx,
        }
    )


def write_results(rows: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)


def run_backtest(
    start_date: dt.date,
    end_date: dt.date,
    tickers: list[str],
    output_path: Path,
    max_workers: int,
    timeout: int,
    lookback_days: int,
    use_current_fundamentals: bool,
) -> BacktestMetrics:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date.")

    settings_obj = get_settings()
    fetch_start = start_date - dt.timedelta(days=lookback_days + 30)
    fetch_end = end_date + dt.timedelta(days=45)

    logger.info(
        "Downloading %s symbols from %s through %s",
        len(tickers),
        fetch_start,
        fetch_end,
    )
    histories = download_histories(tickers, fetch_start, fetch_end, settings_obj, max_workers, timeout)
    trading_days = iter_trading_days(histories, start_date, end_date)
    logger.info("Resolved %s trading days in requested range.", len(trading_days))

    states: dict[str, SimulatedMomentumStock] = {}
    rows: list[dict[str, object]] = []

    for day_index, signal_date in enumerate(trading_days, start=1):
        seen_symbols: set[str] = set()
        for symbol, full_history in histories.items():
            df = history_until(full_history, signal_date, lookback_days)
            if df.empty or df.index[-1].date() != signal_date:
                continue

            passes, details = passes_momentum_filters(
                symbol,
                df,
                settings_obj,
                use_current_fundamentals,
            )
            if not passes:
                continue

            update_ranking_state(states, symbol, signal_date, details, settings_obj)
            seen_symbols.add(symbol)

        decay_unseen_ranks(states, seen_symbols, signal_date)
        top_picks = select_top_picks(states, settings_obj, signal_date)
        for stock in top_picks:
            rows.append(build_trade_row(stock, signal_date, histories))

        logger.info(
            "Backtested %s/%s: %s qualified, %s top picks, %s total trades",
            day_index,
            len(trading_days),
            len(seen_symbols),
            len(top_picks),
            len(rows),
        )

    metrics = calculate_metrics(rows)
    append_summary_row(rows, metrics)
    write_results(rows, output_path)
    return metrics


def configure_logging(settings_obj) -> None:
    logging.basicConfig(
        level=getattr(logging, settings_obj.LOG_LEVEL, logging.INFO),
        format="[ANVESHQ:BACKTEST] [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_symbols(symbols: str | None) -> list[str] | None:
    if not symbols:
        return None
    parsed = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]
    return parsed or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an Anveshq historical momentum backtest.")
    parser.add_argument("--start", required=True, type=parse_date, help="Backtest start date, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, type=parse_date, help="Backtest end date, YYYY-MM-DD.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="CSV output path. Defaults to data/backtest_results.csv.",
    )
    parser.add_argument("--max-workers", type=int, default=8, help="Parallel Yahoo Finance download workers.")
    parser.add_argument("--timeout", type=int, default=15, help="Yahoo Finance request timeout in seconds.")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=370,
        help="Calendar-day lookback used to approximate the scanner's 1y history window.",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Optional comma-separated symbols for a smaller run, e.g. RELIANCE.NS,TCS.NS.",
    )
    parser.add_argument(
        "--use-current-fundamentals",
        action="store_true",
        help="Apply the existing fundamental check using current yfinance metadata.",
    )
    return parser


def select_tickers(settings_obj, symbols: Iterable[str] | None) -> list[str]:
    if symbols:
        return list(dict.fromkeys(symbols))
    return load_universe(settings_obj)


def main() -> None:
    settings_obj = get_settings()
    configure_logging(settings_obj)

    args = build_parser().parse_args()
    tickers = select_tickers(settings_obj, parse_symbols(args.symbols))
    if not tickers:
        raise SystemExit("No tickers found for backtest.")

    metrics = run_backtest(
        start_date=args.start,
        end_date=args.end,
        tickers=tickers,
        output_path=Path(args.output),
        max_workers=args.max_workers,
        timeout=args.timeout,
        lookback_days=args.lookback_days,
        use_current_fundamentals=args.use_current_fundamentals,
    )

    logger.info("Backtest complete. Results written to %s", Path(args.output).resolve())
    logger.info(
        "Trades=%s win_rate_10d=%s avg_5d=%s avg_10d=%s avg_20d=%s max_drawdown=%s sharpe=%s",
        metrics.trade_count,
        metrics.win_rate_10d_pct,
        metrics.average_return_5d_pct,
        metrics.average_return_10d_pct,
        metrics.average_return_20d_pct,
        metrics.maximum_drawdown_pct,
        metrics.sharpe_ratio_approx,
    )


if __name__ == "__main__":
    main()
