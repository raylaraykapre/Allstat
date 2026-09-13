# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy 12: Multi-Factor Confluence (Supertrend + EMA + RSI + MACD)
======================================================================
Combines the 4 strongest individual signals into one high-confidence strategy.
Inspired by TradingView's "asami.Multifactor + Supertrend AutoTrade" (free).
Requires 3 of 4 confirmations for entry.

Factors checked:
  1. Supertrend direction
  2. EMA alignment (fast > slow > 200 for bull)
  3. RSI (not overbought/oversold extremes for entry)
  4. MACD histogram (positive = bullish momentum)

Scoring:
  4/4 = ultra high confidence
  3/4 = high confidence → enter
  2/4 = wait
  1/4 = skip

Minimum required score to enter: 3
"""

import pandas as pd
import pandas_ta as ta

from strategies.base import BaseStrategy, Signal, StrategyResult


class MultiFactorStrategy(BaseStrategy):
    NAME   = "Multi_Factor"
    TP_PCT = 3.5
    SL_PCT = 1.5

    def __init__(self,
                 ema_fast: int = 9, ema_slow: int = 21, ema_trend: int = 200,
                 st_period: int = 10, st_mult: float = 3.0,
                 rsi_period: int = 14,
                 macd_fast: int = 12, macd_slow: int = 26, macd_sig: int = 9,
                 min_score: int = 3):
        self.ema_fast   = ema_fast
        self.ema_slow   = ema_slow
        self.ema_trend  = ema_trend
        self.st_period  = st_period
        self.st_mult    = st_mult
        self.rsi_period = rsi_period
        self.macd_fast  = macd_fast
        self.macd_slow  = macd_slow
        self.macd_sig   = macd_sig
        self.min_score  = min_score

    def min_candles(self) -> int:
        return self.ema_trend + 30

    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        price = close.iloc[-1]

        # --- Compute all indicators ---
        ema_f = ta.ema(close, length=self.ema_fast)
        ema_s = ta.ema(close, length=self.ema_slow)
        ema_t = ta.ema(close, length=self.ema_trend)
        st    = ta.supertrend(high, low, close,
                              length=self.st_period, multiplier=self.st_mult)
        rsi   = ta.rsi(close, length=self.rsi_period)
        macd  = ta.macd(close, fast=self.macd_fast,
                        slow=self.macd_slow, signal=self.macd_sig)

        if any(x is None for x in [ema_f, ema_s, ema_t, st, rsi, macd]):
            return StrategyResult(signal=Signal.NONE, strategy_name=self.NAME,
                                  symbol=symbol, reason="indicator error")

        # --- Factor 1: Supertrend ---
        dir_col  = f"SUPERTd_{self.st_period}_{self.st_mult}"
        st_bull  = st[dir_col].iloc[-1] == 1 if dir_col in st.columns else False
        st_bear  = st[dir_col].iloc[-1] == -1 if dir_col in st.columns else False
        st_prev  = st[dir_col].iloc[-2] if dir_col in st.columns else 0
        st_flipped_bull = (st_prev == -1) and st_bull
        st_flipped_bear = (st_prev == 1)  and st_bear

        # --- Factor 2: EMA Alignment ---
        ef, es, et = ema_f.iloc[-1], ema_s.iloc[-1], ema_t.iloc[-1]
        ema_bull   = ef > es and es > et and price > et
        ema_bear   = ef < es and es < et and price < et

        # --- Factor 3: RSI (confirm not overextended) ---
        rsi_val   = rsi.iloc[-1]
        rsi_ok_long  = 40 < rsi_val < 70   # not overbought, momentum present
        rsi_ok_short = 30 < rsi_val < 60   # not oversold, momentum present

        # --- Factor 4: MACD histogram ---
        hist_col     = f"MACDh_{self.macd_fast}_{self.macd_slow}_{self.macd_sig}"
        hist_now     = macd[hist_col].iloc[-1] if hist_col in macd.columns else 0
        hist_prev    = macd[hist_col].iloc[-2] if hist_col in macd.columns else 0
        macd_bull    = hist_now > 0 and hist_now > hist_prev
        macd_bear    = hist_now < 0 and hist_now < hist_prev

        # --- Score ---
        long_score  = sum([st_bull, ema_bull, rsi_ok_long, macd_bull])
        short_score = sum([st_bear, ema_bear, rsi_ok_short, macd_bear])

        long_entry  = long_score  >= self.min_score
        short_entry = short_score >= self.min_score

        # Prefer flip signals as triggers
        signal = Signal.NONE
        reason = ""

        if long_entry and (st_flipped_bull or long_score == 4):
            signal = Signal.LONG
            reason = (f"Multi-factor LONG: score={long_score}/4 "
                      f"[ST={st_bull}, EMA={ema_bull}, "
                      f"RSI={rsi_ok_long}({rsi_val:.0f}), MACD={macd_bull}]")
        elif short_entry and (st_flipped_bear or short_score == 4):
            signal = Signal.SHORT
            reason = (f"Multi-factor SHORT: score={short_score}/4 "
                      f"[ST={st_bear}, EMA={ema_bear}, "
                      f"RSI={rsi_ok_short}({rsi_val:.0f}), MACD={macd_bear}]")
        elif st_flipped_bear or (ema_bear and not ema_bull and long_score <= 1):
            signal = Signal.CLOSE
            reason = f"Multi-factor: conditions reversed — close long"
        elif st_flipped_bull or (ema_bull and not ema_bear and short_score <= 1):
            signal = Signal.CLOSE
            reason = f"Multi-factor: conditions reversed — close short"

        tp, sl = self._tp_sl(price, signal, self.TP_PCT, self.SL_PCT)
        score   = long_score if signal == Signal.LONG else \
                  short_score if signal == Signal.SHORT else 0
        conf    = score / 4.0

        return StrategyResult(
            signal=signal, strategy_name=self.NAME, symbol=symbol,
            entry_price=price, take_profit=tp, stop_loss=sl,
            confidence=conf, reason=reason,
            meta={"long_score": long_score, "short_score": short_score,
                  "ema_fast": ef, "ema_slow": es, "ema_trend": et,
                  "st_bull": st_bull, "rsi": rsi_val,
                  "macd_hist": hist_now}
        )
