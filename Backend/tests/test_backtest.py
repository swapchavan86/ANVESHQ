from pathlib import Path
import sys

import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.backtest import simulate_with_stop_loss


def test_simulate_with_stop_loss_clips_returns_and_marks_exit():
    trades = pd.DataFrame(
        [
            {"row_type": "TRADE", "return_5d_pct": -12.0, "return_10d_pct": 20.0, "return_20d_pct": 4.0},
            {"row_type": "SUMMARY", "return_5d_pct": None, "return_10d_pct": None, "return_20d_pct": None},
        ]
    )

    adjusted = simulate_with_stop_loss(trades, stop_pct=-8.0, target_pct=15.0)

    assert adjusted.loc[0, "adjusted_return_5d_pct"] == -8.0
    assert adjusted.loc[0, "adjusted_exit_5d"] == "STOP_LOSS"
    assert adjusted.loc[0, "adjusted_return_10d_pct"] == 15.0
    assert adjusted.loc[0, "adjusted_exit_10d"] == "TAKE_PROFIT"
    assert adjusted.loc[0, "adjusted_return_20d_pct"] == 4.0
    assert adjusted.loc[0, "adjusted_exit_20d"] == "HORIZON"
