# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Base strategy interface.
Every strategy must subclass BaseStrategy and implement generate_signal().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import pandas as pd


class Signal(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    CLOSE = "CLOSE"   # close existing position
    NONE  = "NONE"    # no action


@dataclass
class StrategyResult:
    """
    Output from a strategy's generate_signal() call.
    """
    signal:         Signal  = Signal.NONE
    strategy_name:  str     = ""
    symbol:         str     = ""
    entry_price:    float   = 0.0
    take_profit:    float   = 0.0
    stop_loss:      float   = 0.0
    confidence:     float   = 0.0   # 0.0 – 1.0
    reason:         str     = ""    # human-readable explanation

    # Extra info that strategies can populate
    meta:           dict    = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        return self.signal in (Signal.LONG, Signal.SHORT)


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    Subclasses must implement:
      - NAME  (class attribute)
      - generate_signal(df, symbol, funding_rate) -> StrategyResult
    """

    NAME: str = "BaseStrategy"

    # Default TP/SL multipliers — strategies can override
    TP_PCT: float = 2.0   # 2% take profit
    SL_PCT: float = 1.0   # 1% stop loss

    def generate_signal(self, df: pd.DataFrame, symbol: str = "",
                        funding_rate: float = 0.0) -> StrategyResult:
        """
        Analyse `df` (OHLCV DataFrame, oldest→newest) and return a StrategyResult.
        Subclasses must implement _compute().
        """
        if df is None or len(df) < self.min_candles():
            return StrategyResult(signal=Signal.NONE,
                                  strategy_name=self.NAME,
                                  symbol=symbol,
                                  reason="insufficient data")
        return self._compute(df, symbol, funding_rate)

    @abstractmethod
    def _compute(self, df: pd.DataFrame, symbol: str,
                 funding_rate: float) -> StrategyResult:
        """Core signal logic — must be implemented by subclasses."""
        ...

    def min_candles(self) -> int:
        """Minimum candles required before generating a signal."""
        return 50

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _tp_sl(entry: float, direction: Signal,
               tp_pct: float, sl_pct: float) -> tuple[float, float]:
        """Return (take_profit_price, stop_loss_price) for a given entry."""
        if direction == Signal.LONG:
            tp = entry * (1 + tp_pct / 100)
            sl = entry * (1 - sl_pct / 100)
        else:  # SHORT
            tp = entry * (1 - tp_pct / 100)
            sl = entry * (1 + sl_pct / 100)
        return round(tp, 6), round(sl, 6)
