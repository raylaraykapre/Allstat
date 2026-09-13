# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 5: Supertrend
======================
ATR-based trend-following indicator by Olivier Seban.
TradingView free strategy — one of the most popular for crypto.

Logic:
  LONG  → Supertrend flips bullish (price crosses above ST line)
           + EMA200 filter (price above 200 EMA = macro uptrend)
  SHORT → Supertrend flips bearish (price crosses below ST line)
           + Price below EMA200
  EXIT  → Supertrend flips opposite

Optimal settings for crypto (backtested):
  period=10, multiplier=3.0 (standard)
  period=7,  multiplier=3.0 (more sensitive for scalping)

Best on: all timeframes, especially 1h / 4h for swing.
"""

import pandas as pd
import pandas_ta as ta
import numpy as np

from strategies.base import BaseStrategy, Signal, StrategyResult


class SupertrendStrategy(BaseStrategy):
    NAME   = "Supertrend"
    TP_PCT = 3.0
    SL_PCT = 1.5

    def __init__(self, period: int = 10, multiplier: float = 3.0,
                 ema_filter: int = 200):
        self.period     = period
        self.multiplier = multiplier
        self.ema_filter = ema_filter

    def min_candles(self) -> int:
        return self.ema_filter + 20

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        price = close.iloc[-1]

        st  = ta.supertrend(high, low, close,
                            length=self.period, multiplier=self.multiplier)
        ema = ta.ema(close, length=self.ema_filter)

        if st is None or ema is None:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="indicator error")

        # pandas_ta supertrend column names
        dir_col  = f"SUPERTd_{self.period}_{self.multiplier}"
        line_col = f"SUPERT_{self.period}_{self.multiplier}"

        if dir_col not in st.columns:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="ST column missing")

        st_dir_now  = st[dir_col].iloc[-1]   # 1 = bullish, -1 = bearish
        st_dir_prev = st[dir_col].iloc[-2]
        st_line     = st[line_col].iloc[-1]
        ema_val     = ema.iloc[-1]

        bull_flip = (st_dir_prev == -1) and (st_dir_now == 1)
        bear_flip = (st_dir_prev == 1)  and (st_dir_now == -1)
        macro_up  = price > ema_val
        macro_dn  = price < ema_val

        signal = Signal.NONE
        reason = ""

        if bull_flip and macro_up:
            signal = Signal.LONG
            reason = (f"Supertrend flipped bullish at {st_line:.4f}; "
                      f"price {price:.4f} > EMA{self.ema_filter} {ema_val:.4f}")
        elif bear_flip and macro_dn:
            signal = Signal.SHORT
            reason = (f"Supertrend flipped bearish at {st_line:.4f}; "
                      f"price {price:.4f} < EMA{self.ema_filter} {ema_val:.4f}")
        elif bear_flip:
            signal = Signal.CLOSE
            reason = "Supertrend bearish flip — close long"
        elif bull_flip:
            signal = Signal.CLOSE
            reason = "Supertrend bullish flip — close short"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)

        # Confidence based on how far price is from ST line (momentum)
        dist_pct = abs(price - st_line) / price * 100
        conf     = min(1.0, dist_pct / 3.0) if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"st_direction": st_dir_now, "st_line": st_line,
                  "ema_filter": ema_val}
        )
