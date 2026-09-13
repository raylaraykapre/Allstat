# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md in the project root for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Bybit Derivatives Trading Bot
==============================
Main entry point. Parses CLI arguments and boots the appropriate mode.

Modes:
  live      — Real trading on Bybit (requires API keys)
  demo      — Paper trading on live Bybit data (no API keys needed for public data)
  backtest  — Run backtests on all pairs and print report
  scan      — One-shot scan showing current signals without trading

Usage:
  python main.py                          # live mode (default from config.yaml)
  python main.py --mode demo              # demo mode, all pairs
  python main.py --mode demo --symbol BTCUSDT
  python main.py --mode backtest --symbol ETHUSDT
  python main.py --mode scan
  python main.py --mode live --refresh   # force re-run strategy selection
  python main.py --list-symbols           # list all tradeable pairs

Linux/systemd:
  sudo bash setup.sh           # one-time Debian/Ubuntu server setup
  botctl start                 # start via systemd
  botctl logs                  # tail journalctl
  ./tmux_bot.sh live           # run in tmux (survives SSH disconnect)

Prerequisites:
  pip install -r requirements.txt
  Copy .env.example to .env and fill in API keys (only required for live mode)
"""

import argparse
import asyncio
import sys
import signal as os_signal
import platform

from rich.console import Console
from rich.panel import Panel

from core.logger import setup_logger, get_logger
from core.config_loader import get_config
from core.bybit_connector import BybitConnector
from core.trade_executor import TradeExecutor
from core.strategy_selector import StrategySelector
from core.scanner import Scanner
from demo.demo_engine import DemoEngine

# On Linux force Rich to use a wider terminal if running under systemd/no-TTY
console = Console(force_terminal=True if not sys.stdout.isatty() else False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bybit Derivatives Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode", choices=["live", "demo", "backtest", "scan"],
        default=None,
        help="Operating mode (overrides config.yaml)",
    )
    parser.add_argument(
        "--symbol", type=str, default=None,
        help="Focus on a single symbol (e.g. BTCUSDT)",
    )
    parser.add_argument(
        "--refresh", action="store_true", default=False,
        help="Force re-run strategy backtests (ignore cache)",
    )
    parser.add_argument(
        "--list-symbols", action="store_true",
        help="Print all tradeable derivative symbols and exit",
    )
    parser.add_argument(
        "--report", type=str, default=None,
        metavar="SYMBOL",
        help="Print full backtest report for a symbol and exit",
    )
    return parser.parse_args()


def print_banner(mode: str) -> None:
    console.print(Panel(
        f"[bold cyan]Bybit Derivatives Trading Bot[/bold cyan]\n"
        f"[dim]12 Strategies · Auto-Backtest Selection · Async Multi-Pair Scanner[/dim]\n\n"
        f"Mode: [bold yellow]{mode.upper()}[/bold yellow]",
        border_style="cyan",
        expand=False,
    ))


async def run_live(connector: BybitConnector, cfg: dict,
                   args: argparse.Namespace) -> None:
    """Live trading mode."""
    console.print("[bold red]⚠  LIVE TRADING MODE — Real funds at risk![/bold red]")
    console.print("[dim]Press Ctrl+C or send SIGTERM to stop gracefully[/dim]\n")

    executor = TradeExecutor(connector, demo_mode=False)
    selector = StrategySelector(connector)
    scanner  = Scanner(connector, executor, selector, demo_mode=False)

    if args.symbol:
        scanner.symbol_strategies = {
            args.symbol: selector.select_for_symbol(
                args.symbol, force_refresh=args.refresh)
        }
    else:
        await scanner.initialise()
        if args.refresh:
            scanner.symbol_strategies = {}
            await scanner.initialise()

    loop = asyncio.get_running_loop()

    def _shutdown():
        console.print("\n[yellow]Shutdown signal received — closing positions…[/yellow]")
        scanner.stop()
        executor.close_all_positions(reason="shutdown")

    # Register asyncio-safe signal handlers (works on Linux with systemd SIGTERM)
    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except (NotImplementedError, OSError):
            # Windows fallback (loop.add_signal_handler not supported on Windows)
            os_signal.signal(sig, lambda s, f: _shutdown())

    await scanner.run_forever()


async def run_demo(connector: BybitConnector, cfg: dict,
                   args: argparse.Namespace) -> None:
    """Demo / paper trading mode using live Bybit data."""
    symbols = [args.symbol] if args.symbol else None
    selector = StrategySelector(connector)
    engine   = DemoEngine(connector, selector, symbols=symbols)

    await engine.initialise()

    loop = asyncio.get_running_loop()

    def _shutdown():
        console.print("\n[yellow]Demo stopped.[/yellow]")
        engine.stop()
        _print_demo_summary(engine)

    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except (NotImplementedError, OSError):
            os_signal.signal(sig, lambda s, f: _shutdown())

    await engine.run()


async def run_backtest(connector: BybitConnector, cfg: dict,
                       args: argparse.Namespace) -> None:
    """Run backtests and print a detailed report."""
    selector = StrategySelector(connector)

    if args.symbol:
        symbols = [args.symbol]
    else:
        console.print("[cyan]Fetching all symbols for backtest…[/cyan]")
        symbols = connector.get_all_symbols(
            cfg["scanner"]["min_volume_usdt"])[:50]  # top 50 by volume

    console.print(f"[green]Running backtests on {len(symbols)} symbols…[/green]")
    for sym in symbols:
        selector.print_backtest_report(sym)

    console.print("[bold green]Backtest complete.[/bold green]")


async def run_scan(connector: BybitConnector, cfg: dict,
                   args: argparse.Namespace) -> None:
    """One-shot scan: print current signals without trading."""
    from rich.table import Table
    from rich import box as rbox

    selector = StrategySelector(connector)
    executor = TradeExecutor(connector, demo_mode=True)
    scanner  = Scanner(connector, executor, selector, demo_mode=True)

    if args.symbol:
        strat = selector.select_for_symbol(args.symbol)
        scanner.symbol_strategies = {args.symbol: strat}
    else:
        await scanner.initialise()

    console.print("[cyan]Running single scan pass…[/cyan]")
    results = await scanner.run_once()

    table = Table(title="Current Signals", box=rbox.ROUNDED)
    table.add_column("Symbol",   style="cyan")
    table.add_column("Signal",   style="bold")
    table.add_column("Strategy", style="yellow")
    table.add_column("Price",    style="white")
    table.add_column("Conf",     style="green")
    table.add_column("Reason",   style="dim")

    for r in sorted(results, key=lambda x: x.confidence, reverse=True):
        sig_col = ("[green]LONG[/]"  if r.signal.value == "LONG"
                   else "[red]SHORT[/]")
        table.add_row(
            r.symbol, sig_col, r.strategy_name,
            f"{r.entry_price:.4f}", f"{r.confidence:.2f}",
            r.reason[:70],
        )

    console.print(table)
    console.print(f"\n[green]{len(results)} signals found across "
                  f"{len(scanner.symbol_strategies)} pairs[/green]")


def _print_demo_summary(engine: "DemoEngine") -> None:
    """Print a summary table after demo session ends."""
    from core.currency import fx

    pnl          = engine.pnl
    final_php    = engine.balance_php
    initial_php  = engine.initial_balance_php
    ret          = (final_php - initial_php) / initial_php * 100 if initial_php > 0 else 0

    console.print(Panel(
        f"[bold]Demo Session Summary[/bold]\n\n"
        f"Initial Balance  : [white]{fx.format_php(initial_php)}[/]\n"
        f"Final Balance    : [{'green' if final_php >= initial_php else 'red'}]"
        f"{fx.format_php(final_php)}[/]\n"
        f"Total Return     : [{'green' if ret >= 0 else 'red'}]{ret:+.2f}%[/]\n"
        f"Realised P&L     : [{'green' if pnl.realised_php >= 0 else 'red'}]"
        f"{fx.format_php(pnl.realised_php)}[/]  "
        f"([{'green' if pnl.realised_usdt >= 0 else 'red'}]"
        f"{pnl.realised_usdt:+.2f} USDT[/])\n"
        f"Exchange Rate    : [dim]1 USD = ₱{fx.rate:.2f}[/]\n"
        f"Total Trades     : {pnl.num_trades}\n"
        f"Wins / Losses    : [green]{pnl.num_wins}[/] / [red]{pnl.num_losses}[/]\n"
        f"Win Rate         : [cyan]{pnl.win_rate*100:.1f}%[/]",
        title="📊 Demo Results",
        border_style="cyan",
    ))


def main() -> None:
    args = parse_args()
    cfg  = get_config()

    # Set up logging
    log_cfg = cfg["logging"]
    setup_logger(
        level        = log_cfg["level"],
        log_file     = log_cfg["log_file"] if log_cfg["log_to_file"] else "/dev/null",
        max_size     = f"{log_cfg['max_log_size_mb']} MB",
        backup_count = log_cfg["backup_count"],
    )

    log = get_logger(__name__)

    # Determine mode
    mode = args.mode or cfg["trading"]["mode"]
    print_banner(mode)

    # Build connector
    connector = BybitConnector()

    # Quick commands that don't need the full bot
    if args.list_symbols:
        syms = connector.get_all_symbols(cfg["scanner"]["min_volume_usdt"])
        console.print(f"\n[cyan]{len(syms)} tradeable pairs:[/cyan]")
        for i, s in enumerate(syms, 1):
            console.print(f"  {i:4d}. {s}")
        return

    if args.report:
        selector = StrategySelector(connector)
        selector.print_backtest_report(args.report)
        return

    # Validate API keys for live mode
    if mode == "live":
        if (cfg["bybit"]["api_key"] in ("YOUR_API_KEY", "") or
                cfg["bybit"]["api_secret"] in ("YOUR_API_SECRET", "")):
            console.print(
                "[bold red]ERROR: API keys not configured.[/bold red]\n"
                "Copy .env.example to .env and fill in BYBIT_API_KEY / BYBIT_API_SECRET"
            )
            sys.exit(1)

    # Run async event loop
    mode_runners = {
        "live":      run_live,
        "demo":      run_demo,
        "backtest":  run_backtest,
        "scan":      run_scan,
    }

    runner = mode_runners.get(mode)
    if not runner:
        console.print(f"[red]Unknown mode: {mode}[/red]")
        sys.exit(1)

    try:
        asyncio.run(runner(connector, cfg, args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")


if __name__ == "__main__":
    main()
