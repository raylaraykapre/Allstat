# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 7: VWAP Deviation
==========================
VWAP (Volume-Weighted Average Price) with standard deviation bands.
Popular institutional strategy — TradingView free indicator.

Logic:
  LONG  → Price pulls back to VWAP -1.5σ band + RSI < 40
  SHORT → Price surges to VWAP +1.5σ band + RSI > 60
  EXIT  → Price returns to VWAP midline

Note: VWAP is calculated from the rolling window (daily reset not possible
on Bybit kline data without timestamps anchoring — we use a rolling window
approximation that works well for derivatives).
"""

import pandas as pd
import numpy as np
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class VWAPDeviationStrategy(BaseStrategy):
    NAME   = "VWAP_Deviation"
    TP_PCT = 1.5
    SL_PCT = 0.8

    def __init__(self, window: int = 20, num_std: float = 1.5,
                 rsi_period: int = 14):
        self.window     = window
        self.num_std    = num_std
        self.rsi_period = rsi_period

    def min_candles(self) -> int:
        return 60

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        volume = df["volume"]
        price  = close.iloc[-1]

        # Typical price
        typical = (high + low + close) / 3
        # VWAP = rolling sum(typical * volume) / rolling sum(volume)
        tp_vol      = typical * volume
        vwap        = tp_vol.rolling(self.window).sum() / volume.rolling(self.window).sum()
        vwap_std    = typical.rolling(self.window).std()

        vwap_now    = vwap.iloc[-1]
        std_now     = vwap_std.iloc[-1]
        upper_band  = vwap_now + self.num_std * std_now
        lower_band  = vwap_now - self.num_std * std_now

        rsi = ta.rsi(close, length=self.rsi_period)
        rsi_val = rsi.iloc[-1] if rsi is not None else 50

        prev_close = close.iloc[-2]
        vwap_prev  = vwap.iloc[-2]

        signal = Signal.NONE
        reason = ""

        # LONG: price dips to lower band and starts recovering
        if price <= lower_band and prev_close > lower_band and rsi_val < 40:
            signal = Signal.LONG
            reason = (f"Price {price:.4f} touched VWAP lower band {lower_band:.4f} "
                      f"(-{self.num_std}σ); RSI={rsi_val:.1f}")

        # SHORT: price spikes to upper band
        elif price >= upper_band and prev_close < upper_band and rsi_val > 60:
            signal = Signal.SHORT
            reason = (f"Price {price:.4f} hit VWAP upper band {upper_band:.4f} "
                      f"(+{self.num_std}σ); RSI={rsi_val:.1f}")

        # EXIT: price crosses back to VWAP midline
        elif ((prev_close < vwap_prev and price >= vwap_now) or
              (prev_close > vwap_prev and price <= vwap_now)):
            signal = Signal.CLOSE
            reason = f"Price crossed back to VWAP {vwap_now:.4f} — exit"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)

        # Confidence = how far from VWAP in std units
        z_score = abs(price - vwap_now) / std_now if std_now > 0 else 0
        conf    = min(1.0, z_score / 2.5) if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"vwap": vwap_now, "upper_band": upper_band,
                  "lower_band": lower_band, "z_score": z_score, "rsi": rsi_val}
        )
