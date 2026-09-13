# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Strategy Registry
=================
Single source of truth for all available strategies.
The strategy selector and scanner import from here.
"""
from __future__ import annotations

from typing import Dict, Type, List
from core.config_loader import get_config
from strategies.base import BaseStrategy

# Import all strategies
from strategies.ema_cross        import EMACrossStrategy
from strategies.rsi_reversal     import RSIReversalStrategy
from strategies.macd_momentum    import MACDMomentumStrategy
from strategies.bollinger_bands  import BollingerBandsStrategy
from strategies.supertrend       import SupertrendStrategy
from strategies.ichimoku         import IchimokuStrategy
from strategies.vwap_deviation   import VWAPDeviationStrategy
from strategies.donchian_breakout import DonchianBreakoutStrategy
from strategies.adx_dmi          import ADXDMIStrategy
from strategies.squeeze_momentum import SqueezeMomentumStrategy
from strategies.funding_rate     import FundingRateStrategy
from strategies.multi_factor     import MultiFactorStrategy


# Registry: config key → strategy class
ALL_STRATEGIES: Dict[str, Type[BaseStrategy]] = {
    "ema_cross":        EMACrossStrategy,
    "rsi_reversal":     RSIReversalStrategy,
    "macd_momentum":    MACDMomentumStrategy,
    "bollinger_bands":  BollingerBandsStrategy,
    "supertrend":       SupertrendStrategy,
    "ichimoku":         IchimokuStrategy,
    "vwap_deviation":   VWAPDeviationStrategy,
    "donchian_breakout":DonchianBreakoutStrategy,
    "adx_dmi":          ADXDMIStrategy,
    "squeeze_momentum": SqueezeMomentumStrategy,
    "funding_rate":     FundingRateStrategy,
    "multi_factor":     MultiFactorStrategy,
}


def get_enabled_strategies() -> List[BaseStrategy]:
    """
    Return instantiated strategy objects that are enabled in config.yaml.
    """
    cfg      = get_config()
    strat_cfg = cfg.get("strategies", {})
    enabled  = []

    for key, cls in ALL_STRATEGIES.items():
        if strat_cfg.get(key, True):  # default enabled if not listed
            enabled.append(cls())

    return enabled


def get_strategy_by_name(name: str) -> BaseStrategy | None:
    """Return an instantiated strategy by its NAME attribute."""
    for cls in ALL_STRATEGIES.values():
        if cls.NAME == name or cls.__name__ == name:
            return cls()
    return None
