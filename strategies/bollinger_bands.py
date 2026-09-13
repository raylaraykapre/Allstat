# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 4: Volatility Band Breakout / Mean Reversion
======================================================
Uses a moving average with upper/lower standard deviation envelopes
(a standard deviation band system) combined with squeeze detection.

The standard deviation envelope formula is standard mathematical fact
and is not proprietary. The name "Bollinger Bands®" is a registered
U.S. trademark of John Bollinger / Capital Growth Letter Inc. (Reg. 2011).
This codebase uses the generic descriptive term "BB" or "volatility bands"
and does not claim any affiliation with or endorsement by John Bollinger.

Dual-mode: breakout OR mean-reversion based on band width (squeeze).

Logic:
  Squeeze mode (narrow bands, low volatility):
    LONG  → Price breaks above upper band after squeeze + volume spike
    SHORT → Price breaks below lower band after squeeze + volume spike

  Mean-reversion mode (wide bands):
    LONG  → Price touches lower band + RSI < 35
    SHORT → Price touches upper band + RSI > 65

  Squeeze: band width < 20-period average band width × 0.75.

Credits: Standard deviation envelope concept — mathematical public domain.
         John Bollinger credited as populariser of this specific 2-sigma
         envelope application. See CREDITS.md for full detail.
"""

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class BollingerBandsStrategy(BaseStrategy):
    NAME   = "Bollinger_Bands"
    TP_PCT = 2.0
    SL_PCT = 1.0

    def __init__(self, period: int = 20, std_dev: float = 2.0,
                 rsi_period: int = 14, volume_factor: float = 1.5):
        self.period        = period
        self.std_dev       = std_dev
        self.rsi_period    = rsi_period
        self.volume_factor = volume_factor

    def min_candles(self) -> int:
        return 80

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close  = df["close"]
        volume = df["volume"]
        price  = close.iloc[-1]

        bb  = ta.bbands(close, length=self.period, std=self.std_dev)
        rsi = ta.rsi(close, length=self.rsi_period)

        if bb is None or rsi is None:
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="indicator error")

        upper = bb[f"BBU_{self.period}_{self.std_dev}"].iloc[-1]
        lower = bb[f"BBL_{self.period}_{self.std_dev}"].iloc[-1]
        mid   = bb[f"BBM_{self.period}_{self.std_dev}"].iloc[-1]
        bwp   = bb[f"BBB_{self.period}_{self.std_dev}"]  # bandwidth %

        rsi_val    = rsi.iloc[-1]
        vol_now    = volume.iloc[-1]
        vol_avg    = volume.rolling(20).mean().iloc[-1]
        vol_spike  = vol_now > vol_avg * self.volume_factor

        # Squeeze: current BB width vs historical average
        bwp_avg    = bwp.rolling(50).mean().iloc[-1]
        bwp_now    = bwp.iloc[-1]
        is_squeeze = bwp_now < bwp_avg * 0.75 if bwp_avg > 0 else False

        prev_close = close.iloc[-2]

        signal = Signal.NONE
        reason = ""

        if is_squeeze:
            # Breakout mode
            if price > upper and prev_close <= upper and vol_spike:
                signal = Signal.LONG
                reason = (f"BB breakout above upper {upper:.4f} "
                          f"after squeeze (BWP={bwp_now:.2f}); vol spike")
            elif price < lower and prev_close >= lower and vol_spike:
                signal = Signal.SHORT
                reason = (f"BB breakout below lower {lower:.4f} "
                          f"after squeeze (BWP={bwp_now:.2f}); vol spike")
        else:
            # Mean-reversion mode
            if price <= lower * 1.005 and rsi_val < 35:
                signal = Signal.LONG
                reason = (f"Price {price:.4f} at lower BB {lower:.4f}; "
                          f"RSI={rsi_val:.1f} oversold")
            elif price >= upper * 0.995 and rsi_val > 65:
                signal = Signal.SHORT
                reason = (f"Price {price:.4f} at upper BB {upper:.4f}; "
                          f"RSI={rsi_val:.1f} overbought")

        # Exit: price returns to midline
        if signal == Signal.NONE:
            prev2 = close.iloc[-3]
            if abs(price - mid) / mid < 0.002:
                signal = Signal.CLOSE
                reason = f"Price returned to BB midline {mid:.4f}"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)
        conf   = 0.75 if (is_squeeze and signal in (Signal.LONG, Signal.SHORT)) else \
                 0.55 if signal in (Signal.LONG, Signal.SHORT) else 0.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"bb_upper": upper, "bb_lower": lower, "bb_mid": mid,
                  "bb_width_pct": bwp_now, "squeeze": is_squeeze,
                  "rsi": rsi_val, "vol_spike": vol_spike}
        )
