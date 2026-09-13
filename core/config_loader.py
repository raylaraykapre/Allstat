# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Loads config.yaml and merges .env overrides.
Single source of truth for all bot configuration.
"""
from __future__ import annotations

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from core.logger import get_logger

log = get_logger(__name__)

# Load .env from bot root
_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH)


def load_config(config_path: str = None) -> dict:
    """
    Load YAML config and override with environment variables.

    Priority: ENV vars > config.yaml defaults
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    # Override API credentials from environment (safer)
    env_key = os.getenv("BYBIT_API_KEY")
    env_secret = os.getenv("BYBIT_API_SECRET")
    env_testnet = os.getenv("BYBIT_TESTNET")

    if env_key:
        cfg["bybit"]["api_key"] = env_key
    if env_secret:
        cfg["bybit"]["api_secret"] = env_secret
    if env_testnet is not None:
        cfg["bybit"]["testnet"] = env_testnet.lower() == "true"

    log.debug(f"Config loaded. Testnet={cfg['bybit']['testnet']}, "
              f"Mode={cfg['trading']['mode']}")
    return cfg


# Singleton config instance
_config: dict | None = None


def get_config() -> dict:
    """Return the singleton config dict, loading it on first call."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
