# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 10: Squeeze Momentum (Volatility Squeeze)
====================================================
Detects low-volatility compression by comparing Bollinger Band width to
Keltner Channel width. When BB is inside KC, the market is in a "squeeze"
(consolidation). When BB expands beyond KC, energy is released — the
direction of the momentum histogram determines long or short.

This mathematical concept combines two public-domain indicators:
  - Bollinger Bands formula (standard deviation envelope)
  - Keltner Channels formula (ATR envelope)

The BB-inside-KC squeeze detection concept was popularised in the
TradingView community by LazyBear (Vikram Murthy) via an open-source
Pine Script. This Python implementation is an independent re-implementation
of the public mathematical concept — no Pine Script code was copied.

NOTE: "TTM Squeeze" is a commercial product name of Simpler Trading / John Carter.
That name is NOT used anywhere in this codebase. This implementation uses
the generic descriptive term "Squeeze Momentum" only.

Logic:
  Squeeze ON  → BB is inside KC (low volatility, market coiling)
  Squeeze OFF → BB expands outside KC (breakout, energy released)

  LONG  → Squeeze just fired (OFF) + momentum histogram positive + rising
  SHORT → Squeeze just fired (OFF) + momentum histogram negative + falling
  EXIT  → Momentum crosses zero or reverses

Credits: Concept independently derived from public BB + KC formulas.
         LazyBear credited for open-source TradingView popularisation.
         John Carter / Simpler Trading credited for original TTM Squeeze concept.
"""

import pandas as pd
import pandas_ta as ta
import numpy as np

from strategies.base import BaseStrategy, Signal, StrategyResult


class SqueezeMomentumStrategy(BaseStrategy):
    NAME   = "Squeeze_Momentum"
    TP_PCT = 3.0
    SL_PCT = 1.5

    def __init__(self, bb_period: int = 20, bb_std: float = 2.0,
                 kc_period: int = 20, kc_mult: float = 1.5,
                 mom_period: int = 12):
        self.bb_period  = bb_period
        self.bb_std     = bb_std
        self.kc_period  = kc_period
        self.kc_mult    = kc_mult
        self.mom_period = mom_period

    def min_candles(self) -> int:
        return 80

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        price  = close.iloc[-1]

        # Bollinger Bands
        bb = ta.bbands(close, length=self.bb_period, std=self.bb_std)
        # Keltner Channels
        kc = ta.kc(high, low, close, length=self.kc_period,
                   scalar=self.kc_mult, mamode="ema")
        # Momentum oscillator (linear regression on delta)
        atr  = ta.atr(high, low, close, length=self.kc_period)

        if bb is None or kc is None or atr is None:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="indicator error")

        bb_upper = bb[f"BBU_{self.bb_period}_{self.bb_std}"]
        bb_lower = bb[f"BBL_{self.bb_period}_{self.bb_std}"]

        kc_cols = [c for c in kc.columns if "KCU" in c]
        kcl_cols = [c for c in kc.columns if "KCL" in c]
        if not kc_cols or not kcl_cols:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="KC columns not found")

        kc_upper = kc[kc_cols[0]]
        kc_lower = kc[kcl_cols[0]]

        # Squeeze: BB inside KC
        squeeze   = (bb_upper < kc_upper) & (bb_lower > kc_lower)
        sq_now    = squeeze.iloc[-1]
        sq_prev   = squeeze.iloc[-2]
        sq_fired  = (sq_prev == True) and (sq_now == False)   # release

        # Momentum: delta from N-bar lookback linear regression
        highest_high = high.rolling(self.mom_period).max()
        lowest_low   = low.rolling(self.mom_period).min()
        mid_hl       = (highest_high + lowest_low) / 2
        mid_ema      = ta.ema(close, length=self.mom_period)
        delta        = close - (mid_hl + mid_ema) / 2
        # 1-period linreg is just the value itself; use EMA for smooth momentum
        momentum     = ta.linreg(delta, length=self.mom_period) if hasattr(ta, 'linreg') else delta.rolling(self.mom_period).mean()

        mom_now  = momentum.iloc[-1] if momentum is not None else 0
        mom_prev = momentum.iloc[-2] if momentum is not None else 0

        mom_bull = mom_now > 0 and mom_now > mom_prev
        mom_bear = mom_now < 0 and mom_now < mom_prev
        mom_zero_cross_up   = mom_prev < 0 and mom_now >= 0
        mom_zero_cross_down = mom_prev > 0 and mom_now <= 0

        signal = Signal.NONE
        reason = ""

        if sq_fired and mom_bull:
            signal = Signal.LONG
            reason = (f"Squeeze fired! Momentum positive & rising "
                      f"({mom_now:.6f}); breakout to upside")
        elif sq_fired and mom_bear:
            signal = Signal.SHORT
            reason = (f"Squeeze fired! Momentum negative & falling "
                      f"({mom_now:.6f}); breakout to downside")
        elif mom_zero_cross_down:
            signal = Signal.CLOSE
            reason = f"Momentum crossed below zero — close long"
        elif mom_zero_cross_up:
            signal = Signal.CLOSE
            reason = f"Momentum crossed above zero — close short"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)
        conf   = min(1.0, abs(mom_now) * 100) if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"squeeze": sq_now, "sq_fired": sq_fired,
                  "momentum": mom_now, "bb_inside_kc": bool(sq_now)}
        )
