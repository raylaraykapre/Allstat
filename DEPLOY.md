# Deployment Guide — Debian / DigitalOcean

## Will the bot run indefinitely? Will it survive reboots?

**Yes to both.** Here's exactly what happens:

| Scenario | What systemd does |
|---|---|
| Droplet reboots (OS update, DigitalOcean maintenance, power cycle) | Bot auto-starts within ~20 seconds of boot, every time |
| Bot crashes (Python exception, OOM kill, network error) | systemd restarts it after 15 seconds — **indefinitely, no limit** |
| SSH session disconnects | Nothing — the bot is a system service, not tied to your terminal |
| Bot exits cleanly (e.g. you `botctl stop`) | systemd does **not** restart (by design — you stopped it on purpose) |

This is handled by three lines in the systemd unit:
```ini
Restart=always              # restart on any non-clean exit
RestartSec=15               # wait 15s before restarting
StartLimitIntervalSec=0     # no burst limit — restart forever
```

`setup.sh` also runs `systemctl enable bybit-bot` automatically, which creates the boot symlink.

To verify at any time:
```bash
botctl check
# Should print:
# Running: YES
# Auto-start on boot: YES (enabled)
```

---
Complete guide for running the bot on a Linux VPS (Debian 11/12, Ubuntu 22.04/24.04).

---

## 1. Create a DigitalOcean Droplet

**Recommended specs:**

| Resource | Minimum | Recommended |
|---|---|---|
| OS | Debian 12 | Debian 12 / Ubuntu 22.04 |
| RAM | 1 GB | 2 GB |
| CPU | 1 vCPU | 2 vCPU |
| Disk | 25 GB SSD | 25 GB SSD |
| Region | Closest to you | Singapore / Frankfurt (low latency to Bybit) |

> A $6/month DigitalOcean Basic Droplet (1 vCPU, 1 GB RAM) is sufficient for up to ~200 pairs.  
> The $12/month (2 vCPU, 2 GB) is recommended for comfort.

---

## 2. First SSH Login

```bash
ssh root@YOUR_DROPLET_IP
```

---

## 3. Upload the Bot to the Droplet

**Option A — Git (recommended):**
```bash
# On your droplet
apt-get install -y git
git clone https://github.com/youruser/yourrepo.git /tmp/bybit_bot
# or use a private repo with deploy keys
```

**Option B — SCP from your local machine:**
```bash
# From your Windows machine (PowerShell or WSL)
scp -r "C:\Users\Ray\Documents\Repos\Allstat\bybit_bot" root@YOUR_DROPLET_IP:/tmp/
```

**Option C — rsync (best for updates):**
```bash
rsync -avz --exclude='.env' --exclude='venv' --exclude='__pycache__' \
  "C:\Users\Ray\Documents\Repos\Allstat\bybit_bot/" \
  root@YOUR_DROPLET_IP:/tmp/bybit_bot/
```

---

## 4. Run the Setup Script

```bash
# On the droplet
cd /tmp/bybit_bot
chmod +x setup.sh
sudo bash setup.sh
```

This will:
- Install Python 3.11, tmux, htop
- Create a `botuser` system account
- Deploy the bot to `/opt/bybit_bot`
- Create a Python virtual environment
- Install all dependencies
- Install the `bybit-bot` systemd service
- Install `botctl` management command
- Set up logrotate

---

## 5. Configure API Keys

```bash
nano /opt/bybit_bot/.env
```

Set these two values:
```
BYBIT_API_KEY=your_actual_api_key
BYBIT_API_SECRET=your_actual_api_secret
BYBIT_TESTNET=false
```

Save: `Ctrl+O`, `Enter`, `Ctrl+X`

**Restrict key file permissions:**
```bash
chmod 640 /opt/bybit_bot/.env
chown botuser:botuser /opt/bybit_bot/.env
```

---

## 6. Test in Demo Mode First

Always verify everything works before going live:

```bash
botctl demo
# or directly:
cd /opt/bybit_bot && sudo -u botuser venv/bin/python main.py --mode demo
```

Press `Ctrl+C` to stop. You should see the live dashboard with virtual trades.

---

## 7. Run a Signal Scan

Check what signals the bot sees right now:

```bash
botctl scan
```

---

## 8. Start Live Trading

```bash
# The service is already enabled for auto-start (setup.sh did this).
# Just start it for the first time:
botctl start

# Confirm it's running AND set to auto-start:
botctl check
```

You should see:
```
Running: YES
Auto-start on boot: YES (enabled)
```

That means:
- **Droplet reboots** → bot starts automatically within ~20 seconds of boot
- **Bot crashes** → systemd restarts it after 15 seconds, indefinitely
- **SSH disconnect** → bot keeps running (it's a system service, not a shell process)

---

## 9. tmux — Survive SSH Disconnects

If you don't use systemd and prefer running interactively:

```bash
cd /opt/bybit_bot
chmod +x tmux_bot.sh
./tmux_bot.sh live       # starts bot in tmux session
```

To reconnect after closing SSH:
```bash
ssh root@YOUR_DROPLET_IP
./tmux_bot.sh attach
```

Inside tmux:
- `Ctrl+B` then `D` — detach (bot keeps running)
- `Ctrl+B` then `[` — scroll up through output (`Q` to exit scroll)
- `Ctrl+B` then `"` — split pane horizontally

---

## botctl Reference

```bash
botctl start          # Start the systemd service
botctl stop           # Stop gracefully (closes all positions)
botctl restart        # Restart
botctl status         # Service status
botctl logs           # Live journal log stream (Ctrl+C to stop)
botctl tail           # Tail logs/bot.log file directly
botctl demo           # Run demo mode interactively
botctl scan           # One-shot signal scan
botctl report BTCUSDT # Full backtest report for a symbol
botctl enable         # Enable auto-start on reboot
botctl disable        # Disable auto-start
```

---

## Updating the Bot

When you update code and want to redeploy:

```bash
# From your local machine
rsync -avz --exclude='.env' --exclude='venv' --exclude='__pycache__' \
  "C:\Users\Ray\Documents\Repos\Allstat\bybit_bot/" \
  root@YOUR_DROPLET_IP:/opt/bybit_bot/

# On the droplet
botctl restart
```

---

## Viewing Logs

**Live (journald — best for systemd):**
```bash
botctl logs
# or
journalctl -u bybit-bot -f
```

**Last 100 lines:**
```bash
journalctl -u bybit-bot -n 100
```

**Since a specific time:**
```bash
journalctl -u bybit-bot --since "2026-01-01 10:00:00"
```

**File log:**
```bash
tail -f /opt/bybit_bot/logs/bot.log
```

---

## Monitoring Resource Usage

```bash
htop                     # interactive process monitor
df -h                    # disk usage
free -h                  # memory usage
systemctl status bybit-bot  # service health
```

---

## Firewall (Optional but Recommended)

The bot only makes outbound connections — no inbound ports needed.

```bash
apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw enable
```

---

## Security Best Practices

1. **Never commit `.env`** — it's in `.gitignore` already
2. **Bybit API key permissions** — on Bybit, enable only:
   - ✅ Read
   - ✅ Trade (Derivatives)
   - ❌ Withdraw — **never enable withdrawal**
3. **IP whitelist your API key** on Bybit with your droplet's IP
4. **Keep OS updated:** `apt-get update && apt-get upgrade -y`
5. **Use SSH keys** instead of password auth

---

## Troubleshooting

**Bot won't start:**
```bash
journalctl -u bybit-bot -n 50    # check for Python errors
botctl status                     # check systemd status
```

**ImportError / ModuleNotFoundError:**
```bash
cd /opt/bybit_bot
sudo -u botuser venv/bin/pip install -r requirements.txt
botctl restart
```

**API connection error:**
```bash
# Test connectivity from droplet
curl -s https://api.bybit.com/v5/market/tickers?category=linear | head -c 200
```

**Strategy cache issues (stale data):**
```bash
rm -rf /opt/bybit_bot/data/strategy_cache/*.json
botctl restart    # will re-run backtests on startup
```

**Out of memory on 1 GB droplet:**
- Increase `scanner.min_volume_usdt` in config.yaml (e.g. 5000000) to scan fewer pairs
- Add swap: `fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`
