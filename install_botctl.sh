#!/usr/bin/env bash
# ==============================================================================
#  install_botctl.sh
#  Run this ONCE on your droplet to install the botctl command.
#  If you already ran setup.sh this is NOT needed — botctl is already installed.
#
#  Usage:
#    sudo bash install_botctl.sh
#
#  After running, you can use:
#    botctl start | stop | restart | status | logs | tail
#    botctl demo | scan | report BTCUSDT
#    botctl enable | disable | check
# ==============================================================================

set -euo pipefail

INSTALL_PATH="/usr/local/bin/botctl"
BOT_DIR="/opt/bybit_bot"
SERVICE="bybit-bot"

# Must be root
if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo bash install_botctl.sh"
    exit 1
fi

echo "Installing botctl to $INSTALL_PATH ..."

cat > "$INSTALL_PATH" << 'BOTCTL_SCRIPT'
#!/usr/bin/env bash
# =============================================================
#  botctl — Bybit Trading Bot management command
#  Installed at /usr/local/bin/botctl
#  Usage: botctl <command>
# =============================================================
SERVICE="bybit-bot"
BOT_DIR="/opt/bybit_bot"
VENV="$BOT_DIR/venv/bin/python"

# Colour helpers
GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'
YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}$*${NC}"; }
fail() { echo -e "${RED}$*${NC}"; }
info() { echo -e "${CYAN}$*${NC}"; }

CMD="${1:-help}"

case "$CMD" in

  # ── Service control ────────────────────────────────────────────────────────
  start)
    systemctl start "$SERVICE"
    ok "✓ Bot started"
    ;;

  stop)
    systemctl stop "$SERVICE"
    ok "✓ Bot stopped"
    ;;

  restart)
    systemctl restart "$SERVICE"
    ok "✓ Bot restarted"
    ;;

  status)
    systemctl status "$SERVICE" --no-pager
    ;;

  # ── Logging ────────────────────────────────────────────────────────────────
  logs)
    info "Streaming journal logs (Ctrl+C to stop)..."
    journalctl -u "$SERVICE" -f --no-pager
    ;;

  tail)
    info "Tailing $BOT_DIR/logs/bot.log (Ctrl+C to stop)..."
    tail -f "$BOT_DIR/logs/bot.log"
    ;;

  # ── Bot modes (interactive, not via systemd) ───────────────────────────────
  demo)
    SYMBOL="${2:-}"
    cd "$BOT_DIR"
    if [[ -n "$SYMBOL" ]]; then
      info "Starting demo mode — symbol: $SYMBOL"
      sudo -u botuser "$VENV" main.py --mode demo --symbol "$SYMBOL"
    else
      info "Starting demo mode — all pairs..."
      sudo -u botuser "$VENV" main.py --mode demo
    fi
    ;;

  scan)
    cd "$BOT_DIR"
    info "Running one-shot signal scan..."
    sudo -u botuser "$VENV" main.py --mode scan
    ;;

  report)
    SYMBOL="${2:-BTCUSDT}"
    cd "$BOT_DIR"
    info "Backtest report for $SYMBOL..."
    sudo -u botuser "$VENV" main.py --report "$SYMBOL"
    ;;

  backtest)
    SYMBOL="${2:-}"
    cd "$BOT_DIR"
    if [[ -n "$SYMBOL" ]]; then
      sudo -u botuser "$VENV" main.py --mode backtest --symbol "$SYMBOL"
    else
      sudo -u botuser "$VENV" main.py --mode backtest
    fi
    ;;

  symbols)
    cd "$BOT_DIR"
    sudo -u botuser "$VENV" main.py --list-symbols
    ;;

  refresh)
    info "Restarting with forced strategy refresh..."
    systemctl stop "$SERVICE" 2>/dev/null || true
    cd "$BOT_DIR"
    sudo -u botuser "$VENV" main.py --mode live --refresh &
    ok "Refresh started — check logs with: botctl logs"
    ;;

  # ── Auto-start control ─────────────────────────────────────────────────────
  enable)
    systemctl enable "$SERVICE"
    ok "✓ Auto-start on boot: ENABLED"
    ;;

  disable)
    systemctl disable "$SERVICE"
    fail "✗ Auto-start on boot: DISABLED"
    ;;

  # ── Health check ───────────────────────────────────────────────────────────
  check)
    echo ""
    echo -e "${BOLD}══════════════════════════════════════${NC}"
    echo -e "${BOLD} Bybit Bot Health Check${NC}"
    echo -e "${BOLD}══════════════════════════════════════${NC}"
    echo ""

    # Running?
    if systemctl is-active --quiet "$SERVICE"; then
      ok "  Running         : YES ✓"
    else
      fail "  Running         : NO  ✗  (run: botctl start)"
    fi

    # Auto-start enabled?
    if systemctl is-enabled --quiet "$SERVICE" 2>/dev/null; then
      ok "  Boot auto-start : YES ✓"
    else
      fail "  Boot auto-start : NO  ✗  (run: botctl enable)"
    fi

    # .env exists?
    if [[ -f "$BOT_DIR/.env" ]]; then
      # Check if keys are filled in
      if grep -q "YOUR_API_KEY" "$BOT_DIR/.env" 2>/dev/null; then
        fail "  API keys        : NOT SET ✗  (edit $BOT_DIR/.env)"
      else
        ok "  API keys        : SET ✓"
      fi
    else
      fail "  .env file       : MISSING ✗  (cp $BOT_DIR/.env.example $BOT_DIR/.env)"
    fi

    # venv exists?
    if [[ -f "$BOT_DIR/venv/bin/python" ]]; then
      ok "  Python venv     : OK ✓"
    else
      fail "  Python venv     : MISSING ✗  (run: sudo bash $BOT_DIR/setup.sh)"
    fi

    # Disk space
    DISK=$(df -h "$BOT_DIR" 2>/dev/null | awk 'NR==2{print $4}')
    echo -e "  Disk free       : ${CYAN}${DISK}${NC}"

    # Memory
    MEM=$(free -h 2>/dev/null | awk '/^Mem/{print $7}')
    echo -e "  Memory free     : ${CYAN}${MEM}${NC}"

    echo ""
    echo -e "${BOLD}══ Last 10 log lines ══${NC}"
    journalctl -u "$SERVICE" -n 10 --no-pager 2>/dev/null || \
      tail -n 10 "$BOT_DIR/logs/bot.log" 2>/dev/null || \
      echo "  (no logs yet)"
    echo ""
    ;;

  # ── Reinstall botctl itself ────────────────────────────────────────────────
  self-update)
    if [[ -f "$BOT_DIR/install_botctl.sh" ]]; then
      info "Reinstalling botctl from $BOT_DIR/install_botctl.sh ..."
      sudo bash "$BOT_DIR/install_botctl.sh"
    else
      fail "install_botctl.sh not found in $BOT_DIR"
    fi
    ;;

  # ── Help ──────────────────────────────────────────────────────────────────
  help|--help|-h|"")
    echo ""
    echo -e "${BOLD}botctl — Bybit Trading Bot Control${NC}"
    echo ""
    echo -e "${BOLD}Service:${NC}"
    echo "  botctl start              Start the bot"
    echo "  botctl stop               Stop the bot"
    echo "  botctl restart            Restart the bot"
    echo "  botctl status             Show systemd service status"
    echo "  botctl enable             Enable auto-start on reboot"
    echo "  botctl disable            Disable auto-start on reboot"
    echo ""
    echo -e "${BOLD}Logs:${NC}"
    echo "  botctl logs               Stream live journal logs"
    echo "  botctl tail               Tail logs/bot.log directly"
    echo ""
    echo -e "${BOLD}Interactive modes:${NC}"
    echo "  botctl demo               Run demo mode (all pairs)"
    echo "  botctl demo BTCUSDT       Run demo on one pair"
    echo "  botctl scan               One-shot signal scan"
    echo "  botctl report BTCUSDT     Full backtest report"
    echo "  botctl symbols            List all tradeable pairs"
    echo ""
    echo -e "${BOLD}Diagnostics:${NC}"
    echo "  botctl check              Full health check"
    echo "  botctl self-update        Reinstall botctl from bot directory"
    echo ""
    ;;

  *)
    fail "Unknown command: $1"
    echo "Run 'botctl help' to see all commands."
    exit 1
    ;;

esac
BOTCTL_SCRIPT

# Make it executable
chmod +x "$INSTALL_PATH"

# Verify it's on PATH
if command -v botctl &>/dev/null; then
    echo ""
    echo "botctl installed at $INSTALL_PATH"
    echo ""
    echo "Try it now:"
    echo "  botctl help"
    echo "  botctl check"
    echo ""
else
    echo ""
    echo "Installed to $INSTALL_PATH but it may not be on your PATH."
    echo "Add this to your ~/.bashrc or ~/.profile:"
    echo ""
    echo '  export PATH="$PATH:/usr/local/bin"'
    echo ""
    echo "Then reload: source ~/.bashrc"
    echo ""
    echo "Or run directly: /usr/local/bin/botctl help"
    echo ""
fi
