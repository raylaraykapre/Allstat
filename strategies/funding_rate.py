# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 11: Funding Rate Mean Reversion
=========================================
Derivatives-specific strategy using Bybit's perpetual funding rates.
Unique to crypto derivatives — not available in TradingView.

Logic:
  Extreme positive funding → market is over-leveraged LONG → SHORT
    (longs are paying shorts; overleveraged crowd will be shaken out)
  Extreme negative funding → market is over-leveraged SHORT → LONG
    (shorts are paying longs; short squeeze risk)

  Thresholds (based on Bybit historical data):
    Extreme positive: funding > +0.05% (5x normal)
    Extreme negative: funding < -0.02%

Confluence: RSI confirmation to avoid entering in strong trending moves.

Reference: Apexstoa CARRY strategy — delta-neutral funding yield.
"""

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class FundingRateStrategy(BaseStrategy):
    NAME   = "Funding_Rate"
    TP_PCT = 1.2
    SL_PCT = 0.6

    EXTREME_LONG_FUNDING  = 0.0005   # +0.05% — shorts should open
    EXTREME_SHORT_FUNDING = -0.0002  # -0.02% — longs should open

    def __init__(self, rsi_period: int = 14,
                 rsi_max_for_long: float = 60,
                 rsi_min_for_short: float = 40):
        self.rsi_period        = rsi_period
        self.rsi_max_for_long  = rsi_max_for_long
        self.rsi_min_for_short = rsi_min_for_short

    def min_candles(self) -> int:
        return 30

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close = df["close"]
        price = close.iloc[-1]

        rsi = ta.rsi(close, length=self.rsi_period)
        rsi_val = rsi.iloc[-1] if rsi is not None else 50

        signal = Signal.NONE
        reason = ""

        if funding_rate >= self.EXTREME_LONG_FUNDING and rsi_val < self.rsi_min_for_short:
            signal = Signal.SHORT
            reason = (f"Extreme positive funding rate {funding_rate*100:.4f}% "
                      f"(market over-leveraged long); RSI={rsi_val:.1f}")

        elif funding_rate <= self.EXTREME_SHORT_FUNDING and rsi_val > self.rsi_max_for_long:
            signal = Signal.LONG
            reason = (f"Extreme negative funding rate {funding_rate*100:.4f}% "
                      f"(market over-leveraged short); RSI={rsi_val:.1f}")

        # Quick TP/SL for mean-reversion (small moves expected)
        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)
        conf   = min(1.0, abs(funding_rate) / self.EXTREME_LONG_FUNDING) if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"funding_rate": funding_rate,
                  "funding_pct": funding_rate * 100,
                  "rsi": rsi_val}
        )
