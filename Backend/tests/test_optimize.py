from pathlib import Path
import sys

import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.optimize import walk_forward_optimize


def test_walk_forward_optimize_outputs_period_results(tmp_path: Path):
    rows = []
    for year in [2022, 2023, 2024]:
        for month in [1, 2, 3]:
            rows.append(
                {
                    "row_type": "TRADE",
                    "signal_date": f"{year}-{month:02d}-01",
                    "return_10d_pct": 2.0 if year < 2024 else 1.0,
                    "risk_score": 1,
                    "rank_score": 4,
                }
            )
    csv_path = tmp_path / "backtest.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    result = walk_forward_optimize(csv_path, train_years=2, test_years=1)

    assert result["periods"]
    assert result["periods"][0]["best_params"]["risk_score_max"] >= 1
    assert result["periods"][0]["out_of_sample"]["trades"] == 3
