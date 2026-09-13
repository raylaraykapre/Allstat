# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Async Multi-Pair Scanner
========================
The hot loop of the bot. Runs continuously, scanning ALL derivative pairs
for trade signals as fast as possible using asyncio concurrency.

Architecture:
  - asyncio event loop
  - asyncio.Semaphore limits concurrent REST calls (avoids rate-limit)
  - Each symbol is scanned in its own coroutine
  - Per-symbol assigned strategy from StrategySelector
  - Results fed to TradeExecutor
  - Live candle updates via WebSocket (optional acceleration)
  - Rich live table displayed in terminal

Rate limit awareness:
  Bybit allows ~120 req/min per IP on REST.
  With semaphore=10 and ~5 symbols/batch, one full cycle stays well within limit.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional

import pandas as pd
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich import box

from core.bybit_connector import BybitConnector
from core.config_loader import get_config
from core.logger import get_logger
from core.trade_executor import TradeExecutor
from core.strategy_selector import StrategySelector
from strategies.base import BaseStrategy, Signal, StrategyResult

log     = get_logger(__name__)
console = Console()


class Scanner:
    """
    Async scanner: fetch klines → run strategy → pass signal to executor.
    Covers all enabled derivative pairs concurrently.
    """

    def __init__(self,
                 connector:  BybitConnector,
                 executor:   TradeExecutor,
                 selector:   StrategySelector,
                 demo_mode:  bool = False):

        self.connector  = connector
        self.executor   = executor
        self.selector   = selector
        self.demo_mode  = demo_mode
        self.cfg        = get_config()
        self.scan_cfg   = self.cfg["scanner"]

        self.interval    = self.scan_cfg["interval_seconds"]
        self.timeframe   = self.scan_cfg["primary_timeframe"]
        self.candle_limit= self.scan_cfg["candle_limit"]
        self.min_volume  = self.scan_cfg["min_volume_usdt"]

        # {symbol: strategy_instance}
        self.symbol_strategies: Dict[str, BaseStrategy] = {}

        # Concurrency control — stay under Bybit rate limits
        self._sem = asyncio.Semaphore(10)

        # Latest signal state for display
        self._signal_log: List[dict] = []
        self._running = False
        self._cycle   = 0

    # ── Public API ────────────────────────────────────────────────────────

    async def initialise(self) -> None:
        """
        One-time setup: fetch all symbols, run strategy selection.
        This blocks until all backtests are done (uses thread pool internally).
        """
        console.print("[bold cyan]Fetching all derivative pairs…[/bold cyan]")
        symbols = self.connector.get_all_symbols(self.min_volume)

        if not symbols:
            log.error("No symbols returned — check API connection")
            return

        console.print(f"[green]Found {len(symbols)} tradeable pairs[/green]")
        console.print("[bold cyan]Running strategy selection backtests…[/bold cyan]"
                      " [dim](this takes ~1-3 minutes)[/dim]")

        # Strategy selection in thread pool (CPU-bound, not async)
        loop = asyncio.get_event_loop()
        self.symbol_strategies = await loop.run_in_executor(
            None,
            self.selector.select_for_symbols,
            symbols,
        )

        console.print(f"[green]Strategy selection complete for "
                      f"{len(self.symbol_strategies)} pairs ✓[/green]")

    async def run_forever(self) -> None:
        """
        Main scan loop. Runs indefinitely until interrupted.
        Scans all pairs every `interval_seconds`.
        """
        self._running = True

        with Live(self._build_table(), refresh_per_second=2,
                  console=console) as live:
            while self._running:
                cycle_start = time.monotonic()
                self._cycle += 1

                # Scan all symbols concurrently
                await self._scan_all(live)

                # Monitor open positions
                self.executor.monitor_positions()

                # Sleep remainder of interval
                elapsed = time.monotonic() - cycle_start
                sleep_time = max(0, self.interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

    async def run_once(self) -> List[StrategyResult]:
        """
        Single scan pass — useful for demo engine and testing.
        Returns list of all actionable signals found.
        """
        results: List[StrategyResult] = []
        tasks = [
            self._scan_symbol(sym, strat)
            for sym, strat in self.symbol_strategies.items()
        ]
        for coro in asyncio.as_completed(tasks):
            try:
                res = await coro
                if res and res.is_actionable:
                    results.append(res)
            except Exception as e:
                log.debug(f"scan error: {e}")
        return results

    def stop(self) -> None:
        self._running = False

    # ── Private: scan helpers ─────────────────────────────────────────────

    async def _scan_all(self, live: Live) -> None:
        """Launch all symbol scans concurrently and collect results."""
        tasks = [
            self._scan_symbol(sym, strat)
            for sym, strat in self.symbol_strategies.items()
        ]

        signals_this_cycle = 0
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                if result is None:
                    continue

                # Feed to executor
                if result.signal != Signal.NONE:
                    acted = self.executor.process_signal(result)
                    if acted:
                        signals_this_cycle += 1
                        self._log_signal(result)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug(f"scan_all error: {e}")

        # Update display
        live.update(self._build_table())

    async def _scan_symbol(self, symbol: str,
                            strategy: BaseStrategy) -> Optional[StrategyResult]:
        """
        Scan a single symbol:
          1. Fetch klines (with concurrency gate)
          2. Run strategy
          3. Return StrategyResult
        """
        async with self._sem:
            try:
                # Offload blocking REST call to thread pool
                loop = asyncio.get_event_loop()
                df   = await loop.run_in_executor(
                    None,
                    self.connector.get_klines,
                    symbol,
                    self.timeframe,
                    self.candle_limit,
                )

                if df is None or df.empty:
                    return None

                # Fetch funding rate (quick, cache-able in real impl)
                funding = await loop.run_in_executor(
                    None,
                    self.connector.get_funding_rate,
                    symbol,
                )

                # Run strategy (CPU, offload to thread)
                result = await loop.run_in_executor(
                    None,
                    strategy.generate_signal,
                    df,
                    symbol,
                    funding,
                )
                return result

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug(f"_scan_symbol({symbol}): {e}")
                return None

    # ── Display ───────────────────────────────────────────────────────────

    def _log_signal(self, result: StrategyResult) -> None:
        """Store the last N signals for the live display."""
        self._signal_log.insert(0, {
            "time":     time.strftime("%H:%M:%S"),
            "symbol":   result.symbol,
            "signal":   result.signal.value,
            "strategy": result.strategy_name,
            "price":    result.entry_price,
            "conf":     result.confidence,
            "reason":   result.reason[:60],
        })
        self._signal_log = self._signal_log[:20]  # keep last 20

    def _build_table(self) -> Table:
        """Build a Rich table showing open positions + recent signals."""
        table = Table(
            title=f"[bold]Bybit Bot — Cycle #{self._cycle}  "
                  f"[dim]{time.strftime('%Y-%m-%d %H:%M:%S')}[/dim][/bold]",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta",
            min_width=120,
        )

        # Open positions panel
        table.add_column("Symbol",   style="cyan",    width=14)
        table.add_column("Dir",      style="bold",    width=6)
        table.add_column("Strategy", style="yellow",  width=20)
        table.add_column("Entry",    style="white",   width=12)
        table.add_column("Signal",   style="bold",    width=8)
        table.add_column("Conf",     style="green",   width=6)
        table.add_column("Age(m)",   style="dim",     width=8)
        table.add_column("Reason",   style="dim",     width=50)

        # Active positions
        for pos in self.executor.get_open_positions_summary():
            dir_col = "[green]LONG[/green]" if pos["direction"] == "long" \
                      else "[red]SHORT[/red]"
            table.add_row(
                pos["symbol"], dir_col, pos["strategy"],
                f"{pos['entry_price']:.4f}", "OPEN",
                "—", f"{pos['age_min']:.1f}", "",
            )

        # Recent signals
        for sig in self._signal_log[:10]:
            sig_col = ("[green]LONG[/green]"  if sig["signal"] == "LONG"  else
                       "[red]SHORT[/red]"     if sig["signal"] == "SHORT" else
                       "[yellow]CLOSE[/yellow]")
            table.add_row(
                sig["symbol"], sig_col, sig["strategy"],
                f"{sig['price']:.4f}", sig["signal"],
                f"{sig['conf']:.2f}", sig["time"], sig["reason"],
            )

        return table
