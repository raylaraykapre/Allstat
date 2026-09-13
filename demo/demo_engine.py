# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Demo Engine
===========
Paper-trading engine using LIVE Bybit market data.
All balances, P&L, and position sizes displayed in Philippine Peso (₱).
Internally all trade math uses USDT; conversion uses live USD/PHP rate.

Usage:
  python main.py --mode demo --symbol BTCUSDT
  python main.py --mode demo  (all pairs)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.columns import Columns

from core.bybit_connector import BybitConnector
from core.config_loader import get_config
from core.currency import fx
from core.logger import get_logger
from core.strategy_selector import StrategySelector
from strategies.base import BaseStrategy, Signal, StrategyResult

log     = get_logger(__name__)
console = Console()

TAKER_FEE = 0.0006
SLIPPAGE  = 0.0002


@dataclass
class DemoPosition:
    symbol:       str
    direction:    str    # "long" | "short"
    entry_price:  float  # USDT
    qty:          float
    leverage:     int
    tp:           float  # USDT
    sl:           float  # USDT
    strategy:     str
    margin_usdt:  float  = 0.0
    margin_php:   float  = 0.0
    tp_roi_pct:   float  = 0.0   # ROI% target for this trade
    sl_roi_pct:   float  = 0.0
    opened_at:    float  = field(default_factory=time.time)

    def roi_pct(self, current_price: float) -> float:
        """ROI % — matches Bybit's position P&L display."""
        if self.entry_price <= 0:
            return 0.0
        if self.direction == "long":
            move = (current_price - self.entry_price) / self.entry_price
        else:
            move = (self.entry_price - current_price) / self.entry_price
        fee = TAKER_FEE * 2
        return (move * self.leverage - fee) * 100

    def pnl_php(self, current_price: float) -> float:
        roi = self.roi_pct(current_price) / 100
        return self.margin_php * roi


@dataclass
class DemoPnL:
    realised_php:  float = 0.0
    realised_usdt: float = 0.0
    num_wins:      int   = 0
    num_losses:    int   = 0
    num_trades:    int   = 0

    @property
    def win_rate(self) -> float:
        return self.num_wins / self.num_trades if self.num_trades else 0


class DemoEngine:
    """Paper-trading demo. All user-facing values in Philippine Peso ₱."""

    def __init__(self, connector: BybitConnector,
                 selector: StrategySelector,
                 symbols: Optional[List[str]] = None):

        self.connector = connector
        self.selector  = selector
        self.cfg       = get_config()
        demo_cfg       = self.cfg["demo"]
        trade_cfg      = self.cfg["trading"]
        scan_cfg       = self.cfg["scanner"]

        # Balance in PHP (config) — convert to USDT for internal math
        self.initial_balance_php  = demo_cfg["initial_balance_php"]
        self.balance_php          = float(self.initial_balance_php)

        self.position_size_php    = trade_cfg["position_size_php"]
        self.configured_leverage  = trade_cfg["leverage"]
        self.tp_roi_pct           = trade_cfg["take_profit_roi_pct"]
        self.sl_roi_pct           = trade_cfg["stop_loss_roi_pct"]
        self.update_interval      = demo_cfg["update_interval"]
        self.timeframe            = scan_cfg["primary_timeframe"]
        self.candle_limit         = scan_cfg["candle_limit"]
        self.min_volume           = scan_cfg["min_volume_usdt"]
        self.max_positions        = trade_cfg["max_open_positions"]

        self.symbols:           List[str]               = symbols or []
        self.symbol_strategies: Dict[str, BaseStrategy] = {}
        self.positions:         Dict[str, DemoPosition] = {}
        self.trade_history:     List[dict]              = []
        self.pnl                                        = DemoPnL()
        self._running                                   = False
        self._sem                                       = asyncio.Semaphore(8)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def initialise(self) -> None:
        if not self.symbols:
            console.print("[cyan]Demo: Fetching live symbols from Bybit…[/cyan]")
            self.symbols = self.connector.get_all_symbols(self.min_volume)

        console.print(f"[green]Demo: {len(self.symbols)} symbols loaded[/green]")
        console.print("[cyan]Demo: Selecting best strategies (backtest)…[/cyan]")

        loop = asyncio.get_event_loop()
        self.symbol_strategies = await loop.run_in_executor(
            None, self.selector.select_for_symbols, self.symbols
        )
        rate = fx.rate
        usdt_equiv = fx.php_to_usd(self.initial_balance_php)
        console.print(
            f"[green]Demo ready | "
            f"Virtual balance: {fx.format_php(self.initial_balance_php)} "
            f"(≈{fx.format_usd(usdt_equiv)}) | "
            f"Rate: 1 USD = ₱{rate:.2f}[/green]"
        )

    async def run(self) -> None:
        self._running = True
        cycle = 0
        with Live(self._render_dashboard(cycle), refresh_per_second=1,
                  console=console, screen=True) as live:
            while self._running:
                t0 = time.monotonic()
                cycle += 1
                await self._scan_all()
                live.update(self._render_dashboard(cycle))
                elapsed = time.monotonic() - t0
                await asyncio.sleep(max(0.5, self.update_interval - elapsed))

    def stop(self) -> None:
        self._running = False

    # ── Scanning ───────────────────────────────────────────────────────────

    async def _scan_all(self) -> None:
        tasks = [self._scan_symbol(s, st)
                 for s, st in self.symbol_strategies.items()]
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._check_position_exits()

    async def _scan_symbol(self, symbol: str, strategy: BaseStrategy) -> None:
        async with self._sem:
            try:
                loop = asyncio.get_event_loop()
                df = await loop.run_in_executor(
                    None, self.connector.get_klines,
                    symbol, self.timeframe, self.candle_limit)
                if df is None or df.empty:
                    return
                funding = await loop.run_in_executor(
                    None, self.connector.get_funding_rate, symbol)
                result = await loop.run_in_executor(
                    None, strategy.generate_signal, df, symbol, funding)
                self._process_signal(result)
            except Exception as e:
                log.debug(f"Demo scan {symbol}: {e}")

    def _process_signal(self, result: StrategyResult) -> None:
        symbol = result.symbol
        signal = result.signal

        if signal == Signal.CLOSE and symbol in self.positions:
            self._close_demo_position(symbol, reason="signal_close")
            return
        if signal not in (Signal.LONG, Signal.SHORT):
            return

        if symbol in self.positions:
            pos = self.positions[symbol]
            if ((signal == Signal.LONG  and pos.direction == "short") or
                (signal == Signal.SHORT and pos.direction == "long")):
                self._close_demo_position(symbol, reason="reversal")
            else:
                return

        if len(self.positions) >= self.max_positions:
            return
        if result.confidence < 0.4:
            return
        if self.balance_php < self.position_size_php:
            return

        price     = result.entry_price
        if price <= 0:
            return

        # Live exchange rate
        usdt_margin = fx.php_to_usd(self.position_size_php)
        direction   = "long" if signal == Signal.LONG else "short"
        lev         = self.configured_leverage

        # ROI-based TP/SL
        tp_move = self.tp_roi_pct / lev / 100
        sl_move = self.sl_roi_pct / lev / 100
        if direction == "long":
            tp = price * (1 + tp_move)
            sl = price * (1 - sl_move)
        else:
            tp = price * (1 - tp_move)
            sl = price * (1 + sl_move)

        qty = (usdt_margin * lev) / price

        self.balance_php -= self.position_size_php  # reserve margin
        self.positions[symbol] = DemoPosition(
            symbol=symbol, direction=direction,
            entry_price=price, qty=qty, leverage=lev,
            tp=tp, sl=sl, strategy=result.strategy_name,
            margin_usdt=usdt_margin, margin_php=self.position_size_php,
            tp_roi_pct=self.tp_roi_pct, sl_roi_pct=self.sl_roi_pct,
        )
        log.info(
            f"[DEMO] OPEN {direction.upper()} {symbol} @ {price:.4f} USDT | "
            f"margin={fx.format_php(self.position_size_php)} | "
            f"lev={lev}x | TP ROI={self.tp_roi_pct}% | SL ROI={self.sl_roi_pct}%"
        )

    async def _check_position_exits(self) -> None:
        for symbol, pos in list(self.positions.items()):
            try:
                loop = asyncio.get_event_loop()
                df = await loop.run_in_executor(
                    None, self.connector.get_klines, symbol, "1", 3)
                if df is None or df.empty:
                    continue
                latest = df.iloc[-1]
                hi, lo = latest["high"], latest["low"]
                if pos.direction == "long":
                    if pos.sl > 0 and lo <= pos.sl:
                        self._close_demo_position(symbol, pos.sl, "SL")
                    elif pos.tp > 0 and hi >= pos.tp:
                        self._close_demo_position(symbol, pos.tp, "TP")
                else:
                    if pos.sl > 0 and hi >= pos.sl:
                        self._close_demo_position(symbol, pos.sl, "SL")
                    elif pos.tp > 0 and lo <= pos.tp:
                        self._close_demo_position(symbol, pos.tp, "TP")
            except Exception as e:
                log.debug(f"check_exits({symbol}): {e}")

    def _close_demo_position(self, symbol: str,
                              exit_price: float = 0,
                              reason: str = "") -> None:
        pos = self.positions.get(symbol)
        if not pos:
            return

        if exit_price <= 0:
            try:
                df = self.connector.get_klines(symbol, "1", 2)
                exit_price = df["close"].iloc[-1] if not df.empty else pos.entry_price
            except Exception:
                exit_price = pos.entry_price

        # P&L in USDT and PHP at current rate
        if pos.direction == "long":
            raw_pct = (exit_price - pos.entry_price) / pos.entry_price
        else:
            raw_pct = (pos.entry_price - exit_price) / pos.entry_price

        fee_pct   = TAKER_FEE * 2
        net_pct   = raw_pct * pos.leverage - fee_pct   # as decimal
        pnl_usdt  = pos.margin_usdt * net_pct
        pnl_php   = fx.usd_to_php(pnl_usdt)

        self.balance_php += pos.margin_php + pnl_php   # return margin + P&L

        roi_pct = net_pct * 100   # as % for display

        self.pnl.realised_php   += pnl_php
        self.pnl.realised_usdt  += pnl_usdt
        self.pnl.num_trades     += 1
        if pnl_php >= 0:
            self.pnl.num_wins   += 1
        else:
            self.pnl.num_losses += 1

        self.trade_history.insert(0, {
            "time":     time.strftime("%H:%M:%S"),
            "symbol":   symbol,
            "dir":      pos.direction,
            "entry":    pos.entry_price,
            "exit":     exit_price,
            "roi_pct":  round(roi_pct, 2),
            "pnl_php":  round(pnl_php, 2),
            "pnl_usdt": round(pnl_usdt, 2),
            "reason":   reason,
            "strategy": pos.strategy,
            "leverage": pos.leverage,
        })
        self.trade_history = self.trade_history[:50]

        log.info(
            f"[DEMO] CLOSE {pos.direction.upper()} {symbol} @ {exit_price:.4f} USDT | "
            f"ROI={roi_pct:+.2f}% | "
            f"P&L={fx.format_php(pnl_php)} ({pnl_usdt:+.2f} USDT) | {reason}"
        )
        del self.positions[symbol]

    # ── Dashboard ──────────────────────────────────────────────────────────

    def _render_dashboard(self, cycle: int) -> Panel:
        rate = fx.rate

        # Portfolio value in PHP
        total_php = self.balance_php
        for sym, pos in self.positions.items():
            try:
                df = self.connector.get_klines(sym, "1", 2)
                if not df.empty:
                    cp       = df["close"].iloc[-1]
                    upnl_php = pos.pnl_php(cp)
                    total_php += pos.margin_php + upnl_php
            except Exception:
                total_php += pos.margin_php

        total_return_pct = (
            (total_php - self.initial_balance_php) / self.initial_balance_php * 100
            if self.initial_balance_php > 0 else 0
        )
        ret_colour = "green" if total_return_pct >= 0 else "red"
        pnl_colour = "green" if self.pnl.realised_php >= 0 else "red"

        # ── Header ─────────────────────────────────────────────────────────
        header_txt = (
            f"[bold cyan]BYBIT DEMO ENGINE[/bold cyan]  "
            f"[dim]Cycle #{cycle} | {time.strftime('%Y-%m-%d %H:%M:%S')} | "
            f"Rate: 1 USD = ₱{rate:.2f}[/dim]\n"
            f"[bold]Balance:[/bold] [green]{fx.format_php(self.balance_php)}[/green]  "
            f"[bold]Portfolio:[/bold] [yellow]{fx.format_php(total_php)}[/yellow]  "
            f"[bold]Return:[/bold] [{ret_colour}]{total_return_pct:+.2f}%[/]  "
            f"[bold]Realised P&L:[/bold] [{pnl_colour}]{fx.format_php(self.pnl.realised_php)}[/]  "
            f"[bold]Win Rate:[/bold] [cyan]{self.pnl.win_rate*100:.1f}%[/cyan]  "
            f"[bold]Trades:[/bold] {self.pnl.num_trades}"
        )

        # ── Open positions table ───────────────────────────────────────────
        pos_table = Table(
            title="[bold]Open Positions[/bold]",
            box=box.SIMPLE_HEAD, header_style="bold blue",
        )
        pos_table.add_column("Symbol",   width=14)
        pos_table.add_column("Dir",      width=7)
        pos_table.add_column("Strategy", width=18)
        pos_table.add_column("Entry",    width=12)
        pos_table.add_column("Curr",     width=12)
        pos_table.add_column("ROI%",     width=9)
        pos_table.add_column("uPnL(₱)",  width=13)
        pos_table.add_column("Margin",   width=13)
        pos_table.add_column("Lev",      width=5)
        pos_table.add_column("TP→",      width=12)
        pos_table.add_column("SL→",      width=12)

        if not self.positions:
            pos_table.add_row("[dim]No open positions[/dim]", *["—"] * 10)
        else:
            for sym, pos in self.positions.items():
                try:
                    df = self.connector.get_klines(sym, "1", 2)
                    cp = df["close"].iloc[-1] if not df.empty else pos.entry_price
                except Exception:
                    cp = pos.entry_price

                roi      = pos.roi_pct(cp)
                upnl_php = pos.pnl_php(cp)
                roi_col  = f"[green]{roi:+.2f}%[/]" if roi >= 0 else f"[red]{roi:+.2f}%[/]"
                pnl_col  = f"[green]{fx.format_php(upnl_php)}[/]" if upnl_php >= 0 \
                           else f"[red]{fx.format_php(upnl_php)}[/]"
                dir_col  = "[green]LONG[/]" if pos.direction == "long" else "[red]SHORT[/]"
                tp_roi   = f"ROI+{pos.tp_roi_pct:.0f}%"
                sl_roi   = f"ROI-{pos.sl_roi_pct:.0f}%"

                pos_table.add_row(
                    sym, dir_col, pos.strategy,
                    f"{pos.entry_price:.4f}", f"{cp:.4f}",
                    roi_col, pnl_col,
                    fx.format_php(pos.margin_php),
                    f"{pos.leverage}x",
                    tp_roi, sl_roi,
                )

        # ── Trade history ──────────────────────────────────────────────────
        hist_table = Table(
            title="[bold]Recent Trades[/bold]",
            box=box.SIMPLE_HEAD, header_style="bold blue",
        )
        hist_table.add_column("Time",     width=10)
        hist_table.add_column("Symbol",   width=14)
        hist_table.add_column("Dir",      width=5)
        hist_table.add_column("Lev",      width=5)
        hist_table.add_column("Strategy", width=18)
        hist_table.add_column("Entry",    width=12)
        hist_table.add_column("Exit",     width=12)
        hist_table.add_column("ROI%",     width=9)
        hist_table.add_column("P&L (₱)",  width=14)
        hist_table.add_column("Why",      width=8)

        if not self.trade_history:
            hist_table.add_row("[dim]No trades yet[/dim]", *["—"] * 9)
        else:
            for t in self.trade_history[:15]:
                roi_col = (f"[green]{t['roi_pct']:+.2f}%[/]" if t["roi_pct"] >= 0
                           else f"[red]{t['roi_pct']:+.2f}%[/]")
                php_col = (f"[green]{fx.format_php(t['pnl_php'])}[/]" if t["pnl_php"] >= 0
                           else f"[red]{fx.format_php(t['pnl_php'])}[/]")
                dir_col = "[green]L[/]" if t["dir"] == "long" else "[red]S[/]"
                hist_table.add_row(
                    t["time"], t["symbol"], dir_col,
                    f"{t.get('leverage', '?')}x",
                    t["strategy"],
                    f"{t['entry']:.4f}", f"{t['exit']:.4f}",
                    roi_col, php_col, t["reason"],
                )

        return Panel(
            Columns([
                Panel(pos_table,  border_style="blue"),
                Panel(hist_table, border_style="yellow"),
            ]),
            title=header_txt,
            border_style="cyan",
        )
