#!/usr/bin/env bash
# ==============================================================================
#  tmux_bot.sh — Launch the bot inside a named tmux session
#  so it keeps running after you disconnect from SSH.
#
#  Usage:
#    ./tmux_bot.sh          # start live bot in tmux session named 'bybit'
#    ./tmux_bot.sh demo     # start demo mode
#    ./tmux_bot.sh attach   # re-attach to the running session
#    ./tmux_bot.sh kill     # kill the tmux session
#    ./tmux_bot.sh logs     # open a new window showing live log tail
#
#  After connecting to your droplet via SSH:
#    ssh user@your-droplet-ip
#    ./tmux_bot.sh attach     ← reconnect to the running bot
#
#  Inside tmux:
#    Ctrl+B then D  — detach (bot keeps running in background)
#    Ctrl+B then [  — scroll mode (q to exit)
# ==============================================================================

SESSION="bybit"
BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CMD="$BOT_DIR/run.sh"

MODE="${1:-live}"

case "$MODE" in
    attach)
        tmux attach-session -t "$SESSION" 2>/dev/null || \
            echo "No session '$SESSION' found. Start one with: $0 live"
        ;;
    kill)
        tmux kill-session -t "$SESSION" 2>/dev/null && \
            echo "Session '$SESSION' killed" || \
            echo "No session found"
        ;;
    logs)
        tmux new-window -t "$SESSION" -n "logs" \
            "tail -f $BOT_DIR/logs/bot.log" 2>/dev/null || \
            tail -f "$BOT_DIR/logs/bot.log"
        ;;
    live|demo|scan|backtest|report|refresh|symbols)
        # Kill existing session if running
        tmux kill-session -t "$SESSION" 2>/dev/null || true

        # Start a new detached session
        tmux new-session -d -s "$SESSION" -n "bot" \
            "bash $CMD $* ; echo 'Bot exited. Press Enter.'; read"

        echo "Bot launched in tmux session '$SESSION'"
        echo ""
        echo "  Attach now : tmux attach -t $SESSION"
        echo "  Detach     : Ctrl+B then D"
        echo "  Kill       : $0 kill"
        echo ""
        echo "Re-attaching in 1 second…"
        sleep 1
        tmux attach-session -t "$SESSION"
        ;;
    *)
        echo "Usage: $0 {live|demo [SYMBOL]|scan|attach|kill|logs}"
        exit 1
        ;;
esac
