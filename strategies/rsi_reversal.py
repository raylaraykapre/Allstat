# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 2: RSI Reversal
========================
Mean-reversion strategy. Best performing on crypto intraday per academic studies.

Logic:
  LONG  → RSI dips below 30 (oversold) and starts turning up
  SHORT → RSI rises above 70 (overbought) and starts turning down
  EXIT  → RSI crosses back to neutral (45-55 zone)

Confluence filter: price must be near Bollinger Band edges.
Best on: ranging/mean-reverting pairs, 15m / 1h.
Academic reference: ResearchGate 2023 study — RSI beat B&H for all 5 cryptos.
"""

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class RSIReversalStrategy(BaseStrategy):
    NAME   = "RSI_Reversal"
    TP_PCT = 1.8
    SL_PCT = 1.0

    def __init__(self, rsi_period: int = 14,
                 oversold: float = 30, overbought: float = 70,
                 bb_period: int = 20, bb_std: float = 2.0):
        self.rsi_period  = rsi_period
        self.oversold    = oversold
        self.overbought  = overbought
        self.bb_period   = bb_period
        self.bb_std      = bb_std

    def min_candles(self) -> int:
        return 60

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close = df["close"]
        price = close.iloc[-1]

        rsi = ta.rsi(close, length=self.rsi_period)
        bb  = ta.bbands(close, length=self.bb_period, std=self.bb_std)

        if rsi is None or bb is None:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="indicator error")

        rsi_now  = rsi.iloc[-1]
        rsi_prev = rsi.iloc[-2]

        bb_lower = bb[f"BBL_{self.bb_period}_{self.bb_std}"].iloc[-1]
        bb_upper = bb[f"BBU_{self.bb_period}_{self.bb_std}"].iloc[-1]
        bb_mid   = bb[f"BBM_{self.bb_period}_{self.bb_std}"].iloc[-1]

        signal = Signal.NONE
        reason = ""

        # LONG: RSI was oversold, now turning up + price near lower BB
        if rsi_prev < self.oversold and rsi_now > rsi_prev and price <= bb_lower * 1.01:
            signal = Signal.LONG
            reason = (f"RSI {rsi_now:.1f} recovering from oversold "
                      f"({self.oversold}); price near lower BB {bb_lower:.4f}")

        # SHORT: RSI was overbought, now turning down + price near upper BB
        elif rsi_prev > self.overbought and rsi_now < rsi_prev and price >= bb_upper * 0.99:
            signal = Signal.SHORT
            reason = (f"RSI {rsi_now:.1f} turning down from overbought "
                      f"({self.overbought}); price near upper BB {bb_upper:.4f}")

        # EXIT: RSI returned to mid-zone
        elif 44 < rsi_now < 56:
            signal = Signal.CLOSE
            reason = f"RSI {rsi_now:.1f} in neutral zone — exit"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)
        conf   = min(1.0, abs(rsi_now - 50) / 30) if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"rsi": rsi_now, "bb_lower": bb_lower,
                  "bb_upper": bb_upper, "bb_mid": bb_mid}
        )
