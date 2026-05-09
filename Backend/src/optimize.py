import argparse
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


logger = logging.getLogger("Anveshq")

NEAR_HIGH_THRESHOLDS = [0.85, 0.88, 0.90, 0.92, 0.95]
VOLUME_FACTORS = [1.0, 1.1, 1.25, 1.5]
RISK_SCORE_MAX = [0, 1, 2, 3]
MIN_RANK_SCORE = [1, 2, 3, 4, 5]


@dataclass
class OptimizationMetrics:
    trades: int
    sharpe: float | None
    win_rate_pct: float | None
    average_return_10d_pct: float | None


def _load_trades(backtest_csv_path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(backtest_csv_path)
    if "row_type" in df.columns:
        df = df[df["row_type"].fillna("TRADE") == "TRADE"].copy()
    if "signal_date" not in df.columns:
        raise ValueError("Backtest CSV must contain signal_date.")
    df["signal_date"] = pd.to_datetime(df["signal_date"], errors="coerce")
    df = df.dropna(subset=["signal_date"])
    df["year"] = df["signal_date"].dt.year
    return df


def _sharpe(returns_pct: pd.Series) -> float | None:
    returns = pd.to_numeric(returns_pct, errors="coerce").dropna() / 100.0
    if returns.empty:
        return None
    std = returns.std(ddof=1)
    if not std or math.isnan(std):
        return None
    return float((returns.mean() / std) * math.sqrt(252 / 10))


def _metrics(df: pd.DataFrame) -> OptimizationMetrics:
    returns = pd.to_numeric(df.get("return_10d_pct"), errors="coerce").dropna()
    if returns.empty:
        return OptimizationMetrics(0, None, None, None)
    return OptimizationMetrics(
        trades=int(len(returns)),
        sharpe=_sharpe(returns),
        win_rate_pct=float((returns > 0).mean() * 100),
        average_return_10d_pct=float(returns.mean()),
    )


def _filter_for_params(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    filtered = df.copy()
    if "risk_score" in filtered.columns:
        filtered = filtered[pd.to_numeric(filtered["risk_score"], errors="coerce") <= params["risk_score_max"]]
    if "rank_score" in filtered.columns:
        filtered = filtered[pd.to_numeric(filtered["rank_score"], errors="coerce") >= params["min_rank_score"]]
    return filtered


def _parameter_grid() -> list[dict]:
    return [
        {
            "near_high_threshold": near_high,
            "volume_factor": volume_factor,
            "risk_score_max": risk_score,
            "min_rank_score": min_rank,
        }
        for near_high, volume_factor, risk_score, min_rank in product(
            NEAR_HIGH_THRESHOLDS,
            VOLUME_FACTORS,
            RISK_SCORE_MAX,
            MIN_RANK_SCORE,
        )
    ]


def walk_forward_optimize(
    backtest_csv_path: str | Path,
    train_years: int = 2,
    test_years: int = 1,
) -> dict:
    trades = _load_trades(backtest_csv_path)
    years = sorted(int(year) for year in trades["year"].dropna().unique())
    results = []

    for start_idx in range(0, len(years) - train_years - test_years + 1):
        train_window = years[start_idx:start_idx + train_years]
        test_window = years[start_idx + train_years:start_idx + train_years + test_years]
        train_df = trades[trades["year"].isin(train_window)]
        test_df = trades[trades["year"].isin(test_window)]

        best_params = None
        best_metrics = None
        for params in _parameter_grid():
            candidate_metrics = _metrics(_filter_for_params(train_df, params))
            score = candidate_metrics.sharpe if candidate_metrics.sharpe is not None else float("-inf")
            best_score = best_metrics.sharpe if best_metrics and best_metrics.sharpe is not None else float("-inf")
            candidate_trades = candidate_metrics.trades
            best_trades = best_metrics.trades if best_metrics is not None else -1
            if best_metrics is None or score > best_score or (score == best_score and candidate_trades > best_trades):
                best_params = params
                best_metrics = candidate_metrics

        test_metrics = _metrics(_filter_for_params(test_df, best_params or {}))
        results.append(
            {
                "train_years": train_window,
                "test_years": test_window,
                "best_params": best_params,
                "in_sample": asdict(best_metrics),
                "out_of_sample": asdict(test_metrics),
            }
        )

    return {
        "source_csv": str(backtest_csv_path),
        "train_years": train_years,
        "test_years": test_years,
        "note": (
            "This CSV-level optimizer can evaluate risk_score_max and min_rank_score immediately. "
            "near_high_threshold and volume_factor are carried in the grid for compatibility with "
            "future backtest exports that include raw signal inputs."
        ),
        "periods": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Walk-forward optimize Anveshq backtest results.")
    parser.add_argument("--csv", required=True, help="Path to backtest CSV.")
    parser.add_argument("--output", default="optimization_results.json", help="Output JSON path.")
    parser.add_argument("--train-years", type=int, default=2)
    parser.add_argument("--test-years", type=int, default=1)
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[ANVESHQ:OPTIMIZE] [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    args = build_parser().parse_args()
    results = walk_forward_optimize(args.csv, train_years=args.train_years, test_years=args.test_years)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    logger.info("Optimization results written to %s", output_path.resolve())


if __name__ == "__main__":
    main()
