# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Backtesting Engine
==================
Event-driven backtester that replays OHLCV candles through any strategy.
Simulates realistic trade execution with:
  - Taker fee (0.06% Bybit default)
  - Slippage (0.02% conservative estimate)
  - Per-trade TP/SL enforcement
  - Position sizing via leverage
  - Trade log with full P&L breakdown

Scoring metrics returned:
  - win_rate       : % of winning trades
  - profit_factor  : gross_profit / gross_loss
  - total_return   : % return over the period
  - max_drawdown   : largest equity drop from peak
  - sharpe_ratio   : annualised risk-adjusted return
  - num_trades     : total trades executed
  - score          : composite score (0-100) for strategy selection
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, StrategyResult
from core.logger import get_logger

log = get_logger(__name__)

# Bybit fee constants
TAKER_FEE   = 0.0006   # 0.06%
SLIPPAGE    = 0.0002   # 0.02%
TOTAL_COST  = TAKER_FEE + SLIPPAGE  # per side; doubled for round-trip


@dataclass
class Trade:
    direction:   str       = ""       # "long" | "short"
    entry_price: float     = 0.0
    exit_price:  float     = 0.0
    entry_idx:   int       = 0
    exit_idx:    int       = 0
    qty:         float     = 1.0
    tp:          float     = 0.0
    sl:          float     = 0.0
    pnl_pct:     float     = 0.0      # % P&L net of fees
    pnl_usdt:    float     = 0.0
    exit_reason: str       = ""       # "TP" | "SL" | "signal" | "end"


@dataclass
class BacktestResult:
    strategy_name:  str         = ""
    symbol:         str         = ""
    timeframe:      str         = ""
    num_candles:    int         = 0
    num_trades:     int         = 0
    win_rate:       float       = 0.0
    profit_factor:  float       = 0.0
    total_return:   float       = 0.0   # %
    max_drawdown:   float       = 0.0   # %
    sharpe_ratio:   float       = 0.0
    avg_win_pct:    float       = 0.0
    avg_loss_pct:   float       = 0.0
    score:          float       = 0.0   # composite 0-100
    trades:         List[Trade] = field(default_factory=list)
    equity_curve:   List[float] = field(default_factory=list)

    def is_valid(self, min_trades: int = 10, min_win_rate: float = 0.45,
                 min_pf: float = 1.3) -> bool:
        return (self.num_trades >= min_trades and
                self.win_rate   >= min_win_rate and
                self.profit_factor >= min_pf)

    def summary(self) -> str:
        return (
            f"{self.strategy_name:20s} | "
            f"Trades={self.num_trades:4d} | "
            f"WR={self.win_rate*100:5.1f}% | "
            f"PF={self.profit_factor:5.2f} | "
            f"Ret={self.total_return:+7.2f}% | "
            f"DD={self.max_drawdown:5.2f}% | "
            f"Sharpe={self.sharpe_ratio:5.2f} | "
            f"Score={self.score:5.1f}"
        )


class Backtester:
    """
    Runs a single strategy against a full OHLCV DataFrame.
    Uses a simple bar-by-bar simulation — no look-ahead bias.
    """

    def __init__(self,
                 initial_capital: float = 1000.0,
                 leverage:        float = 5.0,
                 risk_per_trade:  float = 0.01,   # 1% of capital per trade
                 min_trades:      int   = 10,
                 min_win_rate:    float = 0.45,
                 min_pf:          float = 1.3):

        self.initial_capital = initial_capital
        self.leverage        = leverage
        self.risk_per_trade  = risk_per_trade
        self.min_trades      = min_trades
        self.min_win_rate    = min_win_rate
        self.min_pf          = min_pf

    def run(self, df: pd.DataFrame, strategy: BaseStrategy,
            symbol: str = "", timeframe: str = "") -> BacktestResult:
        """
        Replay every candle through the strategy and simulate trades.
        df must have columns: open, high, low, close, volume (oldest first).
        """
        result = BacktestResult(
            strategy_name=strategy.NAME,
            symbol=symbol,
            timeframe=timeframe,
            num_candles=len(df),
        )

        if len(df) < strategy.min_candles() + 5:
            log.debug(f"Backtest skip {strategy.NAME}/{symbol}: not enough candles "
                      f"({len(df)} < {strategy.min_candles()})")
            return result

        capital      = self.initial_capital
        equity       = [capital]
        trades: List[Trade] = []
        open_trade: Optional[Trade] = None
        warmup       = strategy.min_candles()

        for i in range(warmup, len(df)):
            candle  = df.iloc[i]
            h, l, c = candle["high"], candle["low"], candle["close"]

            # ── Manage open trade ────────────────────────────────
            if open_trade is not None:
                closed, exit_price, reason = self._check_exit(
                    open_trade, h, l, c)
                if closed:
                    pnl_pct, pnl_usdt = self._calc_pnl(
                        open_trade, exit_price, capital)
                    open_trade.exit_price  = exit_price
                    open_trade.exit_idx    = i
                    open_trade.pnl_pct     = pnl_pct
                    open_trade.pnl_usdt    = pnl_usdt
                    open_trade.exit_reason = reason
                    capital += pnl_usdt
                    capital  = max(capital, 0.01)  # no negative capital
                    trades.append(open_trade)
                    equity.append(capital)
                    open_trade = None
                    continue

            # ── Generate signal on this bar ──────────────────────
            if open_trade is None:
                window = df.iloc[max(0, i - strategy.min_candles() - 5): i + 1]
                try:
                    sig: StrategyResult = strategy.generate_signal(window, symbol)
                except Exception as e:
                    log.debug(f"Strategy error at bar {i}: {e}")
                    continue

                if sig.signal in (Signal.LONG, Signal.SHORT):
                    entry_price = c * (1 + SLIPPAGE if sig.signal == Signal.LONG
                                       else 1 - SLIPPAGE)
                    qty = (capital * self.risk_per_trade * self.leverage) / entry_price

                    open_trade = Trade(
                        direction  = "long" if sig.signal == Signal.LONG else "short",
                        entry_price= entry_price,
                        entry_idx  = i,
                        qty        = qty,
                        tp         = sig.take_profit,
                        sl         = sig.stop_loss,
                    )

            equity.append(capital)

        # Close any open trade at end of data
        if open_trade is not None:
            last_close = df["close"].iloc[-1]
            pnl_pct, pnl_usdt = self._calc_pnl(open_trade, last_close, capital)
            open_trade.exit_price  = last_close
            open_trade.exit_idx    = len(df) - 1
            open_trade.pnl_pct     = pnl_pct
            open_trade.pnl_usdt    = pnl_usdt
            open_trade.exit_reason = "end"
            capital += pnl_usdt
            trades.append(open_trade)

        # ── Compute metrics ──────────────────────────────────────
        result.trades       = trades
        result.equity_curve = equity
        result.num_trades   = len(trades)

        if trades:
            result = self._compute_metrics(result, equity)

        return result

    # ── Private helpers ──────────────────────────────────────────────────

    def _check_exit(self, trade: Trade, high: float, low: float,
                    close: float) -> tuple[bool, float, str]:
        """
        Check if TP, SL, or neither is hit during this candle.
        Returns (closed, exit_price, reason).
        """
        if trade.direction == "long":
            if trade.sl > 0 and low <= trade.sl:
                return True, trade.sl, "SL"
            if trade.tp > 0 and high >= trade.tp:
                return True, trade.tp, "TP"
        else:  # short
            if trade.sl > 0 and high >= trade.sl:
                return True, trade.sl, "SL"
            if trade.tp > 0 and low <= trade.tp:
                return True, trade.tp, "TP"
        return False, close, ""

    def _calc_pnl(self, trade: Trade, exit_price: float,
                  capital: float) -> tuple[float, float]:
        """
        Calculate net P&L including fees (both entry and exit taker fees).
        Returns (pnl_pct, pnl_usdt).
        """
        if trade.direction == "long":
            raw_pct = (exit_price - trade.entry_price) / trade.entry_price
        else:
            raw_pct = (trade.entry_price - exit_price) / trade.entry_price

        # Deduct fees (entry + exit, both taker)
        fee_pct = TOTAL_COST * 2
        net_pct = raw_pct * self.leverage - fee_pct

        notional   = trade.qty * trade.entry_price
        pnl_usdt   = notional * (net_pct / self.leverage)
        return round(net_pct * 100, 4), round(pnl_usdt, 4)

    def _compute_metrics(self, result: BacktestResult,
                         equity: List[float]) -> BacktestResult:
        trades = result.trades
        wins   = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]

        result.win_rate    = len(wins) / len(trades) if trades else 0
        gross_profit       = sum(t.pnl_pct for t in wins)
        gross_loss         = abs(sum(t.pnl_pct for t in losses)) or 1e-9
        result.profit_factor = gross_profit / gross_loss
        result.avg_win_pct   = (gross_profit / len(wins)) if wins else 0
        result.avg_loss_pct  = (gross_loss / len(losses)) if losses else 0

        # Total return
        if equity:
            result.total_return = (equity[-1] / equity[0] - 1) * 100

        # Max drawdown
        peak    = equity[0]
        max_dd  = 0.0
        for val in equity:
            if val > peak:
                peak = val
            dd = (peak - val) / peak * 100
            max_dd = max(max_dd, dd)
        result.max_drawdown = max_dd

        # Sharpe ratio (annualised, assuming daily returns from equity curve)
        eq_arr  = np.array(equity, dtype=float)
        returns = np.diff(eq_arr) / eq_arr[:-1]
        if len(returns) > 1 and returns.std() > 0:
            # Approximate: 365 trading days
            result.sharpe_ratio = (returns.mean() / returns.std()) * math.sqrt(365)
        else:
            result.sharpe_ratio = 0.0

        # Composite score (0-100)
        result.score = self._composite_score(result)
        return result

    @staticmethod
    def _composite_score(r: BacktestResult) -> float:
        """
        Weighted composite score for strategy ranking.
        Higher = better strategy for this symbol.
        """
        if r.num_trades == 0:
            return 0.0

        # Normalise each metric to 0-1
        wr_score   = min(1.0, max(0.0, (r.win_rate - 0.40) / 0.35))      # 40-75%
        pf_score   = min(1.0, max(0.0, (r.profit_factor - 1.0) / 2.0))   # 1.0-3.0
        ret_score  = min(1.0, max(0.0, r.total_return / 50.0))            # 0-50%
        dd_score   = min(1.0, max(0.0, 1 - r.max_drawdown / 30.0))       # lower DD = better
        sh_score   = min(1.0, max(0.0, r.sharpe_ratio / 3.0))             # 0-3
        trades_ok  = min(1.0, r.num_trades / 30)                          # more trades = confident

        score = (
            wr_score  * 25 +
            pf_score  * 30 +
            ret_score * 20 +
            dd_score  * 15 +
            sh_score  * 5  +
            trades_ok * 5
        )
        return round(score, 2)
