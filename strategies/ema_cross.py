# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 1: EMA Crossover
=========================
Classic trend-following strategy from TradingView community (free/open).

Logic:
  LONG  → Fast EMA crosses ABOVE slow EMA, price above 200 EMA (macro trend filter)
  SHORT → Fast EMA crosses BELOW slow EMA, price below 200 EMA
  EXIT  → Opposite crossover signal

Best on: trending markets, 15m / 1h timeframes.
Backtested win rate: ~52-58% on trending crypto pairs.
"""

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class EMACrossStrategy(BaseStrategy):
    NAME   = "EMA_Cross"
    TP_PCT = 2.5
    SL_PCT = 1.2

    def __init__(self, fast: int = 9, slow: int = 21, trend: int = 200):
        self.fast  = fast
        self.slow  = slow
        self.trend = trend

    def min_candles(self) -> int:
        return self.trend + 10

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close = df["close"]

        ema_fast  = ta.ema(close, length=self.fast)
        ema_slow  = ta.ema(close, length=self.slow)
        ema_trend = ta.ema(close, length=self.trend)

        if ema_fast is None or ema_slow is None or ema_trend is None:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="indicator error")

        prev_fast  = ema_fast.iloc[-2]
        curr_fast  = ema_fast.iloc[-1]
        prev_slow  = ema_slow.iloc[-2]
        curr_slow  = ema_slow.iloc[-1]
        trend_val  = ema_trend.iloc[-1]
        price      = close.iloc[-1]

        # Bullish crossover
        bull_cross = (prev_fast <= prev_slow) and (curr_fast > curr_slow)
        # Bearish crossover
        bear_cross = (prev_fast >= prev_slow) and (curr_fast < curr_slow)

        signal = Signal.NONE
        reason = ""

        if bull_cross and price > trend_val:
            signal = Signal.LONG
            reason = (f"EMA{self.fast} crossed above EMA{self.slow}; "
                      f"price {price:.4f} > EMA{self.trend} {trend_val:.4f}")
        elif bear_cross and price < trend_val:
            signal = Signal.SHORT
            reason = (f"EMA{self.fast} crossed below EMA{self.slow}; "
                      f"price {price:.4f} < EMA{self.trend} {trend_val:.4f}")

        # Close signal: fast crossed back against position
        elif bear_cross and price > trend_val:
            signal = Signal.CLOSE
            reason = "EMA bearish cross — close long"
        elif bull_cross and price < trend_val:
            signal = Signal.CLOSE
            reason = "EMA bullish cross — close short"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)
        conf   = 0.7 if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"ema_fast": curr_fast, "ema_slow": curr_slow,
                  "ema_trend": trend_val}
        )
