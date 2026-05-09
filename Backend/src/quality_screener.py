import logging

import pandas as pd

from src.services import RiskAndQualityAnalyzer
from src.yahoo_finance import download_history


logger = logging.getLogger("Anveshq")


class QualityScreener:
    @staticmethod
    def _price_vs_52w_high(symbol: str) -> tuple[float | None, float | None]:
        try:
            df = download_history(symbol, period="1y", interval="1d", auto_adjust=True, timeout=10)
            if df is None or df.empty or "Close" not in df.columns or "High" not in df.columns:
                return None, None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            current_price = float(pd.to_numeric(df["Close"], errors="coerce").dropna().iloc[-1])
            high_52 = float(pd.to_numeric(df["High"], errors="coerce").dropna().max())
            return current_price, (current_price / high_52 * 100) if high_52 else None
        except Exception as exc:
            logger.warning("QUALITY: price lookup failed for %s: %s", symbol, exc)
            return None, None

    @staticmethod
    def screen_quality_stocks(tickers: list[str], settings_obj) -> list[dict]:
        candidates = []
        for symbol in tickers:
            info = RiskAndQualityAnalyzer.get_fundamentals_with_fallback(symbol)
            if not info:
                continue

            pe = info.get("trailingPE") or info.get("forwardPE")
            debt_to_equity = info.get("debtToEquity")
            roe = info.get("returnOnEquity")
            promoter_holding = info.get("promoterHoldingPercent")
            if pe is None or pe <= 0 or pe > settings_obj.QUALITY_MAX_PE:
                continue
            if debt_to_equity is not None and debt_to_equity > settings_obj.QUALITY_MAX_DEBT_TO_EQUITY:
                continue
            if roe is not None and roe * 100 < settings_obj.QUALITY_MIN_ROE:
                continue
            if promoter_holding is not None and promoter_holding < settings_obj.QUALITY_MIN_PROMOTER_HOLDING_PCT:
                continue

            current_price, price_vs_high = QualityScreener._price_vs_52w_high(symbol)
            if price_vs_high is None or not (70 <= price_vs_high <= 85):
                continue

            debt_score = max(0.0, settings_obj.QUALITY_MAX_DEBT_TO_EQUITY - float(debt_to_equity or 0))
            pe_score = max(0.0, settings_obj.QUALITY_MAX_PE - float(pe))
            roe_score = float(roe or 0) * 100
            quality_score = pe_score + debt_score * 10 + roe_score
            candidates.append(
                {
                    "symbol": symbol,
                    "current_price": current_price,
                    "pe_ratio": pe,
                    "debt_to_equity": debt_to_equity,
                    "roe_pct": roe_score if roe is not None else None,
                    "price_vs_52w_high_pct": price_vs_high,
                    "quality_score": quality_score,
                }
            )

        return sorted(candidates, key=lambda item: item["quality_score"], reverse=True)[:10]
