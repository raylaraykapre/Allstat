# Bybit Derivatives Trading Bot

> **License:** MIT with Additional Restrictions — see [LICENSE](LICENSE)
> **Author:** Ray (Allstat) · Copyright © 2026
> **Strategy Credits:** See [CREDITS.md](CREDITS.md)
>
> ⚠️ **Disclaimer:** This software is provided for educational purposes only.
> The author accepts **no liability** for any financial losses. Trading
> derivatives carries substantial risk. Use entirely at your own risk.
> This software must **not** be used for fraud, market manipulation, or any
> illegal activity — see LICENSE clause 2 for full prohibited uses.

A fully Python-based, async, multi-strategy trading bot for Bybit USDT perpetual derivatives.

---

## Features

| Feature | Details |
|---|---|
| **12 Strategies** | EMA Cross, RSI Reversal, MACD Momentum, Bollinger Bands (Squeeze), Supertrend, Ichimoku, VWAP Deviation, Donchian Breakout (Turtle), ADX/DMI, Squeeze Momentum (LazyBear), Funding Rate Mean-Reversion, Multi-Factor Confluence |
| **Auto Strategy Selection** | Backtests all strategies on each pair, picks the best one (score = win rate + profit factor + Sharpe + drawdown) |
| **Async Multi-Pair Scanner** | Uses `asyncio` + `Semaphore` to scan hundreds of pairs concurrently |
| **Demo Engine** | Paper-trades using live Bybit candles — full P&L tracking, Rich terminal dashboard |
| **Backtest Engine** | Bar-by-bar replay with realistic fees (0.06% taker), slippage (0.02%), TP/SL enforcement |
| **WebSocket Streaming** | Low-latency kline stream with auto-reconnect |
| **Risk Management** | Per-trade sizing, max positions cap, trailing stop, cooldown between trades |

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
copy .env.example .env
# Edit .env with your Bybit API key and secret
```

### 3. Run in demo mode (no API keys needed)

```bash
python main.py --mode demo
```

### 4. Scan for current signals

```bash
python main.py --mode scan
```

### 5. Run backtest report for a specific pair

```bash
python main.py --report BTCUSDT
```

### 6. Go live

```bash
python main.py --mode live
```

---

## CLI Reference

```
python main.py [--mode MODE] [--symbol SYMBOL] [--refresh] [--list-symbols] [--report SYMBOL]

  --mode         live | demo | backtest | scan  (default: from config.yaml)
  --symbol       Focus on one symbol, e.g. BTCUSDT
  --refresh      Force re-run backtests (ignore 6-hour cache)
  --list-symbols List all tradeable USDT perpetual pairs and exit
  --report       Print detailed backtest table for a symbol and exit
```

---

## Strategies

| # | Name | Type | Best On |
|---|------|------|---------|
| 1 | EMA Cross | Trend following | Trending markets, 15m/1h |
| 2 | RSI Reversal | Mean reversion | Ranging markets, 15m/1h |
| 3 | MACD Momentum | Trend momentum | Trending, 1h/4h |
| 4 | Bollinger Bands | Breakout + mean-rev | All timeframes |
| 5 | Supertrend | Trend following | All timeframes |
| 6 | Ichimoku Cloud | Multi-factor trend | Swing, 1h/4h/1d |
| 7 | VWAP Deviation | Mean reversion | Intraday, 15m/1h |
| 8 | Donchian Breakout | Turtle/breakout | Strong trends, 4h/1d |
| 9 | ADX/DMI | Trend strength | Trending, 1h/4h |
| 10 | Squeeze Momentum | Breakout | Low-vol accumulation |
| 11 | Funding Rate | Derivatives-specific | Over-leveraged markets |
| 12 | Multi-Factor | Confluence | All conditions |

---

## Configuration

Edit `config.yaml` to tune:

- `trading.leverage` — default leverage (5x)
- `trading.position_size_usdt` — USDT per trade (50 USDT)
- `trading.max_open_positions` — concurrent positions cap (5)
- `scanner.interval_seconds` — scan frequency (5s)
- `scanner.min_volume_usdt` — volume filter (1M USDT/day)
- `backtest.min_win_rate` — minimum win rate to accept a strategy (0.45)
- `backtest.min_profit_factor` — minimum profit factor (1.3)
- `demo.initial_balance` — virtual balance for demo mode (10,000 USDT)

---

## Architecture

```
bybit_bot/
├── main.py                    # CLI entry point
├── config.yaml                # All configuration
├── .env                       # API keys (not committed)
├── requirements.txt
│
├── core/
│   ├── bybit_connector.py     # REST + WebSocket API layer
│   ├── config_loader.py       # Config singleton
│   ├── logger.py              # Loguru setup
│   ├── backtester.py          # Bar-by-bar backtest engine
│   ├── strategy_selector.py   # Parallel backtest → best strategy per symbol
│   ├── trade_executor.py      # Order placement + position lifecycle
│   └── scanner.py             # Async multi-pair signal scanner
│
├── strategies/
│   ├── base.py                # BaseStrategy, Signal, StrategyResult
│   ├── registry.py            # Strategy lookup table
│   ├── ema_cross.py
│   ├── rsi_reversal.py
│   ├── macd_momentum.py
│   ├── bollinger_bands.py
│   ├── supertrend.py
│   ├── ichimoku.py
│   ├── vwap_deviation.py
│   ├── donchian_breakout.py
│   ├── adx_dmi.py
│   ├── squeeze_momentum.py
│   ├── funding_rate.py
│   └── multi_factor.py
│
├── demo/
│   └── demo_engine.py         # Live-data paper trading + dashboard
│
├── data/
│   └── strategy_cache/        # JSON cache of best strategy per symbol
└── logs/
    └── bot.log
```

---

## Risk Warning

**Trading derivatives involves substantial risk of loss.** This software is provided for educational purposes. Past backtest performance does not guarantee future results. Always test in demo mode first. Never trade with money you cannot afford to lose.
