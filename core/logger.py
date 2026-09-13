# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ray (Allstat). All rights reserved.
# See LICENSE and CREDITS.md for full terms and attributions.
# USE AT YOUR OWN RISK — the author accepts no liability for trading losses.
"""
Centralized logging setup using loguru.
All modules import get_logger() from here.

Linux/systemd note:
  When running under systemd (no TTY), stdout is captured by journald.
  Colorize is auto-disabled when stdout is not a terminal.
  Journal output is also written to logs/bot.log for persistent access.
"""

import sys
import platform
from loguru import logger
from pathlib import Path


def setup_logger(level: str = "INFO", log_file: str = "logs/bot.log",
                 max_size: str = "10 MB", backup_count: int = 5) -> None:
    """Configure loguru with console + rotating file output."""
    logger.remove()  # Remove default handler

    # Auto-detect if we have a real terminal (False under systemd/cron)
    is_tty = sys.stdout.isatty()

    # Console / journal handler
    logger.add(
        sys.stdout,
        level=level,
        colorize=is_tty,      # no ANSI codes when piped to journald
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
        ),
    )

    # File handler — always write to disk regardless of TTY
    # Use nul on Windows, /dev/null sentinel handled here
    skip_file = log_file in ("/dev/null", "nul", "NUL", "")
    if not skip_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            level=level,
            rotation=max_size,
            retention=backup_count,
            compression="zip",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} — {message}",
            enqueue=True,   # thread-safe; safe for asyncio + multi-thread
        )


def get_logger(name: str):
    """Return a bound logger with the given module name."""
    return logger.bind(name=name)
