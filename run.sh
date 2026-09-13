#!/usr/bin/env bash
# ==============================================================================
#  run.sh — Run the bot directly without systemd
#  Useful for testing, tmux sessions, or screen sessions.
#
#  Usage:
#    ./run.sh               # live mode
#    ./run.sh demo          # demo mode
#    ./run.sh demo BTCUSDT  # demo mode, single pair
#    ./run.sh scan          # one-shot scan
#    ./run.sh report BTCUSDT
#    ./run.sh backtest
# ==============================================================================

set -euo pipefail

# Resolve bot directory regardless of where script is called from
BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$BOT_DIR/venv"
PYTHON="$VENV/bin/python"

# ── Check venv exists ────────────────────────────────────────────────────────
if [[ ! -f "$PYTHON" ]]; then
    echo "ERROR: Virtual environment not found at $VENV"
    echo "Run setup first:"
    echo "  sudo bash $BOT_DIR/setup.sh"
    echo "Or create manually:"
    echo "  python3.11 -m venv $VENV"
    echo "  $VENV/bin/pip install -r $BOT_DIR/requirements.txt"
    exit 1
fi

# ── Load .env if present (for local/tmux runs) ────────────────────────────────
if [[ -f "$BOT_DIR/.env" ]]; then
    set -a
    source "$BOT_DIR/.env"
    set +a
fi

# ── Set Python path so imports resolve ────────────────────────────────────────
export PYTHONPATH="$BOT_DIR"
export PYTHONUNBUFFERED=1

# ── Parse first arg as mode ───────────────────────────────────────────────────
MODE="${1:-live}"
SYMBOL="${2:-}"

cd "$BOT_DIR"

case "$MODE" in
    live)
        echo "Starting LIVE trading mode…"
        exec "$PYTHON" main.py --mode live
        ;;
    demo)
        if [[ -n "$SYMBOL" ]]; then
            echo "Starting DEMO mode — symbol: $SYMBOL"
            exec "$PYTHON" main.py --mode demo --symbol "$SYMBOL"
        else
            echo "Starting DEMO mode — all pairs"
            exec "$PYTHON" main.py --mode demo
        fi
        ;;
    scan)
        echo "Running one-shot scan…"
        exec "$PYTHON" main.py --mode scan
        ;;
    backtest)
        if [[ -n "$SYMBOL" ]]; then
            exec "$PYTHON" main.py --mode backtest --symbol "$SYMBOL"
        else
            exec "$PYTHON" main.py --mode backtest
        fi
        ;;
    report)
        SYM="${2:-BTCUSDT}"
        exec "$PYTHON" main.py --report "$SYM"
        ;;
    refresh)
        echo "Forcing strategy refresh…"
        exec "$PYTHON" main.py --mode live --refresh
        ;;
    symbols)
        exec "$PYTHON" main.py --list-symbols
        ;;
    *)
        echo "Usage: $0 {live|demo [SYMBOL]|scan|backtest [SYMBOL]|report SYMBOL|refresh|symbols}"
        exit 1
        ;;
esac
