# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy Selector
=================
For each trading pair, runs ALL enabled strategies through the backtester
and selects the single best-performing one.

Results are cached to disk so the bot doesn't re-backtest on every restart
unless the cache is stale (older than `cache_ttl_hours`).

Selection criteria (in order of priority):
  1. Must pass minimum validity thresholds (min_trades, min_win_rate, min_pf)
  2. Highest composite score wins
  3. Fallback: Multi_Factor strategy (most robust across conditions)

Uses asyncio + ThreadPoolExecutor for parallel backtesting of all pairs.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Optional, List, Tuple

import pandas as pd

from core.backtester import Backtester, BacktestResult
from core.bybit_connector import BybitConnector
from core.config_loader import get_config
from core.logger import get_logger
from strategies.base import BaseStrategy
from strategies.registry import get_enabled_strategies, get_strategy_by_name

log = get_logger(__name__)

CACHE_DIR      = Path("data/strategy_cache")
CACHE_TTL_SECS = 6 * 3600   # 6 hours


class StrategySelector:
    """
    Determines the best strategy for each symbol via parallel backtesting.
    """

    def __init__(self, connector: BybitConnector):
        self.connector  = connector
        self.cfg        = get_config()
        self.bt_cfg     = self.cfg["backtest"]
        self.backtester = Backtester(
            leverage      = self.cfg["trading"]["leverage"],
            min_trades    = self.bt_cfg["min_trades"],
            min_win_rate  = self.bt_cfg["min_win_rate"],
            min_pf        = self.bt_cfg["min_profit_factor"],
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public API ───────────────────────────────────────────────────────

    def select_for_symbol(self, symbol: str,
                          force_refresh: bool = False) -> Optional[BaseStrategy]:
        """
        Return the best strategy instance for `symbol`.
        Uses cache if available and fresh.
        """
        cached = self._load_cache(symbol)
        if cached and not force_refresh:
            strat = get_strategy_by_name(cached["strategy_name"])
            log.info(f"[{symbol}] Cached strategy: {cached['strategy_name']} "
                     f"(score={cached['score']:.1f}, "
                     f"WR={cached['win_rate']*100:.1f}%)")
            return strat

        results = self._run_all_backtests(symbol)
        best    = self._pick_best(results, symbol)

        if best:
            self._save_cache(symbol, best)
            return get_strategy_by_name(best.strategy_name)

        # Fallback to multi-factor
        log.warning(f"[{symbol}] No strategy passed thresholds — "
                    f"using Multi_Factor fallback")
        return get_strategy_by_name("Multi_Factor")

    def select_for_symbols(self, symbols: List[str],
                           max_workers: int = 8,
                           force_refresh: bool = False) -> Dict[str, BaseStrategy]:
        """
        Parallel strategy selection for a list of symbols.
        Returns {symbol: strategy_instance}.
        """
        results: Dict[str, BaseStrategy] = {}

        # Separate symbols needing refresh from cached ones
        to_backtest = []
        for sym in symbols:
            cached = self._load_cache(sym)
            if cached and not force_refresh:
                strat = get_strategy_by_name(cached["strategy_name"])
                if strat:
                    results[sym] = strat
            else:
                to_backtest.append(sym)

        if not to_backtest:
            log.info(f"All {len(symbols)} symbols loaded from cache")
            return results

        log.info(f"Running backtests for {len(to_backtest)} symbols "
                 f"({max_workers} workers)…")

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._safe_select, sym): sym
                for sym in to_backtest
            }
            done = 0
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    strat = future.result()
                    if strat:
                        results[sym] = strat
                except Exception as e:
                    log.error(f"select_for_symbol({sym}) failed: {e}")
                done += 1
                if done % 10 == 0:
                    log.info(f"  Backtest progress: {done}/{len(to_backtest)}")

        log.info(f"Strategy selection complete: {len(results)}/{len(symbols)} symbols")
        return results

    def print_backtest_report(self, symbol: str) -> None:
        """Print a full backtest report for all strategies on a symbol."""
        results = self._run_all_backtests(symbol)
        if not results:
            log.warning(f"No backtest results for {symbol}")
            return

        print(f"\n{'='*90}")
        print(f" Backtest Report: {symbol} | {self.bt_cfg['timeframe']} "
              f"| {self.bt_cfg['candle_limit']} candles")
        print(f"{'='*90}")
        sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
        for r in sorted_results:
            valid = "✓" if r.is_valid(self.bt_cfg["min_trades"],
                                       self.bt_cfg["min_win_rate"],
                                       self.bt_cfg["min_profit_factor"]) else "✗"
            print(f"  [{valid}] {r.summary()}")
        print(f"{'='*90}\n")

    # ── Private helpers ──────────────────────────────────────────────────

    def _safe_select(self, symbol: str) -> Optional[BaseStrategy]:
        """Wraps select_for_symbol with error handling for thread pool."""
        try:
            return self.select_for_symbol(symbol)
        except Exception as e:
            log.error(f"_safe_select({symbol}): {e}")
            return get_strategy_by_name("Multi_Factor")

    def _run_all_backtests(self, symbol: str) -> List[BacktestResult]:
        """Fetch candles once, run all enabled strategies, return results list."""
        tf     = self.bt_cfg["timeframe"]
        limit  = self.bt_cfg["candle_limit"]

        df = self.connector.get_klines(symbol, interval=tf, limit=limit)
        if df.empty:
            log.warning(f"No klines for {symbol}")
            return []

        strategies  = get_enabled_strategies()
        all_results = []

        for strategy in strategies:
            try:
                res = self.backtester.run(df, strategy, symbol=symbol, timeframe=tf)
                all_results.append(res)
                log.debug(f"  {symbol}/{strategy.NAME}: "
                          f"score={res.score:.1f} trades={res.num_trades} "
                          f"WR={res.win_rate*100:.1f}%")
            except Exception as e:
                log.debug(f"Backtest error {symbol}/{strategy.NAME}: {e}")

        return all_results

    def _pick_best(self, results: List[BacktestResult],
                   symbol: str) -> Optional[BacktestResult]:
        """Pick the highest-scoring valid result."""
        valid = [
            r for r in results
            if r.is_valid(self.bt_cfg["min_trades"],
                          self.bt_cfg["min_win_rate"],
                          self.bt_cfg["min_profit_factor"])
        ]
        if not valid:
            log.debug(f"[{symbol}] No valid strategy found in backtest")
            return None

        best = max(valid, key=lambda r: r.score)
        log.info(f"[{symbol}] Best strategy: {best.strategy_name} "
                 f"score={best.score:.1f} WR={best.win_rate*100:.1f}% "
                 f"PF={best.profit_factor:.2f} ret={best.total_return:.2f}%")
        return best

    # ── Cache helpers ────────────────────────────────────────────────────

    def _cache_path(self, symbol: str) -> Path:
        return CACHE_DIR / f"{symbol}.json"

    def _load_cache(self, symbol: str) -> Optional[dict]:
        path = self._cache_path(symbol)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            age  = time.time() - data.get("timestamp", 0)
            if age > CACHE_TTL_SECS:
                return None
            return data
        except Exception:
            return None

    def _save_cache(self, symbol: str, result: BacktestResult) -> None:
        path = self._cache_path(symbol)
        try:
            data = {
                "symbol":        result.symbol,
                "strategy_name": result.strategy_name,
                "score":         result.score,
                "win_rate":      result.win_rate,
                "profit_factor": result.profit_factor,
                "total_return":  result.total_return,
                "max_drawdown":  result.max_drawdown,
                "sharpe_ratio":  result.sharpe_ratio,
                "num_trades":    result.num_trades,
                "timeframe":     result.timeframe,
                "timestamp":     time.time(),
            }
            path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.debug(f"Cache write error ({symbol}): {e}")
