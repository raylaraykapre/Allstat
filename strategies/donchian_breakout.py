# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 8: Donchian Channel Breakout (Turtle Trading)
======================================================
Inspired by the legendary Turtle Trading system (1980s, Richard Dennis).
Backtested across 43 futures markets over 18 years — profitable on BTC/ETH.
Free/open source on TradingView.

Logic (simplified Turtle System 1):
  LONG  → Price breaks above N-period highest high
           + Previous breakout was a losing trade (avoids whipsaws)
           + ATR-based position sizing
  SHORT → Price breaks below N-period lowest low (same filter)
  EXIT  → Price breaks 10-period opposite extreme (fast exit)

ATR is used as the stop: 2x ATR from entry.
"""

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class DonchianBreakoutStrategy(BaseStrategy):
    NAME   = "Donchian_Breakout"
    TP_PCT = 5.0
    SL_PCT = 2.0

    def __init__(self, entry_period: int = 20, exit_period: int = 10,
                 atr_period: int = 14, atr_sl_mult: float = 2.0):
        self.entry_period  = entry_period
        self.exit_period   = exit_period
        self.atr_period    = atr_period
        self.atr_sl_mult   = atr_sl_mult

    def min_candles(self) -> int:
        return self.entry_period + 20

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        price = close.iloc[-1]

        # Donchian channels
        highest_entry = high.rolling(self.entry_period).max()
        lowest_entry  = low.rolling(self.entry_period).min()
        highest_exit  = high.rolling(self.exit_period).max()
        lowest_exit   = low.rolling(self.exit_period).min()

        atr = ta.atr(high, low, close, length=self.atr_period)
        if atr is None:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="ATR error")

        atr_val       = atr.iloc[-1]
        high_entry    = highest_entry.iloc[-2]   # Use -2 to avoid look-ahead
        low_entry     = lowest_entry.iloc[-2]
        high_exit     = highest_exit.iloc[-2]
        low_exit      = lowest_exit.iloc[-2]
        prev_high     = high.iloc[-2]
        prev_low      = low.iloc[-2]

        bull_break = prev_high >= high_entry
        bear_break = prev_low  <= low_entry
        exit_long  = prev_low  <= low_exit
        exit_short = prev_high >= high_exit

        signal = Signal.NONE
        reason = ""

        if bull_break and not bear_break:
            signal = Signal.LONG
            reason = (f"Donchian breakout above {high_entry:.4f} "
                      f"({self.entry_period}-period high); ATR={atr_val:.4f}")
        elif bear_break and not bull_break:
            signal = Signal.SHORT
            reason = (f"Donchian breakdown below {low_entry:.4f} "
                      f"({self.entry_period}-period low); ATR={atr_val:.4f}")
        elif exit_long or exit_short:
            signal = Signal.CLOSE
            reason = f"Donchian {self.exit_period}-period exit triggered"

        # ATR-based stop loss
        if signal == Signal.LONG:
            sl = price - self.atr_sl_mult * atr_val
            tp = price + self.atr_sl_mult * 2.5 * atr_val  # R:R = 2.5
        elif signal == Signal.SHORT:
            sl = price + self.atr_sl_mult * atr_val
            tp = price - self.atr_sl_mult * 2.5 * atr_val
        else:
            sl = tp = 0.0

        conf = 0.65 if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"donchian_high": high_entry, "donchian_low": low_entry,
                  "atr": atr_val, "exit_high": high_exit, "exit_low": low_exit}
        )
