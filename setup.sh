#!/usr/bin/env bash
# ==============================================================================
#  Bybit Trading Bot — Debian/Ubuntu Setup Script
#  Run once on a fresh Debian 11/12 or Ubuntu 22.04/24.04 droplet:
#    chmod +x setup.sh && sudo bash setup.sh
#
#  What this does:
#    1. Updates system packages
#    2. Installs Python 3.11, pip, venv, git, tmux, htop
#    3. Creates a dedicated 'botuser' system account (no login shell)
#    4. Copies the bot to /opt/bybit_bot
#    5. Creates a Python virtual environment at /opt/bybit_bot/venv
#    6. Installs all pip dependencies
#    7. Creates .env from .env.example if not already present
#    8. Installs and enables the systemd service
#    9. Sets up logrotate for logs/bot.log
# ==============================================================================

set -euo pipefail

BOT_DIR="/opt/bybit_bot"
BOT_USER="botuser"
SERVICE_NAME="bybit-bot"
PYTHON="python3.11"

# ── Colour helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

# ── Must be root ────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Run as root: sudo bash setup.sh"

# ── Detect source directory (where this script lives) ───────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. System update ─────────────────────────────────────────────────────────
info "Updating system packages…"
apt-get update -qq
apt-get upgrade -y -qq
success "System updated"

# ── 2. Install system dependencies ───────────────────────────────────────────
info "Installing Python 3.11 and tools…"
apt-get install -y -qq \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    git curl wget tmux htop screen \
    build-essential libssl-dev libffi-dev \
    ca-certificates gnupg2 \
    logrotate
success "System dependencies installed"

# ── 3. Create bot user ────────────────────────────────────────────────────────
if ! id "$BOT_USER" &>/dev/null; then
    info "Creating system user '$BOT_USER'…"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$BOT_USER"
    success "User '$BOT_USER' created"
else
    warn "User '$BOT_USER' already exists — skipping"
fi

# ── 4. Deploy bot files ───────────────────────────────────────────────────────
info "Deploying bot to $BOT_DIR…"
mkdir -p "$BOT_DIR"
mkdir -p "$BOT_DIR/logs" "$BOT_DIR/data/strategy_cache"

# Copy all bot files (excluding venv, __pycache__, .git)
rsync -a --exclude='venv' --exclude='__pycache__' \
         --exclude='*.pyc' --exclude='.git' \
         --exclude='.env' \
         "$SCRIPT_DIR/" "$BOT_DIR/"

# Create .env if it doesn't exist
if [[ ! -f "$BOT_DIR/.env" ]]; then
    cp "$BOT_DIR/.env.example" "$BOT_DIR/.env"
    warn ".env created from template — EDIT $BOT_DIR/.env with your API keys!"
else
    info ".env already exists — not overwriting"
fi

# Set ownership
chown -R "$BOT_USER:$BOT_USER" "$BOT_DIR"
chmod 750 "$BOT_DIR"
chmod 640 "$BOT_DIR/.env"    # restrict key file

success "Bot files deployed to $BOT_DIR"

# ── 5. Create virtual environment ─────────────────────────────────────────────
info "Creating Python virtual environment…"
sudo -u "$BOT_USER" $PYTHON -m venv "$BOT_DIR/venv"
success "venv created at $BOT_DIR/venv"

# ── 6. Install Python dependencies ───────────────────────────────────────────
info "Installing Python packages (this may take 2-3 minutes)…"
sudo -u "$BOT_USER" "$BOT_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$BOT_USER" "$BOT_DIR/venv/bin/pip" install \
    --no-cache-dir \
    -r "$BOT_DIR/requirements.txt"
success "Python packages installed"

# ── 7. Install systemd service ────────────────────────────────────────────────
info "Installing systemd service '$SERVICE_NAME'…"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=Bybit Derivatives Trading Bot
Documentation=file://${BOT_DIR}/README.md
# Start only after network is fully up (important for API connectivity)
After=network-online.target
Wants=network-online.target
# If the network drops and comes back, restart the bot
After=network.target

[Service]
Type=simple
User=${BOT_USER}
Group=${BOT_USER}
WorkingDirectory=${BOT_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=${BOT_DIR}
EnvironmentFile=${BOT_DIR}/.env

ExecStart=${BOT_DIR}/venv/bin/python main.py --mode live

# ── Crash recovery ────────────────────────────────────────────────────────────
# Restart=always  → restart on ANY exit: crash, OOM, exception, signal
Restart=always
# Wait 15s before restarting (avoids hammering Bybit API on repeated crashes)
RestartSec=15
# No burst limit — allow unlimited restarts so the bot always comes back.
# This is intentional: we WANT indefinite restart on a VPS.
StartLimitIntervalSec=0

StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

# ── Security hardening ────────────────────────────────────────────────────────
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
ReadWritePaths=${BOT_DIR}/logs ${BOT_DIR}/data

[Install]
# WantedBy=multi-user.target ensures this unit is started on every normal boot
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# ── CRITICAL: enable so the service starts automatically on every boot ────────
systemctl enable "${SERVICE_NAME}"
success "systemd service installed AND enabled (will auto-start on reboot)"

# ── 8. Set up logrotate ───────────────────────────────────────────────────────
info "Configuring logrotate…"
cat > "/etc/logrotate.d/${SERVICE_NAME}" << EOF
${BOT_DIR}/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su ${BOT_USER} ${BOT_USER}
}
EOF
success "logrotate configured (daily, 14-day retention)"

# ── 9. Create convenience management script ───────────────────────────────────
cat > "/usr/local/bin/botctl" << 'BOTCTL'
#!/usr/bin/env bash
# botctl — convenience wrapper for the Bybit bot service
SERVICE="bybit-bot"
BOT_DIR="/opt/bybit_bot"
case "$1" in
  start)    systemctl start   "$SERVICE" && echo "Bot started" ;;
  stop)     systemctl stop    "$SERVICE" && echo "Bot stopped" ;;
  restart)  systemctl restart "$SERVICE" && echo "Bot restarted" ;;
  status)   systemctl status  "$SERVICE" ;;
  logs)     journalctl -u "$SERVICE" -f --no-pager ;;
  tail)     tail -f "$BOT_DIR/logs/bot.log" ;;
  demo)     cd "$BOT_DIR" && sudo -u botuser venv/bin/python main.py --mode demo ;;
  scan)     cd "$BOT_DIR" && sudo -u botuser venv/bin/python main.py --mode scan ;;
  report)   cd "$BOT_DIR" && sudo -u botuser venv/bin/python main.py --report "${2:-BTCUSDT}" ;;
  enable)
    systemctl enable "$SERVICE"
    echo "Auto-start on boot: ENABLED"
    ;;
  disable)
    systemctl disable "$SERVICE"
    echo "Auto-start on boot: DISABLED"
    ;;
  check)
    echo ""
    echo "=== Service status ==="
    systemctl is-active "$SERVICE" && echo "Running: YES" || echo "Running: NO"
    systemctl is-enabled "$SERVICE" && echo "Auto-start on boot: YES (enabled)" || echo "Auto-start on boot: NO  (disabled - run: botctl enable)"
    echo ""
    echo "=== Last 20 log lines ==="
    journalctl -u "$SERVICE" -n 20 --no-pager
    ;;
  *)
    echo "Usage: botctl {start|stop|restart|status|logs|tail|demo|scan|report [SYMBOL]|enable|disable|check}"
    ;;
esac
BOTCTL
chmod +x "/usr/local/bin/botctl"

# Verify botctl is reachable on PATH
if ! command -v botctl &>/dev/null; then
    warn "botctl installed but /usr/local/bin may not be on PATH."
    warn "If 'botctl' is not found after setup, run:"
    warn "  echo 'export PATH=\"\$PATH:/usr/local/bin\"' >> ~/.bashrc && source ~/.bashrc"
fi
success "botctl command installed — use 'botctl help' to see all commands"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Setup complete!${NC}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}What's already done for you:${NC}"
echo -e "  ${GREEN}✓${NC} Bot deployed to $BOT_DIR"
echo -e "  ${GREEN}✓${NC} Python venv + all packages installed"
echo -e "  ${GREEN}✓${NC} systemd service installed"
echo -e "  ${GREEN}✓${NC} Auto-start on boot ENABLED  ← bot survives droplet reboots"
echo -e "  ${GREEN}✓${NC} Crash auto-restart ENABLED  ← bot restarts indefinitely on failure"
echo -e "  ${GREEN}✓${NC} Log rotation configured (14 days)"
echo ""
echo -e "  ${BOLD}Required next steps:${NC}"
echo -e "  1. Add your Bybit API keys:"
echo -e "     ${CYAN}nano $BOT_DIR/.env${NC}"
echo ""
echo -e "  2. Test demo mode (no real trades):"
echo -e "     ${CYAN}botctl demo${NC}"
echo ""
echo -e "  3. Start live trading:"
echo -e "     ${CYAN}botctl start${NC}"
echo ""
echo -e "  4. Watch the logs:"
echo -e "     ${CYAN}botctl logs${NC}"
echo ""
echo -e "  5. Verify auto-start and health at any time:"
echo -e "     ${CYAN}botctl check${NC}"
echo ""
echo -e "  ${YELLOW}The bot will now start automatically on every reboot.${NC}"
echo -e "  ${YELLOW}If it crashes, systemd restarts it after 15 seconds — indefinitely.${NC}"
echo ""
