# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Currency Converter — Live USD/PHP Exchange Rate
================================================
Fetches the current USD → PHP rate from a public free API.
Falls back through multiple sources if one is unavailable.
Caches the rate for `CACHE_TTL_SECONDS` to avoid hammering the API
on every trade calculation, while still staying up-to-date.

Sources tried in order:
  1. ExchangeRate-API (free, no key needed): api.exchangerate-api.com
  2. Frankfurter (ECB data, free): api.frankfurter.app
  3. Fixer fallback rate (hardcoded safety net — only used if both APIs fail)

Usage:
    from core.currency import fx
    usdt = fx.php_to_usd(2800)    # ₱2800 → ~$50
    php  = fx.usd_to_php(50)      # $50   → ~₱2800
    rate = fx.rate                # current PHP per 1 USD
"""

from __future__ import annotations

import time
import threading
import urllib.request
import json
from core.logger import get_logger

log = get_logger(__name__)

# How long (seconds) to cache the rate before re-fetching
CACHE_TTL_SECONDS = 300   # 5 minutes

# Hard fallback — only used if ALL live sources fail
FALLBACK_PHP_PER_USD = 57.0


class FXConverter:
    """
    Thread-safe, auto-refreshing USD/PHP converter.
    Singleton — import `fx` from this module.
    """

    def __init__(self):
        self._rate: float        = FALLBACK_PHP_PER_USD
        self._fetched_at: float  = 0.0
        self._lock                = threading.Lock()
        # Fetch immediately on construction
        self._refresh()

    # ── Public interface ──────────────────────────────────────────────────

    @property
    def rate(self) -> float:
        """PHP per 1 USD — auto-refreshes if cache is stale."""
        with self._lock:
            if time.time() - self._fetched_at > CACHE_TTL_SECONDS:
                self._refresh()
            return self._rate

    def php_to_usd(self, php: float) -> float:
        """Convert Philippine Peso to US Dollars."""
        return php / self.rate

    def usd_to_php(self, usd: float) -> float:
        """Convert US Dollars to Philippine Peso."""
        return usd * self.rate

    def format_php(self, amount: float) -> str:
        """Format a PHP amount with ₱ symbol and comma separators."""
        return f"₱{amount:,.2f}"

    def format_usd(self, amount: float) -> str:
        return f"${amount:,.2f}"

    # ── Private: fetch logic ──────────────────────────────────────────────

    def _refresh(self) -> None:
        """Try each API source in order; update self._rate on success."""
        rate = self._try_exchangerate_api()
        if rate is None:
            rate = self._try_frankfurter()
        if rate is None:
            log.warning(
                f"All FX sources failed — using fallback rate "
                f"1 USD = ₱{FALLBACK_PHP_PER_USD:.2f}"
            )
            rate = FALLBACK_PHP_PER_USD

        old = self._rate
        self._rate       = rate
        self._fetched_at = time.time()

        if abs(old - rate) > 0.01:
            log.info(f"Exchange rate updated: 1 USD = ₱{rate:.4f} PHP")

    def _try_exchangerate_api(self) -> float | None:
        """
        ExchangeRate-API — free tier, no API key required.
        https://api.exchangerate-api.com/v4/latest/USD
        """
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "bybit-bot/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                rate = float(data["rates"]["PHP"])
                log.debug(f"FX (exchangerate-api): 1 USD = ₱{rate:.4f}")
                return rate
        except Exception as e:
            log.debug(f"exchangerate-api failed: {e}")
            return None

    def _try_frankfurter(self) -> float | None:
        """
        Frankfurter API — ECB reference rates, free, no key.
        https://api.frankfurter.app/latest?from=USD&to=PHP
        """
        url = "https://api.frankfurter.app/latest?from=USD&to=PHP"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "bybit-bot/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                rate = float(data["rates"]["PHP"])
                log.debug(f"FX (frankfurter): 1 USD = ₱{rate:.4f}")
                return rate
        except Exception as e:
            log.debug(f"frankfurter failed: {e}")
            return None


# ── Module-level singleton ────────────────────────────────────────────────────
# All other modules do: from core.currency import fx
fx = FXConverter()
