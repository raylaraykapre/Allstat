# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 9: ADX / DMI Trend Strength
=====================================
Uses ADX to confirm trend strength and DI lines for direction.
TradingView DMI Toolbox — 64% win rate, 3.34 profit factor on crypto (3h).

Logic:
  LONG  → DI+ crosses above DI- + ADX > 25 (strong trend) + ADX rising
  SHORT → DI- crosses above DI+ + ADX > 25 + ADX rising
  EXIT  → ADX falls below 20 (trend weakening) OR DI cross reversal

Trend strength tiers:
  ADX 20-25: weak trend (avoid)
  ADX 25-40: strong trend (trade)
  ADX 40+  : very strong (trade with caution — potential exhaustion)
"""

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class ADXDMIStrategy(BaseStrategy):
    NAME   = "ADX_DMI"
    TP_PCT = 2.5
    SL_PCT = 1.2

    def __init__(self, adx_period: int = 14, adx_min: float = 25.0,
                 adx_max: float = 50.0):
        self.adx_period = adx_period
        self.adx_min    = adx_min
        self.adx_max    = adx_max

    def min_candles(self) -> int:
        return 60

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        price = close.iloc[-1]

        adx_df = ta.adx(high, low, close, length=self.adx_period)
        if adx_df is None:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="ADX error")

        adx_col  = f"ADX_{self.adx_period}"
        dmp_col  = f"DMP_{self.adx_period}"   # DI+
        dmn_col  = f"DMN_{self.adx_period}"   # DI-

        adx_now  = adx_df[adx_col].iloc[-1]
        adx_prev = adx_df[adx_col].iloc[-2]
        dip_now  = adx_df[dmp_col].iloc[-1]
        dip_prev = adx_df[dmp_col].iloc[-2]
        din_now  = adx_df[dmn_col].iloc[-1]
        din_prev = adx_df[dmn_col].iloc[-2]

        adx_rising    = adx_now > adx_prev
        trend_valid   = self.adx_min <= adx_now <= self.adx_max
        di_bull_cross = (dip_prev <= din_prev) and (dip_now > din_now)
        di_bear_cross = (dip_prev >= din_prev) and (dip_now < din_now)

        signal = Signal.NONE
        reason = ""

        if di_bull_cross and trend_valid and adx_rising:
            signal = Signal.LONG
            reason = (f"DI+ crossed above DI- ({dip_now:.1f} vs {din_now:.1f}); "
                      f"ADX={adx_now:.1f} rising")
        elif di_bear_cross and trend_valid and adx_rising:
            signal = Signal.SHORT
            reason = (f"DI- crossed above DI+ ({din_now:.1f} vs {dip_now:.1f}); "
                      f"ADX={adx_now:.1f} rising")
        elif adx_now < 20 or di_bear_cross or di_bull_cross:
            signal = Signal.CLOSE
            reason = f"ADX={adx_now:.1f} weakening or DI cross — close position"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)
        conf   = min(1.0, (adx_now - 20) / 30) if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"adx": adx_now, "di_plus": dip_now,
                  "di_minus": din_now, "adx_rising": adx_rising}
        )
