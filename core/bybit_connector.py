# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Bybit API Connector — REST + WebSocket
======================================
Uses pybit v5 (official SDK) for REST calls.
Uses raw asyncio WebSocket for ultra-low-latency live kline streaming.

Supports:
  - Fetching all linear (USDT perpetual) derivative pairs
  - Fetching historical OHLCV candles (klines)
  - Placing/closing orders (market, limit)
  - Managing positions (get, set leverage)
  - Real-time kline streaming via WebSocket
  - Funding rate queries
"""

import asyncio
import json
import time
from typing import Optional, Callable, Dict, List, Any

import pandas as pd
import websockets
from pybit.unified_trading import HTTP

from core.logger import get_logger
from core.config_loader import get_config

log = get_logger(__name__)


class BybitConnector:
    """
    Handles all communication with Bybit.
    REST via pybit.HTTP, WebSocket via websockets library for speed.
    """

    # Bybit WS endpoints
    WS_PUBLIC_LIVE    = "wss://stream.bybit.com/v5/public/linear"
    WS_PUBLIC_TESTNET = "wss://stream-testnet.bybit.com/v5/public/linear"
    WS_PRIVATE_LIVE   = "wss://stream.bybit.com/v5/private"
    WS_PRIVATE_TESTNET= "wss://stream-testnet.bybit.com/v5/private"

    def __init__(self):
        cfg = get_config()
        self.api_key    = cfg["bybit"]["api_key"]
        self.api_secret = cfg["bybit"]["api_secret"]
        self.testnet    = cfg["bybit"]["testnet"]
        self.category   = cfg["bybit"]["category"]  # "linear"

        # REST client
        self._session = HTTP(
            testnet=self.testnet,
            api_key=self.api_key,
            api_secret=self.api_secret,
            recv_window=10000,
        )

        # WebSocket state
        self._ws_callbacks: Dict[str, List[Callable]] = {}  # topic -> [callbacks]
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_subscriptions: List[str] = []

        log.info(f"BybitConnector ready. Testnet={self.testnet}, Category={self.category}")

    # ──────────────────────────────────────────────
    # REST: Market Data
    # ──────────────────────────────────────────────

    def get_all_symbols(self, min_volume_usdt: float = 1_000_000) -> List[str]:
        """
        Fetch all linear (USDT perpetual) derivative symbols.
        Filters out low-volume pairs using the 24h turnover field.
        """
        try:
            resp = self._session.get_tickers(category=self.category)
            tickers = resp["result"]["list"]
            cfg = get_config()
            blacklist = set(cfg["scanner"].get("blacklist", []))

            symbols = []
            for t in tickers:
                symbol = t.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                if symbol in blacklist:
                    continue
                # 24h turnover filter
                try:
                    vol = float(t.get("turnover24h", 0))
                except (ValueError, TypeError):
                    vol = 0
                if vol >= min_volume_usdt:
                    symbols.append(symbol)

            log.info(f"Found {len(symbols)} symbols with ≥{min_volume_usdt:,.0f} USDT volume")
            return sorted(symbols)
        except Exception as e:
            log.error(f"get_all_symbols failed: {e}")
            return []

    def get_klines(self, symbol: str, interval: str = "15",
                   limit: int = 300) -> pd.DataFrame:
        """
        Fetch historical klines (OHLCV) for a symbol.
        Returns a DataFrame with columns: time, open, high, low, close, volume.
        Sorted oldest → newest.
        """
        try:
            resp = self._session.get_kline(
                category=self.category,
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
            raw = resp["result"]["list"]
            if not raw:
                return pd.DataFrame()

            df = pd.DataFrame(raw, columns=[
                "time", "open", "high", "low", "close", "volume", "turnover"
            ])
            df = df.astype({
                "time": "int64",
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64",
            })
            # Bybit returns newest first — reverse to oldest first
            df = df.iloc[::-1].reset_index(drop=True)
            df["time"] = pd.to_datetime(df["time"], unit="ms")
            return df
        except Exception as e:
            log.error(f"get_klines({symbol}, {interval}) failed: {e}")
            return pd.DataFrame()

    def get_funding_rate(self, symbol: str) -> float:
        """Return the current funding rate for a symbol (as a decimal, e.g. 0.0001)."""
        try:
            resp = self._session.get_tickers(category=self.category, symbol=symbol)
            data = resp["result"]["list"][0]
            return float(data.get("fundingRate", 0))
        except Exception as e:
            log.warning(f"get_funding_rate({symbol}) failed: {e}")
            return 0.0

    def get_orderbook(self, symbol: str, limit: int = 5) -> dict:
        """Return top-N bids and asks."""
        try:
            resp = self._session.get_orderbook(
                category=self.category, symbol=symbol, limit=limit
            )
            return resp["result"]
        except Exception as e:
            log.warning(f"get_orderbook({symbol}) failed: {e}")
            return {}

    # ──────────────────────────────────────────────
    # REST: Account & Positions
    # ──────────────────────────────────────────────

    def get_wallet_balance(self) -> float:
        """Return available USDT balance."""
        try:
            resp = self._session.get_wallet_balance(accountType="UNIFIED")
            coins = resp["result"]["list"][0]["coin"]
            for coin in coins:
                if coin["coin"] == "USDT":
                    return float(coin.get("availableToWithdraw", 0))
            return 0.0
        except Exception as e:
            log.error(f"get_wallet_balance failed: {e}")
            return 0.0

    def get_positions(self) -> List[dict]:
        """Return all open derivative positions."""
        try:
            resp = self._session.get_positions(
                category=self.category, settleCoin="USDT"
            )
            return [p for p in resp["result"]["list"] if float(p.get("size", 0)) > 0]
        except Exception as e:
            log.error(f"get_positions failed: {e}")
            return []

    def get_position(self, symbol: str) -> Optional[dict]:
        """Return the open position for a specific symbol, or None."""
        try:
            resp = self._session.get_positions(
                category=self.category, symbol=symbol
            )
            positions = resp["result"]["list"]
            for p in positions:
                if float(p.get("size", 0)) > 0:
                    return p
            return None
        except Exception as e:
            log.error(f"get_position({symbol}) failed: {e}")
            return None

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol."""
        try:
            self._session.set_leverage(
                category=self.category,
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
            log.debug(f"Leverage set: {symbol} = {leverage}x")
            return True
        except Exception as e:
            # Often fails if leverage already set — not critical
            log.debug(f"set_leverage({symbol}, {leverage}): {e}")
            return False

    # ──────────────────────────────────────────────
    # REST: Order Management
    # ──────────────────────────────────────────────

    def place_market_order(self, symbol: str, side: str, qty: float,
                           reduce_only: bool = False,
                           tp_price: float = None,
                           sl_price: float = None) -> Optional[dict]:
        """
        Place a market order.
        side: 'Buy' (long) | 'Sell' (short)
        qty: contract quantity (base asset units)
        """
        try:
            params: Dict[str, Any] = {
                "category": self.category,
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": str(qty),
                "timeInForce": "IOC",
                "reduceOnly": reduce_only,
            }
            if tp_price:
                params["takeProfit"] = str(round(tp_price, 4))
            if sl_price:
                params["stopLoss"] = str(round(sl_price, 4))

            resp = self._session.place_order(**params)
            order_id = resp["result"].get("orderId", "unknown")
            log.info(f"ORDER {side} {symbol} qty={qty} reduce={reduce_only} "
                     f"TP={tp_price} SL={sl_price} → orderId={order_id}")
            return resp["result"]
        except Exception as e:
            log.error(f"place_market_order({symbol}, {side}, {qty}) failed: {e}")
            return None

    def close_position(self, symbol: str, side: str, qty: float) -> Optional[dict]:
        """
        Close an existing position.
        side should be opposite of position side:
          Long position → side='Sell', Short position → side='Buy'
        """
        return self.place_market_order(
            symbol=symbol,
            side=side,
            qty=qty,
            reduce_only=True,
        )

    def cancel_all_orders(self, symbol: str) -> bool:
        """Cancel all open orders for a symbol."""
        try:
            self._session.cancel_all_orders(
                category=self.category, symbol=symbol
            )
            log.debug(f"Cancelled all orders for {symbol}")
            return True
        except Exception as e:
            log.warning(f"cancel_all_orders({symbol}) failed: {e}")
            return False

    def set_trading_stop(self, symbol: str, position_idx: int,
                         tp: float = None, sl: float = None,
                         trailing_stop: float = None) -> bool:
        """Update TP/SL/trailing-stop on an open position."""
        try:
            params: Dict[str, Any] = {
                "category": self.category,
                "symbol": symbol,
                "positionIdx": position_idx,
            }
            if tp:
                params["takeProfit"] = str(round(tp, 4))
            if sl:
                params["stopLoss"] = str(round(sl, 4))
            if trailing_stop:
                params["trailingStop"] = str(round(trailing_stop, 4))

            self._session.set_trading_stop(**params)
            return True
        except Exception as e:
            log.warning(f"set_trading_stop({symbol}) failed: {e}")
            return False

    def get_min_order_qty(self, symbol: str) -> float:
        """Return the minimum order quantity for a symbol."""
        try:
            resp = self._session.get_instruments_info(
                category=self.category, symbol=symbol
            )
            lot_size = resp["result"]["list"][0]["lotSizeFilter"]
            return float(lot_size.get("minOrderQty", 0.001))
        except Exception as e:
            log.warning(f"get_min_order_qty({symbol}) failed: {e}")
            return 0.001

    def get_max_leverage(self, symbol: str) -> int:
        """
        Return the maximum leverage Bybit allows for a symbol.
        Used to cap the configured leverage against the symbol's actual limit.
        e.g. BTCUSDT max=100, XYZUSDT max=10
        """
        try:
            resp = self._session.get_instruments_info(
                category=self.category, symbol=symbol
            )
            info = resp["result"]["list"][0]
            # Bybit returns leverageFilter.maxLeverage as a string
            lev_filter = info.get("leverageFilter", {})
            max_lev = float(lev_filter.get("maxLeverage", 100))
            return int(max_lev)
        except Exception as e:
            log.warning(f"get_max_leverage({symbol}) failed: {e}")
            return 100  # safe fallback — leverage will still be capped by config

    def get_effective_leverage(self, symbol: str, configured_leverage: int) -> int:
        """
        Return the leverage the bot should actually use for this symbol.
        Rule: use the LOWER of configured_leverage and the symbol's Bybit max.
        """
        symbol_max = self.get_max_leverage(symbol)
        effective  = min(configured_leverage, symbol_max)
        if effective < configured_leverage:
            log.debug(
                f"[{symbol}] Leverage capped: configured={configured_leverage}x "
                f"symbol_max={symbol_max}x → using {effective}x"
            )
        return effective

    def calculate_qty(self, symbol: str, usdt_amount: float,
                      leverage: int, price: float) -> float:
        """
        Convert USDT amount to contract quantity.
        qty = (usdt * leverage) / price, rounded to minOrderQty step.
        """
        try:
            resp = self._session.get_instruments_info(
                category=self.category, symbol=symbol
            )
            lot_filter = resp["result"]["list"][0]["lotSizeFilter"]
            min_qty  = float(lot_filter.get("minOrderQty", 0.001))
            qty_step = float(lot_filter.get("qtyStep", 0.001))

            raw_qty = (usdt_amount * leverage) / price
            # Round down to nearest qty_step
            steps = int(raw_qty / qty_step)
            qty = round(steps * qty_step, 8)
            qty = max(qty, min_qty)
            return qty
        except Exception as e:
            log.warning(f"calculate_qty({symbol}) failed: {e}")
            return 0.001

    # ──────────────────────────────────────────────
    # WebSocket: Real-time Kline Streaming
    # ──────────────────────────────────────────────

    def subscribe_klines(self, symbols: List[str], interval: str,
                         callback: Callable[[str, dict], None]) -> None:
        """
        Register a callback for live kline updates.
        callback(symbol, candle_dict) is called on each new/updated candle.
        """
        for symbol in symbols:
            topic = f"kline.{interval}.{symbol}"
            if topic not in self._ws_callbacks:
                self._ws_callbacks[topic] = []
                self._ws_subscriptions.append(topic)
            if callback not in self._ws_callbacks[topic]:
                self._ws_callbacks[topic].append(callback)

    async def start_websocket(self) -> None:
        """
        Start the WebSocket listener loop.
        Automatically reconnects on disconnect.
        Designed to run as a background asyncio task.
        """
        url = self.WS_PUBLIC_TESTNET if self.testnet else self.WS_PUBLIC_LIVE
        backoff = 1

        while True:
            try:
                log.info(f"WS connecting to {url} …")
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=30,
                    max_size=10 * 1024 * 1024,
                ) as ws:
                    log.info("WS connected ✓")
                    backoff = 1

                    # Subscribe in batches of 10 (Bybit limit)
                    subs = self._ws_subscriptions[:]
                    for i in range(0, len(subs), 10):
                        batch = subs[i:i+10]
                        sub_msg = {"op": "subscribe", "args": batch}
                        await ws.send(json.dumps(sub_msg))
                        log.debug(f"WS subscribed batch: {batch}")

                    async for raw in ws:
                        await self._handle_ws_message(raw)

            except websockets.exceptions.ConnectionClosed as e:
                log.warning(f"WS disconnected: {e}. Reconnecting in {backoff}s…")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except Exception as e:
                log.error(f"WS error: {e}. Reconnecting in {backoff}s…")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _handle_ws_message(self, raw: str) -> None:
        """Parse and dispatch an incoming WebSocket message."""
        try:
            msg = json.loads(raw)

            # Heartbeat response
            if msg.get("op") == "pong" or msg.get("ret_msg") == "pong":
                return

            topic = msg.get("topic", "")
            if not topic:
                return

            data_list = msg.get("data", [])
            if not isinstance(data_list, list):
                data_list = [data_list]

            callbacks = self._ws_callbacks.get(topic, [])
            for candle in data_list:
                # Extract symbol from topic: "kline.15.BTCUSDT" → "BTCUSDT"
                parts = topic.split(".")
                symbol = parts[2] if len(parts) >= 3 else ""
                for cb in callbacks:
                    cb(symbol, candle)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            log.debug(f"WS message handling error: {e}")

    def start_ws_background(self, loop: asyncio.AbstractEventLoop = None) -> None:
        """Launch the WebSocket as a fire-and-forget background task."""
        if loop is None:
            loop = asyncio.get_event_loop()
        self._ws_task = loop.create_task(self.start_websocket())
        log.info("WebSocket background task started")
