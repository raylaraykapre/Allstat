# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 6: Ichimoku Cloud
==========================
Full Ichimoku Kinko Hyo system — comprehensive trend confirmation.

Logic:
  LONG  → Price above cloud (kumo) + Tenkan > Kijun + Chikou above price 26 bars ago
           + Cloud is bullish (Senkou A > Senkou B)
  SHORT → Price below cloud + Tenkan < Kijun + Chikou below price 26 bars ago
           + Cloud is bearish (Senkou A < Senkou B)
  EXIT  → Price re-enters cloud OR Tenkan/Kijun crossover against position

Strongest signal: ALL 4 conditions met simultaneously (full alignment).
"""

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class IchimokuStrategy(BaseStrategy):
    NAME   = "Ichimoku"
    TP_PCT = 3.5
    SL_PCT = 1.8

    def __init__(self, tenkan: int = 9, kijun: int = 26,
                 senkou_b: int = 52, chikou: int = 26):
        self.tenkan   = tenkan
        self.kijun    = kijun
        self.senkou_b = senkou_b
        self.chikou   = chikou

    def min_candles(self) -> int:
        return self.senkou_b + self.chikou + 10

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        price = close.iloc[-1]

        # Compute Ichimoku manually (pandas_ta sometimes inconsistent)
        n = len(df)

        def midpoint(hi, lo, p): return (hi.rolling(p).max() + lo.rolling(p).min()) / 2

        tenkan_sen  = midpoint(high, low, self.tenkan)
        kijun_sen   = midpoint(high, low, self.kijun)
        senkou_a    = ((tenkan_sen + kijun_sen) / 2).shift(self.kijun)
        senkou_b    = midpoint(high, low, self.senkou_b).shift(self.kijun)
        chikou_span = close.shift(-self.chikou)

        tenkan_now  = tenkan_sen.iloc[-1]
        kijun_now   = kijun_sen.iloc[-1]
        tenkan_prev = tenkan_sen.iloc[-2]
        kijun_prev  = kijun_sen.iloc[-2]
        cloud_a_now = senkou_a.iloc[-1]
        cloud_b_now = senkou_b.iloc[-1]

        # Chikou confirmation: chikou 26 bars ago vs price 26 bars ago
        chikou_val   = close.iloc[-1 - self.chikou] if n > self.chikou else None
        price_26_ago = close.iloc[-1 - self.chikou * 2] if n > self.chikou * 2 else None

        cloud_top    = max(cloud_a_now, cloud_b_now)
        cloud_bottom = min(cloud_a_now, cloud_b_now)
        in_cloud     = cloud_bottom <= price <= cloud_top

        above_cloud  = price > cloud_top
        below_cloud  = price < cloud_bottom
        bull_cloud   = cloud_a_now > cloud_b_now
        bear_cloud   = cloud_a_now < cloud_b_now

        tk_bull_cross = (tenkan_prev <= kijun_prev) and (tenkan_now > kijun_now)
        tk_bear_cross = (tenkan_prev >= kijun_prev) and (tenkan_now < kijun_now)

        chikou_bull = (chikou_val is not None and price_26_ago is not None
                       and chikou_val > price_26_ago)
        chikou_bear = (chikou_val is not None and price_26_ago is not None
                       and chikou_val < price_26_ago)

        # Score conditions (0-4)
        long_score  = sum([above_cloud, tenkan_now > kijun_now,
                           bull_cloud, chikou_bull])
        short_score = sum([below_cloud, tenkan_now < kijun_now,
                           bear_cloud, chikou_bear])

        signal = Signal.NONE
        reason = ""

        if long_score >= 3 and tk_bull_cross:
            signal = Signal.LONG
            reason = (f"Ichimoku full bull alignment (score={long_score}/4); "
                      f"TK cross; above cloud")
        elif short_score >= 3 and tk_bear_cross:
            signal = Signal.SHORT
            reason = (f"Ichimoku full bear alignment (score={short_score}/4); "
                      f"TK cross; below cloud")
        elif in_cloud or tk_bear_cross or tk_bull_cross:
            signal = Signal.CLOSE
            reason = f"Price entered cloud or TK cross reversal — exit position"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)
        conf   = (long_score if signal == Signal.LONG else
                  short_score if signal == Signal.SHORT else 0) / 4.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"tenkan": tenkan_now, "kijun": kijun_now,
                  "cloud_top": cloud_top, "cloud_bottom": cloud_bottom,
                  "long_score": long_score, "short_score": short_score}
        )
