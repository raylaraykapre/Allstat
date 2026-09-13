# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Trade Execution Engine
======================
Manages the full lifecycle of a trade.

Key behaviours:
  • Position size is configured in Philippine Peso (₱).
    The bot converts to USDT at the live exchange rate before sizing.

  • Leverage is capped per-symbol:
    effective_leverage = min(config.leverage, symbol_bybit_max)
    e.g. config=30x, BTCUSDT max=100x → uses 30x
         config=30x, XYZUSDT max=10x  → uses 10x

  • TP / SL are expressed as ROI % (return on your margin, like Bybit shows).
    price_move% = ROI% / leverage
    e.g. TP ROI=60%, leverage=30x → price only needs to move +2% to hit TP

  • All logging and display values shown in ₱ (PHP).
    Internally all Bybit API calls still use USDT.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.bybit_connector import BybitConnector
from core.config_loader import get_config
from core.currency import fx
from core.logger import get_logger
from strategies.base import Signal, StrategyResult

log = get_logger(__name__)


@dataclass
class OpenPosition:
    """In-memory record of an active bot-managed position."""
    symbol:          str
    side:            str        # "Buy" (long) | "Sell" (short)
    direction:       str        # "long" | "short"
    entry_price:     float      # USDT
    qty:             float
    leverage:        int        # effective leverage used
    take_profit:     float      # USDT price
    stop_loss:       float      # USDT price
    strategy:        str
    margin_usdt:     float = 0.0   # USDT margin reserved
    margin_php:      float = 0.0   # PHP equivalent at time of entry
    opened_at:       float = field(default_factory=time.time)
    trailing_active: bool  = False

    @property
    def age_seconds(self) -> float:
        return time.time() - self.opened_at

    def is_long(self) -> bool:
        return self.direction == "long"

    def unrealised_pnl_pct_roi(self, current_price: float) -> float:
        """ROI % — matches how Bybit shows P&L on the position page."""
        if self.entry_price <= 0:
            return 0.0
        if self.direction == "long":
            price_move_pct = (current_price - self.entry_price) / self.entry_price * 100
        else:
            price_move_pct = (self.entry_price - current_price) / self.entry_price * 100
        return price_move_pct * self.leverage   # ROI = price_move * leverage


class TradeExecutor:
    """
    High-level trade orchestrator.
    All monetary values consumed from config in PHP; converted to USDT internally.
    """

    LONG_SIDE        = "Buy"
    SHORT_SIDE       = "Sell"
    CLOSE_LONG_SIDE  = "Sell"
    CLOSE_SHORT_SIDE = "Buy"

    def __init__(self, connector: BybitConnector, demo_mode: bool = False):
        self.connector  = connector
        self.demo_mode  = demo_mode
        self.cfg        = get_config()
        self.trade_cfg  = self.cfg["trading"]

        self.max_positions      = self.trade_cfg["max_open_positions"]
        self.position_size_php  = self.trade_cfg["position_size_php"]
        self.configured_leverage= self.trade_cfg["leverage"]
        self.tp_roi_pct         = self.trade_cfg["take_profit_roi_pct"]
        self.sl_roi_pct         = self.trade_cfg["stop_loss_roi_pct"]
        self.trailing_on        = self.trade_cfg["trailing_stop"]
        self.trailing_act       = self.trade_cfg["trailing_stop_activation_pct"]
        self.trailing_cb        = self.trade_cfg["trailing_stop_callback_pct"]

        # In-memory position tracking {symbol: OpenPosition}
        self.positions:  Dict[str, OpenPosition] = {}
        self._cooldown:  Dict[str, float]        = {}
        self._cooldown_secs = 60

        log.info(
            f"TradeExecutor ready | demo={demo_mode} | "
            f"position_size={fx.format_php(self.position_size_php)} | "
            f"≈{fx.format_usd(fx.php_to_usd(self.position_size_php))} USDT | "
            f"configured_leverage={self.configured_leverage}x | "
            f"TP ROI={self.tp_roi_pct}% | SL ROI={self.sl_roi_pct}%"
        )

    # ── Public API ────────────────────────────────────────────────────────

    def process_signal(self, result: StrategyResult) -> bool:
        """
        Main entry point called by the scanner.
        Decides whether to open, close, or ignore a position.
        Returns True if an action was taken.
        """
        symbol = result.symbol
        signal = result.signal

        if signal == Signal.CLOSE:
            if symbol in self.positions:
                log.info(f"[{symbol}] CLOSE signal: {result.reason}")
                return self._close_position(symbol, reason="signal_close")
            return False

        if signal == Signal.NONE:
            return False

        if symbol in self.positions:
            pos = self.positions[symbol]
            if ((signal == Signal.LONG  and pos.direction == "short") or
                (signal == Signal.SHORT and pos.direction == "long")):
                log.info(f"[{symbol}] Reversal — closing {pos.direction} → {signal.value}")
                self._close_position(symbol, reason="reversal")
                time.sleep(0.3)
                return self._open_position(result)
            else:
                log.debug(f"[{symbol}] Already {pos.direction} — skip")
                return False

        if self._in_cooldown(symbol):
            log.debug(f"[{symbol}] Cooldown — skip")
            return False

        if len(self.positions) >= self.max_positions:
            log.debug(f"[{symbol}] Max positions ({self.max_positions}) — skip")
            return False

        if result.confidence < 0.4:
            log.debug(f"[{symbol}] Low confidence {result.confidence:.2f} — skip")
            return False

        return self._open_position(result)

    def monitor_positions(self) -> None:
        """Reconcile local position tracker against Bybit; activate trailing stops."""
        if not self.positions:
            return

        live         = self.connector.get_positions()
        live_symbols = {p["symbol"] for p in live}

        for sym in list(self.positions.keys()):
            if sym not in live_symbols:
                log.info(f"[{sym}] Position closed externally (TP/SL/manual)")
                self._set_cooldown(sym)
                del self.positions[sym]

        if self.trailing_on:
            for sym, pos in list(self.positions.items()):
                if not pos.trailing_active:
                    self._check_activate_trailing(sym, pos, live)

    def close_all_positions(self, reason: str = "shutdown") -> None:
        for sym in list(self.positions.keys()):
            self._close_position(sym, reason=reason)

    def get_open_positions_summary(self) -> List[dict]:
        """Return position summary with PHP values for display."""
        summary = []
        for p in self.positions.values():
            margin_php = p.margin_php or fx.usd_to_php(p.margin_usdt)
            summary.append({
                "symbol":      p.symbol,
                "direction":   p.direction,
                "entry_price": p.entry_price,
                "qty":         p.qty,
                "leverage":    p.leverage,
                "strategy":    p.strategy,
                "age_min":     round(p.age_seconds / 60, 1),
                "tp":          p.take_profit,
                "sl":          p.stop_loss,
                "margin_php":  margin_php,
                "margin_usdt": p.margin_usdt,
            })
        return summary

    # ── Private: Open ─────────────────────────────────────────────────────

    def _open_position(self, result: StrategyResult) -> bool:
        symbol = result.symbol
        signal = result.signal
        price  = result.entry_price

        side      = self.LONG_SIDE if signal == Signal.LONG else self.SHORT_SIDE
        direction = "long"          if signal == Signal.LONG else "short"

        # ── 1. Get live exchange rate and convert PHP → USDT ──────────────
        usdt_per_trade = fx.php_to_usd(self.position_size_php)
        php_display    = fx.format_php(self.position_size_php)
        usd_display    = fx.format_usd(usdt_per_trade)

        # ── 2. Effective leverage: cap at symbol's Bybit max ──────────────
        if self.demo_mode:
            effective_lev = self.configured_leverage
        else:
            effective_lev = self.connector.get_effective_leverage(
                symbol, self.configured_leverage)

        # ── 3. ROI-based TP/SL → convert to price distance ───────────────
        # ROI% = price_move% × leverage
        # price_move% = ROI% / leverage
        tp_price_move = self.tp_roi_pct / effective_lev / 100  # as decimal
        sl_price_move = self.sl_roi_pct / effective_lev / 100

        if direction == "long":
            tp = price * (1 + tp_price_move)
            sl = price * (1 - sl_price_move)
        else:
            tp = price * (1 - tp_price_move)
            sl = price * (1 + sl_price_move)

        # ── 4. Calculate order quantity ───────────────────────────────────
        if self.demo_mode:
            qty = round((usdt_per_trade * effective_lev) / price, 6) if price > 0 else 0.001
        else:
            self.connector.set_leverage(symbol, effective_lev)
            qty = self.connector.calculate_qty(
                symbol, usdt_per_trade, effective_lev, price)

        if qty <= 0:
            log.warning(f"[{symbol}] qty={qty} — skip")
            return False

        log.info(
            f"[{symbol}] ▶ OPEN {direction.upper()} | "
            f"strategy={result.strategy_name} | "
            f"price={price:.4f} USDT | qty={qty} | lev={effective_lev}x | "
            f"margin={php_display} ({usd_display}) | "
            f"TP={tp:.4f} (ROI +{self.tp_roi_pct}%) | "
            f"SL={sl:.4f} (ROI -{self.sl_roi_pct}%) | "
            f"conf={result.confidence:.2f}"
        )

        if not self.demo_mode:
            order = self.connector.place_market_order(
                symbol=symbol, side=side, qty=qty,
                tp_price=tp, sl_price=sl,
            )
            if order is None:
                log.error(f"[{symbol}] Order placement FAILED")
                return False

        self.positions[symbol] = OpenPosition(
            symbol       = symbol,
            side         = side,
            direction    = direction,
            entry_price  = price,
            qty          = qty,
            leverage     = effective_lev,
            take_profit  = tp,
            stop_loss    = sl,
            strategy     = result.strategy_name,
            margin_usdt  = usdt_per_trade,
            margin_php   = self.position_size_php,
        )
        return True

    # ── Private: Close ────────────────────────────────────────────────────

    def _close_position(self, symbol: str, reason: str = "") -> bool:
        pos = self.positions.get(symbol)
        if not pos:
            return False

        close_side = self.CLOSE_LONG_SIDE if pos.is_long() else self.CLOSE_SHORT_SIDE

        log.info(
            f"[{symbol}] ◀ CLOSE {pos.direction.upper()} | "
            f"qty={pos.qty} | lev={pos.leverage}x | "
            f"margin={fx.format_php(pos.margin_php)} | "
            f"reason={reason} | age={pos.age_seconds/60:.1f}m"
        )

        if not self.demo_mode:
            result = self.connector.close_position(
                symbol=symbol, side=close_side, qty=pos.qty)
            if result is None:
                log.error(f"[{symbol}] Close order FAILED")
                return False

        self._set_cooldown(symbol)
        del self.positions[symbol]
        return True

    # ── Private: Trailing Stop ─────────────────────────────────────────────

    def _check_activate_trailing(self, symbol: str, pos: OpenPosition,
                                  live_positions: list) -> None:
        live_pos = next((p for p in live_positions if p["symbol"] == symbol), None)
        if not live_pos:
            return
        try:
            current_price = float(live_pos.get("markPrice", pos.entry_price))
        except (ValueError, TypeError):
            return

        if pos.is_long():
            gain_pct = (current_price - pos.entry_price) / pos.entry_price * 100
        else:
            gain_pct = (pos.entry_price - current_price) / pos.entry_price * 100

        if gain_pct >= self.trailing_act:
            trail_val = current_price * self.trailing_cb / 100
            pos_idx   = int(live_pos.get("positionIdx", 0))
            if not self.demo_mode:
                self.connector.set_trading_stop(
                    symbol=symbol, position_idx=pos_idx, trailing_stop=trail_val)
            pos.trailing_active = True
            log.info(
                f"[{symbol}] Trailing stop activated | "
                f"+{gain_pct:.2f}% gain | callback={self.trailing_cb}%"
            )

    # ── Private: Helpers ───────────────────────────────────────────────────

    def _in_cooldown(self, symbol: str) -> bool:
        return (time.time() - self._cooldown.get(symbol, 0)) < self._cooldown_secs

    def _set_cooldown(self, symbol: str) -> None:
        self._cooldown[symbol] = time.time()
