# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 3: MACD Momentum
=========================
Trend-momentum strategy. Free TradingView community strategy.

Logic:
  LONG  → MACD histogram crosses from negative to positive (momentum turning bullish)
           + MACD line crosses above signal line
           + ADX > 20 (trend has strength)
  SHORT → MACD histogram crosses positive to negative
           + MACD line crosses below signal line
           + ADX > 20
  EXIT  → Histogram flips sign opposite to position

Best on: trending markets, 1h / 4h.
"""

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class MACDMomentumStrategy(BaseStrategy):
    NAME   = "MACD_Momentum"
    TP_PCT = 3.0
    SL_PCT = 1.5

    def __init__(self, fast: int = 12, slow: int = 26,
                 signal: int = 9, adx_period: int = 14,
                 adx_threshold: float = 20.0):
        self.fast          = fast
        self.slow          = slow
        self.signal_period = signal
        self.adx_period    = adx_period
        self.adx_threshold = adx_threshold

    def min_candles(self) -> int:
        return 60

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        price = close.iloc[-1]

        macd = ta.macd(close, fast=self.fast, slow=self.slow,
                       signal=self.signal_period)
        adx  = ta.adx(high, low, close, length=self.adx_period)

        if macd is None or adx is None:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="indicator error")

        macd_col = f"MACD_{self.fast}_{self.slow}_{self.signal_period}"
        sig_col  = f"MACDs_{self.fast}_{self.slow}_{self.signal_period}"
        hist_col = f"MACDh_{self.fast}_{self.slow}_{self.signal_period}"
        adx_col  = f"ADX_{self.adx_period}"

        hist_now  = macd[hist_col].iloc[-1]
        hist_prev = macd[hist_col].iloc[-2]
        macd_now  = macd[macd_col].iloc[-1]
        sig_now   = macd[sig_col].iloc[-1]
        macd_prev = macd[macd_col].iloc[-2]
        sig_prev  = macd[sig_col].iloc[-2]
        adx_val   = adx[adx_col].iloc[-1]

        hist_bull_cross = (hist_prev < 0) and (hist_now >= 0)
        hist_bear_cross = (hist_prev > 0) and (hist_now <= 0)
        macd_bull_cross = (macd_prev < sig_prev) and (macd_now >= sig_now)
        macd_bear_cross = (macd_prev > sig_prev) and (macd_now <= sig_now)
        trending        = adx_val >= self.adx_threshold

        signal = Signal.NONE
        reason = ""

        if hist_bull_cross and macd_bull_cross and trending:
            signal = Signal.LONG
            reason = (f"MACD hist crossed positive; MACD bullish cross; "
                      f"ADX={adx_val:.1f}")
        elif hist_bear_cross and macd_bear_cross and trending:
            signal = Signal.SHORT
            reason = (f"MACD hist crossed negative; MACD bearish cross; "
                      f"ADX={adx_val:.1f}")
        elif hist_bear_cross:
            signal = Signal.CLOSE
            reason = "MACD hist turned negative — close long"
        elif hist_bull_cross:
            signal = Signal.CLOSE
            reason = "MACD hist turned positive — close short"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)
        conf   = min(1.0, adx_val / 50) if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"macd": macd_now, "signal": sig_now,
                  "histogram": hist_now, "adx": adx_val}
        )
